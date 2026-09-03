# -*- coding: utf-8 -*-

"""
OCR文字识别任务模块
支持指定窗口区域进行文字识别，CPU模式优化
"""

import logging
import time
import copy
import threading
import numpy as np
from typing import Dict, Any, Optional, Tuple, List
from tasks.task_utils import (
    get_recorded_region_binding_mismatch_detail,
    resolve_region_selection_params,
)

# Windows API 相关导入
try:
    import win32gui
    PYWIN32_AVAILABLE = True
except ImportError:
    PYWIN32_AVAILABLE = False

# 【主程序零OCR】不再使用统一OCR服务，只使用多进程OCR池
# 统一OCR服务已废弃，避免在主进程中加载OCR模型

# 先初始化logger
logger = logging.getLogger(__name__)

# 并发OCR管理器已移除，直接使用统一OCR服务作为备选
CONCURRENT_OCR_AVAILABLE = False

# 导入截图能力
try:
    from tasks.task_utils import is_smart_capture_available

    CAPTURE_AVAILABLE = is_smart_capture_available()
except ImportError as e:
    CAPTURE_AVAILABLE = False
    logger.warning(f"[OCR截图] 截图引擎不可用: {e}")


def _should_save_ocr_context(card_id: Optional[int], params: Optional[Dict[str, Any]] = None) -> bool:
    """脚本内识字必须写入上下文；画布卡片仍按出线决定。"""
    if isinstance(params, dict):
        flag = params.get("force_save_ocr_context")
        if flag in {True, 1, "1", "true", "True", "真", "是"}:
            return True
    try:
        from task_workflow.workflow_context import get_workflow_context

        context = get_workflow_context()
        executor = getattr(context, "executor", None)
        connections_map = getattr(executor, "_connections_map", None) if executor is not None else None
        if connections_map is None:
            return True
        connections = connections_map.get(card_id, [])
        for conn in connections:
            if conn.get("type", "") in {"success", "sequential"}:
                return True
        return False
    except Exception:
        return True


def _capture_window_for_ocr(hwnd: int, timeout: float = 4.0):
    """
    OCR截图统一走截图池入口：
    - 同窗口同引擎并发请求共享同一轮抓帧结果
    - 避免多线程同时向底层引擎重复抢帧
    """
    try:
        from services.screenshot_pool import capture_window

        return capture_window(
            hwnd=int(hwnd),
            client_area_only=True,
            use_cache=False,
            timeout=max(0.1, float(timeout)),
        )
    except Exception as exc:
        logger.warning(f"[OCR截图] 共享截图入口调用失败: {exc}")
        return None

# 任务类型标识
TASK_TYPE = "OCR文字识别"
TASK_NAME = "OCR文字识别"


class _OcrInFlightRequest:
    __slots__ = ("event", "results", "error")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.results: List[Dict[str, Any]] = []
        self.error: str = ""


_OCR_INFLIGHT_LOCK = threading.RLock()
_OCR_INFLIGHT: Dict[Tuple[Any, ...], _OcrInFlightRequest] = {}

def _get_ocr_engine() -> Optional[dict]:
    """获取可用的OCR引擎（使用多进程OCR池）"""
    return {'engine': 'multiprocess', 'instance': None}


def _recognize_text_with_shared_inflight(
    multi_ocr_pool,
    window_title: str,
    window_hwnd: int,
    image: np.ndarray,
    confidence: float = 0.1,
    scope_key: Optional[Tuple[int, int, int, int]] = None,
    wait_timeout: float = 32.0,
) -> List[Dict[str, Any]]:
    """
    同窗口同帧并发OCR请求复用：
    - 仅共享同一轮 in-flight 识别结果
    - 当前轮次完成后立即失效，不保留旧结果
    """
    def _do_recognize_once() -> List[Dict[str, Any]]:
        # recognize_text 内部会分配/等待 worker，并先登记在途请求，
        # 避免先预创建再识别时被空闲热重置插进 reset_engine 帧。
        recognized_once = multi_ocr_pool.recognize_text(
            window_title=window_title,
            window_hwnd=window_hwnd,
            image=image,
            confidence=confidence,
        )
        if isinstance(recognized_once, list):
            return recognized_once
        return []

    if image is None or (not isinstance(image, np.ndarray)) or image.size <= 0:
        return _do_recognize_once()

    try:
        confidence_bucket = int(float(confidence) * 1000)
    except Exception:
        confidence_bucket = 100
    normalized_scope_key: Tuple[Any, ...]
    if isinstance(scope_key, tuple) and len(scope_key) == 4:
        try:
            normalized_scope_key = (
                int(scope_key[0]),
                int(scope_key[1]),
                int(scope_key[2]),
                int(scope_key[3]),
            )
        except Exception:
            normalized_scope_key = ("shape", int(image.shape[1]), int(image.shape[0]))
    else:
        normalized_scope_key = ("shape", int(image.shape[1]), int(image.shape[0]))

    # 同一时间同窗口同区域直接复用，不依赖像素哈希，避免并发抓帧产生微差导致失配
    inflight_key = (int(window_hwnd), confidence_bucket, normalized_scope_key)

    owner = False
    with _OCR_INFLIGHT_LOCK:
        inflight = _OCR_INFLIGHT.get(inflight_key)
        if inflight is None:
            inflight = _OcrInFlightRequest()
            _OCR_INFLIGHT[inflight_key] = inflight
            owner = True

    if owner:
        try:
            recognized = _do_recognize_once()
            if isinstance(recognized, list):
                inflight.results = copy.deepcopy(recognized)
            else:
                inflight.results = []
        except Exception as exc:
            inflight.error = str(exc)
            inflight.results = []
        finally:
            inflight.event.set()
            with _OCR_INFLIGHT_LOCK:
                _OCR_INFLIGHT.pop(inflight_key, None)

        if inflight.error:
            raise RuntimeError(inflight.error)
        return copy.deepcopy(inflight.results)

    if not inflight.event.wait(timeout=max(0.5, float(wait_timeout))):
        logger.warning(
            f"[OCR共享复用] 等待同帧结果超时，直接返回空结果，避免并发线程重复触发OCR扩容: hwnd={window_hwnd}"
        )
        return []

    if inflight.error:
        raise RuntimeError(inflight.error)
    return copy.deepcopy(inflight.results)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _remember_ocr_source_for_jump(context: Any, jump_card_id: Any, ocr_card_id: Any) -> None:
    if jump_card_id is None or jump_card_id == "":
        return
    try:
        context.set_card_data(jump_card_id, 'associated_ocr_card_id', ocr_card_id)
    except Exception:
        pass


def _resolve_region_params(params: Dict[str, Any]) -> Tuple[str, int, int, int, int]:
    """
    统一解析OCR区域参数，避免测试链路与执行链路分叉。
    """
    return resolve_region_selection_params(params, default_mode='指定区域')


