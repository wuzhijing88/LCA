import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLineEdit

from ui.player.player_settings_dialog import PlayerSettingsDialog


def _qapp():
    return QApplication.instance() or QApplication([])


def test_player_settings_has_plugin_fields():
    text = Path("ui/player/player_settings_dialog.py").read_text(encoding="utf-8")
    assert "plugin_reg_code" in text
    assert "plugin_dir" in text
    assert "tools/plugin" in text
    assert "PluginHost.exe" in text
    assert "dm.dll" in text
    assert "RegDll.dll" in text
    assert "tools/op" not in text
    assert "op_c_api" not in text


def test_player_settings_writes_plugin_fields_to_local_save_config(monkeypatch):
    _qapp()
    saved = {}
    monkeypatch.setattr(
        "ui.player.player_settings_dialog.load_config",
        lambda: {"screenshot_engine": "wgc", "plugin_reg_code": "old", "plugin_dir": ""},
    )

    def _save(cfg):
        saved.update(cfg)

    monkeypatch.setattr("ui.player.player_settings_dialog.save_config", _save)
    dlg = PlayerSettingsDialog(ui={"start_hotkey": "F6"}, state={})
    assert dlg.plugin_reg_code_edit.echoMode() == QLineEdit.EchoMode.Password
    dlg.plugin_reg_code_edit.setText("local-code")
    dlg.plugin_dir_edit.setText(r"D:\tools\plugin")
    payload = dlg.settings_payload()
    assert "plugin_reg_code" not in payload
    assert "plugin_dir" not in payload
    dlg.accept()
    assert saved["plugin_reg_code"] == "local-code"
    assert saved["plugin_dir"] == r"D:\tools\plugin"
    assert saved["screenshot_engine"] == "wgc"
    dlg.close()

