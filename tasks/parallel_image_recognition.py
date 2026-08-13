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
import threading
import concurrent.futures
from typing import Dict, Any, Optional, Tuple, List
import cv2
import numpy as np
from utils.smart_image_matcher import normalize_match_image
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
    try:
        # 使用专门的CPU检测工具
        from utils.cpu_info_detector import detect_optimal_thread_count as cpu_detect  # type: ignore
        return cpu_detect()
    except ImportError:
        # 回退到简单检测
        import os
        cpu_count = os.cpu_count() or 4
        optimal_threads = max(2, min(cpu_count, 32))
        logger.debug(f"使用简单CPU检测: 核心数={cpu_count}, 推荐线程数={optimal_threads}")
        return optimal_threads

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
            try:
                if stop_checker():
                    return []
            except Exception:
                pass

        start_time = time.time()
        try:
            logger.info(f"[并行识别] 开始处理{len(image_paths)}张图片，模式={mode.value}")

            try:
                from utils.screenshot_helper import clear_screenshot_cache
                clear_screenshot_cache(target_hwnd)
            except Exception as e:
                logger.debug(f"[并行识别] 清除截图缓存失败: {e}")

            if not target_hwnd:
                logger.error("[并行识别] 缺少有效窗口句柄，无法使用子进程截图匹配")
                return []

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
    def _get_screenshot_cached(self, execution_mode: str, target_hwnd: Optional[int], params: Dict[str, Any]) -> Optional[np.ndarray]:
        """获取缓存的截图"""
        # 【闪退修复】使用固定key而非时间戳，避免每秒产生新key导致内存泄漏
        cache_key = f"{execution_mode}_{target_hwnd}"

        with self._cache_lock:
            # 检查缓存是否存在且未过期（30ms TTL - 长期运行优化）
            if cache_key in self._screenshot_cache:
                cached_data = self._screenshot_cache[cache_key]
                # 兼容旧格式(直接是screenshot)和新格式(tuple)
                if isinstance(cached_data, tuple):
                    cached_screenshot, cached_time = cached_data
                    # 检查是否过期(30ms内复用 - 更激进释放内存)
                    if (time.time() - cached_time) < 0.03:
                        logger.debug("使用缓存截图")
                        return cached_screenshot
                    else:
                        # 过期，显式删除numpy数组
                        logger.debug(f"缓存截图已过期({(time.time() - cached_time)*1000:.1f}ms)，重新截图")
                        try:
                            del cached_screenshot
                        except Exception:
                            pass
                        del self._screenshot_cache[cache_key]
                else:
                    # 旧格式缓存，清理掉
                    try:
                        del cached_data
                    except Exception:
                        pass
                    del self._screenshot_cache[cache_key]

        # 获取新截图
        screenshot = self._capture_screenshot(execution_mode, target_hwnd, params)

        if screenshot is not None:
            with self._cache_lock:
                # 【闪退修复】清理所有旧缓存，避免内存累积
                for key in list(self._screenshot_cache.keys()):
                    try:
                        old_data = self._screenshot_cache[key]
                        if isinstance(old_data, tuple):
                            old_ss, _ = old_data
                            del old_ss
                        else:
                            del old_data
                    except Exception:
                        pass
                self._screenshot_cache.clear()
                # 保存新截图和时间戳
                self._screenshot_cache[cache_key] = (screenshot, time.time())

        return screenshot
    
    def _capture_screenshot(self, execution_mode: str, target_hwnd: Optional[int], params: Dict[str, Any]) -> Optional[np.ndarray]:
        """Capture a screenshot using local engines only."""
        try:
            # 原有模式：优先使用异步截图
            screenshot = None
            # 后台模式
            is_background_mode = execution_mode and execution_mode.startswith('background')
            if is_background_mode and target_hwnd:
                # 【稳定性修复】禁用线程池异步截图，避免 WinRT/WGC 跨线程并发导致崩溃
                screenshot = None

            # 降级方案：使用传统WGC/OpenCV截图
            if screenshot is None:
                    # 验证窗口句柄是否有效
                    if is_background_mode and target_hwnd:
                        import win32gui
                        try:
                            if not win32gui.IsWindow(target_hwnd):
                                logger.error(f"[并行识别-后台] 窗口句柄{target_hwnd}无效或窗口已关闭")
                                return None
                        except Exception as e:
                            logger.error(f"[并行识别-后台] 验证窗口句柄时出错: {e}")
                            return None

                        # 后台/模拟器模式：使用统一截图接口
                        from utils.screenshot_helper import take_window_screenshot
                        pil_img = take_window_screenshot(target_hwnd, client_area_only=True)
                        if pil_img is not None:
                            screenshot = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
                        else:
                            screenshot = None
                    elif execution_mode and execution_mode.startswith('foreground'):
                        # 前台模式：也使用统一截图接口（与后台模式保持一致）
                        # 这样识别出的坐标是客户区坐标，与click_coordinate的处理方式一致
                        if target_hwnd:
                            import win32gui
                            try:
                                if not win32gui.IsWindow(target_hwnd):
                                    logger.error(f"[并行识别-前台] 窗口句柄{target_hwnd}无效或窗口已关闭")
                                    return None
                            except Exception as e:
                                logger.error(f"[并行识别-前台] 验证窗口句柄时出错: {e}")
                                return None

                            from utils.screenshot_helper import take_window_screenshot
                            pil_img = take_window_screenshot(target_hwnd, client_area_only=True)
                            if pil_img is not None:
                                screenshot = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
                            else:
                                screenshot = None
                            logger.debug("[并行识别-前台] 使用统一截图接口，确保坐标为客户区坐标")
                        else:
                            # 没有窗口句柄时才使用全屏截图
                            import mss
                            import mss.tools
                            with mss.mss() as sct:
                                monitor = sct.monitors[1]  # 主显示器
                                sct_img = sct.grab(monitor)
                                screenshot = np.array(sct_img)
                                screenshot = cv2.cvtColor(screenshot, cv2.COLOR_BGRA2BGR)
                            logger.warning("[并行识别-前台] 无窗口句柄，使用全屏截图（坐标为屏幕坐标）")
                    else:
                        logger.error(f"不支持的执行模式: {execution_mode}")
                        return None

            if screenshot is None:
                return None

            # 格式统一：BGRA转BGR（不做其他预处理，与找图点击保持一致）
            if len(screenshot.shape) == 3 and screenshot.shape[2] == 4:
                return cv2.cvtColor(screenshot, cv2.COLOR_BGRA2BGR)
            return screenshot

        except Exception as e:
            logger.error(f"截图失败: {e}")
            return None

    def _execute_parallel_recognition(self, tasks: List[ImageTask], screenshot: Optional[np.ndarray], mode: RecognitionMode, stop_checker=None) -> List[RecognitionResult]:
        """执行并行识别。"""
        results = []
        stop_event = threading.Event()

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_task = {}
            for task in tasks:
                if callable(stop_checker):
                    try:
                        if stop_checker():
                            stop_event.set()
                            break
                    except Exception:
                        pass
                future = executor.submit(self._recognize_single_image, task, screenshot, stop_event)
                future_to_task[future] = task

            found_first_match = False
            for future in concurrent.futures.as_completed(future_to_task):
                if callable(stop_checker):
                    try:
                        if stop_checker():
                            stop_event.set()
                    except Exception:
                        pass
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
            return False, 0.0, None

        try:
            match_response = capture_and_match_template_smart(
                target_hwnd=target_hwnd,
                template=template,
                confidence_threshold=float(confidence_threshold),
                template_key=(str(template_key) if template_key else None),
                capture_timeout=0.8,
                roi=roi,
                client_area_only=True,
                use_cache=False,
            )

            if not match_response or not bool(match_response.get("success")):
                return False, 0.0, None

            try:
                score = float(match_response.get("confidence", 0.0) or 0.0)
            except Exception:
                score = 0.0

            raw_location = match_response.get("location")
            parsed_location = None
            if isinstance(raw_location, (list, tuple)) and len(raw_location) == 4:
                try:
                    parsed_location = (
                        int(raw_location[0]),
                        int(raw_location[1]),
                        int(raw_location[2]),
                        int(raw_location[3]),
                    )
                except Exception:
                    parsed_location = None

            if bool(match_response.get("matched", False)) and parsed_location is not None and score >= confidence_threshold:
                return True, score, parsed_location
            return False, score, None

        except Exception as e:
            logger.error(f"本地截图引擎匹配失败: {e}")
            return False, 0.0, None
    def _load_template_image(self, image_path: str, task: ImageTask) -> Optional[np.ndarray]:
        """加载模板图片"""
        try:
            # 【性能优化】优先从模板缓存加载
            template = None
            try:
                from utils.template_preloader import get_global_preloader
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

    def _match_template(self, screenshot: np.ndarray, template: np.ndarray, confidence_threshold: float,
                       image_path: str = None, target_hwnd: Optional[int] = None) -> Tuple[bool, float, Optional[Tuple[int, int, int, int]]]:
        """兼容保留接口：主进程模板匹配已禁用。"""
        logger.error("主进程模板匹配路径已禁用，请使用统一截图匹配")
        return False, 0.0, None
    
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

    def clear_cache(self):
        """兼容接口：清理缓存。"""
        self.cleanup()

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
