# -*- coding: utf-8 -*-
"""大漠 BindWindow(Ex) 的 mouse / keypad / mode / input display 枚举。"""

from __future__ import annotations

from utils.capture.engine_ids import PLUGIN_SCREENSHOT_ENGINES, to_dm_display_mode

PLUGIN_BIND_GROUP_BASIC = "基础绑定"
PLUGIN_BIND_GROUP_COMPAT = "兼容扩展"
PLUGIN_BIND_GROUP_EX = "高级绑定"

PLUGIN_BIND_KIND_BASIC = "basic"
PLUGIN_BIND_KIND_ADVANCED = "advanced"
PLUGIN_BIND_KINDS = (PLUGIN_BIND_KIND_BASIC, PLUGIN_BIND_KIND_ADVANCED)

# BindWindow 缩写；BindWindowEx 也接受这些值。
BINDWINDOW_MOUSE_MODES = (
    "normal",
    "windows",
    "windows2",
    "windows3",
    "dx",
    "dx2",
)
# BindWindowEx 鼠标明细；只能走 BindWindowEx。
BINDWINDOWEX_MOUSE_MODES = (
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
PLUGIN_MOUSE_MODES = BINDWINDOW_MOUSE_MODES + BINDWINDOWEX_MOUSE_MODES

BINDWINDOW_KEYPAD_MODES = (
    "normal",
    "windows",
    "dx",
)
BINDWINDOWEX_KEYPAD_MODES = (
    "dx.keypad.input.lock.api",
    "dx.keypad.api",
    "dx.keypad.raw.input",
)
PLUGIN_KEYPAD_MODES = BINDWINDOW_KEYPAD_MODES + BINDWINDOWEX_KEYPAD_MODES

BINDWINDOW_MODE_PRESETS = (0, 2)
# 官方 BindWindow 模式表：0/1/2/3/4/5/6/7/11/13/101/103。奇数模式是对应偶数模式的“锁定窗口”变体，
# 这里只开放常用的偶数项；不存在的模式（如 8）一律不提供。
BINDWINDOW_COMPAT_MODE_PRESETS = (4, 6)
BINDWINDOWEX_MODE_PRESETS = (101, 103)
PLUGIN_BIND_MODE_PRESETS = (
    BINDWINDOW_MODE_PRESETS + BINDWINDOW_COMPAT_MODE_PRESETS + BINDWINDOWEX_MODE_PRESETS
)

PLUGIN_INPUT_DISPLAYS = tuple(PLUGIN_SCREENSHOT_ENGINES)

_MOUSE_LABELS = {
    "normal": "通用",
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
    "normal": "通用",
    "windows": "Windows",
    "dx": "DX",
    "dx.keypad.input.lock.api": "DX · 输入锁定(API)",
    "dx.keypad.api": "DX · API",
    "dx.keypad.raw.input": "DX · RawInput",
}

# 下拉只写清楚类型；细节放 tooltip，避免一堆「防崩溃」口号。
_BIND_MODE_LABELS = {
    0: "推荐（通用后台）",
    2: "兼容绑定",
    4: "兼容绑定",
    6: "兼容绑定",
    101: "超级绑定（隐藏 DLL）",
    103: "超级绑定（备用）",
}

_BIND_MODE_TOOLTIPS = {
    0: "常用推荐项，多数窗口后台效果最好。不确定时选这个。",
    2: "效果接近推荐项。推荐项不稳定时再试；绑定成功后主线程需保持运行。",
    4: "官方模式 4：同模式 0 的另一种实现，部分 DirectX 窗口在 0/2 失败时可试。",
    6: "官方模式 6：同模式 2 的另一种实现，0/2/4 都不稳定时再试。",
    101: "超级绑定，可隐藏目标进程里的 dm.dll（付费版能力）。",
    103: "同超级绑定。101 不稳定时再试。",
}

_MOUSE_SET = frozenset(PLUGIN_MOUSE_MODES)
_KEYPAD_SET = frozenset(PLUGIN_KEYPAD_MODES)


def iter_plugin_mouse_ui_groups() -> tuple[tuple[str, tuple[str, ...]], ...]:
    return (
        (PLUGIN_BIND_GROUP_BASIC, BINDWINDOW_MOUSE_MODES),
        (PLUGIN_BIND_GROUP_EX, BINDWINDOWEX_MOUSE_MODES),
    )


def iter_plugin_keypad_ui_groups() -> tuple[tuple[str, tuple[str, ...]], ...]:
    return (
        (PLUGIN_BIND_GROUP_BASIC, BINDWINDOW_KEYPAD_MODES),
        (PLUGIN_BIND_GROUP_EX, BINDWINDOWEX_KEYPAD_MODES),
    )


def iter_plugin_bind_mode_ui_groups() -> tuple[tuple[str, tuple[int, ...]], ...]:
    return (
        (PLUGIN_BIND_GROUP_BASIC, BINDWINDOW_MODE_PRESETS),
        (PLUGIN_BIND_GROUP_COMPAT, BINDWINDOW_COMPAT_MODE_PRESETS),
        (PLUGIN_BIND_GROUP_EX, BINDWINDOWEX_MODE_PRESETS),
    )


def normalize_plugin_bind_kind(value: object) -> str:
    kind = str(value or "").strip().lower()
    if kind in {PLUGIN_BIND_KIND_ADVANCED, "ex", "bindwindowex", "高级", "高级绑定"}:
        return PLUGIN_BIND_KIND_ADVANCED
    if kind in {PLUGIN_BIND_KIND_BASIC, "bindwindow", "基础", "基础绑定"}:
        return PLUGIN_BIND_KIND_BASIC
    raise ValueError(f"不支持的插件绑定方式: {value!r}")


def plugin_bind_kind_label(value: object) -> str:
    try:
        kind = normalize_plugin_bind_kind(value)
    except ValueError:
        kind = PLUGIN_BIND_KIND_BASIC
    return PLUGIN_BIND_GROUP_EX if kind == PLUGIN_BIND_KIND_ADVANCED else PLUGIN_BIND_GROUP_BASIC


def plugin_mouse_options_for_kind(kind: object) -> tuple[str, ...]:
    if normalize_plugin_bind_kind(kind) == PLUGIN_BIND_KIND_ADVANCED:
        return BINDWINDOWEX_MOUSE_MODES
    return BINDWINDOW_MOUSE_MODES


def plugin_keypad_options_for_kind(kind: object) -> tuple[str, ...]:
    if normalize_plugin_bind_kind(kind) == PLUGIN_BIND_KIND_ADVANCED:
        return BINDWINDOWEX_KEYPAD_MODES
    return BINDWINDOW_KEYPAD_MODES


def plugin_bind_mode_options_for_kind(kind: object) -> tuple[int, ...]:
    if normalize_plugin_bind_kind(kind) == PLUGIN_BIND_KIND_ADVANCED:
        return BINDWINDOWEX_MODE_PRESETS
    return BINDWINDOW_MODE_PRESETS + BINDWINDOW_COMPAT_MODE_PRESETS


def plugin_display_options_for_kind(kind: object) -> tuple[str, ...]:
    from utils.capture.engine_ids import (
        PLUGIN_SCREENSHOT_BASIC_ENGINES,
        PLUGIN_SCREENSHOT_EX_ENGINES,
    )

    if normalize_plugin_bind_kind(kind) == PLUGIN_BIND_KIND_ADVANCED:
        return PLUGIN_SCREENSHOT_EX_ENGINES
    return PLUGIN_SCREENSHOT_BASIC_ENGINES


def clamp_choice(value: object, options: tuple, default=None):
    if value in options:
        return value
    text = str(value or "").strip().lower()
    for item in options:
        if str(item).strip().lower() == text:
            return item
    if default is not None and default in options:
        return default
    return options[0]


def infer_plugin_bind_kind(
    *,
    display: object = "normal",
    mouse: object = "normal",
    keypad: object = "normal",
    bind_mode: object = 0,
) -> str:
    if plugin_bind_api(display=display, mouse=mouse, keypad=keypad) == "BindWindowEx":
        return PLUGIN_BIND_KIND_ADVANCED
    try:
        mode = int(bind_mode)
    except (TypeError, ValueError):
        mode = 0
    if mode in BINDWINDOWEX_MODE_PRESETS:
        return PLUGIN_BIND_KIND_ADVANCED
    return PLUGIN_BIND_KIND_BASIC


def _is_bindwindowex_token(value: object) -> bool:
    return "." in str(value or "")


def plugin_bind_api(
    display: object = "normal",
    mouse: object = "normal",
    keypad: object = "normal",
) -> str:
    """宿主应按参数选择 BindWindow 或 BindWindowEx。"""
    tokens = (
        to_dm_display_mode(display),
        str(mouse or "").strip().lower(),
        str(keypad or "").strip().lower(),
    )
    if any(_is_bindwindowex_token(token) for token in tokens):
        return "BindWindowEx"
    return "BindWindow"


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


def plugin_bind_mode_tooltip(value: object) -> str:
    mode = normalize_plugin_bind_mode(value)
    detail = _BIND_MODE_TOOLTIPS.get(mode)
    if detail:
        return detail
    return f"自定义绑定 mode={mode}（请按大漠 BindWindowEx 文档理解）。"


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
