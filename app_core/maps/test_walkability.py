import numpy as np

from app_core.maps.record import CELL_BLOCKED, CELL_UNKNOWN, CELL_WALKABLE
from app_core.maps.walkability import flood_blocked, is_stuck, mark_footprints, merged_walkability


def test_footprints_do_not_overwrite_paint():
    walk = np.zeros((6, 6), dtype=np.uint8)
    painted = np.zeros((6, 6), dtype=np.uint8)
    painted[2, 2] = 1
    out = mark_footprints(walk, painted, [(2, 2), (3, 2)])
    assert int(out[2, 2]) == CELL_UNKNOWN
    assert int(out[2, 3]) == CELL_WALKABLE


def test_flood_marks_similar_color_but_skips_painted_walkable():
    image = np.zeros((10, 10, 3), dtype=np.uint8)
    image[:, :] = (10, 200, 10)
    image[0:3, 0:3] = (10, 10, 200)
    walk = np.zeros((10, 10), dtype=np.uint8)
    painted = np.zeros((10, 10), dtype=np.uint8)
    painted[8, 8] = 1
    walk[8, 8] = CELL_WALKABLE
    out = flood_blocked(image, walk, painted, (5, 5), hsv_tol=12)
    assert int(out[5, 5]) == CELL_BLOCKED
    assert int(out[7, 7]) == CELL_BLOCKED
    assert int(out[1, 1]) == CELL_UNKNOWN
    assert int(merged_walkability(out, painted)[8, 8]) == CELL_BLOCKED


def test_stuck_threshold():
    assert is_stuck((10, 10), (11, 10), thresh_px=2.0) is True
    assert is_stuck((10, 10), (14, 10), thresh_px=2.0) is False
