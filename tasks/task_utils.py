# -*- coding: utf-8 -*-
"""
任务工具模块 - 提供统一的延迟处理、跳转处理、参数定义和智能截图
"""
import logging
import time
import random
import cv2
import numpy as np
import sys
import os
import math
import threading
from pathlib import Path
from typing import Dict, Any, Tuple, Optional, List
from collections import OrderedDict
from task_workflow.task_result import validate_step_action, validate_card_target
from utils.window.hwnd_utils import as_hwnd
from utils.image_paths import get_image_path_resolver
from utils.precise_sleep import precise_sleep as _shared_precise_sleep
from utils.window.window_coordinate_common import (
    find_region_binding_equivalent_descendant,
    normalize_region_binding_hwnd,
)

logger = logging.getLogger(__name__)

REGION_BINDING_CLIENT_SIZE_TOLERANCE = 2


# ==================== 参数转换辅助 ====================


def coerce_bool(value: Any) -> bool:
    """校验现行布尔参数，不推测文本或数字的含义。"""
    if type(value) is bool:
        return value
    raise ValueError(f"布尔参数必须是布尔值: {value!r}")


def coerce_int(value: Any) -> int:
    """校验现行整数参数。"""
    if type(value) is int:
        return value
    raise ValueError(f"整数参数必须是整数: {value!r}")


def coerce_float(value: Any) -> float:
    """校验现行有限数值参数。"""
    if type(value) in (int, float) and math.isfinite(value):
        return float(value)
    raise ValueError(f"数值参数必须是有限数值: {value!r}")


def resolve_region_selection_params(
    params: Dict[str, Any],
    default_mode: str = "指定区域",
) -> Tuple[str, int, int, int, int]:
    """只读取现行的区域坐标字段；展示文本不参与执行。"""
    if any(key in params for key in ("region_x1", "region_y1", "region_x2", "region_y2")):
        raise ValueError("区域参数含旧字段，请先转换为现行工程格式")
    region_mode = params.get("region_mode", default_mode)
    values = tuple(params.get(key, 0) for key in ("region_x", "region_y", "region_width", "region_height"))
    if any(type(value) is not int for value in values):
        raise ValueError("区域坐标和尺寸必须是整数")
    return region_mode, *values



