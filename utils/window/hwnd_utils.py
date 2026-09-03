# -*- coding: utf-8 -*-
"""Win32 HWND 规范化。

HWND 在 Windows 上是无符号句柄。pywin32 常把它收成有符号 32 位 LONG，
PySide 的 Signal(int) 也是 32 位有符号。当最高位为 1 时，Python 会显示成负数，
例如 0xEEC22B54 -> -289143244。这不是句柄失效，只是符号解释错误。
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Any, Iterable, Optional

_HWND_U32_MASK = 0xFFFFFFFF
_WM_GETTEXT = 0x000D
_SMTO_ABORTIFHUNG = 0x0002
_MAX_WINDOW_TEXT = 512

_user32 = ctypes.windll.user32
_InternalGetWindowText = getattr(_user32, "InternalGetWindowText", None)
if _InternalGetWindowText is not None:
    _InternalGetWindowText.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _InternalGetWindowText.restype = ctypes.c_int

_SendMessageTimeoutW = getattr(_user32, "SendMessageTimeoutW", None)
if _SendMessageTimeoutW is not None:
    _SendMessageTimeoutW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
        wintypes.UINT,
        wintypes.UINT,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    _SendMessageTimeoutW.restype = wintypes.LPARAM


def as_hwnd(hwnd: Any) -> int:
    """把 HWND 规范成无符号 32 位正整数；无效值返回 0。"""
    if hwnd is None or isinstance(hwnd, bool):
        return 0
    try:
        value = int(hwnd)
    except (TypeError, ValueError):
        return 0
    if value < 0:
        value &= _HWND_U32_MASK
    return int(value)


def hwnds_equal(left: Any, right: Any) -> bool:
    """比较两个 HWND 是否指向同一句柄（忽略有符号/无符号差异）。"""
    left_hwnd = as_hwnd(left)
    right_hwnd = as_hwnd(right)
    return left_hwnd != 0 and left_hwnd == right_hwnd


def normalize_bound_windows_hwnds(windows: Optional[Iterable[Any]]) -> None:
    """就地把绑定窗口列表里的 hwnd / input_hwnd 规范成无符号 32 位。"""
    if not isinstance(windows, list):
        return
    for item in windows:
        if not isinstance(item, dict):
            continue
        if "hwnd" in item:
            item["hwnd"] = as_hwnd(item.get("hwnd"))
        if "display_hwnd" in item:
            item["display_hwnd"] = as_hwnd(item.get("display_hwnd"))
        if "input_hwnd" in item:
            item["input_hwnd"] = as_hwnd(item.get("input_hwnd"))


def get_window_text(hwnd: Any, timeout_ms: int = 80) -> str:
    """读窗口标题，不走会卡住无响应窗口的 GetWindowText。"""
    handle = as_hwnd(hwnd)
    if handle == 0:
        return ""

    text = _internal_get_window_text(handle)
    if text:
        return text
    return _get_window_text_timeout(handle, timeout_ms)


def _internal_get_window_text(hwnd: int) -> str:
    if _InternalGetWindowText is None:
        return ""
    try:
        buffer = ctypes.create_unicode_buffer(_MAX_WINDOW_TEXT)
        length = int(_InternalGetWindowText(hwnd, buffer, _MAX_WINDOW_TEXT) or 0)
        if length <= 0:
            return ""
        return (buffer.value or "").strip()
    except Exception:
        return ""


def _get_window_text_timeout(hwnd: int, timeout_ms: int) -> str:
    if _SendMessageTimeoutW is None:
        return ""
    try:
        buffer = ctypes.create_unicode_buffer(_MAX_WINDOW_TEXT)
        result = ctypes.c_size_t(0)
        ok = _SendMessageTimeoutW(
            hwnd,
            _WM_GETTEXT,
            _MAX_WINDOW_TEXT,
            ctypes.cast(buffer, ctypes.c_void_p).value,
            _SMTO_ABORTIFHUNG,
            max(1, int(timeout_ms)),
            ctypes.byref(result),
        )
        if not ok:
            return ""
        return (buffer.value or "").strip()
    except Exception:
        return ""
