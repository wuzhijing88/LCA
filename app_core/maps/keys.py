from __future__ import annotations

import math

DEFAULT_KEYS_4 = {"up": "w", "down": "s", "left": "a", "right": "d"}
DEFAULT_KEYS_8 = {
    **DEFAULT_KEYS_4,
    "up_left": "q",
    "up_right": "e",
    "down_left": "z",
    "down_right": "c",
}

_LABELS_4 = ("up", "right", "down", "left")
_LABELS_8 = (
    "up",
    "up_right",
    "right",
    "down_right",
    "down",
    "down_left",
    "left",
    "up_left",
)


def command_heading(from_xy: tuple[int, int], to_xy: tuple[int, int]) -> float:
    dx = int(to_xy[0]) - int(from_xy[0])
    dy = int(to_xy[1]) - int(from_xy[1])
    return float(math.degrees(math.atan2(dx, -dy)) % 360)


def normalize_key_map(mode: str, mapping: dict | None) -> dict[str, str]:
    base = DEFAULT_KEYS_8 if mode == "八向" else DEFAULT_KEYS_4
    if mapping is None:
        return dict(base)
    merged = dict(base)
    merged.update(mapping)
    if mode == "四向":
        return {label: merged[label] for label in _LABELS_4}
    return {label: merged[label] for label in _LABELS_8}


def _direction_label(angle_deg: float, mode: str) -> str:
    labels = _LABELS_8 if mode == "八向" else _LABELS_4
    step = 45 if mode == "八向" else 90
    index = round(angle_deg / step) % len(labels)
    return labels[index]


def key_for_step(
    position,
    next_pixel,
    *,
    mode: str,
    key_map: dict,
    heading_deg: float | None,
) -> str:
    heading = command_heading(position, next_pixel)
    if heading_deg is not None:
        heading = (heading - heading_deg) % 360
    label = _direction_label(heading, mode)
    return key_map[label]
