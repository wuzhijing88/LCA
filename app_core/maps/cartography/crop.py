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
        return "请先绑定游戏窗口"
    if int(minimap_width) <= 0 or int(minimap_height) <= 0:
        return "请先在卡片上框选小地图区域"
    return None


def crop_minimap(
    frame_bgr: np.ndarray,
    *,
    x: int,
    y: int,
    width: int,
    height: int,
) -> np.ndarray | None:
    if frame_bgr is None or frame_bgr.size == 0:
        return None
    if width <= 0 or height <= 0:
        return None
    frame_h, frame_w = frame_bgr.shape[:2]
    x0 = max(0, int(x))
    y0 = max(0, int(y))
    x1 = min(frame_w, int(x) + int(width))
    y1 = min(frame_h, int(y) + int(height))
    if x1 <= x0 or y1 <= y0:
        return None
    return np.ascontiguousarray(frame_bgr[y0:y1, x0:x1])
