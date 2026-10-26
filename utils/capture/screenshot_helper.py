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

from utils.window.hwnd_utils import as_hwnd
from utils.capture.engine_ids import (
    SUPPORTED_SCREENSHOT_ENGINES,
    canonicalize_screenshot_engine,
    is_plugin_screenshot_engine,
    is_supported_screenshot_engine,
    screenshot_engine_log_label,
)

logger = logging.getLogger(__name__)


def _shutdown_existing_async_pipeline() -> bool:
    """Stop the async pipeline without importing new modules during shutdown."""
    async_module = sys.modules.get("utils.capture.async_screenshot")
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

def set_window_manager(manager):
    """设置全局窗口管理器实例（由 main.py 调用）"""
    global _window_manager
    _window_manager = manager
    logger.info("[OK] 窗口管理器实例已设置")

# 截图引擎（主进程直连，不再走子进程）
try:
    import utils.capture.wgc_hwnd_capture as _wgc_module
    from utils.capture.wgc_hwnd_capture import (
        capture_window_wgc_optimized as _capture_window_wgc_raw,
        clear_wgc_cache as _clear_wgc_cache_raw,
        cleanup_wgc as _cleanup_wgc_raw,
        get_existing_global_capture as _get_existing_wgc_capture,
        get_global_capture as _get_global_wgc_capture,
        get_last_wgc_capture_failure_reason as _get_last_wgc_failure_reason,
    )
except Exception as e:
    _wgc_module = None
    _capture_window_wgc_raw = None
    _clear_wgc_cache_raw = None
    _cleanup_wgc_raw = None
    _get_existing_wgc_capture = None
    _get_global_wgc_capture = None
    _get_last_wgc_failure_reason = None
    logger.warning(f"[ERROR] WGC 引擎不可用: {e}")

try:
    from utils.capture.printwindow_capture import (
        capture_window_printwindow as _capture_window_printwindow_raw,
        clear_printwindow_runtime_cache as _clear_printwindow_runtime_cache_raw,
        cleanup_printwindow as _cleanup_printwindow_raw,
        get_existing_global_capture as _get_printwindow_capture,
        get_last_printwindow_capture_failure_reason as _get_last_printwindow_failure_reason,
        get_pixel_color_printwindow as _get_pixel_color_printwindow_raw,
        is_printwindow_available as _is_printwindow_available_raw,
    )
except Exception as e:
    _capture_window_printwindow_raw = None
    _clear_printwindow_runtime_cache_raw = None
    _cleanup_printwindow_raw = None
    _get_printwindow_capture = None
    _get_last_printwindow_failure_reason = None
    _get_pixel_color_printwindow_raw = None
    _is_printwindow_available_raw = None
    logger.warning(f"[ERROR] PrintWindow 引擎不可用: {e}")

try:
    from utils.capture.gdi_capture import (
        capture_screen_gdi as _capture_screen_gdi_raw,
        capture_window_gdi as _capture_window_gdi_raw,
        clear_gdi_runtime_cache as _clear_gdi_runtime_cache_raw,
        cleanup_gdi as _cleanup_gdi_raw,
        get_existing_global_capture as _get_gdi_capture,
        get_pixel_color_gdi as _get_pixel_color_gdi_raw,
        is_gdi_available as _is_gdi_available_raw,
    )
except Exception as e:
    _capture_screen_gdi_raw = None
    _capture_window_gdi_raw = None
    _clear_gdi_runtime_cache_raw = None
    _cleanup_gdi_raw = None
    _get_gdi_capture = None
    _get_pixel_color_gdi_raw = None
    _is_gdi_available_raw = None
    logger.warning(f"[ERROR] GDI 引擎不可用: {e}")

