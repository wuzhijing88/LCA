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
import threading
from pathlib import Path
from typing import Dict, Any, Tuple, Optional, List
from collections import OrderedDict
from utils.window.hwnd_utils import as_hwnd
from utils.image_paths import ImagePathResolver, get_image_path_resolver
from utils.precise_sleep import precise_sleep as _shared_precise_sleep
from utils.window.window_coordinate_common import (
    find_region_binding_equivalent_descendant,
    normalize_region_binding_hwnd,
)

logger = logging.getLogger(__name__)

REGION_BINDING_CLIENT_SIZE_TOLERANCE = 2


# ==================== 参数转换辅助 ====================


def coerce_bool(value: Any) -> bool:
    """Convert possibly string/int values to a strict bool."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("1", "true", "yes", "y", "on", "是", "真"):
            return True
        if text in ("0", "false", "no", "n", "off", "否", "假", ""):
            return False
    return False


def coerce_int(value: Any, default: int = 0) -> int:
    """Convert possibly string/float values to int with a default fallback."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return default
        try:
            return int(float(text))
        except ValueError:
            return default
    return default


def coerce_float(value: Any, default: float = 0.0) -> float:
    """Convert possibly string/int values to float with a default fallback."""
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return default
        try:
            return float(text)
        except ValueError:
            return default
    return default


