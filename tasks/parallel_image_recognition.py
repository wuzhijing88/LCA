"""
并行图片识别模块 - 多图识别性能优化
支持多线程并行处理，显著提升多图识别速度

主要特性：
1. 并行图片识别：多张图片同时处理
2. 智能截图复用：避免重复截图开销
3. 线程池管理：动态调整线程数量
4. 结果聚合：统一处理识别结果
5. 错误隔离：单张图片失败不影响其他
"""

import time
import math
from task_workflow.script_parameters import integer_parameter
import threading
import concurrent.futures
from typing import Dict, Any, Optional, Tuple, List
import cv2
import numpy as np
from utils.match.smart_image_matcher import normalize_match_image
import logging
from tasks.task_utils import coerce_bool, capture_and_match_template_smart
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

def detect_optimal_thread_count() -> int:
    """
    智能检测最优线程数

    Returns:
        int: 推荐的线程数
    """
    import os

    cpu_count = os.cpu_count()
    if cpu_count is None:
        raise RuntimeError("无法确定可用CPU数量，不能自动创建识别线程池")
    return max(2, min(cpu_count, 32))

class RecognitionMode(Enum):
    """识别模式"""
    FIRST_MATCH = "first_match"      # 找到第一张就停止
    ALL_MATCHES = "all_matches"      # 识别所有图片
    BEST_MATCH = "best_match"        # 找到置信度最高的

@dataclass
class ImageTask:
    """图片识别任务"""
    image_path: str
    image_name: str
    index: int
    params: Dict[str, Any]

@dataclass
class RecognitionResult:
    """识别结果"""
    image_path: str
    image_name: str
    index: int
    success: bool
    confidence: float
    location: Optional[Tuple[int, int, int, int]]
    center_x: Optional[int]
    center_y: Optional[int]
    error_message: Optional[str]
    processing_time: float

