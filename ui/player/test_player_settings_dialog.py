import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ui.player.player_settings_dialog import PlayerSettingsDialog


def _qapp():
    return QApplication.instance() or QApplication([])


def test_settings_dialog_result_state_roundtrip():
    _qapp()
    ui = {
        "list_order": ["L1", "L2"],
        "widgets": [
            {
                "id": "L1",
                "type": "script_list",
                "title": "日常",
                "items": [{"id": "a", "title": "A"}, {"id": "b", "title": "B"}],
            },
            {
                "id": "L2",
                "type": "script_list",
                "title": "刷图",
                "items": [{"id": "c", "title": "C"}],
            },
        ],
        "window": {"width": 480, "height": 360},
    }
    dlg = PlayerSettingsDialog(ui=ui, state={})
    assert dlg._list_order.count() == 2
    state = dlg.result_state()
    assert state["list_order"] == ["L1", "L2"]
    assert state["window_width"] >= 240
    assert "start_hotkey" in dlg.settings_payload()
    dlg.close()
