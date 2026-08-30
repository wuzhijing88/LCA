from __future__ import annotations

import numpy as np


def can_capture_minimap(
    *,
    hwnd,
    minimap_x: int,
    minimap_y: int,
    minimap_width: int,
    minimap_height: int,
) -> str | None:
    if not hwnd:
        return "请先绑定目标窗口"
    if minimap_width <= 0 or minimap_height <= 0:
        return "小地图区域无效"
    return None


def crop_minimap(
    frame_bgr: np.ndarray,
    *,
    x: int,
    y: int,
    width: int,
    height: int,
) -> np.ndarray | None:
    if width <= 0 or height <= 0:
        return None

    frame_h, frame_w = frame_bgr.shape[:2]
    x0 = max(0, x)
    y0 = max(0, y)
    x1 = min(frame_w, x + width)
    y1 = min(frame_h, y + height)

    if x1 <= x0 or y1 <= y0:
        return None

    return np.ascontiguousarray(frame_bgr[y0:y1, x0:x1])
