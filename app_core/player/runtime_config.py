"""Bake editor execution settings into a standalone player package."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from app_core.config_sections import DEFAULT_HOTKEYS, apply_sections

RUNTIME_CONFIG_FILENAME = "runtime.json"

# 独立程序必须跟编辑器同一套截图/键鼠/启停热键；窗口绑定是安装机本地状态，不能打包。
PACKAGED_RUNTIME_KEYS = (
    "execution_mode",
    "foreground_mouse_driver_backend",
    "foreground_keyboard_driver_backend",
    "foreground_py_backend",
    "ibinputsimulator_driver",
    "ibinputsimulator_driver_arg",
    # 本机 AutoHotkey 绝对路径不能打进独立包，目标机用自带 tools/ibinputsimulator。
    "operation_mode",
    "screenshot_format",
    "screenshot_engine",
    "binding_method",
    "multi_window_delay",
    "custom_width",
    "custom_height",
    "start_task_hotkey",
    "stop_task_hotkey",
    "pause_workflow_hotkey",
)

PLAYER_HOTKEY_MAP = {
    "start_hotkey": "start_task_hotkey",
    "stop_hotkey": "stop_task_hotkey",
    "pause_hotkey": "pause_workflow_hotkey",
}


def snapshot_export_runtime_config(config: Mapping[str, Any] | None) -> dict[str, Any]:
    from utils.input_simulation.mode_utils import migrate_legacy_normal_hd_config

    normalized = apply_sections(config or {})
    snapshot: dict[str, Any] = {}
    for key in PACKAGED_RUNTIME_KEYS:
        if key in normalized:
            snapshot[key] = normalized[key]
    if not snapshot:
        return {}
    snapshot = migrate_legacy_normal_hd_config(snapshot)
    from app_core.hotkey_spec import normalize_hotkey

    for key in PLAYER_HOTKEY_MAP.values():
        if key in snapshot:
            spec = normalize_hotkey(snapshot.get(key))
            if spec:
                snapshot[key] = spec
    return snapshot


def apply_player_runtime_config(
    base_config: Mapping[str, Any] | None,
    packaged: Mapping[str, Any] | None,
) -> dict[str, Any]:
    result = dict(base_config or {})
    snapshot = snapshot_export_runtime_config(packaged)
    if not snapshot:
        return apply_sections(result, prefer="flat")
    bound_windows = result.get("bound_windows")
    target_title = result.get("target_window_title")
    result.update(snapshot)
    if bound_windows is not None:
        result["bound_windows"] = bound_windows
    if "target_window_title" in (base_config or {}):
        result["target_window_title"] = target_title
    return apply_sections(result, prefer="flat")


def load_packaged_runtime_config(*, package_dir: str = "") -> dict[str, Any]:
    from app_core.player.memory_store import get_player_memory_json

    data = get_player_memory_json(RUNTIME_CONFIG_FILENAME)
    if isinstance(data, dict) and data:
        return snapshot_export_runtime_config(data)
    root = str(package_dir or "").strip()
    if not root:
        return {}
    path = Path(root) / RUNTIME_CONFIG_FILENAME
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        return {}
    return snapshot_export_runtime_config(payload if isinstance(payload, dict) else {})


def resolve_player_hotkeys(*sources: Mapping[str, Any] | None) -> dict[str, str]:
    from app_core.hotkey_spec import normalize_hotkey

    resolved = {
        "start_hotkey": DEFAULT_HOTKEYS["start_task_hotkey"],
        "stop_hotkey": DEFAULT_HOTKEYS["stop_task_hotkey"],
        "pause_hotkey": DEFAULT_HOTKEYS["pause_workflow_hotkey"],
        "start_task_hotkey": DEFAULT_HOTKEYS["start_task_hotkey"],
        "stop_task_hotkey": DEFAULT_HOTKEYS["stop_task_hotkey"],
        "pause_workflow_hotkey": DEFAULT_HOTKEYS["pause_workflow_hotkey"],
    }
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        for ui_key, config_key in PLAYER_HOTKEY_MAP.items():
            raw = source.get(config_key)
            if raw is None or str(raw).strip() == "":
                raw = source.get(ui_key)
            spec = normalize_hotkey(raw)
            if spec:
                resolved[ui_key] = spec
                resolved[config_key] = spec
    return resolved


def apply_player_ui_hotkeys(ui: Mapping[str, Any] | None, *sources: Mapping[str, Any] | None) -> dict[str, Any]:
    result = dict(ui or {})
    resolved = resolve_player_hotkeys(result, *sources)
    for ui_key in PLAYER_HOTKEY_MAP:
        result[ui_key] = resolved[ui_key]
    return result
