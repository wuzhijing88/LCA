import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog, QLineEdit

from ui.player.player_settings_dialog import PlayerSettingsDialog
from ui.player.player_window import PlayerWindow


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


def test_player_window_refreshes_plugin_config_after_settings(monkeypatch):
    _qapp()
    runtime_updates = []
    host_kills = []

    class _FakeRuntime:
        def update_config(self, config):
            runtime_updates.append(dict(config))

    class _FakeDialog:
        def exec(self):
            return QDialog.DialogCode.Accepted

        def settings_payload(self):
            return {
                "start_hotkey": "F6",
                "stop_hotkey": "F7",
                "pause_hotkey": "F8",
                "auto_start": False,
                "exit_on_finish": False,
                "notify_on_finish": True,
            }

    monkeypatch.setattr(
        "ui.player.player_window.PlayerSettingsDialog",
        lambda *args, **kwargs: _FakeDialog(),
    )
    monkeypatch.setattr(
        "app_core.config_store.load_config",
        lambda: {
            "plugin_reg_code": "fresh-code",
            "plugin_dir": r"D:\fresh\plugin",
        },
    )
    monkeypatch.setattr(
        "utils.plugin.runtime.terminate_plugin_host",
        lambda: host_kills.append(True),
    )

    window = type("_StubWindow", (), {})()
    window._config = {"plugin_reg_code": "stale", "plugin_dir": ""}
    window.config = window._config
    window._runtime = _FakeRuntime()
    window._ui = {}
    window._ui_state = {}
    window._exit_on_finish = False
    window._notify_on_finish = True
    window._persist_ui_state = lambda: None
    window._install_hotkeys = lambda: None
    window._append_log = lambda *args, **kwargs: None
    window._refresh_local_plugin_config = PlayerWindow._refresh_local_plugin_config.__get__(
        window, PlayerWindow
    )
    window.open_settings_dialog = PlayerWindow.open_settings_dialog.__get__(window, PlayerWindow)

    window.open_settings_dialog()

    assert window._config["plugin_reg_code"] == "fresh-code"
    assert window._config["plugin_dir"] == r"D:\fresh\plugin"
    assert runtime_updates[-1]["plugin_reg_code"] == "fresh-code"
    assert runtime_updates[-1]["plugin_dir"] == r"D:\fresh\plugin"
    assert host_kills == [True]

