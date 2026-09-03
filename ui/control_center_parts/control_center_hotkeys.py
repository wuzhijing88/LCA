from __future__ import annotations

from typing import Any, Mapping, Optional

from app_core.config_sections import DEFAULT_HOTKEYS
from app_core.hotkey_spec import is_mouse_hotkey, normalize_hotkey

_ACTION_FIELDS = {
    "start": "start_task_hotkey",
    "stop": "stop_task_hotkey",
    "pause": "pause_workflow_hotkey",
}


def resolve_control_center_hotkeys(config: Optional[Mapping[str, Any]]) -> dict[str, str]:
    """中控开始/停止/暂停热键跟全局设置，缺省回落出厂键。"""
    values = config if isinstance(config, Mapping) else {}
    resolved: dict[str, str] = {}
    for action, field in _ACTION_FIELDS.items():
        resolved[action] = normalize_hotkey(values.get(field)) or DEFAULT_HOTKEYS[field]
    return resolved


def to_qt_shortcut_text(value: Any) -> str:
    spec = normalize_hotkey(value)
    if not spec or is_mouse_hotkey(spec):
        return ""
    return spec.replace("CTRL", "Ctrl").replace("ALT", "Alt").replace("SHIFT", "Shift")
