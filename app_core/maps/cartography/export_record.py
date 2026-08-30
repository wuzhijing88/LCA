from __future__ import annotations

from pathlib import Path

import numpy as np

from app_core.maps.cartography.session import AnnotationState
from app_core.maps.record import MapRecord, create_map, save_map


def export_to_map_record(
    mosaic: np.ndarray,
    annotations: AnnotationState,
    *,
    existing: MapRecord | None = None,
    root: Path | None = None,
) -> MapRecord:
    image = np.ascontiguousarray(mosaic)
    route = list(annotations.route)
    goal = None if route else annotations.goal
    if existing is None:
        record = create_map(
            annotations.name,
            image,
            route=route,
            goal=goal,
            root=root,
        )
    else:
        record = existing
        record.name = annotations.name.strip() or record.name or "未命名地图"
        record.image_bgr = image
        record.route = route
        record.goal = goal
        if record.walkability.shape[:2] != image.shape[:2]:
            height, width = image.shape[:2]
            resized = np.zeros((height, width), dtype=np.uint8)
            old = record.walkability
            h = min(height, old.shape[0])
            w = min(width, old.shape[1])
            resized[:h, :w] = old[:h, :w]
            record.walkability = resized
        record.painted_blocked = np.zeros(image.shape[:2], dtype=np.uint8)

    height, width = record.painted_blocked.shape[:2]
    for x, y in annotations.painted_cells:
        if 0 <= x < width and 0 <= y < height:
            record.painted_blocked[y, x] = 1
    save_map(record, root=root)
    return record
