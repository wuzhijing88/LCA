# -*- coding: utf-8 -*-
"""原生仿真输入。

前台把每个 UTF-16 码元用 SendInput(KEYEVENTF_UNICODE) 送进系统键盘流，
窗口收到的是 WM_CHAR，当前输入法不会把字母重新当成拼音。
后台不抢前台，向目标窗口发送同样的 WM_CHAR。
"""

from __future__ import annotations

import ctypes
import logging
import math
from ctypes import wintypes

import win32gui

from utils.precise_sleep import precise_sleep

logger = logging.getLogger(__name__)

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = (
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    )


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = (
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    )


class _INPUTUNION(ctypes.Union):
    _fields_ = (("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT))


class _INPUT(ctypes.Structure):
    _fields_ = (("type", wintypes.DWORD), ("union", _INPUTUNION))


_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int)
_user32.SendInput.restype = wintypes.UINT


def _code_units(text: str) -> list[int]:
    data = str(text or "").encode("utf-16-le")
    return [data[index] | (data[index + 1] << 8) for index in range(0, len(data), 2)]


def _pause_seconds(delay: float) -> float:
    value = float(delay)
    if not math.isfinite(value) or value < 0:
        raise ValueError("文字输入间隔必须是大于等于零的有限数字")
    return value


def _emit_unicode_unit(unit: int) -> bool:
    events = (_INPUT * 2)()
    for index, key_up in enumerate((False, True)):
        flags = KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if key_up else 0)
        events[index].type = INPUT_KEYBOARD
        events[index].union.ki = _KEYBDINPUT(0, int(unit) & 0xFFFF, flags, 0, None)
    sent = int(_user32.SendInput(2, events, ctypes.sizeof(_INPUT)))
    if sent != 2:
        logger.error(
            "[仿真输入] Unicode 键盘输入失败 (SendInput=%s, error=%s)",
            sent,
            ctypes.get_last_error(),
        )
        return False
    return True


def _valid_window(hwnd: int) -> int:
    try:
        root = int(hwnd or 0)
    except (TypeError, ValueError):
        root = 0
    if root <= 0 or not win32gui.IsWindow(root):
        return 0
    return root


def send_simulated_text(
    hwnd: int,
    text: str,
    delay: float = 0.0,
    stop_checker=None,
    use_focus: bool = False,
    *,
    execution_mode: str | None = None,
) -> bool:
    """前台 use_focus 走 Unicode SendInput；后台把 WM_CHAR 送给目标窗口。"""
    root = _valid_window(hwnd)
    if root <= 0:
        logger.error("[仿真输入] 目标窗口无效")
        return False
    units = _code_units(text)
    if not units:
        return True
    pause = _pause_seconds(delay)
    if not use_focus:
        from utils.runtime_config import get_runtime_config
        from utils.input_simulation.factory import global_input_simulator_manager
        from utils.input_simulation.mode_utils import is_plugin_input_backend

        config = get_runtime_config()
        if is_plugin_input_backend(config):
            raise ValueError("原生仿真输入不支持插件后端")
        mode = config.get("execution_mode") if execution_mode is None else execution_mode
        if mode not in {"background_sendmessage", "background_postmessage"}:
            raise ValueError(f"后台仿真输入执行模式无效：{mode!r}")
        simulator = global_input_simulator_manager.create_temporary_simulator(root, mode)
        if simulator is None:
            return False
        try:
            return simulator.send_text(text, stop_checker=stop_checker, delay=pause)
        finally:
            global_input_simulator_manager.close_simulator(simulator)

    for index, unit in enumerate(units):
        if stop_checker and stop_checker():
            raise InterruptedError("仿真输入已停止")
        if not _emit_unicode_unit(unit):
            return False
        if pause > 0 and index + 1 < len(units):
            precise_sleep(pause)
    return True
