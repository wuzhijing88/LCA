# -*- coding: utf-8 -*-
"""Win32 HWND 规范化。

HWND 在 Windows 上是无符号句柄。pywin32 常把它收成有符号 32 位 LONG，
PySide 的 Signal(int) 也是 32 位有符号。当最高位为 1 时，Python 会显示成负数，
例如 0xEEC22B54 -> -289143244。这不是句柄失效，只是符号解释错误。
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

_HWND_U32_MASK = 0xFFFFFFFF


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
    """就地把绑定窗口列表里的 hwnd 规范成无符号 32 位。"""
    if not isinstance(windows, list):
        return
    for item in windows:
        if isinstance(item, dict) and "hwnd" in item:
            item["hwnd"] = as_hwnd(item.get("hwnd"))
