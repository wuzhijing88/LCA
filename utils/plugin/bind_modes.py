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

_MOUSE_LABELS = {
    "normal": "正常",
    "windows": "Windows",
    "windows2": "Windows2",
    "windows3": "Windows3",
    "dx": "DX",
    "dx2": "DX2",
    "dx.mouse.position.lock.api": "DX · 锁定坐标(API)",
    "dx.mouse.position.lock.message": "DX · 锁定坐标(消息)",
    "dx.mouse.api": "DX · API",
    "dx.mouse.api.lock.api": "DX · API+锁定(API)",
    "dx.mouse.api.lock.message": "DX · API+锁定(消息)",
    "dx.mouse.cursor": "DX · 光标",
    "dx.mouse.raw.input": "DX · RawInput",
    "dx.mouse.input.lock.api": "DX · 输入锁定(API)",
    "dx.mouse.input.lock.message": "DX · 输入锁定(消息)",
    "dx.mouse.focus.input.api": "DX · 焦点输入(API)",
    "dx.mouse.focus.input.message": "DX · 焦点输入(消息)",
}

_KEYPAD_LABELS = {
    "normal": "正常",
    "windows": "Windows",
    "dx": "DX",
    "dx.keypad.input.lock.api": "DX · 输入锁定(API)",
    "dx.keypad.api": "DX · API",
    "dx.keypad.raw.input": "DX · RawInput",
}

_BIND_MODE_LABELS = {
    0: "默认（推荐）",
    2: "预设 2",
    4: "预设 4",
    6: "预设 6",
    8: "预设 8",
    101: "高级 101",
    103: "高级 103",
}

_MOUSE_SET = frozenset(PLUGIN_MOUSE_MODES)
_KEYPAD_SET = frozenset(PLUGIN_KEYPAD_MODES)


def plugin_mouse_label(value: object) -> str:
    mode = str(value or "").strip().lower()
    return _MOUSE_LABELS.get(mode, mode or "未知")


def plugin_keypad_label(value: object) -> str:
    mode = str(value or "").strip().lower()
    return _KEYPAD_LABELS.get(mode, mode or "未知")


def plugin_bind_mode_label(value: object) -> str:
    mode = normalize_plugin_bind_mode(value)
    title = _BIND_MODE_LABELS.get(mode, "自定义")
    return f"{mode} · {title}"


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