def get_recorded_region_binding_mismatch_detail(
    params: Dict[str, Any],
    target_hwnd: Optional[int],
) -> Optional[str]:
    """检查已录制区域所属窗口是否与当前执行窗口明显不一致。"""
    current_hwnd = as_hwnd(target_hwnd)
    if current_hwnd == 0:
        return None

    recorded_hwnd = as_hwnd(params.get("region_hwnd", 0))
    recorded_title = str(params.get("region_window_title", "") or "").strip()
    recorded_class = str(params.get("region_window_class", "") or "").strip()
    recorded_client_width = coerce_int(params.get("region_client_width", 0))
    recorded_client_height = coerce_int(params.get("region_client_height", 0))

    has_recording_binding = any((
        recorded_hwnd > 0,
        bool(recorded_title),
        bool(recorded_class),
        recorded_client_width > 0,
        recorded_client_height > 0,
    ))
    if not has_recording_binding:
        return None

    if recorded_hwnd > 0 and recorded_hwnd == current_hwnd:
        return None

    try:
        import win32gui
    except Exception:
        return None

    try:
        if not win32gui.IsWindow(current_hwnd):
            return None

        current_title = str(win32gui.GetWindowText(current_hwnd) or "").strip()
        current_class = str(win32gui.GetClassName(current_hwnd) or "").strip()
        current_client_rect = win32gui.GetClientRect(current_hwnd)
        current_client_width = max(0, int(current_client_rect[2] - current_client_rect[0]))
        current_client_height = max(0, int(current_client_rect[3] - current_client_rect[1]))
        recorded_hwnd_alive = bool(recorded_hwnd > 0 and win32gui.IsWindow(recorded_hwnd))
    except Exception:
        return None

    normalized_current_hwnd, normalized_current_title, normalized_current_class, normalized_current_width, normalized_current_height = (
        normalize_region_binding_hwnd(
            current_hwnd,
            title_hint=current_title,
            class_hint=current_class,
            client_width=current_client_width,
            client_height=current_client_height,
            client_size_tolerance=REGION_BINDING_CLIENT_SIZE_TOLERANCE,
        )
    )
    if as_hwnd(normalized_current_hwnd) == 0:
        normalized_current_hwnd = current_hwnd
    if not normalized_current_title:
        normalized_current_title = current_title
    if not normalized_current_class:
        normalized_current_class = current_class
    if normalized_current_width <= 0:
        normalized_current_width = current_client_width
    if normalized_current_height <= 0:
        normalized_current_height = current_client_height

    normalized_recorded_hwnd, normalized_recorded_title, normalized_recorded_class, normalized_recorded_width, normalized_recorded_height = (
        normalize_region_binding_hwnd(
            recorded_hwnd,
            title_hint=recorded_title,
            class_hint=recorded_class,
            client_width=recorded_client_width,
            client_height=recorded_client_height,
            client_size_tolerance=REGION_BINDING_CLIENT_SIZE_TOLERANCE,
        )
    )

    if recorded_hwnd_alive and (
        (recorded_title and normalized_recorded_title != recorded_title)
        or (recorded_class and normalized_recorded_class != recorded_class)
    ):
        # 旧句柄还在，但已经不是录制时的那扇窗口（重启后句柄复用很常见）。
        recorded_hwnd_alive = False
        normalized_recorded_hwnd = 0

    if normalized_recorded_hwnd > 0 and normalized_recorded_hwnd == normalized_current_hwnd:
        return None

    equivalent_descendant_hwnd = find_region_binding_equivalent_descendant(
        normalized_current_hwnd,
        title_hint=recorded_title,
        class_hint=recorded_class,
        client_width=recorded_client_width,
        client_height=recorded_client_height,
        client_size_tolerance=REGION_BINDING_CLIENT_SIZE_TOLERANCE,
    )
    if equivalent_descendant_hwnd > 0:
        return None

    recorded_compare_title = recorded_title or (
        normalized_recorded_title if normalized_recorded_hwnd > 0 else ""
    )
    recorded_compare_class = recorded_class or (
        normalized_recorded_class if normalized_recorded_hwnd > 0 else ""
    )
    recorded_compare_width = recorded_client_width if recorded_client_width > 0 else (
        normalized_recorded_width if normalized_recorded_width > 0 else 0
    )
    recorded_compare_height = recorded_client_height if recorded_client_height > 0 else (
        normalized_recorded_height if normalized_recorded_height > 0 else 0
    )

    same_title = bool(recorded_compare_title and recorded_compare_title == normalized_current_title)
    same_class = bool(recorded_compare_class and recorded_compare_class == normalized_current_class)
    same_client_size = (
        recorded_compare_width > 0
        and recorded_compare_height > 0
        and abs(recorded_compare_width - normalized_current_width) <= REGION_BINDING_CLIENT_SIZE_TOLERANCE
        and abs(recorded_compare_height - normalized_current_height) <= REGION_BINDING_CLIENT_SIZE_TOLERANCE
    )

    # 游戏重启后 HWND 必变，客户区尺寸也常变（全屏/窗口化/分辨率）。
    # 标题+类名能对上即视为同一窗口，不再要求客户区尺寸一致。
    if same_title and same_class:
        return None
    if same_title and same_client_size:
        return None
    if same_class and same_client_size:
        return None

    if not recorded_hwnd_alive:
        # 录制时的句柄已随进程退出。标题或类名任一能对上，即按同一窗口重连。
        if same_title or same_class:
            return None
        if not recorded_title and not recorded_class:
            return None

    detail_parts: List[str] = []
    if recorded_hwnd > 0:
        detail_parts.append(f"录制HWND={recorded_hwnd}")
    detail_parts.append(f"执行HWND={current_hwnd}")
    if recorded_title:
        detail_parts.append(f"录制标题={recorded_title}")
    if current_title:
        detail_parts.append(f"执行标题={current_title}")
    if recorded_class:
        detail_parts.append(f"录制类名={recorded_class}")
    if current_class:
        detail_parts.append(f"执行类名={current_class}")
    if recorded_client_width > 0 and recorded_client_height > 0:
        detail_parts.append(f"录制客户区={recorded_client_width}x{recorded_client_height}")
    detail_parts.append(f"执行客户区={current_client_width}x{current_client_height}")

    return (
        "识别区域录制所基于的窗口与当前执行窗口不一致，请在当前绑定窗口重新框选识别区域"
        f"（{'，'.join(detail_parts)}）"
    )


# ==================== 高精度睡眠函数 ====================

