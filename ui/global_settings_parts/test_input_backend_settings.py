import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ui.global_settings_parts.global_settings_dialog import GlobalSettingsDialog


def _qapp():
    return QApplication.instance() or QApplication([])


def test_exec_mode_combo_no_longer_requires_background_dx_label():
    source = Path("ui/global_settings_parts/global_settings_dialog_tabs_mixin.py").read_text(
        encoding="utf-8"
    )
    assert "input_backend" in source or "键鼠类型" in source


def test_get_settings_includes_input_backend_and_plugin_bind_fields():
    _qapp()
    dialog = GlobalSettingsDialog(
        {
            "execution_mode": "background_sendmessage",
            "screenshot_engine": "wgc",
            "input_backend": "native",
            "plugin_mouse": "normal",
            "plugin_keypad": "normal",
            "plugin_input_display": "normal",
            "plugin_bind_mode": 0,
            "bound_windows": [],
        }
    )
    backend_index = dialog.input_backend_combo.findData("plugin")
    assert backend_index >= 0
    dialog.input_backend_combo.setCurrentIndex(backend_index)
    mouse_index = dialog.plugin_mouse_combo.findData("dx2")
    assert mouse_index >= 0
    dialog.plugin_mouse_combo.setCurrentIndex(mouse_index)
    keypad_index = dialog.plugin_keypad_combo.findData("dx")
    assert keypad_index >= 0
    dialog.plugin_keypad_combo.setCurrentIndex(keypad_index)
    dialog.plugin_input_display_follow_check.setChecked(False)
    display_index = dialog.plugin_input_display_combo.findData("plugin.gdi")
    assert display_index >= 0
    dialog.plugin_input_display_combo.setCurrentIndex(display_index)
    mode_index = dialog.plugin_bind_mode_combo.findData(101)
    assert mode_index >= 0
    dialog.plugin_bind_mode_combo.setCurrentIndex(mode_index)

    settings = dialog.get_settings()
    assert settings["input_backend"] == "plugin"
    assert settings["plugin_mouse"] == "dx2"
    assert settings["plugin_keypad"] == "dx"
    assert settings["plugin_input_display"] == "plugin.gdi"
    assert settings["plugin_input_display_follow"] is False
    assert settings["plugin_bind_mode"] == 101
    dialog.close()


def test_plugin_screenshot_list_includes_plugin_gdi():
    _qapp()
    dialog = GlobalSettingsDialog(
        {
            "execution_mode": "background_sendmessage",
            "screenshot_engine": "normal",
            "bound_windows": [],
        }
    )
    group_index = dialog.screenshot_engine_group_combo.findData("插件")
    assert group_index >= 0
    dialog.screenshot_engine_group_combo.setCurrentIndex(group_index)
    engines = [
        dialog.screenshot_engine_combo.itemData(i)
        for i in range(dialog.screenshot_engine_combo.count())
    ]
    assert "plugin.gdi" in engines
    labels = [
        dialog.screenshot_engine_combo.itemText(i)
        for i in range(dialog.screenshot_engine_combo.count())
    ]
    assert "GDI" in labels
    dialog.close()


def test_plugin_bind_mode_shows_chinese_labels_and_follow_syncs_display():
    _qapp()
    dialog = GlobalSettingsDialog(
        {
            "execution_mode": "background_sendmessage",
            "screenshot_engine": "wgc",
            "input_backend": "plugin",
            "plugin_input_display_follow": True,
            "bound_windows": [],
        }
    )
    mode_texts = [
        dialog.plugin_bind_mode_combo.itemText(i)
        for i in range(dialog.plugin_bind_mode_combo.count())
    ]
    assert any("默认" in text for text in mode_texts)
    assert dialog.plugin_advanced_panel.isHidden()
    dialog.plugin_advanced_toggle.setChecked(True)
    assert not dialog.plugin_advanced_panel.isHidden()

    assert dialog.plugin_input_display_follow_check.isChecked()
    assert not dialog.plugin_input_display_combo.isEnabled()
    assert dialog.plugin_input_display_combo.currentData() == "normal"

    group_index = dialog.screenshot_engine_group_combo.findData("插件")
    dialog.screenshot_engine_group_combo.setCurrentIndex(group_index)
    engine_index = dialog.screenshot_engine_combo.findData("gdi2")
    assert engine_index >= 0
    dialog.screenshot_engine_combo.setCurrentIndex(engine_index)
    dialog._sync_plugin_input_display_follow()
    assert dialog.plugin_input_display_combo.currentData() == "gdi2"

    settings = dialog.get_settings()
    assert settings["plugin_input_display_follow"] is True
    assert settings["plugin_input_display"] == "gdi2"
    dialog.close()
