# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from utils.window.hwnd_utils import as_hwnd, normalize_bound_windows_hwnds
from utils.window.window_identity import (
    apply_window_identity,
    is_window_alive,
    refresh_bound_windows,
    resolve_bound_window_hwnd,
)


def get_native_bound_windows(config: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not isinstance(config, dict):
        return []
    windows = config.get("bound_windows", [])
    if not isinstance(windows, list):
        return []
    normalize_bound_windows_hwnds(windows)
    return windows


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
            normalize_bound_windows_hwnds(active)
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


def refresh_bound_window_handles(windows: Optional[List[Dict[str, Any]]]) -> bool:
    """刷新绑定列表中的 HWND，找不到也不删除记录。"""
    if not isinstance(windows, list):
        return False
    normalize_bound_windows_hwnds(windows)
    return refresh_bound_windows(windows)


def get_active_bound_window_hwnd(config: Optional[Dict[str, Any]]) -> Optional[int]:
    window_info = get_active_bound_window(config)
    if not isinstance(window_info, dict):
        return None
    hwnd = as_hwnd(window_info.get("hwnd"))
    if hwnd and is_window_alive(hwnd):
        return hwnd
    hwnd = resolve_bound_window_hwnd(window_info)
    if hwnd:
        apply_window_identity(window_info, hwnd)
        return hwnd
    return None


def _alive_hwnd(hwnd: Any, hwnd_alive) -> Optional[int]:
    handle = as_hwnd(hwnd)
    if handle and hwnd_alive(handle):
        return handle
    return None


def _hwnd_from_window_info(window_info: Optional[Dict[str, Any]], hwnd_alive) -> Optional[int]:
    if not isinstance(window_info, dict):
        return None
    hwnd = _alive_hwnd(window_info.get("hwnd"), hwnd_alive)
    if hwnd:
        return hwnd
    hwnd = as_hwnd(resolve_bound_window_hwnd(window_info, hwnd_alive=hwnd_alive))
    if hwnd:
        apply_window_identity(window_info, hwnd)
        return hwnd
    return None


def _enabled_bound_hwnds(windows: Optional[List[Dict[str, Any]]]) -> set:
    hwnds = set()
    if not isinstance(windows, list):
        return hwnds
    for item in windows:
        if not isinstance(item, dict) or not item.get("enabled", True):
            continue
        for key in ("hwnd", "display_hwnd"):
            handle = as_hwnd(item.get(key))
            if handle:
                hwnds.add(handle)
    return hwnds


def _host_enabled_bound_hwnds(host: Any) -> Optional[set]:
    """当前启用的绑定句柄。运行时 bound_windows 优先，不并入配置里的旧副本。"""
    if host is None:
        return None
    runtime = getattr(host, "bound_windows", None)
    if isinstance(runtime, list):
        return _enabled_bound_hwnds(runtime)
    config = getattr(host, "config", None)
    if isinstance(config, dict):
        return _enabled_bound_hwnds(get_native_bound_windows(config))
    return None


def resolve_live_target_hwnd(
    host: Any,
    cached_hwnd: Optional[Any] = None,
    *,
    hwnd_alive: Optional[Any] = None,
) -> Optional[int]:
    """按当前绑定列表解析截图/取点用的目标窗口句柄。

    顺序：宿主任务绑定、运行时 bound_windows、配置、调用方缓存。
    已从绑定列表移除的句柄一律不用，即使窗口还开着。
    """
    alive = hwnd_alive or is_window_alive
    if host is None:
        return _alive_hwnd(cached_hwnd, alive)

    candidates: List[Any] = []
    resolve_preferred = getattr(host, "_resolve_panel_target_hwnd", None)
    if callable(resolve_preferred):
        preferred = resolve_preferred()
        if preferred:
            candidates.append(preferred)

    bound_windows = getattr(host, "bound_windows", None)
    if not isinstance(bound_windows, list):
        bound_windows = get_native_bound_windows(getattr(host, "config", None))
    for window_info in bound_windows:
        if not isinstance(window_info, dict) or not window_info.get("enabled", True):
            continue
        from_bound = _hwnd_from_window_info(window_info, alive)
        if from_bound:
            candidates.append(from_bound)
            break

    if cached_hwnd:
        candidates.append(cached_hwnd)

    bound_hwnds = _host_enabled_bound_hwnds(host)
    seen = set()
    for candidate in candidates:
        handle = _alive_hwnd(candidate, alive)
        if not handle or handle in seen:
            continue
        seen.add(handle)
        if bound_hwnds is not None and handle not in bound_hwnds:
            continue
        return handle
    return None


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


def resolve_plugin_bind_hwnds(
    window_info: Optional[Dict[str, Any]] = None,
    *,
    display_hwnd: Optional[Any] = None,
    input_hwnd: Optional[Any] = None,
) -> Tuple[int, int]:
    """解析插件绑定用的显示/输入句柄。缺省或无效时 input 回退为 display。"""
    display = as_hwnd(display_hwnd)
    if isinstance(window_info, dict):
        if display <= 0:
            display = as_hwnd(window_info.get("display_hwnd")) or as_hwnd(window_info.get("hwnd"))
        explicit_input = as_hwnd(input_hwnd) if input_hwnd is not None else as_hwnd(window_info.get("input_hwnd"))
    else:
        explicit_input = as_hwnd(input_hwnd)
    input_target = explicit_input if explicit_input > 0 else display
    if display <= 0:
        return 0, 0
    return display, input_target


def resolve_plugin_input_hwnd_for_display(
    display_hwnd: Any,
    config: Optional[Dict[str, Any]] = None,
) -> int:
    """按显示句柄在绑定列表中查找 input_hwnd；没有分离配置时返回显示句柄本身。"""
    display = as_hwnd(display_hwnd)
    if display <= 0:
        return 0
    cfg = config
    if cfg is None:
        from utils.runtime_config import get_runtime_config

        cfg = get_runtime_config() or None
    for window_info in get_active_bound_windows(cfg):
        if not isinstance(window_info, dict):
            continue
        bound_display = as_hwnd(window_info.get("display_hwnd")) or as_hwnd(window_info.get("hwnd"))
        if bound_display != display:
            continue
        _, input_target = resolve_plugin_bind_hwnds(window_info, display_hwnd=display)
        return input_target
    return display
