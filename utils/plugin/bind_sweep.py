# -*- coding: utf-8 -*-
"""按窗口依次试大漠 BindWindow(Ex) 参数，停在第一组截图和键鼠都成功的组合。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping, Optional

from utils.capture.engine_ids import is_plugin_screenshot_engine, normalize_screenshot_engine
from utils.plugin.bind_modes import (
    PLUGIN_BIND_KIND_ADVANCED,
    PLUGIN_BIND_KIND_BASIC,
    normalize_plugin_bind_kind,
    normalize_plugin_bind_mode,
    normalize_plugin_keypad,
    normalize_plugin_mouse,
    plugin_bind_kind_label,
    plugin_bind_mode_label,
    plugin_bind_mode_options_for_kind,
    plugin_display_options_for_kind,
    plugin_keypad_label,
    plugin_keypad_options_for_kind,
    plugin_mouse_label,
    plugin_mouse_options_for_kind,
)
from utils.plugin.bind_probe import PluginBindProbeResult, probe_plugin_window_bind

logger = logging.getLogger(__name__)

DEFAULT_PLUGIN_BIND_SWEEP_TIMEOUT = 1.0

# 基础 mode 只试官方说明里效果不同的取值；3/5/6/7 与 2/4/6 同效果。
_SWEEP_MODES = {
    PLUGIN_BIND_KIND_BASIC: (0, 2, 1, 4),
    PLUGIN_BIND_KIND_ADVANCED: (101, 103, 11, 13),
}
_SWEEP_DEFAULT_INPUT = {
    PLUGIN_BIND_KIND_BASIC: ("normal", "normal"),
    PLUGIN_BIND_KIND_ADVANCED: ("dx.mouse.api", "dx.keypad.api"),
}
_SWEEP_EXTRA_INPUT = {
    PLUGIN_BIND_KIND_BASIC: (
        ("windows", "windows"),
        ("windows3", "windows"),
        ("dx", "dx"),
    ),
    PLUGIN_BIND_KIND_ADVANCED: (
        ("dx.mouse.position.lock.api", "dx.keypad.input.lock.api"),
        ("dx.mouse.api.lock.api", "dx.keypad.api"),
        ("dx.mouse.raw.input", "dx.keypad.raw.input"),
    ),
}


@dataclass(frozen=True)
class PluginBindCandidate:
    kind: str
    display: str
    mouse: str
    keypad: str
    mode: int


@dataclass(frozen=True)
class PluginBindSweepResult:
    ok: bool
    cancelled: bool
    winner: Optional[PluginBindCandidate]
    tried: int
    total: int
    message: str = ""


def plugin_bind_candidate_label(candidate: PluginBindCandidate) -> str:
    from utils.capture.engine_ids import screenshot_engine_label

    return (
        f"{plugin_bind_kind_label(candidate.kind)} · "
        f"图色 {screenshot_engine_label(candidate.display)} · "
        f"鼠标 {plugin_mouse_label(candidate.mouse)} · "
        f"键盘 {plugin_keypad_label(candidate.keypad)} · "
        f"{plugin_bind_mode_label(candidate.mode)}"
    )


def plugin_bind_sweep_failure_text(result: PluginBindSweepResult, window_title: object = "") -> str:
    title = str(window_title or "").strip() or "窗口"
    detail = str(result.message or "").strip()
    if detail:
        return f"窗口「{title}」绑定失败。\n{detail}"
    return f"窗口「{title}」绑定失败。"


def config_for_plugin_bind_candidate(base: Mapping, candidate: PluginBindCandidate) -> dict:
    values = dict(base or {})
    values["input_backend"] = "plugin"
    values["screenshot_engine"] = candidate.display
    values["plugin_input_display"] = candidate.display
    values["plugin_input_display_follow"] = True
    values["plugin_bind_kind"] = candidate.kind
    values["plugin_mouse"] = candidate.mouse
    values["plugin_keypad"] = candidate.keypad
    values["plugin_bind_mode"] = candidate.mode
    return values


def _candidate(
    kind: str,
    display: str,
    mouse: str,
    keypad: str,
    mode: int,
) -> Optional[PluginBindCandidate]:
    try:
        kind_value = normalize_plugin_bind_kind(kind)
        display_value = normalize_screenshot_engine(display)
        mouse_value = normalize_plugin_mouse(mouse)
        keypad_value = normalize_plugin_keypad(keypad)
        mode_value = normalize_plugin_bind_mode(mode)
    except ValueError:
        return None
    if display_value not in plugin_display_options_for_kind(kind_value):
        return None
    if mouse_value not in plugin_mouse_options_for_kind(kind_value):
        return None
    if keypad_value not in plugin_keypad_options_for_kind(kind_value):
        return None
    if mode_value not in plugin_bind_mode_options_for_kind(kind_value):
        return None
    return PluginBindCandidate(kind_value, display_value, mouse_value, keypad_value, mode_value)


def plugin_bind_candidate_from_config(config: Optional[Mapping] = None) -> Optional[PluginBindCandidate]:
    values = dict(config or {})
    display = normalize_screenshot_engine(values.get("screenshot_engine"))
    if not is_plugin_screenshot_engine(display):
        display = normalize_screenshot_engine(values.get("plugin_input_display"))
    try:
        kind = normalize_plugin_bind_kind(values.get("plugin_bind_kind", PLUGIN_BIND_KIND_BASIC))
    except ValueError:
        return None
    return _candidate(
        kind,
        display,
        values.get("plugin_mouse"),
        values.get("plugin_keypad"),
        values.get("plugin_bind_mode"),
    )


def iter_plugin_bind_sweep_candidates(config: Optional[Mapping] = None) -> tuple[PluginBindCandidate, ...]:
    """当前配置优先，再按基础/高级、图色、常用键鼠组合依次展开。"""
    seen: set[PluginBindCandidate] = set()
    items: list[PluginBindCandidate] = []

    def _add(candidate: Optional[PluginBindCandidate]) -> None:
        if candidate is None or candidate in seen:
            return
        seen.add(candidate)
        items.append(candidate)

    _add(plugin_bind_candidate_from_config(config))
    for kind in (PLUGIN_BIND_KIND_BASIC, PLUGIN_BIND_KIND_ADVANCED):
        displays = plugin_display_options_for_kind(kind)
        modes = _SWEEP_MODES[kind]
        default_mouse, default_keypad = _SWEEP_DEFAULT_INPUT[kind]
        for display in displays:
            for mode in modes:
                _add(_candidate(kind, display, default_mouse, default_keypad, mode))
        primary_mode = modes[0]
        for display in displays:
            for mouse, keypad in _SWEEP_EXTRA_INPUT[kind]:
                _add(_candidate(kind, display, mouse, keypad, primary_mode))
    return tuple(items)


def _unbind_hwnd(hwnd: int, unbind_fn: Optional[Callable[[], None]]) -> None:
    if unbind_fn is not None:
        try:
            unbind_fn()
        except Exception:
            logger.debug("测试绑定解绑回调失败 hwnd=%s", hwnd, exc_info=True)
        return
    try:
        from utils.plugin.session import unbind_shared_plugin_windows

        unbind_shared_plugin_windows(int(hwnd or 0))
    except Exception:
        logger.debug("测试绑定解绑失败 hwnd=%s", hwnd, exc_info=True)


def sweep_plugin_window_bind(
    hwnd: int,
    config: Optional[Mapping] = None,
    *,
    timeout: float = DEFAULT_PLUGIN_BIND_SWEEP_TIMEOUT,
    should_stop: Optional[Callable[[], bool]] = None,
    on_progress: Optional[Callable[[int, int, PluginBindCandidate], None]] = None,
    probe_fn: Optional[Callable[..., PluginBindProbeResult]] = None,
    unbind_fn: Optional[Callable[[], None]] = None,
    candidates: Optional[Iterable[PluginBindCandidate]] = None,
) -> PluginBindSweepResult:
    try:
        target = int(hwnd or 0)
    except (TypeError, ValueError):
        target = 0
    values = dict(config or {})
    if candidates is None:
        candidate_list = iter_plugin_bind_sweep_candidates(values)
    else:
        candidate_list = tuple(candidates)
    total = len(candidate_list)
    if target <= 0:
        return PluginBindSweepResult(False, False, None, 0, total, "无效窗口句柄")

    def _cancelled() -> bool:
        try:
            return bool(should_stop is not None and should_stop())
        except Exception:
            return False

    if probe_fn is None:
        from utils.plugin.runtime import is_plugin_runtime_available

        if not is_plugin_runtime_available():
            return PluginBindSweepResult(False, False, None, 0, total, "插件运行库不可用")
        probe_fn = probe_plugin_window_bind

    try:
        wait_seconds = max(0.05, float(timeout))
    except (TypeError, ValueError):
        wait_seconds = DEFAULT_PLUGIN_BIND_SWEEP_TIMEOUT

    last_error = ""
    tried = 0
    for index, candidate in enumerate(candidate_list, start=1):
        if _cancelled():
            _unbind_hwnd(target, unbind_fn)
            return PluginBindSweepResult(False, True, None, tried, total, "已取消测试绑定")
        if on_progress is not None:
            try:
                on_progress(index, total, candidate)
            except Exception:
                logger.debug("测试绑定进度回调异常", exc_info=True)
        cfg = config_for_plugin_bind_candidate(values, candidate)
        try:
            result = probe_fn(target, cfg, timeout=wait_seconds)
        except Exception as exc:  # noqa: BLE001
            logger.debug("测试绑定试参异常: %s", exc, exc_info=True)
            result = PluginBindProbeResult(False, False, False, f"{exc.__class__.__name__}: {exc}")
        tried = index
        if result is not None and result.ok:
            return PluginBindSweepResult(True, False, candidate, tried, total, "")
        last_error = str(getattr(result, "message", "") or "").strip()
    _unbind_hwnd(target, unbind_fn)
    return PluginBindSweepResult(
        False,
        False,
        None,
        tried,
        total,
        last_error or "没有找到能截图并绑定成功的参数",
    )
