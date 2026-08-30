import numpy as np

from app_core.maps.cartography.register import append_frame, start_session


def _textured_canvas(width: int = 200, height: int = 120) -> np.ndarray:
    rng = np.random.default_rng(0)
    base = rng.integers(40, 200, size=(height, width, 3), dtype=np.uint8)
    for x in range(0, width, 17):
        base[:, x : x + 2] = (20, 220, 40)
    for y in range(0, height, 13):
        base[y : y + 2, :] = (220, 40, 40)
    return base


def test_append_expands_mosaic_for_overlapping_shift():
    world = _textured_canvas()
    left = world[:, 0:140].copy()
    right = world[:, 60:200].copy()
    state = start_session(left)
    assert append_frame(state, right) is True
    assert state.mosaic is not None
    assert state.mosaic.shape[1] >= 180
    assert len(state.frames) == 2


def test_append_rejects_unrelated_frame():
    world = _textured_canvas()
    other = np.zeros((120, 140, 3), dtype=np.uint8)
    other[:] = (10, 10, 200)
    state = start_session(world[:, 0:140].copy())
    assert append_frame(state, other) is False
    assert "配准" in state.last_error
    assert len(state.frames) == 1
