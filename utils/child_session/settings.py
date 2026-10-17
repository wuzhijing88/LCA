# -*- coding: utf-8 -*-
"""桌面分身配置：严格校验，缺项用出厂值补齐。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping, Optional

_BOOL_KEYS = (
    "topmost_enabled",
    "smart_sizing_enabled",
    "keep_aspect_ratio",
    "send_system_shortcuts_to_remote",
    "audio_muted",
    "block_physical_mouse",
)
_POSITION_KEYS = ("normal_window_position", "small_window_position")
_MIN_DESKTOP_EDGE = 200
_MAX_DESKTOP_EDGE = 8192
DESKTOP_RESOLUTIONS = (
    (1280, 720),
    (1366, 768),
    (1600, 900),
    (1920, 1080),
    (2560, 1440),
    (3840, 2160),
)


def default_child_session_config() -> dict[str, Any]:
    return {
        "topmost_enabled": False,
        "smart_sizing_enabled": True,
        "keep_aspect_ratio": True,
        "send_system_shortcuts_to_remote": True,
        "audio_muted": False,
        "block_physical_mouse": False,
        "desktop_width": 1920,
        "desktop_height": 1080,
        "normal_window_position": None,
        "small_window_position": None,
    }


def normalize_child_session_config(value: object) -> dict[str, Any]:
    if value is None:
        return default_child_session_config()
    if not isinstance(value, Mapping):
        raise ValueError(f"配置项 child_session 必须是对象: {value!r}")
    result = default_child_session_config()
    unknown = set(value) - set(result)
    if unknown:
        raise ValueError("配置项 child_session 含有未知字段: " + ", ".join(sorted(unknown)))
    for key in _BOOL_KEYS:
        if key not in value:
            continue
        raw = value[key]
        if not isinstance(raw, bool):
            raise ValueError(f"配置项 child_session.{key} 必须是布尔值: {raw!r}")
        result[key] = raw
    for key in ("desktop_width", "desktop_height"):
        if key not in value:
            continue
        result[key] = _normalize_desktop_edge(value[key], key)
    for key in _POSITION_KEYS:
        if key not in value:
            continue
        result[key] = _normalize_position(value[key], key)
    return result


def window_position_tuple(config: Mapping[str, Any], key: str) -> Optional[tuple[int, int]]:
    raw = config.get(key)
    if raw is None:
        return None
    return int(raw["left"]), int(raw["top"])


def position_dict(left: int, top: int) -> dict[str, int]:
    return {"left": int(left), "top": int(top)}


def _normalize_desktop_edge(raw: object, key: str) -> int:
    if type(raw) is not int:
        raise ValueError(f"配置项 child_session.{key} 必须是整数: {raw!r}")
    if raw < _MIN_DESKTOP_EDGE or raw > _MAX_DESKTOP_EDGE:
        raise ValueError(
            f"配置项 child_session.{key} 必须在 {_MIN_DESKTOP_EDGE} 到 {_MAX_DESKTOP_EDGE} 之间: {raw}"
        )
    return raw


def _normalize_position(raw: object, key: str) -> Optional[dict[str, int]]:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ValueError(f"配置项 child_session.{key} 必须是对象或 null: {raw!r}")
    if set(raw) != {"left", "top"}:
        raise ValueError(f"配置项 child_session.{key} 只能包含 left 与 top: {raw!r}")
    try:
        left = int(raw["left"])
        top = int(raw["top"])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"配置项 child_session.{key} 的坐标无效: {raw!r}") from exc
    return {"left": left, "top": top}


def copy_child_session_config(config: Mapping[str, Any]) -> dict[str, Any]:
    return deepcopy(normalize_child_session_config(config.get("child_session")))
