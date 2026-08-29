# ui/maps/test_editor_payload.py
import numpy as np
import pytest

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
