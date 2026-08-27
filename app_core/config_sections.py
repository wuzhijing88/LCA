"""Typed logical sections layered over the legacy flat config mapping."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


CONFIG_SCHEMA_VERSION = 3

# 出厂快捷键必须互不重复。缺任一键时，热键注册会各自 fallback，容易再次撞车。
DEFAULT_HOTKEYS = {
    "start_task_hotkey": "F9",
    "stop_task_hotkey": "F10",
    "pause_workflow_hotkey": "F11",
    "record_hotkey": "F12",
    "replay_hotkey": "F8",
}

SECTION_FIELDS = {
    "ui": (
        "enable_canvas_grid",
        "enable_card_snap",
        "enable_parameter_panel_snap",
        "enable_floating_status_window",
        "enable_connection_line_animation",
        "close_behavior",
        "close_behavior_remember",
    ),
    "execution": (
        "execution_mode",
        "foreground_mouse_driver_backend",
        "foreground_keyboard_driver_backend",
        "ibinputsimulator_driver",
        "ibinputsimulator_driver_arg",
        "ibinputsimulator_ahk_path",
        "ibinputsimulator_ahk_dir",
        "operation_mode",
        "screenshot_format",
        "screenshot_engine",
        "binding_method",
        "window_binding_mode",
        "multi_window_delay",
    ),
    "scheduling": ("main_schedule", "control_schedule"),
    "windows": (
        "target_window_title",
        "custom_width",
        "custom_height",
        "bound_windows",
    ),
    "hotkeys": tuple(DEFAULT_HOTKEYS),
}


def apply_sections(config: Mapping[str, Any], *, prefer: str = "section") -> dict[str, Any]:
    """Return a flat-compatible config with canonical section mirrors.

    prefer="section": nested section overwrites flat keys (load / migrate).
    prefer="flat": flat keys overwrite section mirrors (save after UI edits).
    """
    use_flat = str(prefer or "section").strip().lower() == "flat"
    result = dict(config)
    for section_name, field_names in SECTION_FIELDS.items():
        existing = result.get(section_name)
        section = dict(existing) if isinstance(existing, Mapping) else {}
        for field_name in field_names:
            if use_flat and field_name in result:
                section[field_name] = result[field_name]
            elif field_name in section:
                result[field_name] = section[field_name]
            elif field_name in result:
                section[field_name] = result[field_name]
        result[section_name] = section
    result["schema_version"] = CONFIG_SCHEMA_VERSION
    # Session-only snapshots are never persisted as a second source of truth.
    result.pop("active_bound_windows", None)
    return result


@dataclass(frozen=True)
class ExecutionSettings:
    execution_mode: str
    screenshot_engine: str
    mouse_backend: str
    keyboard_backend: str
    multi_window_delay_ms: int


def execution_settings(config: Mapping[str, Any]) -> ExecutionSettings:
    normalized = apply_sections(config)
    return ExecutionSettings(
        execution_mode=str(normalized.get("execution_mode") or "background_sendmessage"),
        screenshot_engine=str(normalized.get("screenshot_engine") or "wgc"),
        mouse_backend=str(normalized.get("foreground_mouse_driver_backend") or "interception"),
        keyboard_backend=str(normalized.get("foreground_keyboard_driver_backend") or "interception"),
        multi_window_delay_ms=max(0, int(normalized.get("multi_window_delay") or 0)),
    )


__all__ = [
    "CONFIG_SCHEMA_VERSION",
    "DEFAULT_HOTKEYS",
    "ExecutionSettings",
    "SECTION_FIELDS",
    "apply_sections",
    "execution_settings",
]
