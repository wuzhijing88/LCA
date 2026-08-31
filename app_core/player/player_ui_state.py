"""导出 exe 用户侧 UI 状态：循环次数与简易设置覆盖。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from app_core.player.package import normalize_schedule_alarms, normalize_script_loop_count

PLAYER_UI_STATE_FILENAME = "player_ui_state.json"


def player_ui_state_path(userdata_dir: str | Path) -> Path:
    return Path(str(userdata_dir or "")).expanduser() / PLAYER_UI_STATE_FILENAME


def default_player_ui_state() -> Dict[str, Any]:
    return {
        "group_loops": 1,
        "loops_by_id": {},
        "settings": {},
        "schedule_alarms": [],
        "list_order": [],
        "list_order_mode": "fixed",
        "list_item_order": {},
        "list_order_modes": {},
        "window_width": 0,
        "window_height": 0,
    }


def _norm_order_mode(raw: Any) -> str:
    mode = str(raw or "fixed").strip().lower()
    return mode if mode in ("fixed", "random") else "fixed"


def load_player_ui_state(userdata_dir: str | Path) -> Dict[str, Any]:
    path = player_ui_state_path(userdata_dir)
    base = default_player_ui_state()
    if not path.is_file():
        return base
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        return base
    if not isinstance(raw, Mapping):
        return base
    loops_raw = raw.get("loops_by_id")
    loops: Dict[str, int] = {}
    if isinstance(loops_raw, Mapping):
        for key, value in loops_raw.items():
            sid = str(key or "").strip()
            if sid:
                loops[sid] = normalize_script_loop_count(value, 1)
    settings = raw.get("settings")
    alarms = raw.get("schedule_alarms")
    list_order = []
    if isinstance(raw.get("list_order"), list):
        list_order = [str(x).strip() for x in raw.get("list_order") if str(x).strip()]
    item_order: Dict[str, list] = {}
    raw_items = raw.get("list_item_order")
    if isinstance(raw_items, Mapping):
        for key, value in raw_items.items():
            lid = str(key or "").strip()
            if not lid or not isinstance(value, list):
                continue
            item_order[lid] = [str(x).strip() for x in value if str(x).strip()]
    modes: Dict[str, str] = {}
    raw_modes = raw.get("list_order_modes")
    if isinstance(raw_modes, Mapping):
        for key, value in raw_modes.items():
            lid = str(key or "").strip()
            if lid:
                modes[lid] = _norm_order_mode(value)
    try:
        win_w = max(0, int(raw.get("window_width") or 0))
    except (TypeError, ValueError):
        win_w = 0
    try:
        win_h = max(0, int(raw.get("window_height") or 0))
    except (TypeError, ValueError):
        win_h = 0
    return {
        "group_loops": normalize_script_loop_count(raw.get("group_loops"), 1),
        "loops_by_id": loops,
        "settings": dict(settings) if isinstance(settings, Mapping) else {},
        "schedule_alarms": normalize_schedule_alarms(alarms) if alarms else [],
        "list_order": list_order,
        "list_order_mode": _norm_order_mode(raw.get("list_order_mode")),
        "list_item_order": item_order,
        "list_order_modes": modes,
        "window_width": win_w,
        "window_height": win_h,
    }


def save_player_ui_state(userdata_dir: str | Path, state: Mapping[str, Any] | None) -> Path:
    path = player_ui_state_path(userdata_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = default_player_ui_state()
    if isinstance(state, Mapping):
        payload["group_loops"] = normalize_script_loop_count(state.get("group_loops"), 1)
        loops_raw = state.get("loops_by_id")
        loops: Dict[str, int] = {}
        if isinstance(loops_raw, Mapping):
            for key, value in loops_raw.items():
                sid = str(key or "").strip()
                if sid:
                    loops[sid] = normalize_script_loop_count(value, 1)
        payload["loops_by_id"] = loops
        settings = state.get("settings")
        if isinstance(settings, Mapping):
            payload["settings"] = dict(settings)
        if "schedule_alarms" in state:
            payload["schedule_alarms"] = normalize_schedule_alarms(state.get("schedule_alarms"))
        if isinstance(state.get("list_order"), list):
            payload["list_order"] = [str(x).strip() for x in state.get("list_order") if str(x).strip()]
        payload["list_order_mode"] = _norm_order_mode(state.get("list_order_mode"))
        item_order = state.get("list_item_order")
        if isinstance(item_order, Mapping):
            payload["list_item_order"] = {
                str(k): [str(x).strip() for x in (v or []) if str(x).strip()]
                for k, v in item_order.items()
                if str(k).strip() and isinstance(v, list)
            }
        modes = state.get("list_order_modes")
        if isinstance(modes, Mapping):
            payload["list_order_modes"] = {
                str(k): _norm_order_mode(v) for k, v in modes.items() if str(k).strip()
            }
        try:
            payload["window_width"] = max(0, int(state.get("window_width") or 0))
        except (TypeError, ValueError):
            payload["window_width"] = 0
        try:
            payload["window_height"] = max(0, int(state.get("window_height") or 0))
        except (TypeError, ValueError):
            payload["window_height"] = 0
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def merge_settings_into_ui(ui: Mapping[str, Any] | None, settings: Mapping[str, Any] | None) -> Dict[str, Any]:
    """把用户设置覆盖进 ui（热键/自动开始/结束后退出等）。"""
    result = dict(ui or {})
    if not isinstance(settings, Mapping) or not settings:
        return result
    for key in ("auto_start", "exit_on_finish", "notify_on_finish"):
        if key in settings:
            result[key] = bool(settings.get(key))
    for key in ("start_hotkey", "stop_hotkey", "pause_hotkey"):
        if key in settings and str(settings.get(key) or "").strip():
            result[key] = str(settings.get(key)).strip()
    return result


def extract_settings_from_ui(ui: Mapping[str, Any] | None) -> Dict[str, Any]:
    data = ui or {}
    return {
        "auto_start": bool(data.get("auto_start")),
        "exit_on_finish": bool(data.get("exit_on_finish")),
        "notify_on_finish": bool(data.get("notify_on_finish", True)),
        "start_hotkey": str(data.get("start_hotkey") or ""),
        "stop_hotkey": str(data.get("stop_hotkey") or ""),
        "pause_hotkey": str(data.get("pause_hotkey") or ""),
    }
