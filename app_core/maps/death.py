from __future__ import annotations

import cv2
import numpy as np

from utils.match.smart_image_matcher import match_template


def _is_spatially_flat(image: np.ndarray) -> bool:
    if image.ndim == 3:
        return all(float(np.std(image[:, :, channel])) < 1.0 for channel in range(image.shape[2]))
    return float(np.std(image)) < 1.0


def _flat_template_found(frame_bgr: np.ndarray, template: np.ndarray) -> bool:
    th, tw = template.shape[:2]
    fh, fw = frame_bgr.shape[:2]
    if fh < th or fw < tw:
        return False
    heat = cv2.matchTemplate(frame_bgr, template, cv2.TM_SQDIFF)
    min_val, _, _, _ = cv2.minMaxLoc(heat)
    return float(min_val) <= 1.0


def is_death_state(
    frame_bgr: np.ndarray,
    templates: list[np.ndarray],
    confidence: float = 0.8,
) -> bool:
    if not templates:
        return False
    for template in templates:
        if _is_spatially_flat(template):
            if _flat_template_found(frame_bgr, template):
                return True
            continue
        if match_template(frame_bgr, template, confidence=confidence).found:
            return True
    return False