def _align_window_image_to_client_area(
    window_image: Optional[np.ndarray],
    target_hwnd: Optional[int],
    diag_prefix: str = "",
) -> Optional[np.ndarray]:
    """
    统一对齐截图到客户区，保证测试与执行使用同一裁剪规则。
    """
    if window_image is None or target_hwnd is None or not PYWIN32_AVAILABLE:
        return window_image

    try:
        height, width = window_image.shape[:2]
        client_rect = win32gui.GetClientRect(int(target_hwnd))
        client_w_logical = int(client_rect[2] - client_rect[0])
        client_h_logical = int(client_rect[3] - client_rect[1])

        if diag_prefix:
            logger.info(f"{diag_prefix} WGC截图尺寸: {width} x {height}")
            logger.info(f"{diag_prefix} GetClientRect尺寸: {client_w_logical} x {client_h_logical}")

        if client_w_logical <= 0 or client_h_logical <= 0:
            return window_image

        if width == client_w_logical and height == client_h_logical:
            if diag_prefix:
                logger.info(f"{diag_prefix} ✓ 截图尺寸与客户区一致")
            return window_image

        if diag_prefix:
            logger.warning(
                f"{diag_prefix} 截图尺寸与客户区不一致！差异: "
                f"Δw={width - client_w_logical}, Δh={height - client_h_logical}"
            )

        if width > client_w_logical or height > client_h_logical:
            wgc_offset_x = max(0, (width - client_w_logical) // 2)
            wgc_offset_y = max(0, height - client_h_logical)
            end_x = min(width, wgc_offset_x + client_w_logical)
            end_y = min(height, wgc_offset_y + client_h_logical)

            if diag_prefix:
                logger.info(f"{diag_prefix} 计算偏移: X={wgc_offset_x}, Y={wgc_offset_y}")

            if end_x > wgc_offset_x and end_y > wgc_offset_y:
                cropped = window_image[wgc_offset_y:end_y, wgc_offset_x:end_x]
                if cropped is not None and cropped.size > 0:
                    if diag_prefix:
                        logger.info(f"{diag_prefix} 已裁剪到客户区: {cropped.shape[1]} x {cropped.shape[0]}")
                    return cropped

    except Exception as e:
        if diag_prefix:
            logger.warning(f"{diag_prefix} 客户区对齐检查失败: {e}")

    return window_image


def _extract_effective_ocr_roi(
    window_image: np.ndarray,
    region_mode: str,
    region_x: int,
    region_y: int,
    region_width: int,
    region_height: int,
    fallback_log_prefix: str = "",
) -> Tuple[Optional[np.ndarray], int, int, int, int, str]:
    """
    统一确定最终OCR区域：
    - 指定区域且宽高有效 -> 使用指定区域
    - 否则 -> 使用整个窗口（与测试按钮一致）
    """
    if window_image is None or window_image.size == 0:
        return None, 0, 0, 0, 0, "无效图像"

    window_h, window_w = window_image.shape[:2]
    use_specified_region = (
        region_mode == '指定区域'
        and int(region_width) > 0
        and int(region_height) > 0
    )

    if use_specified_region:
        roi_image = _extract_region(window_image, int(region_x), int(region_y), int(region_width), int(region_height))
        if roi_image is None or roi_image.size == 0:
            return None, 0, 0, 0, 0, "指定区域"
        roi_h, roi_w = roi_image.shape[:2]
        region_desc = f"X={int(region_x)}, Y={int(region_y)}, 宽={roi_w}, 高={roi_h}"
        return roi_image, int(region_x), int(region_y), int(roi_w), int(roi_h), region_desc

    if fallback_log_prefix and region_mode == '指定区域':
        logger.info(f"{fallback_log_prefix} 指定区域未有效配置，自动使用整个窗口")

    return window_image, 0, 0, int(window_w), int(window_h), "整个窗口"


def _recognize_with_multiprocess_pool(
    window_title: str,
    window_hwnd: int,
    image: np.ndarray,
    scope_key: Optional[Tuple[int, int, int, int]] = None,
    confidence: float = 0.1,
) -> List[Dict[str, Any]]:
    from services.multiprocess_ocr_pool import get_multiprocess_ocr_pool

    multi_ocr_pool = get_multiprocess_ocr_pool()
    if not multi_ocr_pool.is_running:
        raise RuntimeError("OCR池已关闭")

    hwnd_int = int(window_hwnd) if window_hwnd else 0
    if hwnd_int == 0:
        raise RuntimeError("窗口句柄无效(为0)")
    if PYWIN32_AVAILABLE and not win32gui.IsWindow(hwnd_int):
        raise RuntimeError(f"窗口句柄无效: {hwnd_int}")

    return _recognize_text_with_shared_inflight(
        multi_ocr_pool=multi_ocr_pool,
        window_title=window_title,
        window_hwnd=hwnd_int,
        image=image,
        confidence=float(confidence),
        scope_key=scope_key,
    )

def execute_task(params: Dict[str, Any], counters: Dict[str, int], execution_mode: str,
                target_hwnd: Optional[int], window_region: Optional[Tuple[int, int, int, int]],
                card_id: Optional[int] = None, **kwargs) -> Tuple[bool, str, Optional[int]]:
    """
    执行OCR区域识别任务

    Args:
        params: 任务参数
        counters: 计数器
        execution_mode: 执行模式
        target_hwnd: 目标窗口句柄
        window_region: 窗口区域
        card_id: 卡片ID
        **kwargs: 其他参数

    Returns:
        Tuple[bool, str, Optional[int]]: (成功状态, 动作, 下一个卡片ID)
    """
    # 获取停止检查器
    stop_checker = kwargs.get('stop_checker', None)

    # 获取参数（统一解析，避免与测试路径分叉）
    region_mode, region_x, region_y, region_width, region_height = _resolve_region_params(params)

    # 目标文字设置
    text_recognition_mode = params.get('text_recognition_mode', '单组文字')
    target_text = params.get('target_text', '')
    target_text_groups = params.get('target_text_groups', '')
    match_mode = params.get('match_mode', '包含')
    reset_clicked_texts_on_next_run = params.get('reset_clicked_texts_on_next_run', False)

    # 数字识别设置
    recognition_type = params.get('recognition_type', '识别所有文本')
    target_number = params.get('target_number', '')
    enable_compare = params.get('enable_compare', False)
    compare_mode = params.get('compare_mode', '等于')


    # 为旧卡片自动添加新参数的默认值
    if 'recognition_type' not in params:
        params['recognition_type'] = '识别所有文本'
    if 'target_number' not in params:
        params['target_number'] = ''
    if 'enable_compare' not in params:
        params['enable_compare'] = False
    if 'compare_mode' not in params:
        params['compare_mode'] = '等于'

    # 解析多组文字
    if text_recognition_mode == '多组文字' and target_text_groups:
        import re
        text_groups = [text.strip() for text in re.split('[,，]', target_text_groups) if text.strip()]
        if not text_groups:
            text_recognition_mode = '单组文字'
    else:
        text_groups = [target_text] if target_text else ['']

    # OCR设置
    ocr_language = '中英文'
    confidence_threshold = params.get('confidence_threshold', 0.8)

    # 【重要优化】移除任务内部重试机制，改由工作流"继续执行本步骤"控制
    # 这样可以在每次重试前检查停止信号，实现更快的停止响应
    # 如果需要重试，请在任务参数中设置：失败时="继续执行本步骤"

    # 执行后操作参数
    on_success_action = params.get('on_success', '执行下一步')
    success_jump_id = params.get('success_jump_target_id')
    on_failure_action = params.get('on_failure', '执行下一步')
    failure_jump_id = params.get('failure_jump_target_id')

    if region_mode == '指定区域':
        binding_mismatch_detail = get_recorded_region_binding_mismatch_detail(params, target_hwnd)
        if binding_mismatch_detail:
            logger.error(f"[OCR] {binding_mismatch_detail}")
            return _handle_failure(
                on_failure_action,
                failure_jump_id,
                card_id,
                stop_checker,
                params,
                detail=binding_mismatch_detail,
            )

    # 获取窗口信息用于并发OCR管理
    window_title = "unknown"
    if target_hwnd:
        try:
            import win32gui
            window_title = win32gui.GetWindowText(target_hwnd)
            if not window_title:
                window_title = f"HWND_{target_hwnd}"
        except Exception:
            window_title = f"HWND_{target_hwnd}"

    # 将窗口标题添加到参数中，供OCR使用
    params['window_title'] = window_title

    # 移除详细的print输出，避免敏感信息泄露
    # 保留基本的日志记录

    # 检查停止信号
    if stop_checker and stop_checker():
        return False, '停止工作流', None

    # 【内存泄漏修复】初始化变量，确保finally块能访问
    window_image = None
    roi_image = None
    ocr_image = None

    try:
        # 1. 获取OCR引擎（支持打包后运行）。OCR文字识别始终走 RapidOCR；插件模式只影响截图来源。
        try:
            ocr_engine = _get_ocr_engine()
            if not ocr_engine:
                logger.error("错误 [OCR引擎] OCR引擎不可用")
                logger.error("可能的原因:")
                logger.error("1. RapidOCR运行依赖不可用")
                logger.error("2. 本地PP-OCRv4模型或运行库缺失")
                logger.error("3. OCR子进程启动失败")
                logger.error("建议: 请检查离线OCR运行时完整性")
                return _handle_failure(
                    on_failure_action,
                    failure_jump_id,
                    card_id,
                    stop_checker,
                    params,
                    detail="OCR引擎不可用，请检查OCR依赖、打包文件或系统权限",
                )
        except Exception as e:
            logger.error(f"错误 [OCR引擎] OCR引擎初始化异常: {e}")
            logger.error("这可能是由于打包环境问题导致的")
            logger.error("建议: 请使用无OCR版本或检查依赖安装")
            return _handle_failure(
                on_failure_action,
                failure_jump_id,
                card_id,
                stop_checker,
                params,
                detail=f"OCR引擎初始化异常: {e}",
            )

        # 2. 捕获窗口截图
        # 【关键检查】在截图前再次检查停止信号
        if stop_checker and stop_checker():
            return False, '停止工作流', None

        # 【关键修复】在OCR执行前清除该卡片的旧OCR结果，防止复用旧数据
        try:
            from task_workflow.workflow_context import get_workflow_context
            context = get_workflow_context()
            context.clear_card_ocr_context(card_id)
        except Exception:
            pass

        if not target_hwnd or not PYWIN32_AVAILABLE:
            detail = f"需要有效的窗口句柄和窗口能力支持 (句柄: {target_hwnd}, pywin32: {PYWIN32_AVAILABLE})"
            logger.error(f"错误 [OCR截图] {detail}")
            return _handle_failure(
                on_failure_action,
                failure_jump_id,
                card_id,
                stop_checker,
                params,
                detail=detail,
            )

        if not win32gui.IsWindow(target_hwnd):
            detail = f"窗口句柄无效: {target_hwnd}"
            logger.error(f"错误 [OCR截图] {detail}")
            return _handle_failure(
                on_failure_action,
                failure_jump_id,
                card_id,
                stop_checker,
                params,
                detail=detail,
            )

        # 获取窗口信息并检查状态
        try:
            window_title = win32gui.GetWindowText(target_hwnd)
            window_rect = win32gui.GetWindowRect(target_hwnd)

            # 检查窗口是否被最小化
            if win32gui.IsIconic(target_hwnd):
                detail = "目标窗口已最小化"
                logger.error(f"[OCR] {detail}")
                return _handle_failure(
                    on_failure_action,
                    failure_jump_id,
                    card_id,
                    stop_checker,
                    params,
                    detail=detail,
                )

            # 检查窗口位置是否异常
            if window_rect[0] < -30000 or window_rect[1] < -30000:
                detail = f"目标窗口位置异常: {window_rect}"
                logger.error(f"[OCR] {detail}")
                return _handle_failure(
                    on_failure_action,
                    failure_jump_id,
                    card_id,
                    stop_checker,
                    params,
                    detail=detail,
                )

        except Exception:
            pass

        # 捕获窗口（插件引擎时截图池会走大漠截图，识别仍用 RapidOCR）
        window_image = _capture_window_for_ocr(target_hwnd, timeout=4.0)
        if window_image is None:
            detail = f"OCR截图失败，窗口句柄={target_hwnd}"
            logger.error(f"[OCR] {detail}")
            return _handle_failure(
                on_failure_action,
                failure_jump_id,
                card_id,
                stop_checker,
                params,
                detail=detail,
            )

        # 统一对齐到客户区
        window_image = _align_window_image_to_client_area(window_image, target_hwnd)
        if window_image is None or window_image.size == 0:
            detail = f"OCR截图数据无效，窗口句柄={target_hwnd}"
            logger.error(f"[OCR] {detail}")
            return _handle_failure(
                on_failure_action,
                failure_jump_id,
                card_id,
                stop_checker,
                params,
                detail=detail,
            )

        # 统一计算有效识别区域（指定区域无效时回退到整窗）
        roi_image, final_x, final_y, final_width, final_height, _region_desc = _extract_effective_ocr_roi(
            window_image=window_image,
            region_mode=region_mode,
            region_x=region_x,
            region_y=region_y,
            region_width=region_width,
            region_height=region_height,
        )
        if roi_image is None:
            detail = (
                f"无法提取OCR区域，区域模式={region_mode}，"
                f"区域=({region_x},{region_y},{region_width},{region_height})"
            )
            logger.error(f"[OCR] {detail}")
            return _handle_failure(
                on_failure_action,
                failure_jump_id,
                card_id,
                stop_checker,
                params,
                detail=detail,
            )



        # 5. 图像预处理
        ocr_image = roi_image

        # 6. 执行OCR识别
        if stop_checker and stop_checker():
            return False, '停止工作流', None

        # 执行OCR识别（统一OCR池入口）
        window_hwnd = target_hwnd if target_hwnd else 0
        try:
            results = _recognize_with_multiprocess_pool(
                window_title=window_title,
                window_hwnd=window_hwnd,
                image=ocr_image,
                scope_key=(int(final_x), int(final_y), int(final_width), int(final_height)),
                confidence=0.1,
            )
        except Exception as e:
            logger.error(f"[OCR] 识别失败: {e}")
            return _handle_failure(
                on_failure_action,
                failure_jump_id,
                card_id,
                stop_checker,
                params,
                detail=f"OCR识别失败: {e}",
            )

        # OCR识别完成后检查停止请求
        if stop_checker and stop_checker():
            return False, '停止工作流', None

        # 【内存泄漏修复】OCR识别完成后立即清理图像数据
        try:
            if ocr_image is not None:
                del ocr_image
                ocr_image = None
            if roi_image is not None:
                del roi_image
                roi_image = None
        except Exception:
            pass

        # 根据是否有目标文字使用不同的置信度阈值
        if not target_text:
            ocr_results = [r for r in results if r.get('confidence', 0) >= 0.3]
        else:
            ocr_results = [r for r in results if r.get('confidence', 0) >= confidence_threshold]
        _cache_ocr_result_snapshot(
            card_id,
            ocr_results,
            target_text=target_text,
            match_mode=match_mode,
            region_offset=(final_x, final_y),
            window_hwnd=target_hwnd,
        )

        # 6. 处理多组文字识别逻辑
        if text_recognition_mode == '多组文字':
            return _handle_multi_text_recognition(
                ocr_results, text_groups, match_mode, card_id,
                final_x, final_y, on_success_action, success_jump_id,
                on_failure_action, failure_jump_id, reset_clicked_texts_on_next_run,
                stop_checker, recognition_type, enable_compare, target_number, compare_mode,
                params
            )
        else:
            # 单组文字识别逻辑
            # 数字识别模式
            if recognition_type == '仅识别数字':
                # 从所有OCR结果中提取数字
                all_numbers = []
                for result in ocr_results:
                    text = result.get('text', '')
                    number = _extract_number_from_text(text)
                    if number is not None:
                        all_numbers.append({
                            'number': number,
                            'text': text,
                            'result': result
                        })

                if not all_numbers:
                    try:
                        from task_workflow.workflow_context import get_workflow_context
                        context = get_workflow_context()
                        context.clear_card_ocr_context(card_id)
                    except Exception:
                        pass
                    return _handle_failure(
                        on_failure_action,
                        failure_jump_id,
                        card_id,
                        stop_checker,
                        params,
                        detail=_build_ocr_number_failure_detail(all_numbers),
                    )

                # 如果有目标数字
                if target_number:
                    try:
                        expected_num = float(target_number)

                        if enable_compare:
                            found_match = False
                            matched_number_info = None

                            for num_info in all_numbers:
                                recognized_num = num_info['number']
                                if _compare_numbers(recognized_num, expected_num, compare_mode):
                                    found_match = True
                                    matched_number_info = num_info
                                    break

                            if not found_match:
                                try:
                                    from task_workflow.workflow_context import get_workflow_context
                                    context = get_workflow_context()
                                    context.clear_card_ocr_context(card_id)
                                except Exception:
                                    pass
                                return _handle_failure(
                                    on_failure_action,
                                    failure_jump_id,
                                    card_id,
                                    stop_checker,
                                    params,
                                    detail=_build_ocr_number_failure_detail(
                                        all_numbers,
                                        target_number=str(target_number or ""),
                                        compare_mode=compare_mode,
                                        enable_compare=True,
                                    ),
                                )

                            target_result = matched_number_info['result']
                            found_target = True
                        else:
                            found_match = False
                            matched_number_info = None

                            for num_info in all_numbers:
                                recognized_num = num_info['number']
                                if recognized_num == expected_num:
                                    found_match = True
                                    matched_number_info = num_info
                                    break

                            if not found_match:
                                try:
                                    from task_workflow.workflow_context import get_workflow_context
                                    context = get_workflow_context()
                                    context.clear_card_ocr_context(card_id)
                                except Exception:
                                    pass
                                return _handle_failure(
                                    on_failure_action,
                                    failure_jump_id,
                                    card_id,
                                    stop_checker,
                                    params,
                                    detail=_build_ocr_number_failure_detail(
                                        all_numbers,
                                        target_number=str(target_number or ""),
                                        compare_mode=compare_mode,
                                        enable_compare=False,
                                    ),
                                )

                            target_result = matched_number_info['result']
                            found_target = True

                    except ValueError:
                        detail = f"无法将目标数字 '{target_number}' 转换为数字"
                        logger.error(f"[OCR] {detail}")
                        return _handle_failure(
                            on_failure_action,
                            failure_jump_id,
                            card_id,
                            stop_checker,
                            params,
                            detail=detail,
                        )
                else:
                    target_result = all_numbers[0]['result']
                    found_target = True

            else:
                # 文字识别逻辑
                found_target, target_result = _check_target_text_with_position(ocr_results, target_text, match_mode)

            if found_target:
                # 检查停止信号
                if stop_checker and stop_checker():
                    return False, '停止工作流', None

                # 循环执行时清理上下文
                if on_success_action == '继续执行本步骤':
                    try:
                        from task_workflow.workflow_context import get_workflow_context
                        context = get_workflow_context()
                        context.clear_card_ocr_context(card_id)
                    except Exception:
                        pass

                should_save_context = _should_save_ocr_context(card_id, params)

                if should_save_context:
                    try:
                        from task_workflow.workflow_context import set_ocr_results, get_workflow_context
                        set_ocr_results(card_id, ocr_results)
                        context = get_workflow_context()
                        context.set_card_data(card_id, 'ocr_target_text', target_text)
                        context.set_card_data(card_id, 'ocr_match_mode', match_mode)
                        context.set_card_data(card_id, 'ocr_region_offset', (final_x, final_y))
                        context.set_card_data(card_id, 'ocr_window_hwnd', target_hwnd)

                        _remember_ocr_source_for_jump(context, success_jump_id, card_id)
                    except Exception:
                        pass

                return _handle_success(on_success_action, success_jump_id, card_id, stop_checker, params)
            else:
                # OCR识别失败时清除上下文数据
                try:
                    from task_workflow.workflow_context import get_workflow_context
                    context = get_workflow_context()
                    context.clear_card_ocr_context(card_id)
                except Exception:
                    pass

                return _handle_failure(
                    on_failure_action,
                    failure_jump_id,
                    card_id,
                    stop_checker,
                    params,
                    detail=_build_ocr_text_failure_detail(ocr_results, target_text, match_mode),
                )

    except Exception as e:
        logger.error(f"OCR区域识别任务执行失败: {e}", exc_info=True)

        # 异常时清除上下文数据
        try:
            from task_workflow.workflow_context import get_workflow_context
            context = get_workflow_context()
            context.clear_card_ocr_context(card_id)
        except Exception:
            pass

        return _handle_failure(
            on_failure_action,
            failure_jump_id,
            card_id,
            stop_checker,
            params,
            detail=str(e),
        )

    finally:

        # 【高频OCR内存优化】更激进的内存清理
        try:
            # 立即删除本次的图像数据
            if window_image is not None:
                del window_image
                window_image = None
            if roi_image is not None:
                del roi_image
                roi_image = None
            if ocr_image is not None:
                del ocr_image
                ocr_image = None

            # 【内存泄漏修复】清理OCR结果变量（如果存在且未被返回）
            # 注意：这里的results可能已被return语句使用，只清理局部变量
            try:
                if 'results' in dir() and results is not None:
                    del results
            except Exception:
                pass

            # 清理counters中保存的历史图像
            for key in ['__last_window_image__', '__last_roi_image__', '__last_ocr_image__']:
                if key in counters:
                    try:
                        del counters[key]
                    except Exception:
                        pass

        except Exception:
            pass


# 旧的DPI处理函数已移除，现在使用统一DPI处理器


def _extract_region(image: np.ndarray, x: int, y: int, width: int, height: int) -> Optional[np.ndarray]:
    """从图片中提取指定区域"""
    try:
        img_h, img_w = image.shape[:2]

        # 确保起始坐标在图像范围内
        x = max(0, min(x, img_w - 1))
        y = max(0, min(y, img_h - 1))

        # 确保区域不超出图像边界
        max_width = img_w - x
        max_height = img_h - y
        width = min(max(1, width), max_width)
        height = min(max(1, height), max_height)

        if width <= 0 or height <= 0:
            return None

        # 提取区域
        roi = image[y:y+height, x:x+width]

        if roi.size == 0:
            return None

        return roi

    except Exception:
        return None

# 已移除不再使用的OCR函数，现在直接使用统一OCR服务





def _extract_number_from_text(text: str) -> Optional[float]:
    """
    从文本中提取数字

    支持格式：
    - 整数：123
    - 小数：123.45
    - 带逗号：1,234.56
    - 负数：-100
    - 带符号：+50
    - 带货币符号：$100, ¥100, 100元
    - 百分比：95.5%

    Args:
        text: 包含数字的文本

    Returns:
        提取的数字，如果无法提取则返回None
    """
    import re

    try:
        # 移除常见的货币符号和单位
        cleaned_text = text.replace('$', '').replace('¥', '').replace('元', '')
        cleaned_text = cleaned_text.replace('%', '').replace(',', '')

        # 提取数字（支持整数、小数、负数）
        # 匹配模式：可选的正负号 + 数字 + 可选的小数部分
        pattern = r'[-+]?\d+\.?\d*'
        match = re.search(pattern, cleaned_text)

        if match:
            number_str = match.group()
            return float(number_str)
        else:
            return None

    except Exception:
        return None


def _compare_numbers(recognized_value: float, expected_value: float, compare_mode: str) -> bool:
    """比对两个数值"""
    try:
        if compare_mode == "等于":
            return recognized_value == expected_value
        elif compare_mode == "大于":
            return recognized_value > expected_value
        elif compare_mode == "小于":
            return recognized_value < expected_value
        elif compare_mode == "大于等于":
            return recognized_value >= expected_value
        elif compare_mode == "小于等于":
            return recognized_value <= expected_value
        else:
            return False
    except Exception:
        return False


def _check_target_text_with_position(results: List[dict], target_text: str, match_mode: str) -> Tuple[bool, Optional[dict]]:
    """检查OCR结果中是否包含目标文字，并返回位置信息"""
    if not results:
        return False, None

    # 如果没有指定目标文字，只要识别到任何文字就算成功
    if not target_text:
        return len(results) > 0, results[0] if results else None

    try:
        for result in results:
            text = result.get('text', '')
            if match_mode == "包含":
                if target_text in text:
                    return True, result
            elif match_mode == "完全匹配":
                if target_text == text.strip():
                    return True, result
            else:
                if target_text in text:
                    return True, result

        return False, None
    except Exception:
        return False, None

def _format_ocr_text_preview(results: List[dict], limit: int = 5) -> str:
    preview_items: List[str] = []
    for result in results or []:
        text = str((result or {}).get('text', '') or '').strip()
        if not text or text in preview_items:
            continue
        preview_items.append(text)

    if not preview_items:
        return "无"

    clipped_items = [f"'{text[:40]}'" for text in preview_items[:limit]]
    preview = "，".join(clipped_items)
    if len(preview_items) > limit:
        preview += f" 等{len(preview_items)}项"
    return preview


def _build_ocr_text_failure_detail(results: List[dict], target_text: str, match_mode: str) -> str:
    preview = _format_ocr_text_preview(results)
    if not results:
        return "OCR未识别到任何满足条件的文本"
    if not target_text:
        return f"OCR已识别到文本，但未命中当前成功条件，识别结果={preview}"
    return f"未匹配到目标文字，匹配方式={match_mode}，目标='{target_text}'，识别结果={preview}"


def _build_ocr_number_failure_detail(
    all_numbers: List[Dict[str, Any]],
    target_number: str = "",
    *,
    compare_mode: str = "等于",
    enable_compare: bool = False,
) -> str:
    if not all_numbers:
        return "OCR结果中未识别到任何数字"

    recognized_numbers = "，".join(
        str(item.get('text') if item.get('text') not in (None, "") else item.get('number'))
        for item in all_numbers[:5]
    )
    if len(all_numbers) > 5:
        recognized_numbers += f" 等{len(all_numbers)}项"

    if target_number:
        if enable_compare:
            return (
                f"未找到满足数字条件的结果，比较方式={compare_mode}，目标={target_number}，"
                f"识别结果={recognized_numbers}"
            )
        return f"未匹配到目标数字，目标={target_number}，识别结果={recognized_numbers}"

    return f"OCR已识别到数字，但未命中当前成功条件，识别结果={recognized_numbers}"


def _handle_success(action: str, jump_id: Optional[int], card_id: Optional[int], stop_checker=None, params: Dict[str, Any] = None) -> Tuple[bool, str, Optional[int]]:
    """处理成功情况"""
    if stop_checker and stop_checker():
        return False, '停止工作流', None

    from .task_utils import resolve_step_action_result

    return resolve_step_action_result(
        success=True,
        action=action,
        jump_id=jump_id,
        card_id=card_id,
    )

def _handle_failure(
    action: str,
    jump_id: Optional[int],
    card_id: Optional[int],
    stop_checker=None,
    params: Dict[str, Any] = None,
    detail: Any = "",
) -> Tuple[Any, ...]:
    """处理失败情况"""
    if stop_checker and stop_checker():
        return False, '停止工作流', None

    from .task_utils import resolve_step_action_result

    return resolve_step_action_result(
        success=False,
        action=action,
        jump_id=jump_id,
        card_id=card_id,
        detail=detail,
    )


def _cache_ocr_result_snapshot(
    card_id: Optional[int],
    results,
    *,
    target_text: Any = "",
    match_mode: Any = "包含",
    region_offset=None,
    window_hwnd: Any = None,
) -> None:
    if card_id is None:
        return
    try:
        from task_workflow.workflow_context import get_workflow_context

        context = get_workflow_context()
        snapshot_fn = getattr(context, "set_ocr_result_snapshot", None)
        if callable(snapshot_fn):
            snapshot_fn(
                card_id,
                results if isinstance(results, list) else [],
                target_text=target_text,
                match_mode=match_mode,
                region_offset=region_offset,
                window_hwnd=window_hwnd,
            )
    except Exception:
        pass


def _handle_multi_text_recognition(ocr_results, text_groups, match_mode, card_id,
                                 final_x, final_y, on_success_action, success_jump_id,
                                 on_failure_action, failure_jump_id, reset_clicked_texts_on_next_run=False,
                                 stop_checker=None, recognition_type='识别所有文本',
                                 enable_compare=False, compare_value='', compare_mode='等于',
                                 params: Dict[str, Any] = None):
    """处理多组文字识别逻辑（支持数字识别和比对）"""
    try:
        from task_workflow.workflow_context import get_workflow_context, set_ocr_results
        context = get_workflow_context()

        # 获取当前识别状态
        text_groups_state, current_index, clicked_texts = context.get_multi_text_recognition_state(card_id)

        # 检查是否需要重置已识别文字记录
        if reset_clicked_texts_on_next_run:
            context.set_multi_text_recognition_state(card_id, text_groups, 0, [])
            text_groups_state, current_index, clicked_texts = context.get_multi_text_recognition_state(card_id)
        elif not text_groups_state:
            context.set_multi_text_recognition_state(card_id, text_groups, 0, [])
            text_groups_state, current_index, clicked_texts = context.get_multi_text_recognition_state(card_id)
        else:
            context.set_card_data(card_id, 'multi_text_groups', text_groups)

        # 检查是否已完成所有组
        if current_index >= len(text_groups):
            context.clear_card_ocr_data(card_id)
            return _handle_success(on_success_action, success_jump_id, card_id, stop_checker, params)

        # 获取当前要识别的文字
        current_target_text = text_groups[current_index]

        # 过滤掉已点击的文字
        filtered_results = []
        for result in ocr_results:
            result_text = result.get('text', '')
            if result_text not in clicked_texts:
                filtered_results.append(result)
        _cache_ocr_result_snapshot(
            card_id,
            filtered_results,
            target_text=current_target_text,
            match_mode=match_mode,
            region_offset=(final_x, final_y),
        )

        # 根据识别类型处理
        if recognition_type == '仅识别数字':
            # 从过滤后的结果中提取数字
            all_numbers = []
            for result in filtered_results:
                text = result.get('text', '')
                number = _extract_number_from_text(text)
                if number is not None:
                    all_numbers.append({
                        'number': number,
                        'text': text,
                        'result': result
                    })

            if not all_numbers:
                found_target = False
                target_result = None
            else:
                if enable_compare and current_target_text:
                    try:
                        expected_num = float(current_target_text)
                        found_match = False
                        matched_number_info = None

                        for num_info in all_numbers:
                            recognized_num = num_info['number']
                            if _compare_numbers(recognized_num, expected_num, compare_mode):
                                found_match = True
                                matched_number_info = num_info
                                break

                        if found_match:
                            target_result = matched_number_info['result']
                            found_target = True
                        else:
                            found_target = False
                            target_result = None

                    except ValueError:
                        found_target = False
                        target_result = None
                else:
                    target_result = all_numbers[0]['result']
                    found_target = True
        else:
            # 原有的文字匹配逻辑
            found_target, target_result = _check_target_text_with_position(filtered_results, current_target_text, match_mode)

        if found_target:
            if stop_checker and stop_checker():
                return False, '停止工作流', None

            should_save_context = _should_save_ocr_context(card_id, params)

            if should_save_context:
                set_ocr_results(card_id, filtered_results)
                context.set_card_data(card_id, 'ocr_target_text', current_target_text)
                context.set_card_data(card_id, 'ocr_match_mode', match_mode)
                context.set_card_data(card_id, 'ocr_region_offset', (final_x, final_y))

                _remember_ocr_source_for_jump(context, success_jump_id, card_id)

            clicked_text = target_result.get('text', '')
            clicked_texts.append(clicked_text)

            next_index = current_index + 1
            context.set_multi_text_recognition_state(card_id, text_groups, next_index, clicked_texts)

            return _handle_success(on_success_action, success_jump_id, card_id, stop_checker, params)
        else:
            next_index = current_index + 1
            if next_index < len(text_groups):
                context.set_multi_text_recognition_state(card_id, text_groups, next_index, clicked_texts)
                return _handle_multi_text_recognition(
                    ocr_results, text_groups, match_mode, card_id,
                    final_x, final_y, on_success_action, success_jump_id,
                    on_failure_action, failure_jump_id, reset_clicked_texts_on_next_run,
                    stop_checker, recognition_type, enable_compare, compare_value, compare_mode,
                    params
                )
            else:
                context.set_multi_text_recognition_state(card_id, text_groups, 0, [])

            try:
                context.clear_card_ocr_context(card_id)
            except Exception:
                pass

            if recognition_type == '仅识别数字':
                all_numbers = []
                for result in filtered_results:
                    text = result.get('text', '')
                    number = _extract_number_from_text(text)
                    if number is not None:
                        all_numbers.append({
                            'number': number,
                            'text': text,
                        })
                detail = _build_ocr_number_failure_detail(
                    all_numbers,
                    target_number="、".join(str(item) for item in text_groups if str(item).strip()),
                    compare_mode=compare_mode,
                    enable_compare=enable_compare,
                )
            else:
                detail = (
                    f"多组文字识别未命中任何目标组，目标组={text_groups}，"
                    f"识别结果={_format_ocr_text_preview(filtered_results)}"
                )

            return _handle_failure(
                on_failure_action,
                failure_jump_id,
                card_id,
                stop_checker,
                params,
                detail=detail,
            )

    except Exception as e:
        try:
            context.clear_card_ocr_context(card_id)
        except Exception:
            pass
        return _handle_failure(
            on_failure_action,
            failure_jump_id,
            card_id,
            stop_checker,
            params,
            detail=str(e),
        )

def get_params_definition() -> Dict[str, Dict[str, Any]]:
    """获取参数定义"""
    return {
        "---region_settings---": {"type": "separator", "label": "识别区域设置"},
        "region_mode": {
            "label": "区域模式",
            "type": "select",
            "options": ["指定区域", "整个窗口"],
            "default": "指定区域",
            "tooltip": "选择如何确定OCR识别区域"
        },

        "---coordinate_mode---": {
            "type": "separator",
            "label": "指定区域模式",
            "condition": {"param": "region_mode", "value": "指定区域"}
        },
        "ocr_region_selector_tool": {
            "label": "框选识别区域",
            "type": "button",
            "button_text": "框选识别指定区域",
            "tooltip": "点击后在绑定窗口中框选OCR识别区域，自动设置识别区域坐标",
            "condition": {"param": "region_mode", "value": "指定区域"},
            "widget_hint": "ocr_region_selector"
        },

        "region_coordinates": {
            "label": "指定的区域",
            "type": "text",
            "default": "未指定识别区域",
            "readonly": True,
            "tooltip": "显示当前选择的识别区域坐标和尺寸（由框选工具自动设置）",
            "condition": {"param": "region_mode", "value": "指定区域"}
        },
        # 隐藏的坐标参数，用于内部逻辑（只在指定区域模式下存在）
        "region_x": {
            "type": "hidden",
            "default": 0,
            "condition": {"param": "region_mode", "value": "指定区域"}
        },
        "region_y": {
            "type": "hidden",
            "default": 0,
            "condition": {"param": "region_mode", "value": "指定区域"}
        },
        "region_width": {
            "type": "hidden",
            "default": 0,
            "condition": {"param": "region_mode", "value": "指定区域"}
        },
        "region_height": {
            "type": "hidden",
            "default": 0,
            "condition": {"param": "region_mode", "value": "指定区域"}
        },
        "region_hwnd": {
            "type": "hidden",
            "default": 0,
            "condition": {"param": "region_mode", "value": "指定区域"}
        },
        "region_window_title": {
            "type": "hidden",
            "default": "",
            "condition": {"param": "region_mode", "value": "指定区域"}
        },
        "region_window_class": {
            "type": "hidden",
            "default": "",
            "condition": {"param": "region_mode", "value": "指定区域"}
        },
        "region_client_width": {
            "type": "hidden",
            "default": 0,
            "condition": {"param": "region_mode", "value": "指定区域"}
        },
        "region_client_height": {
            "type": "hidden",
            "default": 0,
            "condition": {"param": "region_mode", "value": "指定区域"}
        },
        "test_ocr_button": {
            "label": "测试识别",
            "type": "button",
            "button_text": "测试输出识别文字",
            "tooltip": "点击测试当前区域的OCR识别，将识别结果输出到记事本",
            "action": "test_ocr_output"
        },

        "---target_text---": {"type": "separator", "label": "目标文字设置"},
        "recognition_type": {
            "label": "识别类型",
            "type": "select",
            "options": ["识别所有文本", "仅识别数字"],
            "default": "识别所有文本",
            "tooltip": "选择识别所有文本还是只识别数字"
        },
        "target_number": {
            "label": "目标数字",
            "type": "str",
            "default": "",
            "tooltip": "指定要识别的目标数字，留空则识别所有数字",
            "condition": {"param": "recognition_type", "value": "仅识别数字"}
        },
        "enable_compare": {
            "label": "启用比对",
            "type": "bool",
            "default": False,
            "tooltip": "启用后将识别的数字与目标数字进行比较（大于、小于等）",
            "condition": {"param": "recognition_type", "value": "仅识别数字"}
        },
        "compare_mode": {
            "label": "比对方式",
            "type": "select",
            "options": ["等于", "大于", "小于", "大于等于", "小于等于"],
            "default": "等于",
            "tooltip": "选择如何比对识别值与目标数字",
            "condition": {
                "param": "recognition_type",
                "value": "仅识别数字",
                "and": {"param": "enable_compare", "value": True}
            }
        },
        "text_recognition_mode": {
            "label": "识别模式",
            "type": "select",
            "options": ["单组文字", "多组文字"],
            "default": "单组文字",
            "tooltip": "选择单组文字识别还是多组文字循环识别\n多组文字格式：用中文逗号（，）或英文逗号（,）分隔，例如：登录，确认，提交",
            "condition": {"param": "recognition_type", "value": "识别所有文本"}
        },
        "target_text": {
            "label": "需要识别的文字",
            "type": "str",
            "default": "",
            "tooltip": "指定要查找的目标文字，留空则识别所有文字",
            "condition": {
                "param": "recognition_type",
                "value": "识别所有文本",
                "and": {"param": "text_recognition_mode", "value": "单组文字"}
            }
        },
        "target_text_groups": {
            "label": "多组文字列表",
            "type": "str",
            "default": "",
            "tooltip": "用逗号分隔多组文字，以及中文逗号（，）和英文逗号（,）",
            "condition": {
                "param": "recognition_type",
                "value": "识别所有文本",
                "and": {"param": "text_recognition_mode", "value": "多组文字"}
            }
        },
        "reset_clicked_texts_on_next_run": {
            "label": "下次执行重置已识别文字记录",
            "type": "bool",
            "default": False,
            "tooltip": "启用后，每次执行OCR多组文字识别时会清除已点击文字的记忆；不启用则保持记忆直到所有文字执行完成",
            "condition": {
                "param": "recognition_type",
                "value": "识别所有文本",
                "and": {"param": "text_recognition_mode", "value": "多组文字"}
            }
        },
        "match_mode": {
            "label": "匹配模式",
            "type": "select",
            "options": ["包含", "完全匹配"],
            "default": "包含",
            "tooltip": "文字匹配的方式",
            "condition": {"param": "recognition_type", "value": "识别所有文本"}
        },


        "---ocr_settings---": {"type": "separator", "label": "OCR设置"},
        "confidence_threshold": {
            "label": "置信度阈值",
            "type": "float",
            "default": 0.8,
            "min": 0.1,
            "max": 1.0,
            "step": 0.1,
            "tooltip": "OCR识别的最低置信度，降低可识别更多文字但可能增加误识别"
        },
        "workflow_retry_interval": {
            "label": "工作流重试间隔(秒)",
            "type": "float",
            "default": 0.5,  # 【关键修复】从0秒改为0.5秒，防止循环过快导致内存泄露
            "min": 0.1,  # 最小100ms，防止设置为0导致CPU和内存压力
            "max": 5.0,
            "step": 0.1,
            "tooltip": "【关键】选择'继续执行本步骤'时的工作流级重试间隔\n• 0.5秒=推荐（防止内存泄露）\n• 0.1-0.3秒=快速但可能导致内存压力\n• >1秒=降低CPU和内存占用\n\n[警告] 设置过小可能导致一分钟内闪退!"
        },



        "---next_step_delay---": {"type": "separator", "label": "下一步延迟执行"},
        "enable_next_step_delay": {
            "label": "启用下一步延迟执行",
            "type": "bool",
            "default": True,  # 【关键】OCR卡片默认开启延迟，防止连续OCR导致闪退
            "tooltip": "【推荐开启】执行完OCR后等待指定时间再执行下一步\n\n开启可防止连续OCR任务导致程序闪退"
        },
        "delay_mode": {
            "label": "延迟模式",
            "type": "select",
            "options": ["固定延迟", "随机延迟"],
            "default": "固定延迟",
            "tooltip": "选择固定延迟时间还是随机延迟时间",
            "condition": {"param": "enable_next_step_delay", "value": True}
        },
        "fixed_delay": {
            "label": "固定延迟 (秒)",
            "type": "float",
            "default": 0.5,  # 【关键】OCR卡片默认0.5秒延迟
            "min": 0.1,
            "max": 60.0,
            "decimals": 2,
            "tooltip": "固定延迟的时间（秒）\n\n推荐值: 0.3-0.5秒",
            "condition": {
                "param": "delay_mode",
                "value": "固定延迟",
                "and": {"param": "enable_next_step_delay", "value": True}
            }
        },
        "min_delay": {
            "label": "最小延迟 (秒)",
            "type": "float",
            "default": 0.3,
            "min": 0.1,
            "max": 60.0,
            "decimals": 2,
            "tooltip": "随机延迟的最小时间（秒）",
            "condition": {
                "param": "delay_mode",
                "value": "随机延迟",
                "and": {"param": "enable_next_step_delay", "value": True}
            }
        },
        "max_delay": {
            "label": "最大延迟 (秒)",
            "type": "float",
            "default": 0.8,
            "min": 0.1,
            "max": 60.0,
            "decimals": 2,
            "tooltip": "随机延迟的最大时间（秒）",
            "condition": {
                "param": "delay_mode",
                "value": "随机延迟",
                "and": {"param": "enable_next_step_delay", "value": True}
            }
        },

        "---post_execute---": {"type": "separator", "label": "执行后操作"},
        "on_success": {
            "type": "select",
            "label": "找到文字时",
            "options": ["执行下一步", "跳转到步骤", "停止工作流", "继续执行本步骤"],
            "default": "执行下一步",
            "tooltip": "成功识别到目标文字时的操作"
        },
        "success_jump_target_id": {
            "type": "int",
            "label": "成功跳转目标 ID",
            "required": False,
            "widget_hint": "card_selector",
            "condition": {"param": "on_success", "value": "跳转到步骤"}
        },
        "on_failure": {
            "type": "select",
            "label": "未找到文字时",
            "options": ["执行下一步", "跳转到步骤", "停止工作流", "继续执行本步骤"],
            "default": "执行下一步",
            "tooltip": "未识别到目标文字时的操作"
        },
        "failure_jump_target_id": {
            "type": "int",
            "label": "失败跳转目标 ID",
            "required": False,
            "widget_hint": "card_selector",
            "condition": {"param": "on_failure", "value": "跳转到步骤"}
        }
    }


def test_ocr_output(params: Dict[str, Any], **kwargs) -> bool:
    """
    测试OCR识别并输出结果到记事本

    Args:
        params: 当前卡片的参数
        **kwargs: 其他参数，包括target_hwnd等
    """
    import tempfile
    import subprocess

    target_hwnd = kwargs.get('target_hwnd')
    full_image = None
    roi_image = None
    results = None
    output_lines = None
    output_text = None

    try:
        # 获取窗口句柄
        if not target_hwnd:
            logger.error("[OCR测试] 未找到目标窗口句柄")
            return False

        binding_mismatch_detail = get_recorded_region_binding_mismatch_detail(params, target_hwnd)
        if binding_mismatch_detail:
            logger.error(f"[OCR测试] {binding_mismatch_detail}")
            return False

        # 获取窗口标题
        window_title = "未知窗口"
        if PYWIN32_AVAILABLE:
            try:
                window_title = win32gui.GetWindowText(target_hwnd)
            except Exception:
                pass

        logger.info(f"[OCR测试] 开始测试OCR，目标窗口: {window_title} (HWND: {target_hwnd})")

        # 统一解析区域参数
        region_mode, region_x, region_y, region_width, region_height = _resolve_region_params(params)

        # 捕获窗口图像
        if not CAPTURE_AVAILABLE:
            logger.error("[OCR测试] 窗口捕获功能不可用")
            return False

        full_image = _capture_window_for_ocr(target_hwnd, timeout=4.0)
        if full_image is None:
            logger.error("[OCR测试] 无法捕获窗口图像")
            return False

        # 统一对齐截图尺寸
        full_image = _align_window_image_to_client_area(full_image, target_hwnd, diag_prefix="[OCR测试-诊断]")
        if full_image is None or full_image.size == 0:
            logger.error("[OCR测试] 对齐后的窗口图像无效")
            return False

        # 统一提取有效ROI（指定区域无效时回退整窗）
        roi_image, final_x, final_y, final_width, final_height, region_desc = _extract_effective_ocr_roi(
            window_image=full_image,
            region_mode=region_mode,
            region_x=region_x,
            region_y=region_y,
            region_width=region_width,
            region_height=region_height,
            fallback_log_prefix="[OCR测试]",
        )
        logger.info(f"[OCR测试] 使用区域: {region_desc}")

        if roi_image is None or roi_image.size == 0:
            logger.error("[OCR测试] 提取的区域为空")
            return False

        logger.info("[OCR测试] 使用本地多进程OCR池执行识别...")
        try:
            results = _recognize_with_multiprocess_pool(
                window_title=window_title if window_title else "测试窗口",
                window_hwnd=target_hwnd if target_hwnd else 0,
                image=roi_image,
                scope_key=(int(final_x), int(final_y), int(final_width), int(final_height)),
                confidence=0.1,
            )
        except Exception as e:
            logger.error(f"[OCR测试] 多进程OCR识别失败: {e}")
            results = []

        if not results:
            logger.info("[OCR测试] 未识别到任何文字")
            # 仍然输出空结果到记事本
            results = []

        logger.info(f"[OCR测试] 识别完成，找到 {len(results)} 个文本区域")

        # 格式化输出
        output_lines = []
        output_lines.append("=" * 60)
        output_lines.append("OCR识别测试结果")
        output_lines.append("=" * 60)
        output_lines.append(f"窗口: {window_title}")
        output_lines.append(f"区域: {region_desc}")
        output_lines.append(f"识别时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        output_lines.append(f"识别数量: {len(results)} 个文本")
        output_lines.append("=" * 60)
        output_lines.append("")

        if results:
            # 按置信度排序
            sorted_results = sorted(results, key=lambda x: x.get('confidence', 0), reverse=True)

            for i, result in enumerate(sorted_results, 1):
                text = result.get('text', '')
                confidence = result.get('confidence', 0)
                bbox = result.get('bbox', [])

                output_lines.append(f"{i}. 文字: {text}")
                output_lines.append(f"   置信度: {confidence:.3f}")
                if bbox:
                    output_lines.append(f"   位置: {bbox}")
                output_lines.append("")
        else:
            output_lines.append("未识别到任何文字")
            output_lines.append("")
            output_lines.append("建议:")
            output_lines.append("1. 检查区域是否包含文字")
            output_lines.append("2. 降低置信度阈值")
            output_lines.append("3. 确保文字清晰可见")

        output_text = "\n".join(output_lines)

        # 写入临时文件并用记事本打开
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', suffix='.txt', delete=False) as f:
            f.write(output_text)
            temp_file = f.name

        # 用记事本打开
        subprocess.Popen(['notepad.exe', temp_file])

        logger.info(f"[OCR测试] 成功输出 {len(results)} 个文本到记事本")
        return True

    except Exception as e:
        logger.error(f"[OCR测试] 测试失败: {e}", exc_info=True)
        return False
    finally:
        # 测试按钮路径只清理当前轮次缓存，不销毁截图引擎，避免连续测试反复冷启动导致WGC不稳定
        try:
            if roi_image is not None:
                del roi_image
                roi_image = None
            if full_image is not None:
                del full_image
                full_image = None
            if results is not None:
                del results
                results = None
            if output_lines is not None:
                output_lines.clear()
                del output_lines
                output_lines = None
            if output_text is not None:
                del output_text
                output_text = None
        except Exception:
            pass

        try:
            from utils.capture.screenshot_helper import clear_screenshot_cache
            clear_screenshot_cache(target_hwnd if target_hwnd else None)
        except Exception:
            pass

        try:
            from services.multiprocess_ocr_pool import get_existing_multiprocess_ocr_pool
            pool = get_existing_multiprocess_ocr_pool()
            if pool is not None:
                try:
                    pool.cleanup_all_processes()
                except Exception:
                    pass
        except Exception:
            pass

        try:
            from services.screenshot_pool import clear_screenshot_runtime_state
            clear_screenshot_runtime_state(hwnd=target_hwnd if target_hwnd else None)
        except Exception:
            pass


if __name__ == '__main__':
    # 测试代码
    logging.basicConfig(level=logging.DEBUG)
    
    # 测试OCR引擎初始化
    engine = _get_ocr_engine()
    if engine:
        logger.info(f"OCR引擎初始化成功: {engine['engine']}")
    else:
        logger.error("OCR引擎初始化失败")
    
    # 测试参数定义
    params_def = get_params_definition()
    logger.info(f"参数定义包含 {len(params_def)} 个参数")




