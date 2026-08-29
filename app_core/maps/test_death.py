import numpy as np

from app_core.maps.death import is_death_state


def test_death_template_hit_and_miss():
    frame = np.zeros((40, 40, 3), dtype=np.uint8)
    frame[5:15, 5:15] = (0, 0, 255)
    template = frame[5:15, 5:15].copy()
    other = np.zeros((10, 10, 3), dtype=np.uint8)
    other[:] = (255, 0, 0)
    assert is_death_state(frame, [template], confidence=0.8) is True
    assert is_death_state(frame, [other], confidence=0.95) is False
    assert is_death_state(frame, [], confidence=0.8) is False