class ParallelImageRecognizer:
    """并行图片识别器"""
    
    def __init__(self, max_workers: Optional[int] = None):
        """
        初始化并行识别器

        Args:
            max_workers: 最大工作线程数，None表示自动检测
        """
        # 自动检测最优线程数
        if max_workers is None:
            max_workers = detect_optimal_thread_count()

        self.max_workers = max_workers
        self.thread_pool = None
        self._screenshot_cache = {}
        self._cache_lock = threading.Lock()

        logger.info(f"并行图片识别器初始化: 最大线程数={max_workers} (CPU线程数自动检测)")
    
    def recognize_images_parallel(self,
                                image_paths: List[str],
                                params: Dict[str, Any],
                                execution_mode: str,
                                target_hwnd: Optional[int],
                                mode: RecognitionMode = RecognitionMode.FIRST_MATCH,
                                get_image_data=None,
                                stop_checker=None) -> List[RecognitionResult]:
        """
        并行识别多张图片。

        强制使用截图子进程执行“截图+匹配”，主进程只接收结果。
        """
        if not image_paths:
            return []
        if callable(stop_checker):
            if stop_checker():
                raise ValueError("多图识别已停止")

        start_time = time.time()
        try:
            logger.info(f"[并行识别] 开始处理{len(image_paths)}张图片，模式={mode.value}")

            try:
                from utils.capture.screenshot_helper import clear_screenshot_cache
                clear_screenshot_cache(target_hwnd)
            except Exception as e:
                logger.debug(f"[并行识别] 清除截图缓存失败: {e}")

            if not target_hwnd:
                raise ValueError("多图识别需要有效的窗口句柄")

            recognition_region = None
            region_offset = (0, 0)

            use_recognition_region = (
                coerce_bool(params.get('use_recognition_region', False)) or
                coerce_bool(params.get('multi_use_recognition_region', False))
            )
            if use_recognition_region:
                region_x = int(params.get('multi_recognition_region_x', params.get('recognition_region_x', 0)) or 0)
                region_y = int(params.get('multi_recognition_region_y', params.get('recognition_region_y', 0)) or 0)
                region_w = int(params.get('multi_recognition_region_width', params.get('recognition_region_width', 0)) or 0)
                region_h = int(params.get('multi_recognition_region_height', params.get('recognition_region_height', 0)) or 0)
                if region_w > 0 and region_h > 0:
                    recognition_region = (region_x, region_y, region_w, region_h)

            logger.info("[并行识别] 使用截图子进程匹配模式（主进程不持有整帧截图）")

            params['_region_offset'] = region_offset
            params['_use_capture_match_subprocess'] = True
            params['_target_hwnd'] = int(target_hwnd)
            params['_capture_roi'] = recognition_region

            tasks = []
            for i, image_path in enumerate(image_paths):
                image_name = self._get_image_name(image_path)
                task = ImageTask(
                    image_path=image_path,
                    image_name=image_name,
                    index=i,
                    params=params.copy()
                )
                if callable(get_image_data):
                    task.params['_get_image_data_cb'] = get_image_data
                tasks.append(task)

            results = self._execute_parallel_recognition(tasks, None, mode, stop_checker)

            total_time = time.time() - start_time
            success_count = sum(1 for r in results if r.success)
            logger.info(f"[并行识别] 完成: {success_count}/{len(image_paths)}张成功, 总耗时={total_time:.2f}s")
            return results
        finally:
            self.cleanup()
    def _execute_parallel_recognition(self, tasks: List[ImageTask], screenshot: Optional[np.ndarray], mode: RecognitionMode, stop_checker=None) -> List[RecognitionResult]:
        """执行并行识别。"""
        results = []
        stop_event = threading.Event()

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_task = {}
            for task in tasks:
                if callable(stop_checker):
                    if stop_checker():
                        stop_event.set()
                        break
                future = executor.submit(self._recognize_single_image, task, screenshot, stop_event)
                future_to_task[future] = task

            found_first_match = False
            for future in concurrent.futures.as_completed(future_to_task):
                if callable(stop_checker):
                    if stop_checker():
                        stop_event.set()
                task = future_to_task[future]
                try:
                    result = future.result()
                    results.append(result)

                    if mode == RecognitionMode.FIRST_MATCH and result.success and not found_first_match:
                        logger.info(f"[并行识别] 找到第一张匹配图片: {result.image_name}")
                        found_first_match = True
                        stop_event.set()
                except Exception as e:
                    logger.error(f"任务执行异常: {task.image_name}, 错误: {e}")
                    results.append(RecognitionResult(
                        image_path=task.image_path,
                        image_name=task.image_name,
                        index=task.index,
                        success=False,
                        confidence=0.0,
                        location=None,
                        center_x=None,
                        center_y=None,
                        error_message=str(e),
                        processing_time=0.0,
                    ))

            if len(results) < len(tasks):
                completed_indices = {r.index for r in results}
                for task in tasks:
                    if task.index not in completed_indices:
                        results.append(RecognitionResult(
                            image_path=task.image_path,
                            image_name=task.image_name,
                            index=task.index,
                            success=False,
                            confidence=0.0,
                            location=None,
                            center_x=None,
                            center_y=None,
                            error_message="任务未完成",
                            processing_time=0.0,
                        ))

        results.sort(key=lambda r: r.index)
        if mode == RecognitionMode.FIRST_MATCH:
            # 并发任务可能在 stop_event 设置前同时完成；对外严格只返回
            # 按输入顺序的第一个成功结果，避免调用方误点多张图片。
            first_success = next((result for result in results if result.success), None)
            if first_success is not None:
                results = [first_success]
        return results

    def _recognize_single_image(self, task: ImageTask, screenshot: Optional[np.ndarray], stop_event: threading.Event) -> RecognitionResult:
        """识别单张图片。"""
        start_time = time.time()

        try:
            if stop_event.is_set():
                return RecognitionResult(
                    image_path=task.image_path,
                    image_name=task.image_name,
                    index=task.index,
                    success=False,
                    confidence=0.0,
                    location=None,
                    center_x=None,
                    center_y=None,
                    error_message="任务被取消",
                    processing_time=time.time() - start_time,
                )

            template_image = self._load_template_image(task.image_path, task)
            if template_image is None:
                raise Exception(f"无法加载模板图片: {task.image_path}")

            confidence_threshold = task.params.get('confidence', 0.8)
            use_capture_match_subprocess = bool(task.params.get('_use_capture_match_subprocess', False))
            if not use_capture_match_subprocess:
                raise Exception("已禁用主进程匹配路径，必须使用子进程截图匹配")

            target_hwnd = task.params.get('_target_hwnd')
            roi = task.params.get('_capture_roi')
            success, confidence, location = self._match_template_via_capture_subprocess(
                target_hwnd=target_hwnd,
                template=template_image,
                confidence_threshold=confidence_threshold,
                roi=roi,
                template_key=task.image_path,
            )

            center_x, center_y = None, None
            if success and location:
                center_x = int(location[0]) + int(location[2]) // 2
                center_y = int(location[1]) + int(location[3]) // 2

            processing_time = time.time() - start_time
            return RecognitionResult(
                image_path=task.image_path,
                image_name=task.image_name,
                index=task.index,
                success=success,
                confidence=confidence,
                location=location,
                center_x=center_x,
                center_y=center_y,
                error_message=None,
                processing_time=processing_time,
            )

        except Exception as e:
            processing_time = time.time() - start_time
            return RecognitionResult(
                image_path=task.image_path,
                image_name=task.image_name,
                index=task.index,
                success=False,
                confidence=0.0,
                location=None,
                center_x=None,
                center_y=None,
                error_message=str(e),
                processing_time=processing_time,
            )

    def _match_template_via_capture_subprocess(
        self,
        target_hwnd: Optional[int],
        template: np.ndarray,
        confidence_threshold: float,
        roi: Optional[Tuple[int, int, int, int]] = None,
        template_key: Optional[str] = None,
    ) -> Tuple[bool, float, Optional[Tuple[int, int, int, int]]]:
        """通过本地截图引擎执行截图+模板匹配。"""
        if not target_hwnd:
            raise ValueError("多图识别需要有效的目标窗口")
        response = capture_and_match_template_smart(
            target_hwnd=target_hwnd, template=template,
            confidence_threshold=float(confidence_threshold),
            template_key=template_key, capture_timeout=0.8, roi=roi,
            client_area_only=True, use_cache=False,
        )
        if not response or not response.get("success"):
            raise ValueError("多图截图匹配失败: " + str((response or {}).get("error") or "未返回有效结果"))
        score = float(response["confidence"])
        if not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError("多图匹配置信度无效")
        if not isinstance(response.get("matched"), bool):
            raise ValueError("多图匹配状态未知")
        if not response["matched"]:
            return False, score, None
        location = response.get("location")
        if not isinstance(location, (list, tuple)) or len(location) != 4:
            raise ValueError("多图匹配位置无效")
        location = tuple(integer_parameter(item, "多图匹配坐标") for item in location)
        if location[2] <= 0 or location[3] <= 0 or score < confidence_threshold:
            raise ValueError("多图匹配结果与命中状态不一致")
        return True, score, location

    def _load_template_image(self, image_path: str, task: ImageTask) -> Optional[np.ndarray]:
        """加载模板图片"""
        try:
            # 【性能优化】优先从模板缓存加载
            template = None
            try:
                from utils.match.template_preloader import get_global_preloader
                preloader = get_global_preloader()
                template = preloader.get_template(image_path)
                if template is not None:
                    import os
                    image_name = image_path.replace('memory://', '') if image_path.startswith('memory://') else os.path.basename(image_path)
                    # 调试：记录模板原始格式
                    logger.debug(f"[并行识别] 缓存模板 '{image_name}': shape={template.shape}, dtype={template.dtype}")
                    # 缓存的模板可能是BGRA格式，需要转换为BGR
                    template = normalize_match_image(template)
                    if template is not None:
                        logger.debug(f"[并行识别] 模板规范化后: shape={template.shape}")
                    return template
            except Exception as e:
                logger.debug(f"[性能优化-并行] 模板缓存读取失败: {e}")

            # 缓存未命中，正常加载
            if image_path.startswith('memory://'):
                # 从内存加载
                image_data = None
                get_image_data = task.params.get('_get_image_data_cb')
                if callable(get_image_data):
                    try:
                        image_data = get_image_data(image_path)
                    except Exception:
                        image_data = None

                if image_data:
                    # 使用IMREAD_UNCHANGED保留原始格式（与单图识别保持一致）
                    img = cv2.imdecode(np.frombuffer(image_data, np.uint8), cv2.IMREAD_UNCHANGED)
                    return normalize_match_image(img)
                return None
            else:
                # 从文件加载（使用np.fromfile支持中文路径）
                try:
                    file_data = np.fromfile(image_path, dtype=np.uint8)
                    if file_data is None or len(file_data) == 0:
                        logger.error(f"[并行识别] 文件数据为空: {image_path}")
                        return None
                    # 使用IMREAD_UNCHANGED保留原始格式（与单图识别保持一致）
                    img = cv2.imdecode(file_data, cv2.IMREAD_UNCHANGED)
                    return normalize_match_image(img)
                except Exception as e:
                    logger.error(f"[并行识别] 文件读取失败: {image_path}, 错误: {e}")
                    return None
        except Exception as e:
            logger.error(f"加载模板图片失败: {image_path}, 错误: {e}")
            return None

    def _get_image_name(self, image_path: str) -> str:
        """获取图片名称"""
        if image_path.startswith('memory://'):
            return image_path.replace('memory://', '')
        else:
            import os
            return os.path.basename(image_path)
    
    def cleanup(self):
        """清理资源"""
        with self._cache_lock:
            for cached_data in list(self._screenshot_cache.values()):
                try:
                    if isinstance(cached_data, tuple) and len(cached_data) >= 1:
                        cached_screenshot = cached_data[0]
                        if cached_screenshot is not None:
                            del cached_screenshot
                    elif cached_data is not None:
                        del cached_data
                except Exception:
                    pass
            self._screenshot_cache.clear()

# 全局实例
_parallel_recognizer = None
_recognizer_lock = threading.Lock()

def get_parallel_recognizer() -> ParallelImageRecognizer:
    """获取全局并行识别器实例"""
    global _parallel_recognizer
    if _parallel_recognizer is None:
        with _recognizer_lock:
            if _parallel_recognizer is None:
                _parallel_recognizer = ParallelImageRecognizer()
    return _parallel_recognizer


def get_existing_parallel_recognizer() -> Optional[ParallelImageRecognizer]:
    """仅返回已存在的并行识别器，不触发初始化。"""
    return _parallel_recognizer


def cleanup_parallel_recognizer(reset_instance: bool = True) -> bool:
    """清理全局并行识别器资源。

    Args:
        reset_instance: 是否同时重置全局单例引用
    """
    global _parallel_recognizer
    with _recognizer_lock:
        recognizer = _parallel_recognizer
        if recognizer is None:
            return False

        try:
            recognizer.cleanup()
        except Exception as exc:
            logger.debug(f"清理并行识别器缓存失败: {exc}")
        finally:
            if reset_instance:
                _parallel_recognizer = None
    return True