try:
    from utils.capture.dxgi_capture import (
        capture_screen_dxgi as _capture_screen_dxgi_raw,
        capture_window_dxgi as _capture_window_dxgi_raw,
        clear_dxgi_runtime_cache as _clear_dxgi_runtime_cache_raw,
        cleanup_dxgi as _cleanup_dxgi_raw,
        get_dxgi_monitors as _get_dxgi_monitors_raw,
        get_existing_global_capture as _get_dxgi_capture,
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

try:
    from utils.plugin.capture import (
        capture_window_plugin as _capture_window_plugin_raw,
        cleanup_plugin as _cleanup_plugin_raw,
        clear_plugin_runtime_cache as _clear_plugin_runtime_cache_raw,
        get_last_plugin_capture_failure_reason as _get_last_plugin_failure_reason,
        get_pixel_color_plugin as _get_pixel_color_plugin_raw,
        is_plugin_capture_available as _is_plugin_capture_available_raw,
    )
except Exception as e:
    _capture_window_plugin_raw = None
    _cleanup_plugin_raw = None
    _clear_plugin_runtime_cache_raw = None
    _get_last_plugin_failure_reason = None
    _get_pixel_color_plugin_raw = None
    _is_plugin_capture_available_raw = None
    logger.warning(f"[ERROR] 插件截图引擎不可用: {e}")


def _safe_timeout_ms(timeout: float) -> int:
    value = int(float(timeout) * 1000)
    if value <= 0 or value > 30000:
        raise ValueError("截图超时必须大于0且不超过30秒")
    return value


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
    return None


def get_pixel_color_gdi(hwnd: int, x: int, y: int, client_coords: bool = True):
    if callable(_get_pixel_color_gdi_raw):
        try:
            return _get_pixel_color_gdi_raw(hwnd, x, y, client_coords)
        except Exception:
            return None
    return None


def get_pixel_color_dxgi(hwnd: int, x: int, y: int, client_coords: bool = True):
    if callable(_get_pixel_color_dxgi_raw):
        try:
            return _get_pixel_color_dxgi_raw(hwnd, x, y, client_coords)
        except Exception:
            return None
    return None


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


def is_plugin_available() -> bool:
    if callable(_is_plugin_capture_available_raw):
        try:
            return bool(_is_plugin_capture_available_raw())
        except Exception:
            return False
    return False


def capture_window_plugin(
    hwnd: int,
    display: str,
    client_area_only: bool = True,
    timeout: float = 4.0,
):
    if not callable(_capture_window_plugin_raw):
        return None
    try:
        return _capture_window_plugin_raw(
            hwnd=hwnd,
            display=display,
            client_area_only=client_area_only,
            timeout=timeout,
        )
    except Exception:
        return None


def get_pixel_color_plugin(hwnd: int, x: int, y: int, display: str, client_coords: bool = True):
    if callable(_get_pixel_color_plugin_raw):
        try:
            return _get_pixel_color_plugin_raw(hwnd, x, y, display, client_coords)
        except Exception:
            return None
    return None


def get_dxgi_monitors():
    if callable(_get_dxgi_monitors_raw):
        try:
            return list(_get_dxgi_monitors_raw() or [])
        except Exception:
            return []
    return []


def probe_dxgi_runtime_available() -> bool:
    return bool(is_dxgi_available() and get_dxgi_monitors())


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
    if not callable(_clear_wgc_cache_raw):
        raise RuntimeError("WGC缓存清理接口不可用")
    _clear_wgc_cache_raw(hwnd=hwnd)


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


def _build_engine_caps() -> dict:
    plugin_ok = bool(is_plugin_available())
    caps = {
        "wgc": bool(is_wgc_available()),
        "printwindow": bool(is_printwindow_available()),
        "gdi": bool(is_gdi_available()),
        "dxgi": bool(is_dxgi_available()),
    }
    for engine_name in SUPPORTED_SCREENSHOT_ENGINES:
        if is_plugin_screenshot_engine(engine_name):
            caps[engine_name] = plugin_ok
    return caps


_ENGINE_CAPS_CACHE = {}
_ENGINE_CAPS_CACHE_TS = 0.0
_ENGINE_CAPS_CACHE_TTL_SEC = 2.0


def _normalize_engine_caps(raw_caps) -> Optional[dict]:
    if not isinstance(raw_caps, dict):
        return None
    normalized = {}
    for engine_name in SUPPORTED_SCREENSHOT_ENGINES:
        if engine_name not in raw_caps or not isinstance(raw_caps[engine_name], bool):
            return None
        normalized[engine_name] = raw_caps[engine_name]
    return normalized


def _query_engine_caps() -> dict:
    return _build_engine_caps()


def _get_engine_caps(force_refresh: bool = False) -> dict:
    global _ENGINE_CAPS_CACHE, _ENGINE_CAPS_CACHE_TS
    now = time.perf_counter()
    if not force_refresh and _ENGINE_CAPS_CACHE and now - _ENGINE_CAPS_CACHE_TS <= _ENGINE_CAPS_CACHE_TTL_SEC:
        return dict(_ENGINE_CAPS_CACHE)
    normalized = _normalize_engine_caps(_query_engine_caps())
    if normalized is None:
        raise RuntimeError("截图引擎能力查询结果未知")
    _ENGINE_CAPS_CACHE = dict(normalized)
    _ENGINE_CAPS_CACHE_TS = now
    return dict(normalized)


def get_last_screenshot_error(engine: Optional[str] = None) -> str:
    target_engine = str(engine or get_screenshot_engine()).strip().lower()
    if target_engine == "wgc" and callable(_get_last_wgc_failure_reason):
        try:
            return str(_get_last_wgc_failure_reason() or "")
        except Exception:
            return ""
    if target_engine == "printwindow" and callable(_get_last_printwindow_failure_reason):
        try:
            return str(_get_last_printwindow_failure_reason() or "")
        except Exception:
            return ""
    if target_engine == "dxgi" and callable(_get_last_dxgi_failure_reason):
        try:
            return str(_get_last_dxgi_failure_reason() or "")
        except Exception:
            return ""
    if is_plugin_screenshot_engine(target_engine) and callable(_get_last_plugin_failure_reason):
        try:
            return str(_get_last_plugin_failure_reason() or "")
        except Exception:
            return ""
    return ""


def clear_screenshot_engine_cache(hwnd: int = None):
    return _clear_screenshot_cache_by_engine(hwnd=hwnd, engine=get_screenshot_engine())


def _clear_screenshot_cache_by_engine(hwnd: Optional[int] = None, engine: Optional[str] = None) -> bool:
    target_engine = get_screenshot_engine() if engine is None else str(engine).strip().lower()
    try:
        if target_engine == "wgc":
            clear_wgc_cache(hwnd=hwnd)
        elif target_engine == "printwindow" and callable(_cleanup_printwindow_raw):
            _cleanup_printwindow_raw(hwnd=hwnd)
        elif target_engine == "gdi" and callable(_cleanup_gdi_raw):
            _cleanup_gdi_raw(hwnd=hwnd)
        elif target_engine == "dxgi" and callable(_cleanup_dxgi_raw):
            _cleanup_dxgi_raw(hwnd=hwnd)
        elif is_plugin_screenshot_engine(target_engine) and callable(_clear_plugin_runtime_cache_raw):
            _clear_plugin_runtime_cache_raw(hwnd=hwnd)
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
    target_engine = get_screenshot_engine() if engine is None else str(engine).strip().lower()
    if not is_supported_screenshot_engine(target_engine):
        raise ValueError(f"未知的截图引擎：{target_engine}")
    if target_engine == "wgc":
        if callable(_cleanup_wgc_raw):
            _cleanup_wgc_raw(hwnd=hwnd, cleanup_d3d=cleanup_d3d if hwnd is None else False)
        return
    cleanup = {
        "printwindow": _cleanup_printwindow_raw,
        "gdi": _cleanup_gdi_raw,
        "dxgi": _cleanup_dxgi_raw,
    }.get(target_engine)
    if is_plugin_screenshot_engine(target_engine):
        cleanup = _cleanup_plugin_raw
    if callable(cleanup):
        cleanup(hwnd=hwnd)


def cleanup_screenshot_runtime() -> None:
    errors = []
    engines = ["wgc", "printwindow", "gdi", "dxgi"]
    plugins = [name for name in SUPPORTED_SCREENSHOT_ENGINES if is_plugin_screenshot_engine(name)]
    if plugins:
        engines.append(plugins[0])
    for name in engines:
        try:
            cleanup_screenshot_engine_runtime(engine=name, hwnd=None, cleanup_d3d=True)
        except Exception as exc:
            errors.append(f"{name}：{exc}")
    if errors:
        raise RuntimeError("截图资源清理未完成：" + "；".join(errors))


def _cleanup_inactive_engines_after_switch(active_engine: str) -> None:
    target_engine = str(active_engine or "").strip().lower()
    errors = []
    plugin_cleaned = False
    for engine_name in SUPPORTED_SCREENSHOT_ENGINES:
        if engine_name == target_engine:
            continue
        if is_plugin_screenshot_engine(engine_name):
            if is_plugin_screenshot_engine(target_engine) or plugin_cleaned:
                continue
            plugin_cleaned = True
        try:
            cleanup_screenshot_engine_runtime(
                engine=engine_name,
                hwnd=None,
                cleanup_d3d=(engine_name == "wgc"),
            )
        except Exception as exc:
            errors.append(f"{engine_name}：{exc}")
    if errors:
        raise RuntimeError("切换截图引擎后资源清理未完成：" + "；".join(errors))


def get_screenshot_capabilities() -> dict:
    return _get_engine_caps(force_refresh=True)


def get_screenshot_diagnostics() -> dict:
    """Return engine capabilities together with current engine failure detail."""
    caps = get_screenshot_capabilities()
    current = str(get_screenshot_engine() or "").strip().lower()
    errors = {}
    for name, available in caps.items():
        if bool(available):
            continue
        try:
            detail = str(get_last_screenshot_error(name) or "").strip()
        except Exception:
            detail = ""
        errors[name] = detail or "不可用或未初始化"
    return {"current_engine": current, "capabilities": dict(caps), "errors": errors}


def get_screenshot_stats(engine: Optional[str] = None) -> dict:
    target_engine = str(engine or get_screenshot_engine()).strip().lower()
    if target_engine == "wgc":
        return get_wgc_stats()
    if target_engine == "printwindow" and callable(_get_printwindow_capture):
        try:
            capture = _get_printwindow_capture()
            return dict(capture.get_stats()) if capture is not None else {}
        except Exception:
            return {}
    if target_engine == "gdi" and callable(_get_gdi_capture):
        try:
            capture = _get_gdi_capture()
            return dict(capture.get_stats()) if capture is not None else {}
        except Exception:
            return {}
    if target_engine == "dxgi" and callable(_get_dxgi_capture):
        try:
            capture = _get_dxgi_capture()
            return dict(capture.get_stats()) if capture is not None else {}
        except Exception:
            return {}
    return {}


caps = _get_engine_caps(force_refresh=False)
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
    requested_engine = canonicalize_screenshot_engine(engine)
    if not is_supported_screenshot_engine(requested_engine):
        raise ValueError(f"未知的截图引擎: {engine}")

    # 只在短时间内持锁读取当前状态，避免能力探测长期占用锁导致 UI 卡顿。
    with _engine_lock:
        previous_engine = str(_current_engine or "").strip().lower()

    available_map = _get_engine_caps(force_refresh=True)

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
        raise RuntimeError(f"截图引擎 {requested_engine} 不可用")

    with _engine_lock:
        _current_engine = requested_engine
    if previous_engine and previous_engine != requested_engine:
        _cleanup_inactive_engines_after_switch(active_engine=requested_engine)
    logger.info(f"截图引擎已切换到: {screenshot_engine_log_label(requested_engine)}")
    return True


def get_screenshot_engine() -> str:
    """获取当前使用的截图引擎"""
    with _engine_lock:
        return _current_engine


def capture_desktop_frame(engine: str = "") -> Optional[np.ndarray]:
    engine_name = get_screenshot_engine() if not engine else str(engine).strip().lower()
    if engine_name == "dxgi":
        return capture_screen_dxgi()
    if engine_name == "gdi" and callable(_capture_screen_gdi_raw):
        return _capture_screen_gdi_raw()
    logger.error("截图引擎%s不支持桌面截图", engine_name)
    return None


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
        from utils.window.window_identity import is_desktop_window

        if is_desktop_window(hwnd):
            logger.debug("按指定引擎执行桌面截图")
            return capture_desktop_frame(engine)

        captured = None
        if engine == 'wgc':
            captured = capture_window_wgc(hwnd, client_area_only, timeout=timeout)
        elif engine == 'printwindow':
            captured = capture_window_printwindow(hwnd, client_area_only, timeout=timeout)
        elif engine == 'gdi':
            captured = capture_window_gdi(hwnd, client_area_only, timeout=timeout)
        elif engine == 'dxgi':
            captured = capture_window_dxgi(hwnd, client_area_only, timeout=timeout)
        elif is_plugin_screenshot_engine(engine):
            captured = capture_window_plugin(hwnd, engine, client_area_only, timeout=timeout)
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


def capture_window_frame(
    hwnd: int,
    client_area_only: bool = True,
    timeout: float = 4.0,
) -> Optional[np.ndarray]:
    """使用当前配置的截图引擎捕获一帧窗口画面（BGR/BGRA ndarray，失败返回 None）。"""
    try:
        engine = get_screenshot_engine()
        return _capture_with_engine(
            int(hwnd),
            bool(client_area_only),
            engine,
            timeout=max(0.1, float(timeout)),
        )
    except Exception as e:
        logger.error(f"窗口截图失败: {e}")
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
        from utils.window.window_identity import is_desktop_window

        if is_desktop_window(hwnd):
            return _pixel_color_from_frame(capture_desktop_frame(engine), x, y)
        if engine == 'wgc':
            return get_pixel_color_wgc(hwnd, x, y, client_coords)
        elif engine == 'printwindow':
            return get_pixel_color_printwindow(hwnd, x, y, client_coords)
        elif engine == 'gdi':
            return get_pixel_color_gdi(hwnd, x, y, client_coords)
        elif engine == 'dxgi':
            return get_pixel_color_dxgi(hwnd, x, y, client_coords)
        elif is_plugin_screenshot_engine(engine):
            return get_pixel_color_plugin(hwnd, x, y, engine, client_coords)
        else:
            raise ValueError(f"未知的截图引擎: {engine}")
    except ValueError:
        raise
    except Exception as e:
        logger.error(f"引擎 {engine} 取色失败: {e}")
        return None
def get_screen_size():
    """获取主屏幕尺寸"""
    from utils.window.multi_monitor_manager import get_primary_screen_size
    return get_primary_screen_size()

def get_virtual_screen_bounds():
    """获取虚拟屏幕边界（支持多显示器）

    Returns:
        tuple: (left, top, width, height) 虚拟屏幕边界
    """
    from utils.window.multi_monitor_manager import get_multi_monitor_manager
    return get_multi_monitor_manager().get_virtual_screen_bounds()

def get_all_monitors():
    """获取所有显示器信息

    Returns:
        list: MonitorInfo 对象列表
    """
    from utils.window.multi_monitor_manager import get_multi_monitor_manager
    return get_multi_monitor_manager().get_monitors()

def get_monitor_for_window(hwnd):
    """获取窗口所在的显示器

    Args:
        hwnd: 窗口句柄

    Returns:
        MonitorInfo 或 None
    """
    from utils.window.multi_monitor_manager import get_multi_monitor_manager
    return get_multi_monitor_manager().get_monitor_for_window(hwnd)

def is_multi_monitor():
    """检查是否为多显示器配置

    Returns:
        bool: True 表示多显示器
    """
    from utils.window.multi_monitor_manager import get_multi_monitor_manager
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
    hwnd = as_hwnd(hwnd)
    if not hwnd:
        logger.error("无效的窗口句柄: hwnd为None或0")
        return None

    try:
        # 获取当前截图引擎（严格使用当前引擎，不自动降级）
        engine_to_use = get_screenshot_engine()
        logger.debug(f"使用 {screenshot_engine_log_label(engine_to_use)} 截图引擎捕获窗口: HWND={hwnd}, client_area_only={client_area_only}")

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
            logger.debug(f"{screenshot_engine_log_label(engine)} 取色成功: hwnd={hwnd}, pos=({x},{y}), color={color}")
            return color

        logger.error(f"{screenshot_engine_log_label(engine)} 取色失败: hwnd={hwnd}, pos=({x},{y})")
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
    return any(_get_engine_caps().values())

def get_screenshot_info():
    """
    获取截图引擎信息

    Returns:
        dict: 截图引擎信息
    """
    engine = get_screenshot_engine()
    caps = _get_engine_caps()

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
        'current_engine_name': engine_names.get(engine, screenshot_engine_log_label(engine)),
        'wgc_available': caps['wgc'],
        'printwindow_available': caps['printwindow'],
        'gdi_available': caps['gdi'],
        'dxgi_available': caps['dxgi'],
        'features': engine_features.get(engine, [])
    }
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
    return clear_screenshot_engine_cache(hwnd=hwnd)

