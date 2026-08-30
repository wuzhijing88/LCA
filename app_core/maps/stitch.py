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


def _match_patch(base: np.ndarray, patch: np.ndarray) -> tuple[tuple[int, int], float] | None:
    ph, pw = patch.shape[:2]
    bh, bw = base.shape[:2]
    if ph > bh or pw > bw:
        return None
    search = np.ascontiguousarray(base)
    contiguous_patch = np.ascontiguousarray(patch)
    if _is_spatially_flat(contiguous_patch):
        heat = cv2.matchTemplate(search, contiguous_patch, cv2.TM_SQDIFF)
        min_val, _, min_loc, _ = cv2.minMaxLoc(heat)
        score = 1.0 if min_val <= 0 else 1.0 / (1.0 + float(min_val))
        loc = min_loc
    else:
        heat = cv2.matchTemplate(search, contiguous_patch, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(heat)
        score = float(max_val) if np.isfinite(max_val) else 0.0
        loc = max_loc
    return ((int(loc[0]), int(loc[1])), score)


def estimate_origin(base: np.ndarray, tile: np.ndarray) -> tuple[int, int] | None:
    if tile.ndim != base.ndim:
        return None
    th, tw = tile.shape[:2]
    bh, bw = base.shape[:2]
    if th < bh and tw < bw:
        matched = _match_patch(base, tile)
        if matched is None or matched[1] < _MATCH_THRESHOLD:
            return None
        return matched[0]

    candidates: list[tuple[np.ndarray, tuple[int, int]]] = []
    strip_width = max(1, min(int(round(tw * 0.35)), bw - 1))
    strip_height = max(1, min(int(round(th * 0.35)), bh - 1))
    if bw > 1:
        candidates.extend(
            [
                (tile[:, :strip_width], (0, 0)),
                (tile[:, tw - strip_width :], (tw - strip_width, 0)),
            ]
        )
    if bh > 1:
        candidates.extend(
            [
                (tile[:strip_height, :], (0, 0)),
                (tile[th - strip_height :, :], (0, th - strip_height)),
            ]
        )

    best: tuple[float, tuple[int, int]] | None = None
    for strip, (offset_x, offset_y) in candidates:
        matched = _match_patch(base, strip)
        if matched is None:
            continue
        (match_x, match_y), score = matched
        if score < _MATCH_THRESHOLD:
            continue
        origin = (match_x - offset_x, match_y - offset_y)
        if best is None or score > best[0]:
            best = (score, origin)
    return None if best is None else best[1]


def next_tile_origin(base: np.ndarray, tile: np.ndarray) -> tuple[int, int]:
    estimated = estimate_origin(base, tile)
    return estimated if estimated is not None else (int(base.shape[1]), 0)
