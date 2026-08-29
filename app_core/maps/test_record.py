import numpy as np
import pytest

from app_core.maps.record import (
    CELL_UNKNOWN,
    create_map,
    effective_goal,
    format_map_option,
    list_maps,
    load_map,
    parse_map_option,
    save_map,
)


def test_route_map_goal_is_last_point(tmp_path):
    image = np.zeros((40, 60, 3), dtype=np.uint8)
    record = create_map(
        "林间",
        image,
        route=[(2, 3), (10, 12), (20, 18)],
        goal=(1, 1),
        root=tmp_path,
    )
    assert effective_goal(record) == (20, 18)
    assert record.goal is None
    assert record.walkability.shape[:2] == (40, 60)
    assert int(record.walkability[0, 0]) == CELL_UNKNOWN
    save_map(record, root=tmp_path)
    loaded = load_map(record.map_id, root=tmp_path)
    assert loaded.name == "林间"
    assert loaded.route == [(2, 3), (10, 12), (20, 18)]
    assert effective_goal(loaded) == (20, 18)
    assert list_maps(tmp_path) == [(record.map_id, "林间")]


def test_goal_only_map_requires_goal(tmp_path):
    image = np.zeros((8, 8, 3), dtype=np.uint8)
    with pytest.raises(ValueError, match="终点"):
        create_map("空", image, root=tmp_path)
    record = create_map("空", image, goal=(4, 5), root=tmp_path)
    assert effective_goal(record) == (4, 5)
    save_map(record, root=tmp_path)
    loaded = load_map(record.map_id, root=tmp_path)
    assert loaded.route == []
    assert loaded.goal == (4, 5)


def test_map_option_roundtrip():
    label = format_map_option("ab12", "森林")
    assert parse_map_option(label) == "ab12"
