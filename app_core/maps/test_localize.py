# app_core/maps/test_localize.py
import cv2
import numpy as np

from app_core.maps.localize import heading_from_arrow, heading_from_delta, locate_on_map


def _arrow(angle: float = 0.0) -> np.ndarray:
    canvas = np.zeros((21, 21, 3), dtype=np.uint8)
    cv2.arrowedLine(canvas, (10, 16), (10, 4), (0, 0, 255), 2, tipLength=0.4)
    matrix = cv2.getRotationMatrix2D((10, 10), angle, 1.0)
    return cv2.warpAffine(canvas, matrix, (21, 21), borderValue=(0, 0, 0))


def test_north_up_dot_uses_match_center():
    big = np.zeros((80, 80, 3), dtype=np.uint8)
    big[20:40, 30:50] = (30, 180, 30)
    mini = big[20:40, 30:50].copy()
    result = locate_on_map(mini, big, marker="圆点", map_rotates=False)
    assert result.found
    assert abs(result.x - 40) <= 2
    assert abs(result.y - 30) <= 2
    assert result.heading_deg is None


def test_dot_heading_from_delta_points_right():
    heading = heading_from_delta((10, 10), (20, 10))
    assert heading is not None
    assert min(heading, 360 - heading) < 8 or abs(heading - 90) < 8


def test_arrow_heading_detects_rotation():
    up = _arrow(0.0)
    rotated = _arrow(-90.0)
    heading = heading_from_arrow(rotated, up, angle_step=15)
    assert heading is not None
    assert abs((heading - 90 + 180) % 360 - 180) < 20
