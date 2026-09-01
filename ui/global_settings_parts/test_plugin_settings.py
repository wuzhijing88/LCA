import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLineEdit, QSizePolicy

from ui.global_settings_parts.global_settings_dialog import GlobalSettingsDialog
from ui.global_settings_parts.global_settings_dialog_tabs_mixin import GlobalSettingsDialogTabsMixin


def _qapp():
    return QApplication.instance() or QApplication([])


def test_plugin_tooltip_mentions_plugin_dir_not_op():
    source = open("ui/global_settings_parts/global_settings_dialog_tabs_mixin.py", encoding="utf-8").read()
    assert "tools/plugin" in source
    assert "PluginHost.exe" in source
    assert "dm.dll" in source
    assert "RegDll.dll" in source
    assert ("tools/" + "op") not in source
    assert ("op_" + "c_api") not in source
    _ = GlobalSettingsDialogTabsMixin


def test_get_settings_includes_plugin_fields():
    _qapp()
    dialog = GlobalSettingsDialog(
        {
            "execution_mode": "background_sendmessage",
            "screenshot_engine": "wgc",
            "plugin_reg_code": "secret-code",
            "plugin_dir": r"C:\tools\plugin",
            "bound_windows": [],
        }
    )
    assert dialog.plugin_reg_code_edit.echoMode() == QLineEdit.EchoMode.Password
    assert dialog.plugin_reg_code_edit.text() == "secret-code"
    assert dialog.plugin_dir_edit.text() == r"C:\tools\plugin"
    settings = dialog.get_settings()
    assert settings["plugin_reg_code"] == "secret-code"
    assert settings["plugin_dir"] == r"C:\tools\plugin"
    dialog.close()


def test_plugin_auth_lives_on_plugin_mode_tab_not_native_tab():
    _qapp()
    dialog = GlobalSettingsDialog(
        {
            "execution_mode": "background_sendmessage",
            "screenshot_engine": "wgc",
            "bound_windows": [],
        }
    )
    tab_titles = [dialog.tab_widget.tabText(i) for i in range(dialog.tab_widget.count())]
    assert "插件模式" in tab_titles
    assert "原生模式" in tab_titles
    assert "执行模式" not in tab_titles
    plugin_index = tab_titles.index("插件模式")
    native_index = tab_titles.index("原生模式")
    plugin_tab = dialog.tab_widget.widget(plugin_index)
    native_tab = dialog.tab_widget.widget(native_index)
    assert plugin_tab.isAncestorOf(dialog.plugin_reg_code_edit)
    assert not native_tab.isAncestorOf(dialog.plugin_reg_code_edit)
    assert plugin_tab.isAncestorOf(dialog.plugin_mouse_combo)
    assert not native_tab.isAncestorOf(dialog.plugin_mouse_combo)
    # 绑定图显下拉必须可拉满宽度，避免「显示不全」
    dialog.plugin_input_enable_check.setChecked(True)
    dialog.plugin_input_display_follow_check.setChecked(False)
    assert (
        dialog.plugin_input_display_combo.sizePolicy().horizontalPolicy()
        == QSizePolicy.Policy.Expanding
    )
    dialog.close()
