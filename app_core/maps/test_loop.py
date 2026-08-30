import numpy as np

from app_core.maps.keys import DEFAULT_KEYS_4
from app_core.maps.localize import LocateResult
from app_core.maps.loop import PathLoopConfig, run_path_loop, validate_run
from app_core.maps.record import CELL_BLOCKED, CELL_UNKNOWN, MapRecord


def _green_map():
    image = np.zeros((48, 48, 3), dtype=np.uint8)
    image[:] = (20, 180, 20)
    image[8:24, 8:24] = (40, 80, 200)
    walk = np.full((48, 48), CELL_UNKNOWN, dtype=np.uint8)
    painted = np.zeros((48, 48), dtype=np.uint8)
    return MapRecord("m", "m", image, walk, painted, route=[], goal=(20, 16))


def test_validate_requires_death_and_arrow():
    record = _green_map()
    assert "死亡" in (validate_run(record, [], "圆点", None) or "")
    assert "箭头" in (validate_run(record, [np.zeros((4, 4, 3), dtype=np.uint8)], "箭头", None) or "")
    assert validate_run(record, [np.zeros((4, 4, 3), dtype=np.uint8)], "圆点", None) is None


def test_death_does_not_paint_wall_or_press():
    record = _green_map()
    record.goal = (16, 16)
    death = np.full((8, 8, 3), 255, dtype=np.uint8)
    frames = {"n": 0, "keys": [], "walls": []}

    def capture_frame():
        frames["n"] += 1
        if frames["n"] <= 2:
            canvas = np.zeros((40, 40, 3), dtype=np.uint8)
            canvas[0:8, 0:8] = 255
            return canvas
        return np.zeros((40, 40, 3), dtype=np.uint8)

    def capture_minimap():
        if frames["n"] <= 2:
            return None
        return record.image_bgr[8:24, 8:24].copy()

    def hold_key(key, seconds):
        frames["keys"].append(key)
        return True

    def persist(item):
        frames["walls"].append(int((item.walkability == CELL_BLOCKED).sum()))

    config = PathLoopConfig(direction_mode="四向", key_map=DEFAULT_KEYS_4, match_fail_limit=8)
    ok, reason = run_path_loop(
        record=record,
        capture_minimap=capture_minimap,
        capture_frame=capture_frame,
        death_templates=[death],
        arrow_template=None,
        config=config,
        hold_key=hold_key,
        persist=persist,
        stop_checker=lambda: frames["n"] > 6,
    )
    assert ok is True, reason
    assert "到达" in reason
    assert frames["keys"] == []
    assert frames["walls"]
    assert frames["walls"][0] == 0


def test_death_after_key_resets_motion_baseline():
    record = _green_map()
    record.goal = (40, 40)
    death = np.full((8, 8, 3), 255, dtype=np.uint8)
    alive = np.zeros((40, 40, 3), dtype=np.uint8)
    dead = alive.copy()
    dead[0:8, 0:8] = 255
    frame_sequence = iter([alive, alive, alive, dead, dead, alive, alive])
    state = {"keys": 0, "frame_calls": 0}

    def capture_frame():
        state["frame_calls"] += 1
        return next(frame_sequence, alive)

    def hold_key(key, seconds):
        state["keys"] += 1
        return True

    saved = []
    ok, reason = run_path_loop(
        record=record,
        capture_minimap=lambda: record.image_bgr[24:40, 24:40].copy(),
        capture_frame=capture_frame,
        death_templates=[death],
        arrow_template=None,
        config=PathLoopConfig(
            direction_mode="四向",
            key_map=DEFAULT_KEYS_4,
            stuck_limit=2,
        ),
        hold_key=hold_key,
        persist=lambda item: saved.append(item.walkability.copy()),
        stop_checker=lambda: state["keys"] >= 3,
    )

    assert ok is False
    assert "卡住" not in reason
    assert state["keys"] == 3
    assert state["frame_calls"] == 7
    assert saved
    assert int((saved[-1] == CELL_BLOCKED).sum()) == 0