def precise_sleep(duration: float, **kwargs):
    """统一高精度睡眠入口。"""
    _shared_precise_sleep(duration, **kwargs)


# ==================== 图像读取功能 ====================

def safe_imread(image_path: str, flags=cv2.IMREAD_COLOR) -> Optional[np.ndarray]:
    """
    安全的图像读取函数，支持中文路径

    Args:
        image_path: 图片文件路径
        flags: cv2读取标志（如 cv2.IMREAD_COLOR, cv2.IMREAD_UNCHANGED 等）

    Returns:
        图像的numpy数组，失败返回None
    """
    try:
        from utils.match.template_preloader import get_global_preloader
        preloader = get_global_preloader()
        template = preloader.get_template(image_path)
        if template is not None:
            logger.debug(f"[性能优化] 使用缓存的模板: {image_path}")
            return template

        # 缓存未命中，正常加载
        if image_path.startswith('memory://'):
            image_bytes = None
            try:
                from task_workflow.resource_context import current_package_session

                package_session = current_package_session()
            except Exception:
                package_session = None

            if package_session is not None:
                try:
                    image_bytes = package_session.get_bytes(image_path)
                except Exception:
                    image_bytes = None
            else:
                try:
                    from utils.match.template_preloader import get_memory_image_provider

                    provider = get_memory_image_provider()
                    if callable(provider):
                        image_bytes = provider(image_path)
                except Exception:
                    image_bytes = None

            if not image_bytes:
                return None

            img_array = np.frombuffer(image_bytes, dtype=np.uint8)
        else:
            # 使用numpy fromfile + imdecode处理中文路径
            img_array = np.fromfile(image_path, dtype=np.uint8)

        if len(img_array) > 0:
            img = cv2.imdecode(img_array, flags)
            if img is not None:
                return img

        return None
    except Exception as e:
        logger.error(f"安全图像读取失败 {image_path}: {e}")
        return None


def capture_window_smart(
    hwnd: int,
    client_area_only: bool = True,
    use_cache: bool = False,
    allow_shared: bool = True,
    capture_timeout: float = 4.0
) -> Optional[np.ndarray]:
    """
    使用本地截图引擎捕获窗口。
    - 使用 WGC (Windows Graphics Capture)
    - GPU 硬件加速
    - 支持遮挡窗口和后台窗口

    Args:
        hwnd: 窗口句柄
        client_area_only: 是否只捕获客户区
        use_cache: 是否使用缓存（默认False，强制获取最新帧）

    Returns:
        BGR/BGRA 格式的 numpy 数组，失败返回 None
    """
    try:
        if allow_shared:
            from task_workflow.workflow_context import get_current_workflow_context
            context = get_current_workflow_context()
            shared_img = context.get_shared_capture(hwnd, client_area_only)
            if shared_img is not None:
                return shared_img.copy()

        from utils.capture.screenshot_helper import get_screenshot_engine, _capture_with_engine

        engine = get_screenshot_engine()
        from utils.capture.engine_ids import screenshot_engine_log_label
        logger.debug(f"[智能截图] 使用 {screenshot_engine_log_label(engine)} 截图引擎")

        img_bgr = _capture_with_engine(
            hwnd,
            client_area_only,
            engine,
            timeout=max(0.1, float(capture_timeout)),
        )
        return img_bgr

    except Exception as e:
        logger.error(f"智能截图失败: {e}", exc_info=True)
        return None


