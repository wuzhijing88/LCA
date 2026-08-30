from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app_core.maps.cartography.register import CartographyState


@dataclass
class AnnotationState:
    route: list[tuple[int, int]] = field(default_factory=list)
    goal: tuple[int, int] | None = None
    painted_cells: list[tuple[int, int]] = field(default_factory=list)
    name: str = "未命名地图"


@dataclass
class SessionData:
    state: CartographyState
    annotations: AnnotationState
    minimap_rect: tuple[int, int, int, int] = (0, 0, 0, 0)


def session_dir(map_root: Path) -> Path:
    return Path(map_root) / "cartography"


def save_session(map_root: Path, data: SessionData) -> None:
    root = session_dir(map_root)
    frames_dir = root / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    for old in frames_dir.glob("*.png"):
        old.unlink(missing_ok=True)

    payload: dict[str, Any] = {
        "name": data.annotations.name,
        "minimap_rect": list(data.minimap_rect),
        "route": [list(p) for p in data.annotations.route],
        "goal": list(data.annotations.goal) if data.annotations.goal is not None else None,
        "painted_cells": [list(p) for p in data.annotations.painted_cells],
        "transforms": [t.astype(float).tolist() for t in data.state.transforms],
        "frame_files": [],
    }
    for index, frame in enumerate(data.state.frames):
        name = f"{index:04d}.png"
        path = frames_dir / name
        cv2.imencode(".png", frame)[1].tofile(str(path))
        payload["frame_files"].append(name)

    if data.state.mosaic is not None:
        mosaic_path = root / "mosaic.png"
        cv2.imencode(".png", data.state.mosaic)[1].tofile(str(mosaic_path))
        payload["mosaic_file"] = "mosaic.png"

    (root / "session.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_session(map_root: Path) -> SessionData | None:
    root = session_dir(map_root)
    manifest = root / "session.json"
    if not manifest.is_file():
        return None
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    frames: list[np.ndarray] = []
    for name in payload.get("frame_files") or []:
        path = root / "frames" / str(name)
        if not path.is_file():
            continue
        data = np.fromfile(str(path), dtype=np.uint8)
        image = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if image is not None:
            frames.append(image)
    transforms = [
        np.asarray(item, dtype=np.float64).reshape(2, 3) for item in (payload.get("transforms") or [])
    ]
    mosaic = None
    mosaic_name = payload.get("mosaic_file")
    if mosaic_name:
        mosaic_path = root / str(mosaic_name)
        if mosaic_path.is_file():
            raw = np.fromfile(str(mosaic_path), dtype=np.uint8)
            mosaic = cv2.imdecode(raw, cv2.IMREAD_COLOR)
    if mosaic is None and frames:
        mosaic = frames[0].copy()
    if not frames or mosaic is None:
        return None
    while len(transforms) < len(frames):
        transforms.append(np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float64))
    rect = payload.get("minimap_rect") or [0, 0, 0, 0]
    goal_raw = payload.get("goal")
    annotations = AnnotationState(
        name=str(payload.get("name") or "未命名地图"),
        route=[(int(x), int(y)) for x, y in (payload.get("route") or [])],
        goal=(int(goal_raw[0]), int(goal_raw[1])) if goal_raw else None,
        painted_cells=[(int(x), int(y)) for x, y in (payload.get("painted_cells") or [])],
    )
    state = CartographyState(frames=frames, transforms=transforms[: len(frames)], mosaic=mosaic)
    return SessionData(
        state=state,
        annotations=annotations,
        minimap_rect=(int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3])),
    )
