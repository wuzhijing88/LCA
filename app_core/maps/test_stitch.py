import numpy as np

from app_core.maps import stitch
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


def test_estimate_origin_finds_same_size_horizontal_overlap():
    rng = np.random.default_rng(142)
    scene = rng.integers(0, 256, size=(48, 96, 3), dtype=np.uint8)
    base = scene[:, :64].copy()
    tile = scene[:, 32:96].copy()

    origin = estimate_origin(base, tile)

    assert origin is not None
    assert abs(origin[0] - 32) <= 1
    assert abs(origin[1]) <= 1


def test_estimate_origin_rejects_unrelated_same_size_tiles():
    base = np.random.default_rng(1).integers(0, 256, size=(48, 64, 3), dtype=np.uint8)
    tile = np.random.default_rng(2).integers(0, 256, size=(48, 64, 3), dtype=np.uint8)

    assert estimate_origin(base, tile) is None


def test_next_tile_origin_falls_back_to_canvas_right_edge():
    base = np.zeros((20, 30, 3), dtype=np.uint8)
    tile = np.full((20, 30, 3), 255, dtype=np.uint8)

    assert stitch.next_tile_origin(base, tile) == (30, 0)