def resolve_region_selection_params(
    params: Dict[str, Any],
    default_mode: str = "指定区域",
) -> Tuple[str, int, int, int, int]:
    """
    统一解析区域选择参数，兼容新旧两套存储格式：
    1. region_x / region_y / region_width / region_height
    2. region_x1 / region_y1 / region_x2 / region_y2
    3. region_coordinates 文本格式
    """
    region_mode = str(params.get("region_mode", default_mode) or default_mode)

    region_x = coerce_int(params.get("region_x", 0), 0)
    region_y = coerce_int(params.get("region_y", 0), 0)
    region_width = coerce_int(params.get("region_width", 0), 0)
    region_height = coerce_int(params.get("region_height", 0), 0)

    if region_width <= 0 or region_height <= 0:
        region_x1 = coerce_int(params.get("region_x1", 0), 0)
        region_y1 = coerce_int(params.get("region_y1", 0), 0)
        region_x2 = coerce_int(params.get("region_x2", 0), 0)
        region_y2 = coerce_int(params.get("region_y2", 0), 0)

        if region_x2 > region_x1 and region_y2 > region_y1:
            region_x = region_x1
            region_y = region_y1
            region_width = region_x2 - region_x1
            region_height = region_y2 - region_y1

    if region_width <= 0 or region_height <= 0:
        import re

        region_coordinates = str(params.get("region_coordinates", "") or "")
        if region_coordinates and region_coordinates != "未指定识别区域":
            x_match = re.search(r"X=(-?\d+)", region_coordinates)
            y_match = re.search(r"Y=(-?\d+)", region_coordinates)
            width_match = re.search(r"宽度?=(-?\d+)", region_coordinates)
            height_match = re.search(r"高度?=(-?\d+)", region_coordinates)

            if x_match and y_match and width_match and height_match:
                region_x = coerce_int(x_match.group(1), 0)
                region_y = coerce_int(y_match.group(1), 0)
                region_width = coerce_int(width_match.group(1), 0)
                region_height = coerce_int(height_match.group(1), 0)
            else:
                x1_match = re.search(r"X1=(-?\d+)", region_coordinates)
                y1_match = re.search(r"Y1=(-?\d+)", region_coordinates)
                x2_match = re.search(r"X2=(-?\d+)", region_coordinates)
                y2_match = re.search(r"Y2=(-?\d+)", region_coordinates)
                if x1_match and y1_match and x2_match and y2_match:
                    region_x = coerce_int(x1_match.group(1), 0)
                    region_y = coerce_int(y1_match.group(1), 0)
                    region_x2 = coerce_int(x2_match.group(1), 0)
                    region_y2 = coerce_int(y2_match.group(1), 0)
                    if region_x2 > region_x and region_y2 > region_y:
                        region_width = region_x2 - region_x
                        region_height = region_y2 - region_y

    return region_mode, region_x, region_y, region_width, region_height


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
    recorded_client_width = coerce_int(params.get("region_client_width", 0), 0)
    recorded_client_height = coerce_int(params.get("region_client_height", 0), 0)

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

    recorded_compare_title = normalized_recorded_title if normalized_recorded_hwnd > 0 else recorded_title
    recorded_compare_class = normalized_recorded_class if normalized_recorded_hwnd > 0 else recorded_class
    recorded_compare_width = normalized_recorded_width if normalized_recorded_width > 0 else recorded_client_width
    recorded_compare_height = normalized_recorded_height if normalized_recorded_height > 0 else recorded_client_height

    same_title = bool(recorded_compare_title and recorded_compare_title == normalized_current_title)
    same_class = bool(recorded_compare_class and recorded_compare_class == normalized_current_class)
    same_client_size = (
        recorded_compare_width > 0
        and recorded_compare_height > 0
        and abs(recorded_compare_width - normalized_current_width) <= REGION_BINDING_CLIENT_SIZE_TOLERANCE
        and abs(recorded_compare_height - normalized_current_height) <= REGION_BINDING_CLIENT_SIZE_TOLERANCE
    )

    if same_title and same_class and same_client_size:
        return None

    if not recorded_hwnd_alive and not (recorded_title or recorded_class or same_client_size):
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
        # 【性能优化】优先从模板缓存加载
        try:
            from utils.match.template_preloader import get_global_preloader
            preloader = get_global_preloader()
            template = preloader.get_template(image_path)
            if template is not None:
                logger.debug(f"[性能优化] 使用缓存的模板: {image_path}")
                return template
        except Exception as e:
            logger.debug(f"[性能优化] 模板缓存读取失败: {e}")

        # 缓存未命中，正常加载
        if image_path.startswith('memory://'):
            image_bytes = None
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

        # 备选方法：直接读取
        if image_path.startswith('memory://'):
            return None

        img = cv2.imread(image_path, flags)
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
            try:
                from task_workflow.workflow_context import get_current_workflow_context
                context = get_current_workflow_context()
                shared_img = context.get_shared_capture(hwnd, client_area_only)
                if shared_img is not None:
                    try:
                        return shared_img.copy()
                    except Exception:
                        return shared_img
            except Exception:
                pass

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
        except Exception:
            value = float(default)
        return max(min_value, min(max_value, value))

    def _read_int_env(name: str, default: int, min_value: int, max_value: int) -> int:
        raw = os.getenv(name)
        if raw is None:
            return max(min_value, min(max_value, int(default)))
        try:
            value = int(raw)
        except Exception:
            value = int(default)
        return max(min_value, min(max_value, value))

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
        if target_hwnd is None:
            failed_response["error"] = "invalid_hwnd"
            return failed_response
        hwnd = as_hwnd(target_hwnd)
        if hwnd == 0:
            failed_response["error"] = "invalid_hwnd"
            return failed_response

        roi_param = None
        if isinstance(roi, (list, tuple)) and len(roi) == 4:
            try:
                rx, ry, rw, rh = int(roi[0]), int(roi[1]), int(roi[2]), int(roi[3])
                if rw > 0 and rh > 0:
                    roi_param = (rx, ry, rw, rh)
            except Exception:
                roi_param = None

        match_engine = str(engine or "").strip().lower()
        if not match_engine:
            try:
                from utils.capture.screenshot_helper import get_screenshot_engine
                match_engine = str(get_screenshot_engine() or "wgc").strip().lower()
            except Exception:
                match_engine = "wgc"
        from utils.capture.engine_ids import is_supported_screenshot_engine

        if not is_supported_screenshot_engine(match_engine):
            match_engine = "wgc"

        timeout = max(0.3, float(capture_timeout))

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
    """处理下一步延迟执行"""
    try:
        if not isinstance(params, dict):
            return

        # 兼容开发环境/打包环境的参数类型差异（bool/float 可能被序列化为字符串）
        if not coerce_bool(params.get('enable_next_step_delay', False)):
            return

        delay_mode_raw = str(params.get('delay_mode', '固定延迟') or '').strip().lower()
        if delay_mode_raw in ('fixed', '固定延迟'):
            delay_time = coerce_float(params.get('fixed_delay', 1.0), 1.0)
            delay_time = max(0.0, delay_time)
            logger.info(f"执行固定延迟: {delay_time:.2f} 秒")
            interruptible_sleep(delay_time, stop_checker)
        elif delay_mode_raw in ('random', '随机延迟'):
            min_delay = max(0.0, coerce_float(params.get('min_delay', 0.5), 0.5))
            max_delay = max(0.0, coerce_float(params.get('max_delay', 2.0), 2.0))
            if min_delay > max_delay:
                min_delay, max_delay = max_delay, min_delay
            delay_time = random.uniform(min_delay, max_delay)
            logger.info(f"执行随机延迟: {delay_time:.2f} 秒 (范围: {min_delay}-{max_delay})")
            interruptible_sleep(delay_time, stop_checker)
        else:
            logger.warning(f"未知的延迟模式: {params.get('delay_mode')}")
    except Exception as e:
        logger.error(f"执行下一步延迟时发生错误: {e}")


