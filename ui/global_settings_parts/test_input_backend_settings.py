import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ui.global_settings_parts.global_settings_dialog import GlobalSettingsDialog


def _qapp():
    return QApplication.instance() or QApplication([])


def test_native_and_plugin_mode_tabs_split_controls():
    source = Path("ui/global_settings_parts/global_settings_dialog_tabs_mixin.py").read_text(
        encoding="utf-8"
    )
    assert 'addTab(self.exec_tab, "原生模式")' in source
    assert '"插件模式"' in source
    assert "plugin_input_enable_check" in source
    assert "plugin_screenshot_enable_check" in source
    assert "QScrollArea" in source


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
    dialog.plugin_input_enable_check.setChecked(True)
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
    assert settings["screenshot_engine"] == "wgc"
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
    assert dialog.plugin_screenshot_enable_check.isChecked()
    engines = [
        dialog.plugin_screenshot_engine_combo.itemData(i)
        for i in range(dialog.plugin_screenshot_engine_combo.count())
    ]
    assert "plugin.gdi" in engines
    labels = [
        dialog.plugin_screenshot_engine_combo.itemText(i)
        for i in range(dialog.plugin_screenshot_engine_combo.count())
    ]
    assert "GDI" in labels
    native_engines = [
        dialog.screenshot_engine_combo.itemData(i)
        for i in range(dialog.screenshot_engine_combo.count())
    ]
    assert "plugin.gdi" not in native_engines
    assert "wgc" in native_engines
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
    assert dialog.plugin_bind_mode_combo.isHidden()
    dialog.plugin_advanced_toggle.setChecked(True)
    assert not dialog.plugin_bind_mode_combo.isHidden()

    assert dialog.plugin_input_enable_check.isChecked()
    assert not dialog.plugin_input_panel.isHidden()
    assert dialog.plugin_input_display_follow_check.isChecked()
    assert dialog.plugin_input_display_row.isHidden()
    assert dialog.plugin_input_display_combo.currentData() == "normal"

    dialog.plugin_screenshot_enable_check.setChecked(True)
    assert not dialog.plugin_screenshot_panel.isHidden()
    engine_index = dialog.plugin_screenshot_engine_combo.findData("gdi2")
    assert engine_index >= 0
    dialog.plugin_screenshot_engine_combo.setCurrentIndex(engine_index)
    dialog._sync_plugin_input_display_follow()
    assert dialog.plugin_input_display_combo.currentData() == "gdi2"

    settings = dialog.get_settings()
    assert settings["plugin_input_display_follow"] is True
    assert settings["plugin_input_display"] == "gdi2"
    assert settings["screenshot_engine"] == "gdi2"
    dialog.close()


def test_plugin_mode_hides_details_when_disabled():
    _qapp()
    dialog = GlobalSettingsDialog(
        {
            "execution_mode": "background_sendmessage",
            "screenshot_engine": "wgc",
            "input_backend": "native",
            "bound_windows": [],
        }
    )
    assert not dialog.plugin_input_enable_check.isChecked()
    assert dialog.plugin_input_panel.isHidden()
    assert not dialog.plugin_screenshot_enable_check.isChecked()
    assert dialog.plugin_screenshot_panel.isHidden()

    dialog.plugin_input_enable_check.setChecked(True)
    assert not dialog.plugin_input_panel.isHidden()
    dialog.plugin_screenshot_enable_check.setChecked(True)
    assert not dialog.plugin_screenshot_panel.isHidden()
    dialog.close()


def test_settings_dialog_default_height_is_compact():
    _qapp()
    dialog = GlobalSettingsDialog(
        {
            "execution_mode": "background_sendmessage",
            "screenshot_engine": "wgc",
            "bound_windows": [],
        }
    )
    assert dialog.maximumHeight() <= 640
    assert dialog.height() <= 520
    dialog.close()


def test_native_input_merged_into_execution_group():
    _qapp()
    dialog = GlobalSettingsDialog(
        {
            "execution_mode": "background_sendmessage",
            "screenshot_engine": "wgc",
            "bound_windows": [],
        }
    )
    assert dialog.exec_mode_group.isAncestorOf(dialog.native_input_panel)
    assert dialog.native_input_panel.isHidden()
    mode_index = dialog.mode_combo.findData("foreground_driver")
    assert mode_index >= 0
    dialog.mode_combo.setCurrentIndex(mode_index)
    dialog._update_input_backend_visibility()
    assert not dialog.native_input_panel.isHidden()
    dialog.close()
