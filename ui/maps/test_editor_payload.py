# ui/maps/test_editor_payload.py
import numpy as np

from ui.maps.editor_payload import apply_editor_payload


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