def interruptible_sleep(duration: float, stop_checker=None):
    """可中断的睡眠函数 - 使用高精度计时器"""
    duration = coerce_float(duration, 0.0)
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
    require_jump_target: bool = False,
    detail: Any = "",
) -> Tuple[Any, ...]:
    """统一解析步骤跳转动作，返回 (success, action_text, next_id)。"""
    action_text = normalize_step_action(action)
    normalized_jump_id = _normalize_jump_target_id(jump_id)
    clean_detail = str(detail or "").strip()

    if action_text == "跳转到步骤":
        if require_jump_target and normalized_jump_id is None:
            result = (success, "执行下一步", None)
        else:
            result = (success, "跳转到步骤", normalized_jump_id)
    elif action_text == "停止工作流":
        result = (success, "停止工作流", None)
    elif action_text == "继续执行本步骤":
        result = (success, "继续执行本步骤", card_id)
    else:
        result = (success, "执行下一步", None)

    if clean_detail:
        return (*result, clean_detail)
    return result


_STEP_ACTION_ALIASES = {
    "执行下一步": {
        "执行下一步",
        "下一步",
        "继续下一步",
    },
    "继续执行本步骤": {
        "继续执行本步骤",
        "继续本步骤",
    },
    "跳转到步骤": {
        "跳转到步骤",
        "跳转到指定步骤",
    },
    "停止工作流": {
        "停止工作流",
        "结束工作流",
        "结束流程",
        "终止流程",
    },
}


def normalize_step_action(action: Any) -> str:
    """规范化动作文案，兼容历史任务中不同动作名称。"""
    action_text = str(action or "").strip()
    if not action_text:
        return "执行下一步"
    for normalized, aliases in _STEP_ACTION_ALIASES.items():
        if action_text in aliases:
            return normalized
    return "执行下一步"


def _normalize_jump_target_id(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def correct_image_paths(raw_paths: List[str], card_id: Optional[int] = None) -> List[str]:
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

    resolver = get_image_path_resolver()
    valid_count = len([p for p in raw_paths if p and p.strip()])

    logger.info(f"[路径纠正] 开始解析 {valid_count} 个图片路径")

    corrected_paths = resolver.resolve_many(raw_paths, filter_invalid=True)

    logger.info(f"[路径纠正] 完成，有效路径: {len(corrected_paths)}/{valid_count}")

    return corrected_paths


def correct_single_image_path(raw_path: str, card_id: Optional[int] = None) -> Optional[str]:
    """【通用工具】纠正单个图片路径

    优化版本：使用 ImagePathResolver，带缓存

    Args:
        raw_path: 原始路径
        card_id: 卡片ID（用于日志，可选）

    Returns:
        纠正后的路径，失败返回None

    示例:
        >>> path = "C:/old/path/pic.png"
        >>> corrected = correct_single_image_path(path)
        >>> # 如果失效，返回: "images/pic.png"（如果存在）
    """
    if not raw_path:
        return None

    resolver = get_image_path_resolver()
    return resolver.resolve(raw_path)


