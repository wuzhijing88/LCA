import numpy as np

from app_core.maps.cartography.export_record import export_to_map_record
from app_core.maps.cartography.register import append_frame, start_session
from app_core.maps.cartography.session import (
    AnnotationState,
    SessionData,
    load_session,
    save_session,
)
from app_core.maps.record import effective_goal, load_map


def _textured_canvas(width: int = 200, height: int = 120) -> np.ndarray:
    rng = np.random.default_rng(1)
    base = rng.integers(40, 200, size=(height, width, 3), dtype=np.uint8)
    for x in range(0, width, 17):
        base[:, x : x + 2] = (20, 220, 40)
    return base


def test_session_roundtrip(tmp_path):
    world = _textured_canvas()
    state = start_session(world[:, 0:140].copy())
    assert append_frame(state, world[:, 60:200].copy())
    annotations = AnnotationState(name="湖", goal=(10, 10), painted_cells=[(2, 3)])
    root = tmp_path / "maps" / "ab"
    root.mkdir(parents=True)
    save_session(
        root,
        SessionData(state=state, annotations=annotations, minimap_rect=(1, 2, 30, 40)),
    )
    loaded = load_session(root)
    assert loaded is not None
    assert loaded.annotations.name == "湖"
    assert loaded.annotations.goal == (10, 10)
    assert len(loaded.state.frames) == 2
    assert loaded.state.mosaic is not None


def test_export_map_record_readable(tmp_path, monkeypatch):
    monkeypatch.setenv("LCA_USER_DATA_DIR", str(tmp_path))
    mosaic = np.zeros((32, 48, 3), dtype=np.uint8)
    mosaic[:] = (30, 120, 30)
    annotations = AnnotationState(name="谷", route=[(4, 4), (20, 10)])
    record = export_to_map_record(mosaic, annotations, root=tmp_path / "maps")
    loaded = load_map(record.map_id, root=tmp_path / "maps")
    assert effective_goal(loaded) == (20, 10)
    assert loaded.name == "谷"
