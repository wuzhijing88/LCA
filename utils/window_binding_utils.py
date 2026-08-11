# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Dict, List, Optional


def get_native_bound_windows(config: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not isinstance(config, dict):
        return []
    windows = config.get("bound_windows", [])
    return windows if isinstance(windows, list) else []


def get_bound_windows_for_mode(config: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return get_native_bound_windows(config)


def get_window_binding_mode(config: Optional[Dict[str, Any]]) -> str:
    if not isinstance(config, dict):
        return "single"
    mode = str(config.get("window_binding_mode", "single") or "single").strip().lower()
    return "multiple" if mode == "multiple" else "single"


def get_active_bound_windows(config: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if isinstance(config, dict):
        active = config.get("active_bound_windows")
        if isinstance(active, list):
            return active
    return get_native_bound_windows(config)


def get_first_enabled_bound_window(
    windows: Optional[List[Dict[str, Any]]],
) -> Optional[Dict[str, Any]]:
    first_valid = None
    if not isinstance(windows, list):
        return None
    for item in windows:
        if not isinstance(item, dict):
            continue
        if first_valid is None:
            first_valid = item
        if item.get("enabled", True):
            return item
    return first_valid


def get_active_bound_window(config: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return get_first_enabled_bound_window(get_active_bound_windows(config))


def get_active_bound_window_hwnd(config: Optional[Dict[str, Any]]) -> Optional[int]:
    window_info = get_active_bound_window(config)
    if not isinstance(window_info, dict):
        return None
    try:
        hwnd = int(window_info.get("hwnd", 0) or 0)
    except Exception:
        return None
    return hwnd or None


def get_active_window_binding_mode(config: Optional[Dict[str, Any]]) -> str:
    if isinstance(config, dict):
        mode = str(config.get("active_window_binding_mode", "") or "").strip().lower()
        if mode in {"single", "multiple"}:
            return mode
    return get_window_binding_mode(config)


def get_active_target_window_title(config: Optional[Dict[str, Any]]) -> Optional[str]:
    window_info = get_active_bound_window(config)
    if isinstance(window_info, dict):
        title = str(window_info.get("title", "") or "").strip()
        if title:
            return title
    if isinstance(config, dict):
        title = str(config.get("target_window_title", "") or "").strip()
        if title:
            return title
    return None


def sync_runtime_window_binding_state(config: Optional[Dict[str, Any]]) -> None:
    if not isinstance(config, dict):
        return
    config["active_bound_windows"] = get_native_bound_windows(config)
    config["active_window_binding_mode"] = get_window_binding_mode(config)
    config["active_target_window_title"] = get_active_target_window_title(config)
