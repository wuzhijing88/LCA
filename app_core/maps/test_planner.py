import numpy as np

from app_core.maps.planner import astar, nearest_route_index, plan_path, reached_goal
from app_core.maps.record import CELL_BLOCKED, CELL_UNKNOWN, CELL_WALKABLE, MapRecord


def _record(route=None, goal=None, blocked=()):
    image = np.zeros((32, 32, 3), dtype=np.uint8)
    walk = np.full((32, 32), CELL_UNKNOWN, dtype=np.uint8)
    painted = np.zeros((32, 32), dtype=np.uint8)
    for x, y in blocked:
        painted[y, x] = 1
        walk[y, x] = CELL_BLOCKED
    return MapRecord("t", "t", image, walk, painted, route=route or [], goal=goal)


def test_astar_goes_around_wall():
    grid = np.zeros((5, 5), dtype=np.uint8)
    grid[0:5, 2] = 1
    grid[4, 2] = 0
    path = astar(grid, (0, 0), (0, 4), eight=False)
    assert path is not None
    assert path[0] == (0, 0)
    assert path[-1] == (0, 4)
    assert all(cell != (2, 2) for cell in path)


def test_join_route_from_outside():
    record = _record(route=[(8, 8), (16, 8), (24, 8)])
    path = plan_path(record, (8, 24), eight=True, cell_size=8)
    assert path
    assert path[-1] == (24, 8) or abs(path[-1][0] - 24) <= 4
    assert nearest_route_index((8, 24), record.route) == 0


def test_goal_only_and_blocked_returns_empty():
    record = _record(goal=(24, 8), blocked=[(x, 8) for x in range(32)])
    assert plan_path(record, (0, 8), eight=False, cell_size=8) == []
    assert reached_goal((24, 8), (24, 8), radius_px=8.0) is True
    assert reached_goal((0, 0), (24, 8), radius_px=8.0) is False


def test_eight_way_does_not_cut_through_blocked_corner():
    grid = np.array([[0, 1], [1, 0]], dtype=np.uint8)

    assert astar(grid, (0, 0), (1, 1), eight=True) is None


def test_planner_prefers_known_walkable_detour_over_unknown_shortcut():
    walk = np.full((5, 5), CELL_BLOCKED, dtype=np.uint8)
    walk[2, 0] = CELL_WALKABLE
    walk[2, 4] = CELL_WALKABLE
    walk[2, 1:4] = CELL_UNKNOWN
    walk[1, :] = CELL_WALKABLE
    image = np.zeros((5, 5, 3), dtype=np.uint8)
    record = MapRecord(
        "weighted",
        "weighted",
        image,
        walk,
        np.zeros((5, 5), dtype=np.uint8),
        goal=(4, 2),
    )

    path = plan_path(record, (0, 2), eight=False, cell_size=1)

    assert path
    assert (2, 1) in path
    assert (2, 2) not in path


def test_planner_can_cross_unknown_when_it_is_the_only_path():
    walk = np.full((3, 5), CELL_BLOCKED, dtype=np.uint8)
    walk[1, :] = CELL_UNKNOWN
    walk[1, 0] = CELL_WALKABLE
    walk[1, 4] = CELL_WALKABLE
    image = np.zeros((3, 5, 3), dtype=np.uint8)
    record = MapRecord(
        "unknown",
        "unknown",
        image,
        walk,
        np.zeros((3, 5), dtype=np.uint8),
        goal=(4, 1),
    )

    path = plan_path(record, (0, 1), eight=False, cell_size=1)

    assert path
    assert path[-1] == (4, 1)
