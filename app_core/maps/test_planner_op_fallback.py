import numpy as np

from app_core.maps.planner import astar, try_op_astar


def test_try_op_astar_none_without_dll(monkeypatch):
    monkeypatch.setattr("app_core.maps.planner._op_astar_available", lambda: False)
    grid = np.zeros((3, 3), dtype=np.uint8)
    assert try_op_astar(grid, (0, 0), (2, 2)) is None
    assert astar(grid, (0, 0), (2, 2)) is not None
