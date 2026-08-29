import numpy as np

from app_core.maps.stitch import estimate_origin, stitch_by_origins


def test_stitch_places_tiles():
    a = np.full((10, 10, 3), 10, dtype=np.uint8)
    b = np.full((10, 10, 3), 200, dtype=np.uint8)
    canvas = stitch_by_origins([a, b], [(0, 0), (8, 0)])
    assert canvas.shape[1] >= 18
    assert int(canvas[2, 2, 0]) == 10
    assert int(canvas[2, 12, 0]) == 200


def test_estimate_origin_finds_overlap():
    base = np.zeros((30, 40, 3), dtype=np.uint8)
    base[5:15, 10:20] = 80
    tile = base[5:15, 10:20].copy()
    origin = estimate_origin(base, tile)
    assert origin == (10, 5)
