from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

CELL_UNKNOWN = 0
CELL_WALKABLE = 1
CELL_BLOCKED = 2
_IMAGE_NAME = "map.png"
_WALK_NAME = "walkability.png"
_PAINT_NAME = "painted.png"
_MANIFEST = "manifest.json"


@dataclass
class MapRecord:
    map_id: str
    name: str
    image_bgr: np.ndarray
    walkability: np.ndarray
    painted_blocked: np.ndarray
    route: list[tuple[int, int]] = field(default_factory=list)
    goal: Optional[tuple[int, int]] = None


def maps_root(root: Optional[Path] = None) -> Path:
    if root is not None:
        path = Path(root)
        path.mkdir(parents=True, exist_ok=True)
        return path
    from utils.app_paths import get_maps_dir

    return Path(get_maps_dir())


def effective_goal(record: MapRecord) -> tuple[int, int]:
    if record.route:
        return (int(record.route[-1][0]), int(record.route[-1][1]))
    if record.goal is None:
        raise ValueError("地图缺少终点")
    return (int(record.goal[0]), int(record.goal[1]))


def format_map_option(map_id: str, name: str) -> str:
    return f"{name} — {map_id}"


def parse_map_option(label: str) -> str:
    text = str(label or "").strip()
    if " — " in text:
        return text.rsplit(" — ", 1)[-1].strip()
    return text


def _blank_layers(image_bgr: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    height, width = image_bgr.shape[:2]
    walk = np.full((height, width), CELL_UNKNOWN, dtype=np.uint8)
    painted = np.zeros((height, width), dtype=np.uint8)
    return walk, painted


def create_map(
    name: str,
    image_bgr: np.ndarray,
    *,
    route: Optional[list[tuple[int, int]]] = None,
    goal: Optional[tuple[int, int]] = None,
    root: Optional[Path] = None,
) -> MapRecord:
    if image_bgr is None or image_bgr.size == 0:
        raise ValueError("大地图图像为空")
    points = [(int(x), int(y)) for x, y in (route or [])]
    resolved_goal: Optional[tuple[int, int]]
    if points:
        resolved_goal = None
    elif goal is None:
        raise ValueError("没有线路时必须标注终点")
    else:
        resolved_goal = (int(goal[0]), int(goal[1]))
    walk, painted = _blank_layers(image_bgr)
    record = MapRecord(
        map_id=uuid.uuid4().hex[:12],
        name=str(name or "").strip() or "未命名地图",
        image_bgr=np.ascontiguousarray(image_bgr),
        walkability=walk,
        painted_blocked=painted,
        route=points,
        goal=resolved_goal,
    )
    save_map(record, root=root)
    return record


def save_map(record: MapRecord, root: Optional[Path] = None) -> Path:
    folder = maps_root(root) / record.map_id
    folder.mkdir(parents=True, exist_ok=True)
    if record.route:
        record.goal = None
    cv2.imwrite(str(folder / _IMAGE_NAME), record.image_bgr)
    cv2.imwrite(str(folder / _WALK_NAME), record.walkability)
    cv2.imwrite(str(folder / _PAINT_NAME), record.painted_blocked)
    payload = {
        "id": record.map_id,
        "name": record.name,
        "image": _IMAGE_NAME,
        "walkability": _WALK_NAME,
        "painted": _PAINT_NAME,
        "route": [list(point) for point in record.route],
        "goal": list(record.goal) if record.goal is not None else None,
    }
    (folder / _MANIFEST).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return folder


def load_map(map_id: str, root: Optional[Path] = None) -> MapRecord:
    folder = maps_root(root) / str(map_id).strip()
    payload = json.loads((folder / _MANIFEST).read_text(encoding="utf-8"))
    image = cv2.imread(str(folder / str(payload.get("image") or _IMAGE_NAME)), cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(folder / _IMAGE_NAME)
    walk = cv2.imread(str(folder / str(payload.get("walkability") or _WALK_NAME)), cv2.IMREAD_GRAYSCALE)
    painted = cv2.imread(str(folder / str(payload.get("painted") or _PAINT_NAME)), cv2.IMREAD_GRAYSCALE)
    if walk is None or walk.shape[:2] != image.shape[:2]:
        walk, _ = _blank_layers(image)
    if painted is None or painted.shape[:2] != image.shape[:2]:
        _, painted = _blank_layers(image)
    route = [(int(x), int(y)) for x, y in (payload.get("route") or [])]
    raw_goal = payload.get("goal")
    goal = (int(raw_goal[0]), int(raw_goal[1])) if raw_goal else None
    if route:
        goal = None
    return MapRecord(
        map_id=str(payload.get("id") or map_id),
        name=str(payload.get("name") or map_id),
        image_bgr=image,
        walkability=walk.astype(np.uint8),
        painted_blocked=(painted > 0).astype(np.uint8),
        route=route,
        goal=goal,
    )


def list_maps(root: Optional[Path] = None) -> list[tuple[str, str]]:
    base = maps_root(root)
    items: list[tuple[str, str]] = []
    if not base.is_dir():
        return items
    for folder in sorted(base.iterdir()):
        manifest = folder / _MANIFEST
        if not manifest.is_file():
            continue
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        items.append((str(payload.get("id") or folder.name), str(payload.get("name") or folder.name)))
    return items