def cleanup_screenshot_engine(hwnd: int = None):
    if hwnd is None:
        errors = []
        for cleanup in (_shutdown_existing_async_pipeline, cleanup_screenshot_runtime):
            try:
                cleanup()
            except Exception as exc:
                errors.append(str(exc))
        if errors:
            raise RuntimeError("截图资源清理未完成：" + "；".join(errors))
    else:
        cleanup_screenshot_engine_runtime(engine=get_screenshot_engine(), hwnd=hwnd, cleanup_d3d=False)


def cleanup_all_screenshot_engines():
    """退出时尝试所有清理入口，失败不得报告完成。"""
    global _window_manager
    errors = []
    for cleanup in (_shutdown_existing_async_pipeline, cleanup_screenshot_runtime):
        try:
            cleanup()
        except Exception as exc:
            errors.append(str(exc))
    _window_manager = None
    if errors:
        raise RuntimeError("截图资源清理未完成：" + "；".join(errors))
    logger.info("所有截图引擎资源已清理")


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
        if is_plugin_screenshot_engine(target_engine):
            return True
    except Exception:
        return False
    return False


def cleanup_screenshot_engines_on_stop(keep_current_engine: bool = True):
    errors = []
    try:
        _shutdown_existing_async_pipeline()
    except Exception as exc:
        errors.append(str(exc))
    if not keep_current_engine:
        try:
            cleanup_screenshot_runtime()
        except Exception as exc:
            errors.append(str(exc))
        if errors:
            raise RuntimeError("停止时截图资源清理未完成：" + "；".join(errors))
        return
    current = get_screenshot_engine()
    if not is_supported_screenshot_engine(current):
        raise RuntimeError("当前截图引擎未知，无法确定清理范围")
    if not _soft_cleanup_engine_runtime(current, hwnd=None):
        errors.append(f"{current}缓存清理失败")
    plugin_cleaned = False
    for name in SUPPORTED_SCREENSHOT_ENGINES:
        if name == current:
            continue
        if is_plugin_screenshot_engine(name):
            if is_plugin_screenshot_engine(current) or plugin_cleaned:
                continue
            plugin_cleaned = True
        try:
            cleanup_screenshot_engine_runtime(engine=name, hwnd=None, cleanup_d3d=(name == "wgc"))
        except Exception as exc:
            errors.append(f"{name}：{exc}")
    if errors:
        raise RuntimeError("停止时截图资源清理未完成：" + "；".join(errors))