def capture_and_match_template_smart(
    target_hwnd: Optional[int],
    template: Optional[np.ndarray],
    confidence_threshold: float,
    template_key: Optional[str] = None,
    capture_timeout: float = 0.8,
    engine: Optional[str] = None,
    roi: Optional[Tuple[int, int, int, int]] = None,
    client_area_only: bool = True,
    use_cache: bool = False,
    template_scale: float = 1.0,
    mode: str = "彩色",
    rotation=0,
) -> Dict[str, Any]:
    """
    统一执行“截图+模板匹配”本地引擎调用。

    返回结构与 services.screenshot_pool.capture_and_match_template 保持一致，
    失败时至少包含 success=False 与 error 字段。
    """
    failed_response: Dict[str, Any] = {
        "success": False,
        "matched": False,
        "confidence": 0.0,
        "location": None,
        "error": "unknown_error",
    }

    def _read_float_env(name: str, default: float, min_value: float, max_value: float) -> float:
        raw = os.getenv(name)
        if raw is None:
            return max(min_value, min(max_value, float(default)))
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"截图配置 {name} 必须是有限数值") from exc
        if not math.isfinite(value) or not min_value <= value <= max_value:
            raise ValueError(f"截图配置 {name} 必须在 {min_value} 到 {max_value} 之间")
        return value

    def _read_int_env(name: str, default: int, min_value: int, max_value: int) -> int:
        raw = os.getenv(name)
        if raw is None:
            return max(min_value, min(max_value, int(default)))
        try:
            value = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"截图配置 {name} 必须是整数") from exc
        if not min_value <= value <= max_value:
            raise ValueError(f"截图配置 {name} 必须在 {min_value} 到 {max_value} 之间")
        return value

    def _is_transient_capture_error(error_text: Any) -> bool:
        text = str(error_text or "").strip().lower()
        if not text:
            return False
        if text in {"capture_failed", "capture_timeout", "capture_worker_limit_timeout", "request_timeout"}:
            return True
        if text.startswith("capture_failed:"):
            return True
        if "timeout" in text and ("capture" in text or "request" in text):
            return True
        return False

    try:
        if template is None:
            failed_response["error"] = "invalid_template"
            return failed_response
        if not isinstance(template, np.ndarray) or template.size == 0:
            failed_response["error"] = "invalid_template"
            return failed_response
        scale = coerce_float(template_scale)
        if not 0.25 <= scale <= 4.0:
            failed_response["error"] = "invalid_template_scale"
            return failed_response
        if abs(scale - 1.0) > 1e-6:
            height, width = template.shape[:2]
            resized_width = max(1, int(round(width * scale)))
            resized_height = max(1, int(round(height * scale)))
            template = cv2.resize(template, (resized_width, resized_height), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
        if target_hwnd is None:
            failed_response["error"] = "invalid_hwnd"
            return failed_response
        hwnd = as_hwnd(target_hwnd)
        if hwnd == 0:
            failed_response["error"] = "invalid_hwnd"
            return failed_response

        roi_param = None
        if roi is not None:
            if (not isinstance(roi, (list, tuple)) or len(roi) != 4
                    or any(type(value) is not int for value in roi)
                    or roi[2] <= 0 or roi[3] <= 0):
                failed_response["error"] = "invalid_roi"
                return failed_response
            roi_param = tuple(roi)

        if engine is None:
            from utils.capture.screenshot_helper import get_screenshot_engine
            engine = get_screenshot_engine()
        match_engine = str(engine).strip().lower()
        from utils.capture.engine_ids import is_supported_screenshot_engine

        if not is_supported_screenshot_engine(match_engine):
            failed_response["error"] = f"无效的截图引擎: {engine!r}"
            return failed_response

        timeout = coerce_float(capture_timeout)
        if timeout <= 0:
            raise ValueError("截图超时必须大于零")
        timeout = max(0.3, timeout)

        from services.screenshot_pool import capture_and_match_template
        from utils.capture.screenshot_helper import clear_screenshot_cache

        # 多开后台高负载时，抓帧偶发超时会导致识图误判失败。
        # 仅对抓帧级瞬时失败做同引擎重试，重试预算由当前超时参数自适应推导并支持环境变量覆盖。
        default_retry_attempts = 1 if timeout < 2.0 else 0
        retry_attempts = _read_int_env(
            "LCA_CAPTURE_RETRY_ATTEMPTS",
            default_retry_attempts,
            min_value=0,
            max_value=3,
        )
        default_retry_factor = 1.0 + min(0.8, timeout * 0.4)
        retry_factor = _read_float_env(
            "LCA_CAPTURE_RETRY_TIMEOUT_FACTOR",
            default_retry_factor,
            min_value=1.0,
            max_value=4.0,
        )
        default_retry_max_timeout = max(timeout, timeout * retry_factor)
        retry_max_timeout = _read_float_env(
            "LCA_CAPTURE_RETRY_MAX_TIMEOUT_SEC",
            default_retry_max_timeout,
            min_value=timeout,
            max_value=30.0,
        )
        default_retry_gap = min(0.12, max(0.01, timeout * 0.05))
        retry_gap = _read_float_env(
            "LCA_CAPTURE_RETRY_GAP_SEC",
            default_retry_gap,
            min_value=0.0,
            max_value=1.0,
        )

        attempt_timeouts: List[float] = [timeout]
        for _ in range(retry_attempts):
            next_timeout = min(retry_max_timeout, attempt_timeouts[-1] * retry_factor)
            if next_timeout <= attempt_timeouts[-1] * 1.001:
                break
            attempt_timeouts.append(float(next_timeout))

        last_response: Optional[Dict[str, Any]] = None
        for attempt_index, attempt_timeout in enumerate(attempt_timeouts, 1):
            response = capture_and_match_template(
                hwnd=hwnd,
                template=template,
                confidence_threshold=float(confidence_threshold),
                template_key=(str(template_key) if template_key else None),
                client_area_only=bool(client_area_only),
                use_cache=bool(use_cache),
                timeout=float(attempt_timeout),
                engine=match_engine,
                roi=roi_param,
                mode=mode,
                rotation=rotation,
            )

            if isinstance(response, dict):
                last_response = response
                if bool(response.get("success")):
                    return response
                if attempt_index >= len(attempt_timeouts):
                    return response
                if not _is_transient_capture_error(response.get("error")):
                    return response

                try:
                    clear_screenshot_cache(hwnd)
                except Exception:
                    pass
                if retry_gap > 0:
                    precise_sleep(retry_gap)
                continue

            last_response = None
            if attempt_index >= len(attempt_timeouts):
                break
            try:
                clear_screenshot_cache(hwnd)
            except Exception:
                pass
            if retry_gap > 0:
                precise_sleep(retry_gap)

        if isinstance(last_response, dict):
            return last_response

        failed_response["error"] = "invalid_response_type"
        return failed_response
    except Exception as exc:
        failed_response["error"] = str(exc) or type(exc).__name__
        return failed_response


def is_smart_capture_available() -> bool:
    """检查智能截图是否可用"""
    try:
        from utils.capture.screenshot_helper import is_screenshot_available
        return is_screenshot_available()
    except ImportError:
        return False


# ==================== 延迟处理功能 ====================



def handle_next_step_delay(params: Dict[str, Any], stop_checker=None):
    """按现行参数执行延迟；无效配置交给执行器报告并停止。"""
    if not isinstance(params, dict):
        raise ValueError("延迟参数必须是字典")
    if not coerce_bool(params.get('enable_next_step_delay', False)):
        return
    delay_mode = params.get('delay_mode', '固定延迟')
    if delay_mode == '固定延迟':
        delay_time = coerce_float(params.get('fixed_delay', 1.0))
        if delay_time < 0:
            raise ValueError("固定延迟不能为负数")
        logger.info("执行固定延迟: %.2f 秒", delay_time)
    elif delay_mode == '随机延迟':
        min_delay = coerce_float(params.get('min_delay', 0.5))
        max_delay = coerce_float(params.get('max_delay', 2.0))
        if not 0 <= min_delay <= max_delay:
            raise ValueError("随机延迟必须满足 0 ≤ 最小值 ≤ 最大值")
        delay_time = random.uniform(min_delay, max_delay)
        logger.info("执行随机延迟: %.2f 秒 (范围: %s-%s)", delay_time, min_delay, max_delay)
    else:
        raise ValueError(f"未知的延迟模式: {delay_mode!r}")
    interruptible_sleep(delay_time, stop_checker)


def interruptible_sleep(duration: float, stop_checker=None):
    """可中断的睡眠函数 - 使用高精度计时器"""
    duration = coerce_float(duration)
    if duration <= 0:
        return

    start_time = time.perf_counter()  # 使用高精度计时器
    check_interval = 0.1  # 每100ms检查一次

    while True:
        elapsed = time.perf_counter() - start_time
        if elapsed >= duration:
            break
        if stop_checker and stop_checker():
            logger.info("延迟被中断")
            break
        # 计算实际需要睡眠的时间
        remaining = duration - elapsed
        precise_sleep(min(check_interval, remaining))


def handle_success_action(params: Dict[str, Any], card_id: Optional[int], stop_checker=None) -> Tuple[bool, str, Optional[int]]:
    """处理成功动作"""
    return resolve_step_action_result(
        success=True,
        action=params.get('on_success', '执行下一步'),
        jump_id=params.get('success_jump_target_id'),
        card_id=card_id,
    )


def handle_failure_action(params: Dict[str, Any], card_id: Optional[int], stop_checker=None) -> Tuple[bool, str, Optional[int]]:
    """处理失败动作"""
    return resolve_step_action_result(
        success=False,
        action=params.get('on_failure', '执行下一步'),
        jump_id=params.get('failure_jump_target_id'),
        card_id=card_id,
    )


def get_standard_next_step_delay_params() -> Dict[str, Dict[str, Any]]:
    """获取标准的下一步延迟参数定义"""
    return {
        "---next_step_delay---": {"type": "separator", "label": "下一步延迟执行"},
        "enable_next_step_delay": {
            "label": "启用下一步延迟执行",
            "type": "bool",
            "default": False,
            "tooltip": "勾选后，执行完当前操作会等待指定时间再执行下一步"
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
            "default": 1.0,
            "min": 0.1,
            "max": 60.0,
            "decimals": 2,
            "tooltip": "固定延迟的时间（秒）",
            "condition": {
                "param": "delay_mode",
                "value": "固定延迟",
                "and": {"param": "enable_next_step_delay", "value": True}
            }
        },
        "min_delay": {
            "label": "最小延迟 (秒)",
            "type": "float",
            "default": 0.5,
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
            "default": 2.0,
            "min": 0.1,
            "max": 60.0,
            "decimals": 2,
            "tooltip": "随机延迟的最大时间（秒）",
            "condition": {
                "param": "delay_mode",
                "value": "随机延迟",
                "and": {"param": "enable_next_step_delay", "value": True}
            }
        }
    }


def get_standard_action_params() -> Dict[str, Dict[str, Any]]:
    """获取标准的成功/失败动作参数定义"""
    return {
        "---post_execution---": {"type": "separator", "label": "执行后操作"},
        "on_success": {
            "type": "select",
            "label": "成功时",
            "options": ["执行下一步", "继续执行本步骤", "跳转到步骤", "停止工作流"],
            "default": "执行下一步",
            "tooltip": "当任务执行成功时的操作"
        },
        "success_jump_target_id": {
            "type": "int",
            "label": "成功跳转目标ID",
            "required": False,
            "condition": {"param": "on_success", "value": "跳转到步骤"},
            "tooltip": "任务成功时要跳转到的卡片ID"
        },
        "on_failure": {
            "type": "select",
            "label": "失败时",
            "options": ["执行下一步", "继续执行本步骤", "跳转到步骤", "停止工作流"],
            "default": "执行下一步",
            "tooltip": "当任务执行失败时的操作"
        },
        "failure_jump_target_id": {
            "type": "int",
            "label": "失败跳转目标ID",
            "required": False,
            "condition": {"param": "on_failure", "value": "跳转到步骤"},
            "tooltip": "任务失败时要跳转到的卡片ID"
        }
    }


def get_standard_click_offset_params() -> Dict[str, Dict[str, Any]]:
    """获取标准的点击偏移参数定义。"""
    return {
        "---click_offset---": {"type": "separator", "label": "点击位置偏移设置"},
        "offset_selector_tool": {
            "label": "偏移选择",
            "type": "button",
            "button_text": "拖拽选择偏移",
            "tooltip": "从目标点拖拽选择固定偏移距离，会自动切换为固定偏移",
            "widget_hint": "offset_selector",
            "related_params": ["fixed_offset_x", "fixed_offset_y", "position_mode"],
        },
        "position_mode": {
            "label": "点击位置",
            "type": "select",
            "options": ["精准坐标", "固定偏移", "随机偏移"],
            "default": "随机偏移",
            "tooltip": "精准坐标：使用指定的坐标精确点击\n固定偏移：先添加固定偏移，再可选叠加随机偏移\n随机偏移：在指定坐标基础上添加随机偏移"
        },
        "fixed_offset_x": {
            "label": "固定X偏移(像素)",
            "type": "int",
            "default": 0,
            "tooltip": "在找到的位置上增加固定的X偏移（正数向右，负数向左）",
            "condition": {"param": "position_mode", "value": "固定偏移"}
        },
        "fixed_offset_y": {
            "label": "固定Y偏移(像素)",
            "type": "int",
            "default": 0,
            "tooltip": "在找到的位置上增加固定的Y偏移（正数向下，负数向上）",
            "condition": {"param": "position_mode", "value": "固定偏移"}
        },
        "random_offset_x": {
            "label": "随机X偏移范围(像素)",
            "type": "int",
            "default": 5,
            "min": 0,
            "tooltip": "X轴随机偏移范围，实际偏移在 [-X, +X] 范围内随机；固定偏移模式下会叠加在固定偏移后的坐标上",
            "condition": {"param": "position_mode", "value": ["固定偏移", "随机偏移"], "operator": "in"}
        },
        "random_offset_y": {
            "label": "随机Y偏移范围(像素)",
            "type": "int",
            "default": 5,
            "min": 0,
            "tooltip": "Y轴随机偏移范围，实际偏移在 [-Y, +Y] 范围内随机；固定偏移模式下会叠加在固定偏移后的坐标上",
            "condition": {"param": "position_mode", "value": ["固定偏移", "随机偏移"], "operator": "in"}
        }
    }



def merge_params_definitions(*param_defs: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """合并多个参数定义字典"""
    merged = {}
    for param_def in param_defs:
        merged.update(param_def)
    return merged


def resolve_step_action_result(
    success: bool,
    action: Any,
    jump_id: Any,
    card_id: Optional[int],
    detail: Any = "",
) -> Tuple[Any, ...]:
    """按现行动作生成卡片结果，非法动作或缺失跳转目标直接失败。"""
    action_text = validate_step_action(action)
    if action_text == "跳转到步骤":
        target = validate_card_target(jump_id)
        if target is None:
            raise ValueError("跳转到步骤必须指定目标卡片")
    elif action_text == "继续执行本步骤":
        target = validate_card_target(card_id)
    else:
        target = None
    if type(success) is not bool or not isinstance(detail, str):
        raise TypeError("任务状态必须是布尔值，结果说明必须是文本")
    result = (success, action_text, target)
    return (*result, detail.strip()) if detail.strip() else result


def normalize_step_action(action: Any) -> str:
    """校验现行动作，不转换别名。"""
    return validate_step_action(action)


def correct_image_paths(
    raw_paths: List[str],
    card_id: Optional[int] = None,
    images_dir: Optional[str] = None,
) -> List[str]:
    """【通用工具】智能纠正图片路径列表，支持自动从images目录匹配同名文件

    优化版本：使用 ImagePathResolver 统一处理，支持：
    - 多目录搜索（工作目录、程序目录、打包目录）
    - 路径缓存（提升性能）
    - 跨平台路径处理（pathlib）
    - 打包环境支持（PyInstaller/Nuitka）

    Args:
        raw_paths: 原始路径列表（可以是绝对路径、相对路径或memory://路径）
        card_id: 卡片ID（用于日志，可选）

    Returns:
        纠正后的有效路径列表（仅包含存在的文件）

    示例:
        >>> paths = [
        ...     "C:/Users/LS/images/pic.png",  # 绝对路径失效
        ...     "images/pic2.png",              # 相对路径有效
        ...     "memory://screenshot_123"       # 内存图片
        ... ]
        >>> corrected = correct_image_paths(paths)
        >>> # 返回: ["images/pic.png", "images/pic2.png", "memory://screenshot_123"]
    """
    if not raw_paths:
        return []

    valid_count = len([p for p in raw_paths if p and p.strip()])
    logger.info(f"[路径纠正] 开始解析 {valid_count} 个图片路径")
    corrected_paths = []
    for item in raw_paths:
        located = correct_single_image_path(item, card_id=card_id, images_dir=images_dir)
        if located:
            corrected_paths.append(located)
    logger.info(f"[路径纠正] 完成，有效路径: {len(corrected_paths)}/{valid_count}")
    return corrected_paths


def correct_single_image_path(
    raw_path: str,
    card_id: Optional[int] = None,
    images_dir: Optional[str] = None,
) -> Optional[str]:
    """【通用工具】纠正单个图片路径

    走统一资源读取：绑定工作区目录，没有才用工程包。

    Args:
        raw_path: 原始路径
        card_id: 卡片ID（用于日志，可选）
        images_dir: 当前工作流图片目录（可选；不传则使用资源上下文）

    Returns:
        纠正后的路径，失败返回None

    示例:
        >>> path = "C:/old/path/pic.png"
        >>> corrected = correct_single_image_path(path)
        >>> # 如果失效，返回: "images/pic.png"（如果存在）
    """
    if not raw_path:
        return None

    from task_workflow.script_resources import resolve_resource_path

    kwargs = {}
    extra = str(images_dir or "").strip()
    if extra:
        kwargs["images_dir"] = extra
    located = resolve_resource_path(str(raw_path).strip(), enforce_jail=False, **kwargs)
    if not located:
        return None
    if str(located).startswith("memory://"):
        return located
    if os.path.isfile(located):
        return located
    return None


