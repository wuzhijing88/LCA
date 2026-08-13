#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
截图助手模块 - 多引擎支持

支持的截图引擎:
- WGC: Windows Graphics Capture (Win10 1903+/Win11)，GPU加速，支持后台
- PrintWindow: Win32 API，支持后台窗口
- GDI: 传统截图方式，兼容性好
- DXGI: Desktop Duplication API，高性能，仅支持前台

依赖要求:
    pip install winrt-Windows.Graphics.Capture winrt-Windows.Graphics.Capture.Interop winrt-Windows.Graphics.DirectX winrt-Windows.Graphics.DirectX.Direct3D11 winrt-Windows.Graphics.Imaging winrt-Windows.AI.MachineLearning numpy opencv-python pillow pywin32
"""

import logging
import numpy as np
import atexit
import sys
import threading
import time
from typing import Optional, Tuple

import cv2
import win32gui
from PIL import Image

logger = logging.getLogger(__name__)


def _shutdown_existing_async_pipeline() -> bool:
    """Stop the async pipeline without importing new modules during shutdown."""
    async_module = sys.modules.get("utils.async_screenshot")
    shutdown_pipeline = getattr(async_module, "shutdown_global_pipeline", None)
    if not callable(shutdown_pipeline):
        return False
    shutdown_pipeline()
    return True

try:
    from utils.runtime_dependency_guard import preload_onnxruntime

    preload_onnxruntime()
except Exception:
    pass

# 当前使用的截图引擎 (可通过 set_screenshot_engine 切换)
_current_engine = 'wgc'
_engine_lock = threading.Lock()
_window_manager = None
SUPPORTED_SCREENSHOT_ENGINES = ("wgc", "printwindow", "gdi", "dxgi")

def set_window_manager(manager):
    """设置全局窗口管理器实例（由 main.py 调用）"""
    global _window_manager
    _window_manager = manager
    logger.info("[OK] 窗口管理器实例已设置")

# 截图引擎（主进程直连，不再走子进程）
try:
    import utils.wgc_hwnd_capture as _wgc_module
    from utils.wgc_hwnd_capture import (
        capture_window_wgc as _capture_window_wgc_raw,
        clear_wgc_cache as _clear_wgc_cache_raw,
        cleanup_wgc as _cleanup_wgc_raw,
        get_existing_global_capture as _get_existing_wgc_capture,
        get_global_capture as _get_global_wgc_capture,
        get_last_wgc_capture_failure_reason as _get_last_wgc_failure_reason,
        shutdown_wgc as _shutdown_wgc_raw,
    )
except Exception as e:
    _wgc_module = None
    _capture_window_wgc_raw = None
    _clear_wgc_cache_raw = None
    _cleanup_wgc_raw = None
    _get_existing_wgc_capture = None
    _get_global_wgc_capture = None
    _get_last_wgc_failure_reason = None
    _shutdown_wgc_raw = None
    logger.warning(f"[ERROR] WGC 引擎不可用: {e}")

try:
    from utils.printwindow_capture import (
        capture_window_printwindow as _capture_window_printwindow_raw,
        clear_printwindow_runtime_cache as _clear_printwindow_runtime_cache_raw,
        cleanup_printwindow as _cleanup_printwindow_raw,
        get_global_capture as _get_printwindow_capture,
        get_pixel_color_printwindow as _get_pixel_color_printwindow_raw,
        is_printwindow_available as _is_printwindow_available_raw,
    )
except Exception as e:
    _capture_window_printwindow_raw = None
    _clear_printwindow_runtime_cache_raw = None
    _cleanup_printwindow_raw = None
    _get_printwindow_capture = None
    _get_pixel_color_printwindow_raw = None
    _is_printwindow_available_raw = None
    logger.warning(f"[ERROR] PrintWindow 引擎不可用: {e}")

try:
    from utils.gdi_capture import (
        capture_window_gdi as _capture_window_gdi_raw,
        clear_gdi_runtime_cache as _clear_gdi_runtime_cache_raw,
        cleanup_gdi as _cleanup_gdi_raw,
        get_global_capture as _get_gdi_capture,
        get_pixel_color_gdi as _get_pixel_color_gdi_raw,
        is_gdi_available as _is_gdi_available_raw,
    )
except Exception as e:
    _capture_window_gdi_raw = None
    _clear_gdi_runtime_cache_raw = None
    _cleanup_gdi_raw = None
    _get_gdi_capture = None
    _get_pixel_color_gdi_raw = None
    _is_gdi_available_raw = None
    logger.warning(f"[ERROR] GDI 引擎不可用: {e}")

try:
    from utils.dxgi_capture import (
        capture_screen_dxgi as _capture_screen_dxgi_raw,
        capture_window_dxgi as _capture_window_dxgi_raw,
        clear_dxgi_runtime_cache as _clear_dxgi_runtime_cache_raw,
        cleanup_dxgi as _cleanup_dxgi_raw,
        get_dxgi_monitors as _get_dxgi_monitors_raw,
        get_global_capture as _get_dxgi_capture,
        get_last_dxgi_capture_failure_reason as _get_last_dxgi_failure_reason,
        get_pixel_color_dxgi as _get_pixel_color_dxgi_raw,
        is_dxgi_available as _is_dxgi_available_raw,
    )
except Exception as e:
    _capture_screen_dxgi_raw = None
    _capture_window_dxgi_raw = None
    _clear_dxgi_runtime_cache_raw = None
    _cleanup_dxgi_raw = None
    _get_dxgi_monitors_raw = None
    _get_dxgi_capture = None
    _get_last_dxgi_failure_reason = None
    _get_pixel_color_dxgi_raw = None
    _is_dxgi_available_raw = None
    logger.warning(f"[ERROR] DXGI 引擎不可用: {e}")


def _safe_timeout_ms(timeout: float, default_ms: int = 4000) -> int:
    try:
        return max(100, int(float(timeout) * 1000))
    except Exception:
        return int(default_ms)


def _pixel_color_from_frame(frame, x: int, y: int):
    if frame is None:
        return None
    if y < 0 or y >= frame.shape[0] or x < 0 or x >= frame.shape[1]:
        return None
    if len(frame.shape) == 2:
        v = int(frame[y, x])
        return (v, v, v)
    b = int(frame[y, x, 0])
    g = int(frame[y, x, 1])
    r = int(frame[y, x, 2])
    return (r, g, b)


def capture_window_wgc(
    hwnd: int,
    client_area_only: bool = True,
    use_cache: bool = False,
    timeout: float = 4.0,
):
    if not callable(_capture_window_wgc_raw):
        return None
    try:
        return _capture_window_wgc_raw(
            hwnd=hwnd,
            client_area_only=client_area_only,
            use_cache=bool(use_cache),
            request_timeout_ms=_safe_timeout_ms(timeout),
        )
    except Exception:
        return None


def capture_window_printwindow(hwnd: int, client_area_only: bool = True, timeout: float = 4.0):
    _ = timeout
    if not callable(_capture_window_printwindow_raw):
        return None
    try:
        return _capture_window_printwindow_raw(hwnd=hwnd, client_area_only=client_area_only)
    except Exception:
        return None


def capture_window_gdi(hwnd: int, client_area_only: bool = True, timeout: float = 4.0):
    _ = timeout
    if not callable(_capture_window_gdi_raw):
        return None
    try:
        return _capture_window_gdi_raw(hwnd=hwnd, client_area_only=client_area_only)
    except Exception:
        return None


def capture_window_dxgi(hwnd: int, client_area_only: bool = True, timeout: float = 4.0):
    _ = timeout
    if not callable(_capture_window_dxgi_raw):
        return None
    try:
        return _capture_window_dxgi_raw(hwnd=hwnd, client_area_only=client_area_only)
    except Exception:
        return None


def capture_screen_dxgi(*args, **kwargs):
    if not callable(_capture_screen_dxgi_raw):
        return None
    try:
        return _capture_screen_dxgi_raw(*args, **kwargs)
    except Exception:
        return None


def get_pixel_color_wgc(hwnd: int, x: int, y: int, client_coords: bool = True):
    frame = capture_window_wgc(hwnd, client_area_only=client_coords, use_cache=False)
    return _pixel_color_from_frame(frame, x, y)


def get_pixel_color_printwindow(hwnd: int, x: int, y: int, client_coords: bool = True):
    if callable(_get_pixel_color_printwindow_raw):
        try:
            return _get_pixel_color_printwindow_raw(hwnd, x, y, client_coords)
        except Exception:
            return None
    frame = capture_window_printwindow(hwnd, client_area_only=client_coords)
    return _pixel_color_from_frame(frame, x, y)


def get_pixel_color_gdi(hwnd: int, x: int, y: int, client_coords: bool = True):
    if callable(_get_pixel_color_gdi_raw):
        try:
            return _get_pixel_color_gdi_raw(hwnd, x, y, client_coords)
        except Exception:
            return None
    frame = capture_window_gdi(hwnd, client_area_only=client_coords)
    return _pixel_color_from_frame(frame, x, y)


def get_pixel_color_dxgi(hwnd: int, x: int, y: int, client_coords: bool = True):
    if callable(_get_pixel_color_dxgi_raw):
        try:
            return _get_pixel_color_dxgi_raw(hwnd, x, y, client_coords)
        except Exception:
            return None
    frame = capture_window_dxgi(hwnd, client_area_only=client_coords)
    return _pixel_color_from_frame(frame, x, y)


def is_wgc_available() -> bool:
    try:
        return bool(_wgc_module is not None and getattr(_wgc_module, "WGC_AVAILABLE", False))
    except Exception:
        return False


def is_printwindow_available() -> bool:
    if callable(_is_printwindow_available_raw):
        try:
            return bool(_is_printwindow_available_raw())
        except Exception:
            return False
    return False


def is_gdi_available() -> bool:
    if callable(_is_gdi_available_raw):
        try:
            return bool(_is_gdi_available_raw())
        except Exception:
            return False
    return False


def is_dxgi_available() -> bool:
    if callable(_is_dxgi_available_raw):
        try:
            return bool(_is_dxgi_available_raw())
        except Exception:
            return False
    return False


def get_dxgi_monitors():
    if callable(_get_dxgi_monitors_raw):
        try:
            return list(_get_dxgi_monitors_raw() or [])
        except Exception:
            return []
    return []


def probe_dxgi_runtime_available() -> bool:
    if not is_dxgi_available():
        return False
    try:
        monitors = get_dxgi_monitors()
        if monitors:
            return True
    except Exception:
        pass
    try:
        from utils.dxgi_capture import cleanup_dxgi, get_dxgi_monitors as _get_dxgi_monitors_retry
        cleanup_dxgi(hwnd=None)
        return bool(_get_dxgi_monitors_retry())
    except Exception:
        return False


def shutdown_wgc():
    if callable(_shutdown_wgc_raw):
        try:
            _shutdown_wgc_raw()
            return
        except Exception:
            pass
    if callable(_cleanup_wgc_raw):
        try:
            _cleanup_wgc_raw(hwnd=None, cleanup_d3d=False)
        except Exception:
            pass


def get_wgc_stats() -> dict:
    capture = None
    if callable(_get_existing_wgc_capture):
        try:
            capture = _get_existing_wgc_capture()
        except Exception:
            capture = None
    if capture is not None and hasattr(capture, "get_stats"):
        try:
            return dict(capture.get_stats() or {})
        except Exception:
            return {}
    return {}


def clear_wgc_cache(hwnd: int = None):
    if callable(_clear_wgc_cache_raw):
        try:
            _clear_wgc_cache_raw(hwnd=hwnd)
        except Exception:
            pass


def get_existing_global_capture():
    if callable(_get_existing_wgc_capture):
        try:
            return _get_existing_wgc_capture()
        except Exception:
            return None
    return None


def get_global_capture():
    if callable(_get_global_wgc_capture):
        try:
            return _get_global_wgc_capture()
        except Exception:
            return None
    return None


_DEFAULT_ENGINE_CAPS = {
    "wgc": bool(is_wgc_available()),
    "printwindow": bool(is_printwindow_available()),
    "gdi": bool(is_gdi_available()),
    "dxgi": bool(is_dxgi_available()),
}
_ENGINE_CAPS_CACHE = dict(_DEFAULT_ENGINE_CAPS)
_ENGINE_CAPS_CACHE_TS = 0.0
_ENGINE_CAPS_CACHE_TTL_SEC = 2.0


def _normalize_engine_caps(raw_caps) -> Optional[dict]:
    if not isinstance(raw_caps, dict):
        return None
    return {
        "wgc": bool(raw_caps.get("wgc", False)),
        "printwindow": bool(raw_caps.get("printwindow", False)),
        "gdi": bool(raw_caps.get("gdi", False)),
        "dxgi": bool(raw_caps.get("dxgi", False)),
    }


def _query_engine_caps() -> dict:
    return {
        "wgc": bool(is_wgc_available()),
        "printwindow": bool(is_printwindow_available()),
        "gdi": bool(is_gdi_available()),
        "dxgi": bool(is_dxgi_available()),
    }


def _get_engine_caps(force_refresh: bool = False, allow_spawn: bool = False) -> dict:
    global _ENGINE_CAPS_CACHE, _ENGINE_CAPS_CACHE_TS
    _ = allow_spawn
    try:
        now = time.perf_counter()
        if (
            (not force_refresh)
            and _ENGINE_CAPS_CACHE
            and (now - _ENGINE_CAPS_CACHE_TS) <= _ENGINE_CAPS_CACHE_TTL_SEC
        ):
            return dict(_ENGINE_CAPS_CACHE)
        normalized = _normalize_engine_caps(_query_engine_caps())
        if normalized is None:
            return dict(_ENGINE_CAPS_CACHE) if _ENGINE_CAPS_CACHE else dict(_DEFAULT_ENGINE_CAPS)
        _ENGINE_CAPS_CACHE = dict(normalized)
        _ENGINE_CAPS_CACHE_TS = now
        return dict(_ENGINE_CAPS_CACHE)
    except Exception:
        return dict(_ENGINE_CAPS_CACHE) if _ENGINE_CAPS_CACHE else dict(_DEFAULT_ENGINE_CAPS)


def get_last_screenshot_error(engine: Optional[str] = None) -> str:
    target_engine = str(engine or get_screenshot_engine()).strip().lower()
    if target_engine == "wgc" and callable(_get_last_wgc_failure_reason):
        try:
            return str(_get_last_wgc_failure_reason() or "")
        except Exception:
            return ""
    if target_engine == "dxgi" and callable(_get_last_dxgi_failure_reason):
        try:
            return str(_get_last_dxgi_failure_reason() or "")
        except Exception:
            return ""
    return ""


def clear_screenshot_engine_cache(hwnd: int = None):
    try:
        target_engine = str(get_screenshot_engine() or "").strip().lower()
    except Exception:
        target_engine = "wgc"
    return _clear_screenshot_cache_by_engine(hwnd=hwnd, engine=target_engine)


def _clear_screenshot_cache_by_engine(hwnd: Optional[int] = None, engine: Optional[str] = None) -> bool:
    target_engine = str(engine or get_screenshot_engine()).strip().lower()
    try:
        if target_engine == "wgc":
            clear_wgc_cache(hwnd=hwnd)
        elif target_engine == "printwindow" and callable(_cleanup_printwindow_raw):
            _cleanup_printwindow_raw(hwnd=hwnd)
        elif target_engine == "gdi" and callable(_cleanup_gdi_raw):
            _cleanup_gdi_raw(hwnd=hwnd)
        elif target_engine == "dxgi" and callable(_cleanup_dxgi_raw):
            _cleanup_dxgi_raw(hwnd=hwnd)
        else:
            return False
        return True
    except Exception:
        return False


def cleanup_screenshot_engine_runtime(
    engine: Optional[str] = None,
    hwnd: Optional[int] = None,
    cleanup_d3d: bool = False,
):
    target_engine = str(engine or get_screenshot_engine()).strip().lower()
    try:
        if target_engine == "wgc":
            if callable(_cleanup_wgc_raw):
                _cleanup_wgc_raw(hwnd=hwnd, cleanup_d3d=cleanup_d3d if hwnd is None else False)
        elif target_engine == "printwindow" and callable(_cleanup_printwindow_raw):
            _cleanup_printwindow_raw(hwnd=hwnd)
        elif target_engine == "gdi" and callable(_cleanup_gdi_raw):
            _cleanup_gdi_raw(hwnd=hwnd)
        elif target_engine == "dxgi" and callable(_cleanup_dxgi_raw):
            _cleanup_dxgi_raw(hwnd=hwnd)
    except Exception:
        pass


def cleanup_screenshot_runtime() -> None:
    cleanup_screenshot_engine_runtime(engine="wgc", hwnd=None, cleanup_d3d=False)
    cleanup_screenshot_engine_runtime(engine="printwindow", hwnd=None, cleanup_d3d=False)
    cleanup_screenshot_engine_runtime(engine="gdi", hwnd=None, cleanup_d3d=False)
    cleanup_screenshot_engine_runtime(engine="dxgi", hwnd=None, cleanup_d3d=False)


def _cleanup_inactive_engines_after_switch(active_engine: str) -> None:
    target_engine = str(active_engine or "").strip().lower()
    for engine_name in ("wgc", "printwindow", "gdi", "dxgi"):
        if engine_name == target_engine:
            continue
        try:
            _clear_screenshot_cache_by_engine(hwnd=None, engine=engine_name)
        except Exception:
            pass
        try:
            cleanup_screenshot_engine_runtime(
                engine=engine_name,
                hwnd=None,
                cleanup_d3d=(engine_name == "wgc"),
            )
        except Exception:
            pass


def get_screenshot_capabilities() -> dict:
    return _get_engine_caps(force_refresh=True, allow_spawn=True)


def get_screenshot_stats(engine: Optional[str] = None) -> dict:
    target_engine = str(engine or get_screenshot_engine()).strip().lower()
    if target_engine == "wgc":
        return get_wgc_stats()
    if target_engine == "printwindow" and callable(_get_printwindow_capture):
        try:
            return dict((_get_printwindow_capture().get_stats() or {}))
        except Exception:
            return {}
    if target_engine == "gdi" and callable(_get_gdi_capture):
        try:
            return dict((_get_gdi_capture().get_stats() or {}))
        except Exception:
            return {}
    if target_engine == "dxgi" and callable(_get_dxgi_capture):
        try:
            return dict((_get_dxgi_capture().get_stats() or {}))
        except Exception:
            return {}
    return {}


caps = _get_engine_caps(force_refresh=False, allow_spawn=False)
WGC_AVAILABLE = bool(caps.get("wgc", False))
PRINTWINDOW_AVAILABLE = bool(caps.get("printwindow", False))
GDI_AVAILABLE = bool(caps.get("gdi", False))
DXGI_AVAILABLE = bool(caps.get("dxgi", False))

logger.info("[OK] 截图引擎本地模式已启用")
atexit.register(cleanup_screenshot_runtime)


# ==================== 截图引擎管理 ====================

def set_screenshot_engine(engine: str) -> bool:
    """
    设置当前使用的截图引擎

    Args:
        engine: 引擎名称 ('wgc', 'printwindow', 'gdi', 'dxgi')
    """
    global _current_engine
    global WGC_AVAILABLE, PRINTWINDOW_AVAILABLE, GDI_AVAILABLE, DXGI_AVAILABLE
    requested_engine = str(engine or "").strip().lower()
    if requested_engine not in SUPPORTED_SCREENSHOT_ENGINES:
        raise ValueError(f"未知的截图引擎: {engine}")

    # 只在短时间内持锁读取当前状态，避免能力探测长期占用锁导致 UI 卡顿。
    with _engine_lock:
        previous_engine = str(_current_engine or "").strip().lower()
        available_map = {
            'wgc': bool(WGC_AVAILABLE),
            'printwindow': bool(PRINTWINDOW_AVAILABLE),
            'gdi': bool(GDI_AVAILABLE),
            'dxgi': bool(DXGI_AVAILABLE),
        }

    try:
        # 用户显式切换引擎时，主动刷新能力探测，避免读取过期状态。
        for attempt in range(4):
            dynamic_caps = _get_engine_caps(force_refresh=True, allow_spawn=True)  # type: ignore[name-defined]
            if isinstance(dynamic_caps, dict):
                available_map.update({
                    'wgc': bool(dynamic_caps.get('wgc', available_map['wgc'])),
                    'printwindow': bool(dynamic_caps.get('printwindow', available_map['printwindow'])),
                    'gdi': bool(dynamic_caps.get('gdi', available_map['gdi'])),
                    'dxgi': bool(dynamic_caps.get('dxgi', available_map['dxgi'])),
                })
            if available_map.get(requested_engine, False):
                break
            if attempt < 3:
                time.sleep(0.12 * (attempt + 1))
    except Exception:
        pass

    if requested_engine == "dxgi" and not available_map.get("dxgi", False):
        # DXGI 能力若误判，以运行态探测做二次确认。
        try:
            if bool(probe_dxgi_runtime_available()):
                available_map["dxgi"] = True
        except Exception:
            pass

    # 与运行时能力保持一致，避免调用方读取过期常量。
    with _engine_lock:
        WGC_AVAILABLE = bool(available_map.get('wgc', False))
        PRINTWINDOW_AVAILABLE = bool(available_map.get('printwindow', False))
        GDI_AVAILABLE = bool(available_map.get('gdi', False))
        DXGI_AVAILABLE = bool(available_map.get('dxgi', False))

    if not available_map.get(requested_engine, False):
        # 严格模式：不可用时保持用户请求，不回退到其他引擎。
        with _engine_lock:
            _current_engine = requested_engine
        if previous_engine and previous_engine != requested_engine:
            _cleanup_inactive_engines_after_switch(active_engine=requested_engine)
        detail = ""
        if requested_engine == "dxgi":
            probe_notes = []
            try:
                from utils.dxgi_capture import is_dxgi_available as _is_dxgi_available
                from utils.dxgi_capture import get_dxgi_monitors as _get_dxgi_monitors
                main_probe_available = bool(_is_dxgi_available())
                probe_notes.append(f"main_probe_available={main_probe_available}")
                if main_probe_available:
                    try:
                        probe_notes.append(f"main_probe_monitors={len(_get_dxgi_monitors())}")
                    except Exception as monitor_exc:
                        probe_notes.append(f"main_probe_monitors_error={type(monitor_exc).__name__}")
            except Exception as probe_exc:
                probe_notes.append(f"main_probe_exception={type(probe_exc).__name__}")
            if probe_notes:
                detail = " (" + ", ".join(probe_notes) + ")"
        raise RuntimeError(f"截图引擎 {requested_engine} 不可用{detail}")

    with _engine_lock:
        _current_engine = requested_engine
    if previous_engine and previous_engine != requested_engine:
        _cleanup_inactive_engines_after_switch(active_engine=requested_engine)
    logger.info(f"截图引擎已切换到: {requested_engine}")
    return True


def get_screenshot_engine() -> str:
    """获取当前使用的截图引擎"""
    with _engine_lock:
        return _current_engine


def _capture_with_engine(
    hwnd: int,
    client_area_only: bool,
    engine: str,
    timeout: float = 4.0
) -> Optional[np.ndarray]:
    """
    使用指定引擎捕获窗口

    Args:
        hwnd: 窗口句柄
        client_area_only: 是否只捕获客户区
        engine: 引擎名称

    Returns:
        BGR 格式的 numpy 数组，失败返回 None
    """
    try:
        captured = None
        if engine == 'wgc':
            captured = capture_window_wgc(hwnd, client_area_only, timeout=timeout)
        elif engine == 'printwindow':
            captured = capture_window_printwindow(hwnd, client_area_only, timeout=timeout)
        elif engine == 'gdi':
            captured = capture_window_gdi(hwnd, client_area_only, timeout=timeout)
        elif engine == 'dxgi':
            captured = capture_window_dxgi(hwnd, client_area_only, timeout=timeout)
        else:
            raise ValueError(f"未知的截图引擎: {engine}")
        if captured is None:
            try:
                last_error = str(get_last_screenshot_error(engine=engine) or "").strip()
            except Exception:
                last_error = ""
            if last_error:
                logger.warning(f"引擎 {engine} 捕获失败: {last_error}")
        return captured
    except ValueError:
        raise
    except Exception as e:
        logger.error(f"引擎 {engine} 捕获失败: {e}")
        return None


def _get_pixel_color_with_engine(
    hwnd: int,
    x: int,
    y: int,
    client_coords: bool,
    engine: str
) -> Optional[Tuple[int, int, int]]:
    """
    使用指定引擎获取像素颜色

    Args:
        hwnd: 窗口句柄
        x: X 坐标
        y: Y 坐标
        client_coords: 是否为客户区坐标
        engine: 引擎名称

    Returns:
        (R, G, B) 颜色值，失败返回 None
    """
    try:
        if engine == 'wgc':
            return get_pixel_color_wgc(hwnd, x, y, client_coords)
        elif engine == 'printwindow':
            return get_pixel_color_printwindow(hwnd, x, y, client_coords)
        elif engine == 'gdi':
            return get_pixel_color_gdi(hwnd, x, y, client_coords)
        elif engine == 'dxgi':
            return get_pixel_color_dxgi(hwnd, x, y, client_coords)
        else:
            raise ValueError(f"未知的截图引擎: {engine}")
    except ValueError:
        raise
    except Exception as e:
        logger.error(f"引擎 {engine} 取色失败: {e}")
        return None
def get_screen_size():
    """获取主屏幕尺寸"""
    from utils.multi_monitor_manager import get_primary_screen_size
    return get_primary_screen_size()

def get_virtual_screen_bounds():
    """获取虚拟屏幕边界（支持多显示器）

    Returns:
        tuple: (left, top, width, height) 虚拟屏幕边界
    """
    from utils.multi_monitor_manager import get_multi_monitor_manager
    return get_multi_monitor_manager().get_virtual_screen_bounds()

def get_all_monitors():
    """获取所有显示器信息

    Returns:
        list: MonitorInfo 对象列表
    """
    from utils.multi_monitor_manager import get_multi_monitor_manager
    return get_multi_monitor_manager().get_monitors()

def get_monitor_for_window(hwnd):
    """获取窗口所在的显示器

    Args:
        hwnd: 窗口句柄

    Returns:
        MonitorInfo 或 None
    """
    from utils.multi_monitor_manager import get_multi_monitor_manager
    return get_multi_monitor_manager().get_monitor_for_window(hwnd)

def is_multi_monitor():
    """检查是否为多显示器配置

    Returns:
        bool: True 表示多显示器
    """
    from utils.multi_monitor_manager import get_multi_monitor_manager
    return get_multi_monitor_manager().is_multi_monitor()

def take_window_screenshot(hwnd, client_area_only=True, return_format="pil"):
    """
    截取指定窗口的截图 - 支持多种截图引擎

    支持引擎:
    - WGC: GPU 硬件加速，支持遮挡和后台窗口
    - PrintWindow: Win32 API，支持后台窗口
    - GDI: 传统截图方式，兼容性好
    - DXGI: Desktop Duplication，高性能，仅支持前台

    Args:
        hwnd: 窗口句柄
        client_area_only: 是否只截取客户区
        return_format: "pil" 或 "bgr"

    Returns:
        PIL.Image 或 BGR numpy 数组，失败返回 None
    """
    return_format = (return_format or "").strip().lower()
    if return_format not in ("pil", "bgr"):
        raise ValueError(f"未知的截图返回格式: {return_format!r}")

    # 检查窗口句柄是否有效
    if hwnd is None or hwnd == 0:
        logger.error("无效的窗口句柄: hwnd为None或0")
        return None

    try:
        # 获取当前截图引擎（严格使用当前引擎，不自动降级）
        engine_to_use = get_screenshot_engine()
        logger.debug(f"使用 {engine_to_use.upper()} 截图引擎捕获窗口: HWND={hwnd}, client_area_only={client_area_only}")

        # 使用当前引擎截图
        img_bgr = _capture_with_engine(hwnd, client_area_only, engine_to_use)

        if img_bgr is None or img_bgr.size == 0:
            logger.error(f"截图失败: HWND={hwnd}")
            return None

        # 转换为 PIL Image (BGR -> RGB)
        # 某些引擎返回的是 BGR，某些是 BGRA
        if return_format == "bgr":
            if len(img_bgr.shape) == 3:
                if img_bgr.shape[2] == 4:
                    img_bgr = cv2.cvtColor(img_bgr, cv2.COLOR_BGRA2BGR)
            else:
                img_bgr = cv2.cvtColor(img_bgr, cv2.COLOR_GRAY2BGR)
            logger.debug(f"Screenshot ok: hwnd={hwnd}, shape={img_bgr.shape}")
            return img_bgr

        if len(img_bgr.shape) == 3:
            if img_bgr.shape[2] == 4:
                img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGRA2RGB)
            else:
                img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        else:
            # 灰度图
            img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_GRAY2RGB)
        img_pil = Image.fromarray(img_rgb)

        logger.debug(f"截图成功: HWND={hwnd}, size={img_pil.size}")
        return img_pil

    except Exception as e:
        logger.exception(f"窗口截图失败: {e}")
        return None

def get_window_pixel_color(hwnd, x, y, client_coords=True):
    """
    获取窗口指定位置的颜色 - 使用当前截图引擎

    Args:
        hwnd: 窗口句柄
        x: X 坐标
        y: Y 坐标
        client_coords: 是否为客户区坐标

    Returns:
        tuple: (R, G, B) 颜色值，失败返回 None
    """
    # 获取当前引擎
    engine = get_screenshot_engine()

    try:
        color = _get_pixel_color_with_engine(hwnd, x, y, client_coords, engine)
        if color is not None:
            logger.debug(f"{engine.upper()} 取色成功: hwnd={hwnd}, pos=({x},{y}), color={color}")
            return color

        logger.error(f"{engine.upper()} 取色失败: hwnd={hwnd}, pos=({x},{y})")
        return None

    except Exception as e:
        logger.error(f"取色异常: {e}")
        return None

def is_screenshot_available():
    """
    检查截图功能是否可用

    Returns:
        bool: True 如果至少有一个引擎可用
    """
    try:
        caps = _get_engine_caps()  # type: ignore[name-defined]
        return any(bool(v) for v in caps.values())
    except Exception:
        return WGC_AVAILABLE or PRINTWINDOW_AVAILABLE or GDI_AVAILABLE or DXGI_AVAILABLE

def get_screenshot_info():
    """
    获取截图引擎信息

    Returns:
        dict: 截图引擎信息
    """
    engine = get_screenshot_engine()

    engine_names = {
        'wgc': 'WGC (Windows Graphics Capture)',
        'printwindow': 'PrintWindow (Win32 API)',
        'gdi': 'GDI (Graphics Device Interface)',
        'dxgi': 'DXGI (Desktop Duplication API)'
    }

    engine_features = {
        'wgc': ['GPU 硬件加速', '支持遮挡窗口', '支持后台窗口', 'Win10 1903+/Win11'],
        'printwindow': ['Win32 API', '支持后台窗口', '兼容性好'],
        'gdi': ['传统截图方式', '仅支持前台（可见区域）', '兼容性好'],
        'dxgi': ['GPU 硬件加速', '高性能', '仅支持前台', '多显示器支持']
    }

    info = {
        'current_engine': engine,
        'current_engine_name': engine_names.get(engine, 'Unknown'),
        'wgc_available': WGC_AVAILABLE,
        'printwindow_available': PRINTWINDOW_AVAILABLE,
        'gdi_available': GDI_AVAILABLE,
        'dxgi_available': DXGI_AVAILABLE,
        'features': engine_features.get(engine, [])
    }
    try:
        caps = _get_engine_caps()  # type: ignore[name-defined]
        if isinstance(caps, dict):
            info['wgc_available'] = bool(caps.get('wgc', info['wgc_available']))
            info['printwindow_available'] = bool(caps.get('printwindow', info['printwindow_available']))
            info['gdi_available'] = bool(caps.get('gdi', info['gdi_available']))
            info['dxgi_available'] = bool(caps.get('dxgi', info['dxgi_available']))
    except Exception:
        pass

    # 添加当前引擎的统计信息
    try:
        info['stats'] = dict(get_screenshot_stats(engine=engine) or {})
    except Exception:
        pass

    return info

def clear_screenshot_cache(hwnd: int = None):
    """清空截图缓存

    Args:
        hwnd: 窗口句柄，None表示清空所有缓存
    """
    try:
        clear_screenshot_engine_cache(hwnd=hwnd)
    except Exception as e:
        logger.error(f"清空缓存失败: {e}")

def cleanup_screenshot_engine(hwnd: int = None):
    """清理截图引擎资源

    Args:
        hwnd: 窗口句柄，None表示清理所有资源
    """
    try:
        # 全量清理时先停异步截图管道，避免引擎被并发占用
        if hwnd is None:
            try:
                _shutdown_existing_async_pipeline()
            except Exception:
                pass

        if hwnd is None:
            cleanup_screenshot_runtime()
        else:
            cleanup_screenshot_engine_runtime(engine=get_screenshot_engine(), hwnd=hwnd, cleanup_d3d=False)
    except Exception as e:
        logger.error(f"清理引擎资源失败: {e}")


def cleanup_all_screenshot_engines():
    """清理所有截图引擎资源（程序退出时调用）"""
    global _window_manager

    try:
        # 先关闭异步截图任务，避免清理过程中仍有截图任务占用引擎资源
        try:
            if _shutdown_existing_async_pipeline():
                logger.debug("异步截图管道已清理")
        except Exception as e:
            logger.error(f"异步截图管道清理失败: {e}")

        # 统一清理截图引擎
        try:
            cleanup_screenshot_runtime()
            logger.debug("截图引擎资源已清理")
        except Exception as e:
            logger.error(f"截图引擎清理失败: {e}")

        # 清理窗口管理器引用
        _window_manager = None

        logger.info("所有截图引擎资源已清理")
    except Exception as e:
        logger.error(f"清理所有截图引擎失败: {e}")


def _soft_cleanup_engine_runtime(engine: str, hwnd: int = None) -> bool:
    target_engine = str(engine or "").strip().lower()
    try:
        if target_engine == "wgc":
            if callable(_clear_wgc_cache_raw):
                _clear_wgc_cache_raw(hwnd=hwnd)
                return True
            return False
        if target_engine == "printwindow":
            if callable(_clear_printwindow_runtime_cache_raw):
                _clear_printwindow_runtime_cache_raw(hwnd=hwnd)
                return True
            return False
        if target_engine == "gdi":
            if callable(_clear_gdi_runtime_cache_raw):
                _clear_gdi_runtime_cache_raw(hwnd=hwnd)
                return True
            return False
        if target_engine == "dxgi":
            if callable(_clear_dxgi_runtime_cache_raw):
                _clear_dxgi_runtime_cache_raw(hwnd=hwnd)
                return True
            return False
    except Exception:
        return False
    return False


def cleanup_screenshot_engines_on_stop(keep_current_engine: bool = True):
    """停止任务时清理截图资源，默认保留当前引擎实例避免重复初始化。"""
    try:
        try:
            _shutdown_existing_async_pipeline()
        except Exception as e:
            logger.error(f"停止时异步截图管道清理失败: {e}")

        try:
            from services.screenshot_pool import clear_screenshot_runtime_state
            clear_screenshot_runtime_state(hwnd=None)
        except Exception:
            pass

        if not bool(keep_current_engine):
            cleanup_screenshot_runtime()
            logger.info("停止时已清理全部截图引擎")
            return

        try:
            current_engine = str(get_screenshot_engine() or "").strip().lower()
        except Exception:
            current_engine = ""

        valid_engines = {"wgc", "printwindow", "gdi", "dxgi"}
        if current_engine not in valid_engines:
            cleanup_screenshot_runtime()
            logger.warning("停止时当前截图引擎未知，已回退为全量清理")
            return

        _soft_cleanup_engine_runtime(current_engine, hwnd=None)

        for engine_name in ("wgc", "printwindow", "gdi", "dxgi"):
            if engine_name == current_engine:
                continue
            try:
                _clear_screenshot_cache_by_engine(hwnd=None, engine=engine_name)
            except Exception:
                pass
            try:
                cleanup_screenshot_engine_runtime(
                    engine=engine_name,
                    hwnd=None,
                    cleanup_d3d=(engine_name == "wgc"),
                )
            except Exception:
                pass

        logger.info(f"停止时截图引擎已清理（保留当前引擎实例）: {current_engine}")
    except Exception as e:
        logger.error(f"停止时清理截图引擎失败: {e}")

# ==================== 测试代码 ====================

if __name__ == "__main__":
    import time

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    logger.info("=" * 80)
    logger.info("截图助手模块测试")
    logger.info("=" * 80)

    # 检查可用性
    if not is_screenshot_available():
        logger.info("\n[ERROR] 截图功能不可用")
        logger.info(get_screenshot_info())
        exit(1)

    logger.info("\n[OK] 截图功能可用")
    logger.info("\n引擎信息:")
    info = get_screenshot_info()
    for key, value in info.items():
        if key != 'stats':
            logger.info(f"  {key}: {value}")

    logger.info("\n可用窗口:")
    windows = []

    def callback(hwnd, extra):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if title:
                windows.append((hwnd, title))

    win32gui.EnumWindows(callback, None)

    for i, (hwnd, title) in enumerate(windows[:10]):
        logger.info(f"{i+1}. {title[:60]} (HWND: {hwnd})")

    # 选择窗口
    try:
        choice = int(input("\n选择窗口编号 (直接回车选择第1个): ") or "1")
        test_hwnd, title = windows[choice - 1]
    except Exception:
        test_hwnd, title = windows[0]

    logger.info(f"\n测试窗口: {title}")
    logger.info(f"HWND: {test_hwnd}")

    # 测试截图
    logger.info("\n" + "=" * 80)
    logger.info("测试: 窗口截图")
    logger.info("=" * 80)

    start = time.time()
    screenshot = take_window_screenshot(test_hwnd, client_area_only=True)
    elapsed_ms = (time.time() - start) * 1000

    if screenshot is not None:
        logger.info("[OK] 截图成功")
        logger.info(f"  尺寸: {screenshot.size}")
        logger.info(f"  耗时: {elapsed_ms:.1f}ms")
        screenshot.save("screenshot_test.png")
        logger.info("  已保存: screenshot_test.png")
    else:
        logger.info("✗ 截图失败")

    # 测试取色
    logger.info("\n" + "=" * 80)
    logger.info("测试: 像素颜色获取")
    logger.info("=" * 80)

    color = get_window_pixel_color(test_hwnd, 100, 100, client_coords=True)
    if color:
        logger.info(f"[OK] 坐标 (100, 100) 的颜色: R={color[0]}, G={color[1]}, B={color[2]}")
    else:
        logger.info("[ERROR] 获取颜色失败")

    # 统计信息
    logger.info("\n" + "=" * 80)
    logger.info("统计信息")
    logger.info("=" * 80)

    info = get_screenshot_info()
    if 'stats' in info:
        for key, value in info['stats'].items():
            logger.info(f"  {key}: {value}")

    logger.info("\n" + "=" * 80)
    logger.info("测试完成")
    logger.info("=" * 80)



