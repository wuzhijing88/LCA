# -*- coding: utf-8 -*-
"""大漠 BindWindow(Ex) 的 mouse / keypad / mode / input display 枚举。"""

from __future__ import annotations

from utils.capture.engine_ids import PLUGIN_SCREENSHOT_ENGINES

PLUGIN_MOUSE_MODES = (
    "normal",
    "windows",
    "windows2",
    "windows3",
    "dx",
    "dx2",
    "dx.mouse.position.lock.api",
    "dx.mouse.position.lock.message",
    "dx.mouse.api",
    "dx.mouse.api.lock.api",
    "dx.mouse.api.lock.message",
    "dx.mouse.cursor",
    "dx.mouse.raw.input",
    "dx.mouse.input.lock.api",
    "dx.mouse.input.lock.message",
    "dx.mouse.focus.input.api",
    "dx.mouse.focus.input.message",
)

PLUGIN_KEYPAD_MODES = (
    "normal",
    "windows",
    "dx",
    "dx.keypad.input.lock.api",
    "dx.keypad.api",
    "dx.keypad.raw.input",
)

PLUGIN_BIND_MODE_PRESETS = (0, 2, 4, 6, 8, 101, 103)

PLUGIN_INPUT_DISPLAYS = tuple(PLUGIN_SCREENSHOT_ENGINES)

_MOUSE_SET = frozenset(PLUGIN_MOUSE_MODES)
_KEYPAD_SET = frozenset(PLUGIN_KEYPAD_MODES)


def normalize_plugin_mouse(value: object) -> str:
    mode = str(value or "").strip().lower()
    if mode not in _MOUSE_SET:
        raise ValueError(f"不支持的插件鼠标模式: {value!r}")
    return mode


def normalize_plugin_keypad(value: object) -> str:
    mode = str(value or "").strip().lower()
    if mode not in _KEYPAD_SET:
        raise ValueError(f"不支持的插件键盘模式: {value!r}")
    return mode


def normalize_plugin_bind_mode(value: object) -> int:
    try:
        mode = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"不支持的插件绑定 mode: {value!r}") from exc
    if mode < 0:
        raise ValueError(f"不支持的插件绑定 mode: {value!r}")
    return mode
