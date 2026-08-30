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


def test_list_map_options_uses_library(tmp_path, monkeypatch):
    import numpy as np
    from app_core.maps.record import create_map, format_map_option
    from tasks.astar_pathfind import list_map_options

    monkeypatch.setenv("LCA_USER_DATA_DIR", str(tmp_path))
    record = create_map("谷", np.zeros((8, 8, 3), dtype=np.uint8), goal=(1, 1), root=tmp_path / "maps")
    # list_map_options 应读 get_maps_dir；若测试用 root 注入，给 list_map_options 加 optional root 仅用于测试不导出
    labels = list_map_options(root=tmp_path / "maps")
    assert format_map_option(record.map_id, "谷") in labels


def test_validate_card_params_allows_empty_death(tmp_path, monkeypatch):
    from app_core.maps.record import create_map, format_map_option

    monkeypatch.setenv("LCA_USER_DATA_DIR", str(tmp_path))
    record = create_map(
        "谷",
        np.zeros((8, 8, 3), dtype=np.uint8),
        goal=(1, 1),
        root=tmp_path / "maps",
    )
    error = validate_card_params(
        {
            "map_option": format_map_option(record.map_id, "谷"),
            "death_image_paths": "",
            "marker_type": "圆点",
        }
    )
    assert error is None
    assert "死亡状态图（可选）" in get_params_definition()["death_image_paths"]["label"]


def test_open_map_stitcher_passes_minimap_and_hwnd(monkeypatch):
    captured = {}

    def fake_open(parent, map_id, *, minimap_rect, target_hwnd):
        captured["map_id"] = map_id
        captured["minimap_rect"] = minimap_rect
        captured["target_hwnd"] = target_hwnd
        return "名 — id"

    monkeypatch.setattr("ui.maps.stitcher_dialog.open_stitcher_dialog", fake_open)
    from tasks.astar_pathfind import open_map_stitcher

    result = open_map_stitcher(
        {
            "map_option": "谷 — ab12",
            "minimap_x": 3,
            "minimap_y": 4,
            "minimap_width": 50,
            "minimap_height": 60,
        },
        target_hwnd=99,
    )
    assert result == "名 — id"
    assert captured["map_id"] == "ab12"
    assert captured["minimap_rect"] == (3, 4, 50, 60)
    assert captured["target_hwnd"] == 99


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
