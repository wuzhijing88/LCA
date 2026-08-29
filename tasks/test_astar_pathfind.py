import numpy as np

from tasks import get_available_tasks, get_task_module
from tasks.astar_pathfind import (
    execute_task,
    get_params_definition,
    open_map_stitcher,
    requires_input_lock,
    validate_card_params,
)


def test_task_is_registered():
    assert "A*寻路" in get_available_tasks()
    assert get_task_module("A*寻路") is not None


def test_params_include_death_and_keys():
    params = get_params_definition()
    assert "death_image_paths" in params
    assert "open_stitcher" in params
    assert params["open_stitcher"]["action"] == "open_map_stitcher"
    assert requires_input_lock({}) is True


def test_validate_card_params_requires_death():
    error = validate_card_params({"map_option": "x — x", "death_image_paths": ""})
    assert error and "死亡" in error


def test_open_map_stitcher_accepts_dispatcher_kwargs():
    from ui.maps.stitcher_dialog import _QT_AVAILABLE

    result = open_map_stitcher(
        {},
        target_hwnd=123,
        main_window=object(),
        parameter_panel=object(),
        parameter_dialog=object(),
        param_name="open_stitcher",
    )
    assert result is _QT_AVAILABLE


def test_execute_task_without_hwnd_skips_path_loop(monkeypatch, caplog):
    from tasks import astar_pathfind

    def fail_if_called(*args, **kwargs):
        raise AssertionError("run_path_loop should not be called")

    monkeypatch.setattr(astar_pathfind, "run_path_loop", fail_if_called)
    monkeypatch.setattr(astar_pathfind, "load_map", lambda map_id: object())
    monkeypatch.setattr(astar_pathfind, "validate_run", lambda *args: None)
    monkeypatch.setattr(
        astar_pathfind,
        "_load_image",
        lambda path, get_image_data=None: np.zeros((4, 4, 3), dtype=np.uint8),
    )

    params = {
        "map_option": "m — m",
        "death_image_paths": "death.png",
        "marker_type": "圆点",
    }
    with caplog.at_level("ERROR"):
        ok, _reason, _jump_id = execute_task(params, {}, target_hwnd=None)

    assert ok is False
    assert any("窗口" in record.message for record in caplog.records)
