import numpy as np

from app_core.maps.planner import astar, try_op_astar


def test_try_op_astar_is_noop():
    grid = np.zeros((3, 3), dtype=np.uint8)
    assert try_op_astar(grid, (0, 0), (2, 2)) is None
    assert astar(grid, (0, 0), (2, 2)) is not None
