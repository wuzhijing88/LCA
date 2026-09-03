# -*- coding: utf-8 -*-
"""OP normal.hd：SendInput 扫描码硬件按键 + 绝对坐标鼠标。"""

from __future__ import annotations

import ctypes
import logging
import threading
import time
from ctypes import wintypes
from typing import Optional, Tuple

from utils.input.input_timing import DEFAULT_CLICK_HOLD_SECONDS, DEFAULT_KEY_HOLD_SECONDS
from utils.precise_sleep import precise_sleep as _shared_precise_sleep

logger = logging.getLogger(__name__)

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_ABSOLUTE = 0x8000
WHEEL_DELTA = 120
MAPVK_VK_TO_VSC = 0

_DEFAULT_KEY_HOLD_SECONDS = DEFAULT_KEY_HOLD_SECONDS
_DEFAULT_CLICK_HOLD_SECONDS = DEFAULT_CLICK_HOLD_SECONDS


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = (
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    )


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = (
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    )


class _INPUTUNION(ctypes.Union):
    _fields_ = (("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT))


class _INPUT(ctypes.Structure):
    _fields_ = (("type", wintypes.DWORD), ("union", _INPUTUNION))


_KEY_ALIASES = {
    "return": "enter",
    "spacebar": "space",
    "control": "ctrl",
    "page_up": "pageup",
    "page_down": "pagedown",
    "pgup": "pageup",
    "pgdn": "pagedown",
    "ins": "insert",
    "del": "delete",
    "caps": "capslock",
    "scroll": "scrolllock",
    "windows": "win",
    "left_shift": "lshift",
    "right_shift": "rshift",
    "left_ctrl": "lctrl",
    "right_ctrl": "rctrl",
    "left_alt": "lalt",
    "right_alt": "ralt",
    "left_win": "lwin",
    "right_win": "rwin",
}

_VK_CODES = {
    "enter": 0x0D,
    "space": 0x20,
    "tab": 0x09,
    "shift": 0x10,
    "ctrl": 0x11,
    "alt": 0x12,
    "esc": 0x1B,
    "escape": 0x1B,
    "backspace": 0x08,
    "delete": 0x2E,
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "insert": 0x2D,
    "capslock": 0x14,
    "numlock": 0x90,
    "scrolllock": 0x91,
    "pause": 0x13,
    "printscreen": 0x2C,
    "lshift": 0xA0,
    "rshift": 0xA1,
    "lctrl": 0xA2,
    "rctrl": 0xA3,
    "lalt": 0xA4,
    "ralt": 0xA5,
    "win": 0x5B,
    "lwin": 0x5B,
    "rwin": 0x5C,
    "f1": 0x70,
    "f2": 0x71,
    "f3": 0x72,
    "f4": 0x73,
    "f5": 0x74,
    "f6": 0x75,
    "f7": 0x76,
    "f8": 0x77,
    "f9": 0x78,
    "f10": 0x79,
    "f11": 0x7A,
    "f12": 0x7B,
}

_EXTENDED_KEYS = {
    "up",
    "down",
    "left",
    "right",
    "home",
    "end",
    "pageup",
    "pagedown",
    "insert",
    "delete",
    "rctrl",
    "ralt",
    "lwin",
    "rwin",
    "win",
    "numpad/",
}

_BUTTON_FLAGS = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}


def normalize_normal_hd_backend(value: object) -> str:
    raw = str(value or "").strip().lower().replace("_", ".")
    if raw in {"normal.hd", "normalhd", "normal.hd."}:
        return "normal.hd"
    return str(value or "").strip().lower()


def resolve_virtual_key(key: str) -> Optional[int]:
    normalized = str(key or "").strip().lower()
    if not normalized:
        return None
    normalized = _KEY_ALIASES.get(normalized, normalized)
    if normalized in _VK_CODES:
        return int(_VK_CODES[normalized])
    if len(normalized) == 1:
        char = normalized.upper()
        if "A" <= char <= "Z" or "0" <= char <= "9":
            return ord(char)
    return None


def is_extended_key(key: str) -> bool:
    normalized = _KEY_ALIASES.get(str(key or "").strip().lower(), str(key or "").strip().lower())
    return normalized in _EXTENDED_KEYS


class NormalHdDriver:
    """OP keypad=normal.hd 的前台实现：扫描码 SendInput。"""

    def __init__(self, user32=None, send_input=None):
        self._user32 = user32 if user32 is not None else ctypes.windll.user32
        self._send_input = send_input
        self._lock = threading.RLock()
        self._pressed_keys: set[str] = set()
        self._pressed_buttons: set[str] = set()
        self.initialized = False

    def initialize(self) -> bool:
        self.initialized = True
        return True

    def close(self) -> None:
        self.release_all_inputs()
        self.initialized = False

    def _send(self, events: list[_INPUT]) -> bool:
        if not events:
            return True
        if self._send_input is not None:
            return bool(self._send_input(events))
        array_type = _INPUT * len(events)
        payload = array_type(*events)
        sent = int(self._user32.SendInput(len(events), ctypes.byref(payload), ctypes.sizeof(_INPUT)))
        return sent == len(events)

    def _keyboard_event(self, key: str, key_up: bool) -> Optional[_INPUT]:
        vk = resolve_virtual_key(key)
        if vk is None:
            return None
        scan = int(self._user32.MapVirtualKeyW(int(vk), MAPVK_VK_TO_VSC))
        flags = KEYEVENTF_SCANCODE
        if is_extended_key(key):
            flags |= KEYEVENTF_EXTENDEDKEY
        if key_up:
            flags |= KEYEVENTF_KEYUP
        event = _INPUT()
        event.type = INPUT_KEYBOARD
        event.union.ki = _KEYBDINPUT(0, scan, flags, 0, None)
        return event

    def _unicode_events(self, char: str) -> list[_INPUT]:
        code = ord(char)
        events = []
        for key_up in (False, True):
            event = _INPUT()
            event.type = INPUT_KEYBOARD
            flags = KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if key_up else 0)
            event.union.ki = _KEYBDINPUT(0, code, flags, 0, None)
            events.append(event)
        return events

    def _virtual_screen_bounds(self) -> Tuple[int, int, int, int]:
        left = int(self._user32.GetSystemMetrics(76))
        top = int(self._user32.GetSystemMetrics(77))
        width = int(self._user32.GetSystemMetrics(78))
        height = int(self._user32.GetSystemMetrics(79))
        if width <= 0 or height <= 0:
            width = int(self._user32.GetSystemMetrics(0))
            height = int(self._user32.GetSystemMetrics(1))
            left = 0
            top = 0
        return left, top, width, height

    def _absolute_mouse_point(self, x: int, y: int) -> Tuple[int, int]:
        left, top, width, height = self._virtual_screen_bounds()
        width_span = max(1, width - 1)
        height_span = max(1, height - 1)
        abs_x = int(round(((int(x) - left) * 65535) / width_span))
        abs_y = int(round(((int(y) - top) * 65535) / height_span))
        return max(0, min(65535, abs_x)), max(0, min(65535, abs_y))

    def _mouse_event(self, x: Optional[int], y: Optional[int], flags: int, data: int = 0) -> _INPUT:
        event = _INPUT()
        event.type = INPUT_MOUSE
        dx = dy = 0
        move_flags = int(flags)
        if x is not None and y is not None:
            dx, dy = self._absolute_mouse_point(int(x), int(y))
            move_flags |= MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
        event.union.mi = _MOUSEINPUT(dx, dy, int(data), move_flags, 0, None)
        return event

    def move_mouse(self, x: int, y: int, absolute: bool = True) -> bool:
        with self._lock:
            if absolute:
                return self._send([self._mouse_event(int(x), int(y), 0)])
            event = _INPUT()
            event.type = INPUT_MOUSE
            event.union.mi = _MOUSEINPUT(int(x), int(y), 0, MOUSEEVENTF_MOVE, 0, None)
            return self._send([event])

    def _normalize_button(self, button: str) -> str:
        name = str(button or "left").strip().lower()
        return name if name in _BUTTON_FLAGS else "left"

    def click_mouse(self, x=None, y=None, button="left", clicks=1, interval=0.0, duration=0.0, **_kwargs) -> bool:
        if x is None or y is None:
            return False
        down_flag, up_flag = _BUTTON_FLAGS[self._normalize_button(button)]
        hold = max(0.0, float(duration or 0.0) or _DEFAULT_CLICK_HOLD_SECONDS)
        safe_clicks = max(1, int(clicks or 1))
        gap = max(0.0, float(interval or 0.0))
        with self._lock:
            for index in range(safe_clicks):
                if index and gap:
                    _shared_precise_sleep(gap)
                if not self._send([self._mouse_event(int(x), int(y), down_flag)]):
                    return False
                if hold:
                    _shared_precise_sleep(hold)
                if not self._send([self._mouse_event(int(x), int(y), up_flag)]):
                    return False
        return True

    def mouse_down(self, x, y, button="left") -> bool:
        name = self._normalize_button(button)
        down_flag, _ = _BUTTON_FLAGS[name]
        with self._lock:
            ok = self._send([self._mouse_event(int(x), int(y), down_flag)])
            if ok:
                self._pressed_buttons.add(name)
            return ok

    def mouse_up(self, x, y, button="left") -> bool:
        name = self._normalize_button(button)
        _, up_flag = _BUTTON_FLAGS[name]
        with self._lock:
            ok = self._send([self._mouse_event(int(x), int(y), up_flag)])
            self._pressed_buttons.discard(name)
            return ok

    def drag_mouse(self, start_x, start_y, end_x, end_y, button="left", duration=1.0) -> bool:
        return self.drag_path([(start_x, start_y), (end_x, end_y)], duration=duration, button=button)

    def drag_path(self, points, duration=1.0, button="left", timestamps=None) -> bool:
        if not points or len(points) < 2:
            return False
        name = self._normalize_button(button)
        down_flag, up_flag = _BUTTON_FLAGS[name]
        start_x, start_y = int(points[0][0]), int(points[0][1])
        with self._lock:
            if not self._send([self._mouse_event(start_x, start_y, down_flag)]):
                return False
            try:
                if timestamps and len(timestamps) == len(points):
                    prev = float(timestamps[0])
                    for (x, y), stamp in zip(points[1:], timestamps[1:]):
                        _shared_precise_sleep(max(0.0, float(stamp) - prev))
                        if not self._send([self._mouse_event(int(x), int(y), 0)]):
                            return False
                        prev = float(stamp)
                else:
                    step = max(0.0, float(duration or 0.0)) / max(1, len(points) - 1)
                    for x, y in points[1:]:
                        if step:
                            _shared_precise_sleep(step)
                        if not self._send([self._mouse_event(int(x), int(y), 0)]):
                            return False
            finally:
                self._send([self._mouse_event(int(points[-1][0]), int(points[-1][1]), up_flag)])
        return True

    def scroll_mouse(self, direction, clicks=1, x=None, y=None) -> bool:
        amount = int(clicks or 1) * WHEEL_DELTA
        if str(direction or "").strip().lower() != "up":
            amount = -amount
        with self._lock:
            return self._send([self._mouse_event(x, y, MOUSEEVENTF_WHEEL, amount)])

    def key_down(self, key: str) -> bool:
        event = self._keyboard_event(key, key_up=False)
        if event is None:
            logger.warning("normal.hd 未知按键: %s", key)
            return False
        with self._lock:
            ok = self._send([event])
            if ok:
                self._pressed_keys.add(str(key).strip().lower())
            return ok

    def key_up(self, key: str) -> bool:
        event = self._keyboard_event(key, key_up=True)
        if event is None:
            return False
        with self._lock:
            ok = self._send([event])
            self._pressed_keys.discard(str(key).strip().lower())
            return ok

    def press_key(self, key: str, duration: float = _DEFAULT_KEY_HOLD_SECONDS) -> bool:
        hold = max(0.0, float(duration or 0.0))
        if not self.key_down(key):
            return False
        if hold:
            _shared_precise_sleep(hold)
        return self.key_up(key)

    def hotkey(self, *keys) -> bool:
        names = [str(item).strip() for item in keys if str(item).strip()]
        if not names:
            return False
        with self._lock:
            for name in names:
                if not self.key_down(name):
                    for released in reversed(names[: names.index(name)]):
                        self.key_up(released)
                    return False
            time.sleep(0.01)
            for name in reversed(names):
                self.key_up(name)
        return True

    def type_text(self, text, **_kwargs) -> bool:
        payload = str(text or "")
        if not payload:
            return True
        events: list[_INPUT] = []
        for char in payload:
            if char == "\n":
                down = self._keyboard_event("enter", False)
                up = self._keyboard_event("enter", True)
                if down and up:
                    events.extend((down, up))
                continue
            events.extend(self._unicode_events(char))
        with self._lock:
            return self._send(events)

    def release_all_keys(self) -> bool:
        with self._lock:
            pending = list(self._pressed_keys)
            self._pressed_keys.clear()
        ok = True
        for key in reversed(pending):
            if not self.key_up(key):
                ok = False
        return ok

    def release_all_inputs(self) -> bool:
        ok = self.release_all_keys()
        with self._lock:
            pending = list(self._pressed_buttons)
            self._pressed_buttons.clear()
        for button in pending:
            try:
                _, up_flag = _BUTTON_FLAGS[button]
                if not self._send([self._mouse_event(None, None, up_flag)]):
                    ok = False
            except Exception:
                ok = False
        return ok
