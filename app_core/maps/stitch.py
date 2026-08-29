from __future__ import annotations

import cv2
import numpy as np

_MATCH_THRESHOLD = 0.4


def stitch_by_origins(
    tiles: list[np.ndarray],
    origins: list[tuple[int, int]],
) -> np.ndarray:
    if not tiles:
        return np.zeros((0, 0, 3), dtype=np.uint8)

    max_y = 0
    max_x = 0
    channels = int(tiles[0].shape[2]) if tiles[0].ndim == 3 else 1
    for tile, (x, y) in zip(tiles, origins):
        h, w = tile.shape[:2]
        max_y = max(max_y, y + h)
        max_x = max(max_x, x + w)

    if channels == 1:
        canvas = np.zeros((max_y, max_x), dtype=np.uint8)
    else:
        canvas = np.zeros((max_y, max_x, channels), dtype=np.uint8)

    for tile, (x, y) in zip(tiles, origins):
        h, w = tile.shape[:2]
        canvas[y : y + h, x : x + w] = tile

    return canvas


def _is_spatially_flat(image: np.ndarray) -> bool:
    if image.ndim == 3:
        return all(float(np.std(image[:, :, channel])) < 1.0 for channel in range(image.shape[2]))
    return float(np.std(image)) < 1.0


def estimate_origin(base: np.ndarray, tile: np.ndarray) -> tuple[int, int] | None:
    if tile.ndim != base.ndim:
        return None
    th, tw = tile.shape[:2]
    bh, bw = base.shape[:2]
    if th >= bh or tw >= bw:
        return None

    search = np.ascontiguousarray(base)
    patch = np.ascontiguousarray(tile)
    if _is_spatially_flat(patch):
        heat = cv2.matchTemplate(search, patch, cv2.TM_SQDIFF)
        min_val, _, min_loc, _ = cv2.minMaxLoc(heat)
        score = 1.0 if min_val <= 0 else 1.0 / (1.0 + float(min_val))
        if score < _MATCH_THRESHOLD:
            return None
        x, y = min_loc
    else:
        heat = cv2.matchTemplate(search, patch, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(heat)
        if not np.isfinite(max_val) or float(max_val) < _MATCH_THRESHOLD:
            return None
        x, y = max_loc
    return (int(x), int(y))
