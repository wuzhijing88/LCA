# -*- coding: utf-8 -*-
"""插件挂钩截图：按 display 模式绑定窗口后取帧。"""

from __future__ import annotations

import atexit
import logging
import threading
from typing import Optional

import numpy as np

from utils.capture.engine_ids import is_plugin_screenshot_engine
from utils.plugin.runtime import is_plugin_runtime_available
from utils.plugin.session import close_shared_plugin_client, get_shared_plugin_client

logger = logging.getLogger(__name__)

_LOCK = threading.RLock()
_LAST_FAILURE = ""


def is_plugin_capture_available() -> bool:
    return bool(is_plugin_runtime_available())


def get_last_plugin_capture_failure_reason() -> str:
    with _LOCK:
        return str(_LAST_FAILURE or "")


def _set_failure(reason: str) -> None:
    global _LAST_FAILURE
    _LAST_FAILURE = str(reason or "").strip()


def capture_window_plugin(
    hwnd: int,
    display: str,
    client_area_only: bool = True,
    timeout: float = 4.0,
    fallback: bool = False,
    bind_extras=None,
    bind_params=None,
) -> Optional[np.ndarray]:
    """按配置的 display 绑定并取帧。默认不静默降级：绑不上就返回 None 并给出可读原因。

    bind_extras=(public, fake_active) 可覆盖运行时配置里的可选绑定参数（设置页边改边试绑用）。
    """
    target = int(hwnd or 0)
    mode = str(display or "").strip().lower()
    if target <= 0 or not is_plugin_screenshot_engine(mode):
        _set_failure("invalid hwnd or display mode")
        return None
    if not is_plugin_capture_available():
        _set_failure("plugin runtime unavailable")
        return None
    try:
        input_hwnd = target
        try:
            from utils.window.window_binding_utils import resolve_plugin_input_hwnd_for_display

            input_hwnd = int(resolve_plugin_input_hwnd_for_display(target) or target)
        except Exception:
            input_hwnd = target
        session = get_shared_plugin_client(target)
        frame = session.capture_bgr(
            target,
            mode,
            input_hwnd=input_hwnd,
            timeout=timeout,
            client_area_only=client_area_only,
            fallback=fallback,
            bind_extras=bind_extras,
            bind_params=bind_params,
        )
        if frame is None:
            reason = session.last_bind_failure_text() if session.last_bind_outcome is not None else "绑定成功但取帧为空"
            _set_failure(
                f"插件截图失败 hwnd={target}：{reason}；"
                "挂钩类 display（dx/opengl）要求目标确实用对应方式渲染，否则请改用 normal / gdi2 或原生 WGC / PrintWindow"
            )
            return None
        _set_failure("")
        return frame
    except Exception as exc:
        _set_failure(f"{type(exc).__name__}: {exc}")
        logger.warning("插件截图失败: hwnd=%s display=%s error=%s", target, mode, exc)
        return None


def get_pixel_color_plugin(
    hwnd: int,
    x: int,
    y: int,
    display: str,
    client_coords: bool = True,
) -> Optional[tuple[int, int, int]]:
    frame = capture_window_plugin(hwnd, display, client_area_only=client_coords)
    if frame is None:
        return None
    if y < 0 or x < 0 or y >= frame.shape[0] or x >= frame.shape[1]:
        return None
    b, g, r = (int(frame[y, x, 0]), int(frame[y, x, 1]), int(frame[y, x, 2]))
    return (r, g, b)


def cleanup_plugin(hwnd: int = None) -> None:
    with _LOCK:
        close_shared_plugin_client(hwnd)


def clear_plugin_runtime_cache(hwnd: int = None) -> None:
    cleanup_plugin(hwnd=hwnd)


atexit.register(cleanup_plugin)
