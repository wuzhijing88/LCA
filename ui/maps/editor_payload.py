from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from app_core.maps.record import MapRecord, create_map, save_map
from app_core.maps.stitch import stitch_by_origins


def _points(value: Any) -> list[tuple[int, int]]:
    return [(int(x), int(y)) for x, y in (value or [])]


def apply_editor_payload(record: MapRecord | None, payload: dict[str, Any]) -> MapRecord:
    root_value = payload.get("root")
    root = Path(root_value) if root_value is not None else None
    image = payload.get("image_bgr")
    if image is None:
        image = stitch_by_origins(
            list(payload.get("tiles") or []),
            _points(payload.get("origins")),
        )

    route = _points(payload.get("route"))
    raw_goal = payload.get("goal")
    if not route and raw_goal is None:
        raise ValueError("没有线路时必须标注终点")
    goal = None if route or raw_goal is None else (int(raw_goal[0]), int(raw_goal[1]))

    if record is None:
        record = create_map(
            str(payload.get("name") or ""),
            image,
            route=route,
            goal=goal,
            root=root,
        )
    else:
        record.name = str(payload.get("name") or "").strip() or "未命名地图"
        record.image_bgr = np.ascontiguousarray(image)
        record.route = route
        record.goal = goal
        if record.walkability.shape[:2] != image.shape[:2]:
            height, width = image.shape[:2]
            record.walkability = np.zeros((height, width), dtype=np.uint8)
        record.painted_blocked = np.zeros(image.shape[:2], dtype=np.uint8)

    height, width = record.painted_blocked.shape[:2]
    for x, y in _points(payload.get("painted_cells")):
        if 0 <= x < width and 0 <= y < height:
            record.painted_blocked[y, x] = 1
    save_map(record, root=root)
    return record
