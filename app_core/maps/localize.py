from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np

_ANGLE_STEP = 5
_MOVE_EPS = 1.0
_MATCH_THRESHOLD = 0.4


@dataclass
class LocateResult:
    found: bool
    x: int = 0
    y: int = 0
    heading_deg: float | None = None
    score: float = 0.0


def heading_from_delta(prev: tuple[int, int], curr: tuple[int, int]) -> float | None:
    """图像坐标 y 向下，atan2(dx, -dy) 转 0–360，向上为 0。位移 < 1 像素返回 None。"""
    dx = int(curr[0]) - int(prev[0])
    dy = int(curr[1]) - int(prev[1])
    if math.hypot(dx, dy) < _MOVE_EPS:
        return None
    return float(math.degrees(math.atan2(dx, -dy)) % 360)


def heading_from_arrow(
    minimap_bgr: np.ndarray,
    arrow_up_bgr: np.ndarray,
    angle_step: int = _ANGLE_STEP,
) -> float | None:
    """小地图中心裁块对朝上箭头模板旋转匹配，0° = 朝上。"""
    crop = _center_crop(minimap_bgr, arrow_up_bgr)
    if crop is None:
        return None
    step = max(1, int(angle_step))
    best_score = -1.0
    best_angle: float | None = None
    for angle in range(0, 360, step):
        rotated = _rotate(crop, angle)
        hit = _best_match(rotated, arrow_up_bgr)
        if hit is None:
            continue
        _, _, score = hit
        if score > best_score:
            best_score = score
            best_angle = float(angle)
    return best_angle


def locate_on_map(
    minimap_bgr,
    map_bgr,
    *,
    marker: str,
    map_rotates: bool,
    arrow_template_bgr=None,
    last_pos=None,
) -> LocateResult:
    """在大地图上定位玩家。

    位置永远是匹配块中心。小地图大于大地图时 found=False。
    - marker == "箭头"：位置用未旋转小地图匹配；朝向用中心裁块对朝上箭头模板旋转匹配，0° = 朝上。
    - marker == "圆点" 且 map_rotates：对小地图每 angle_step 度旋转后匹配，最佳角度为朝向，位置用该角度下的匹配中心。
    - marker == "圆点" 且不转：0° 匹配出位置；朝向仅当 last_pos 有值时用 heading_from_delta，否则 heading_deg is None。
    """
    if not _fits(minimap_bgr, map_bgr):
        return LocateResult(found=False)
    if marker == "圆点" and map_rotates:
        return _locate_rotating_dot(minimap_bgr, map_bgr)
    hit = _best_match(map_bgr, minimap_bgr)
    if hit is None:
        return LocateResult(found=False)
    x, y, score = hit
    if score < _MATCH_THRESHOLD:
        return LocateResult(found=False, x=x, y=y, score=score)
    heading: float | None = None
    if marker == "箭头":
        heading = heading_from_arrow(minimap_bgr, arrow_template_bgr) if arrow_template_bgr is not None else None
    elif last_pos is not None:
        heading = heading_from_delta((int(last_pos[0]), int(last_pos[1])), (x, y))
    return LocateResult(found=True, x=x, y=y, heading_deg=heading, score=score)


def _is_spatially_flat(image: np.ndarray) -> bool:
    if image.ndim == 3:
        return all(float(np.std(image[:, :, channel])) < 1.0 for channel in range(image.shape[2]))
    return float(np.std(image)) < 1.0


def _fits(template: Optional[np.ndarray], image: Optional[np.ndarray]) -> bool:
    if template is None or image is None or template.size == 0 or image.size == 0:
        return False
    th, tw = template.shape[:2]
    ih, iw = image.shape[:2]
    return ih >= th and iw >= tw


def _center_crop(image: Optional[np.ndarray], template: Optional[np.ndarray]) -> Optional[np.ndarray]:
    if image is None or template is None or image.size == 0 or template.size == 0:
        return None
    th, tw = template.shape[:2]
    ih, iw = image.shape[:2]
    if ih < th or iw < tw:
        return None
    x0 = (iw - tw) // 2
    y0 = (ih - th) // 2
    return np.ascontiguousarray(image[y0 : y0 + th, x0 : x0 + tw])


def _rotate(image: np.ndarray, angle: float) -> np.ndarray:
    height, width = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2.0, height / 2.0), float(angle), 1.0)
    return cv2.warpAffine(image, matrix, (width, height), borderValue=(0, 0, 0))


def _best_match(image: np.ndarray, template: np.ndarray) -> Optional[tuple[int, int, float]]:
    if not _fits(template, image):
        return None
    search = np.ascontiguousarray(image)
    patch = np.ascontiguousarray(template)
    if _is_spatially_flat(patch):
        if np.any(patch):
            heat = cv2.matchTemplate(search, patch, cv2.TM_SQDIFF_NORMED)
            min_val, _, min_loc, _ = cv2.minMaxLoc(heat)
            score = max(0.0, 1.0 - float(min_val)) if np.isfinite(min_val) else 0.0
        else:
            heat = cv2.matchTemplate(search, patch, cv2.TM_SQDIFF)
            min_val, _, min_loc, _ = cv2.minMaxLoc(heat)
            score = 1.0 if min_val <= 0 else 1.0 / (1.0 + float(min_val))
        loc = min_loc
    else:
        heat = cv2.matchTemplate(search, patch, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(heat)
        loc = max_loc
        score = float(max_val) if np.isfinite(max_val) else 0.0
    th, tw = patch.shape[:2]
    return (int(loc[0]) + tw // 2, int(loc[1]) + th // 2, score)


def _locate_rotating_dot(minimap_bgr: np.ndarray, map_bgr: np.ndarray) -> LocateResult:
    best: Optional[tuple[int, int, float, float]] = None
    for angle in range(0, 360, _ANGLE_STEP):
        hit = _best_match(map_bgr, _rotate(minimap_bgr, angle))
        if hit is None:
            continue
        x, y, score = hit
        if best is None or score > best[2]:
            best = (x, y, score, float(angle))
    if best is None:
        return LocateResult(found=False)
    x, y, score, heading = best
    if score < _MATCH_THRESHOLD:
        return LocateResult(found=False, x=x, y=y, heading_deg=heading, score=score)
    return LocateResult(found=True, x=x, y=y, heading_deg=heading, score=score)