def test_stuck_paints_green_not_blue(monkeypatch):
    record = _green_map()
    record.goal = (40, 40)
    death = np.full((2, 2, 3), 1, dtype=np.uint8)
    frames = {"n": 0, "keys": 0}
    monkeypatch.setattr(
        "app_core.maps.loop.locate_on_map",
        lambda *args, **kwargs: LocateResult(found=True, x=28, y=30),
    )
    monkeypatch.setattr(
        "app_core.maps.loop.plan_path",
        lambda *args, **kwargs: [(28, 30), (38, 30)],
    )

    def capture_frame():
        return np.zeros((20, 20, 3), dtype=np.uint8)

    def capture_minimap():
        frames["n"] += 1
        return record.image_bgr[24:40, 24:40].copy()

    def hold_key(key, seconds):
        frames["keys"] += 1
        return True

    walls = []

    def persist(item):
        walls.append(item.walkability.copy())

    ok, reason = run_path_loop(
        record=record,
        capture_minimap=capture_minimap,
        capture_frame=capture_frame,
        death_templates=[death],
        arrow_template=None,
        config=PathLoopConfig(direction_mode="四向", key_map=DEFAULT_KEYS_4, stuck_limit=3),
        hold_key=hold_key,
        persist=lambda item: walls.append(item.walkability.copy()),
        stop_checker=lambda: frames["keys"] > 3,
    )
    assert ok is False
    assert "卡住超限" in reason
    assert frames["keys"] == 4
    assert walls
    last = walls[-1]
    assert int(last[30, 30]) == CELL_BLOCKED
    assert int(last[12, 12]) == CELL_UNKNOWN


def test_stop_persists():
    record = _green_map()
    saved = {"n": 0}

    def persist(item):
        saved["n"] += 1

    ok, reason = run_path_loop(
        record=record,
        capture_minimap=lambda: record.image_bgr[8:24, 8:24].copy(),
        capture_frame=lambda: np.zeros((20, 20, 3), dtype=np.uint8),
        death_templates=[np.zeros((2, 2, 3), dtype=np.uint8)],
        arrow_template=None,
        config=PathLoopConfig(),
        hold_key=lambda key, seconds: True,
        persist=persist,
        stop_checker=lambda: True,
    )
    assert ok is False
    assert "停止" in reason
    assert saved["n"] == 1


def test_route_progress_never_rejoins_completed_loop_segment(monkeypatch):
    record = _green_map()
    record.route = [(8, 8), (24, 8), (24, 24), (8, 24), (8, 8), (40, 8)]
    record.goal = None
    positions = iter([(24, 24), (8, 8)])
    progress_calls = []
    key_calls = []

    monkeypatch.setattr(
        "app_core.maps.loop.locate_on_map",
        lambda *args, **kwargs: LocateResult(found=True, x=(point := next(positions))[0], y=point[1]),
    )

    def fake_plan(_record, position, **kwargs):
        progress_calls.append(kwargs["route_progress"])
        return [position, (position[0] + 1, position[1])]

    monkeypatch.setattr("app_core.maps.loop.plan_path", fake_plan)

    ok, reason = run_path_loop(
        record=record,
        capture_minimap=lambda: np.zeros((4, 4, 3), dtype=np.uint8),
        capture_frame=lambda: np.zeros((8, 8, 3), dtype=np.uint8),
        death_templates=[np.full((2, 2, 3), 255, dtype=np.uint8)],
        arrow_template=None,
        config=PathLoopConfig(
            direction_mode="四向",
            key_map=DEFAULT_KEYS_4,
            cell_size=1,
            arrive_px=1,
        ),
        hold_key=lambda key, seconds: key_calls.append(key) is None,
        persist=lambda item: None,
        stop_checker=lambda: len(key_calls) >= 2,
    )

    assert ok is False
    assert "停止" in reason
    assert progress_calls == [2, 4]


def test_death_keeps_unfinished_route_progress(monkeypatch):
    record = _green_map()
    record.route = [(8, 8), (24, 8), (24, 24), (8, 24), (8, 8), (40, 8)]
    record.goal = None
    positions = iter([(24, 24), (8, 8)])
    progress_calls = []
    frame_calls = {"count": 0}
    key_calls = []
    alive = np.zeros((8, 8, 3), dtype=np.uint8)
    dead = np.full((8, 8, 3), 255, dtype=np.uint8)

    monkeypatch.setattr(
        "app_core.maps.loop.locate_on_map",
        lambda *args, **kwargs: LocateResult(found=True, x=(point := next(positions))[0], y=point[1]),
    )

    def fake_plan(_record, position, **kwargs):
        progress_calls.append(kwargs["route_progress"])
        return [position, (position[0] + 1, position[1])]

    def capture_frame():
        frame_calls["count"] += 1
        return dead if frame_calls["count"] == 2 else alive

    monkeypatch.setattr("app_core.maps.loop.plan_path", fake_plan)

    ok, reason = run_path_loop(
        record=record,
        capture_minimap=lambda: np.zeros((4, 4, 3), dtype=np.uint8),
        capture_frame=capture_frame,
        death_templates=[np.full((2, 2, 3), 255, dtype=np.uint8)],
        arrow_template=None,
        config=PathLoopConfig(
            direction_mode="四向",
            key_map=DEFAULT_KEYS_4,
            cell_size=1,
            arrive_px=1,
        ),
        hold_key=lambda key, seconds: key_calls.append(key) is None,
        persist=lambda item: None,
        stop_checker=lambda: len(key_calls) >= 2,
    )

    assert ok is False
    assert "停止" in reason
    assert progress_calls == [2, 4]
