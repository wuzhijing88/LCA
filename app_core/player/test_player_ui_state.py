from pathlib import Path

from app_core.player.player_ui_state import (
    extract_settings_from_ui,
    load_player_ui_state,
    merge_settings_into_ui,
    save_player_ui_state,
)


def test_save_and_load_player_ui_state(tmp_path: Path):
    save_player_ui_state(
        tmp_path,
        {
            "group_loops": 3,
            "loops_by_id": {"a": 2, "b": 0},
            "settings": {"auto_start": True, "notify_on_finish": False},
            "list_order": ["L2", "L1"],
            "list_order_mode": "random",
            "list_item_order": {"L1": ["b", "a"]},
            "list_order_modes": {"L1": "random"},
            "window_width": 520,
            "window_height": 400,
        },
    )
    state = load_player_ui_state(tmp_path)
    assert state["group_loops"] == 3
    assert state["loops_by_id"]["a"] == 2
    assert state["loops_by_id"]["b"] == 1
    assert state["settings"]["auto_start"] is True
    assert state["settings"]["notify_on_finish"] is False
    assert state["list_order"] == ["L2", "L1"]
    assert state["list_order_mode"] == "random"
    assert state["list_item_order"]["L1"] == ["b", "a"]
    assert state["list_order_modes"]["L1"] == "random"
    assert state["window_width"] == 520
    assert state["window_height"] == 400


def test_merge_settings_into_ui():
    ui = merge_settings_into_ui(
        {"title": "演示", "auto_start": False, "start_hotkey": "F6"},
        {"auto_start": True, "start_hotkey": "F7", "notify_on_finish": False},
    )
    assert ui["auto_start"] is True
    assert ui["start_hotkey"] == "F7"
    assert ui["notify_on_finish"] is False
    assert ui["title"] == "演示"


def test_extract_settings_from_ui_defaults_notify():
    settings = extract_settings_from_ui({"auto_start": True})
    assert settings["auto_start"] is True
    assert settings["notify_on_finish"] is True
