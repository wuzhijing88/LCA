# ui/maps/test_editor_payload.py
import numpy as np
import pytest

from app_core.maps.record import CELL_UNKNOWN, CELL_WALKABLE
from ui.maps.editor_payload import apply_editor_payload


@pytest.fixture(autouse=True)
def _isolate_user_data(monkeypatch, tmp_path):
    monkeypatch.setenv("LCA_USER_DATA_DIR", str(tmp_path))


def test_payload_route_overrides_goal():
    tile = np.zeros((16, 16, 3), dtype=np.uint8)
    record = apply_editor_payload(
        None,
        {
            "name": "测",
            "tiles": [tile],
            "origins": [(0, 0)],
            "route": [(1, 1), (8, 8)],
            "goal": (2, 2),
            "painted_cells": [(3, 3)],
        },
    )
    assert record.route[-1] == (8, 8)
    assert record.goal is None
    assert int(record.painted_blocked[3, 3]) == 1


def test_payload_update_rejects_missing_route_and_goal(tmp_path):
    tile = np.zeros((16, 16, 3), dtype=np.uint8)
    payload = {
        "name": "测",
        "image_bgr": tile,
        "route": [],
        "goal": (2, 2),
        "root": tmp_path,
    }
    record = apply_editor_payload(None, payload)

    payload["goal"] = None
    with pytest.raises(ValueError, match="终点"):
        apply_editor_payload(record, payload)


def test_expanding_image_preserves_learned_walkability(tmp_path):
    record = apply_editor_payload(
        None,
        {
            "name": "扩图",
            "image_bgr": np.zeros((4, 5, 3), dtype=np.uint8),
            "route": [],
            "goal": (3, 2),
            "root": tmp_path,
        },
    )
    record.walkability[1, 2] = CELL_WALKABLE

    updated = apply_editor_payload(
        record,
        {
            "name": "扩图",
            "image_bgr": np.zeros((7, 8, 3), dtype=np.uint8),
            "route": [],
            "goal": (6, 5),
            "root": tmp_path,
        },
    )

    assert updated.walkability.shape == (7, 8)
    assert int(updated.walkability[1, 2]) == CELL_WALKABLE
    assert int(updated.walkability[6, 7]) == CELL_UNKNOWN
