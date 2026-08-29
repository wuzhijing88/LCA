from __future__ import annotations

import math

import cv2
import numpy as np

from app_core.maps.record import CELL_BLOCKED, CELL_WALKABLE


def merged_walkability(walkability: np.ndarray, painted_blocked: np.ndarray) -> np.ndarray:
    merged = np.array(walkability, copy=True)
    merged[painted_blocked > 0] = CELL_BLOCKED
    return merged


def mark_footprints(
    walkability: np.ndarray,
    painted_blocked: np.ndarray,
    points: list[tuple[int, int]],
) -> np.ndarray:
    out = np.array(walkability, copy=True)
    height, width = out.shape[:2]
    for x, y in points:
        if x < 0 or y < 0 or x >= width or y >= height:
            continue
        if painted_blocked[y, x] > 0:
            continue
        out[y, x] = CELL_WALKABLE
    return out


def flood_blocked(
    image_bgr: np.ndarray,
    walkability: np.ndarray,
    painted_blocked: np.ndarray,
    seed: tuple[int, int],
    hsv_tol: int = 12,
) -> np.ndarray:
    out = np.array(walkability, copy=True)
    height, width = out.shape[:2]
    sx, sy = int(seed[0]), int(seed[1])
    if sx < 0 or sy < 0 or sx >= width or sy >= height:
        return out
    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)
    seed_hsv = hsv[sy, sx].astype(np.int16)
    lower = np.array(
        [max(0, int(seed_hsv[0]) - hsv_tol), max(0, int(seed_hsv[1]) - hsv_tol), max(0, int(seed_hsv[2]) - hsv_tol)],
        dtype=np.uint8,
    )
    upper = np.array(
        [min(179, int(seed_hsv[0]) + hsv_tol), min(255, int(seed_hsv[1]) + hsv_tol), min(255, int(seed_hsv[2]) + hsv_tol)],
        dtype=np.uint8,
    )
    color_ok = cv2.inRange(hsv, lower, upper) > 0
    painted_walk = (painted_blocked == 0) & (walkability == CELL_WALKABLE)
    seen = np.zeros((height, width), dtype=np.uint8)
    queue = [(sx, sy)]
    seen[sy, sx] = 1
    while queue:
        x, y = queue.pop(0)
        if not color_ok[y, x] or painted_walk[y, x]:
            continue
        out[y, x] = CELL_BLOCKED
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if nx < 0 or ny < 0 or nx >= width or ny >= height or seen[ny, nx]:
                continue
            seen[ny, nx] = 1
            queue.append((nx, ny))
    out[painted_blocked > 0] = CELL_BLOCKED
    return out


def is_stuck(prev: tuple[int, int], curr: tuple[int, int], thresh_px: float = 2.0) -> bool:
    dx = float(curr[0] - prev[0])
    dy = float(curr[1] - prev[1])
    return math.hypot(dx, dy) < float(thresh_px)
