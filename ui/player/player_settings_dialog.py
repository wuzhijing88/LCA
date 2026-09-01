# -*- coding: utf-8 -*-
"""播放器设置：热键与运行相关开关。"""

from __future__ import annotations

from typing import Any, Dict, Optional

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app_core.config_store import load_config, save_config
from app_core.hotkey_spec import display_hotkey, normalize_hotkey
from app_core.player.player_ui_state import extract_settings_from_ui

PLUGIN_LOCAL_HINT = (
    "插件：正常 / GDI2（无需挂钩）；DX / OpenGL（需注入）。"
    "需要 tools/plugin 下 PluginHost.exe、dm.dll、RegDll.dll"
)


class PlayerSettingsDialog(QDialog):
    def __init__(
        self,
        parent=None,
        *,
        ui: Optional[dict] = None,
        state: Optional[dict] = None,
        on_bind=None,
    ):
        super().__init__(parent)
        self.setObjectName("PlayerSettingsDialog")
        self.setWindowTitle("设置")
        self.setModal(True)
        self.resize(420, 360)
        self._ui = dict(ui or {})
        seed = extract_settings_from_ui(self._ui)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)
        hint = QLabel("热键与运行选项保存在本机 userdata。插件注册码与目录只写入本机配置，不会进入导出包。")
        hint.setWordWrap(True)
        hint.setToolTip(PLUGIN_LOCAL_HINT)
        root.addWidget(hint)
        root.addWidget(self._build_hotkey_page(seed))
        root.addWidget(self._build_plugin_group(), 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _build_hotkey_page(self, seed: dict) -> QWidget:
        page = QWidget(self)
        form = QFormLayout(page)
        form.setSpacing(8)
        self._start_hotkey = QLineEdit(display_hotkey(seed.get("start_hotkey")))
        self._stop_hotkey = QLineEdit(display_hotkey(seed.get("stop_hotkey")))
        self._pause_hotkey = QLineEdit(display_hotkey(seed.get("pause_hotkey")))
        for edit, tip in (
            (self._start_hotkey, "开始任务热键"),
            (self._stop_hotkey, "停止任务热键"),
            (self._pause_hotkey, "暂停/继续热键"),
        ):
            edit.setPlaceholderText("例如 F6")
            edit.setToolTip(tip)
        form.addRow("开始热键", self._start_hotkey)
        form.addRow("停止热键", self._stop_hotkey)
        form.addRow("暂停热键", self._pause_hotkey)
        self._auto_start = QCheckBox("打开后自动执行")
        self._auto_start.setChecked(bool(seed.get("auto_start")))
        self._exit_on_finish = QCheckBox("结束后退出程序")
        self._exit_on_finish.setChecked(bool(seed.get("exit_on_finish")))
        self._notify_on_finish = QCheckBox("完成后系统/托盘通知")
        self._notify_on_finish.setChecked(bool(seed.get("notify_on_finish", True)))
        form.addRow("", self._auto_start)
        form.addRow("", self._exit_on_finish)
        form.addRow("", self._notify_on_finish)
        return page

    def _build_plugin_group(self) -> QGroupBox:
        group = QGroupBox("插件", self)
        form = QFormLayout(group)
        form.setSpacing(8)
        local_cfg = {}
        try:
            loaded = load_config()
            if isinstance(loaded, dict):
                local_cfg = loaded
        except Exception:
            local_cfg = {}
        plugin_hint = QLabel(PLUGIN_LOCAL_HINT)
        plugin_hint.setWordWrap(True)
        plugin_hint.setToolTip(PLUGIN_LOCAL_HINT)
        form.addRow(plugin_hint)
        self.plugin_reg_code_edit = QLineEdit(str(local_cfg.get("plugin_reg_code", "") or ""))
        self.plugin_reg_code_edit.setObjectName("plugin_reg_code_edit")
        self.plugin_reg_code_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.plugin_reg_code_edit.setToolTip(PLUGIN_LOCAL_HINT)
        self.plugin_dir_edit = QLineEdit(str(local_cfg.get("plugin_dir", "") or "").strip())
        self.plugin_dir_edit.setObjectName("plugin_dir_edit")
        self.plugin_dir_edit.setToolTip(PLUGIN_LOCAL_HINT)
        browse = QPushButton("浏览")
        browse.clicked.connect(self._browse_plugin_dir)
        dir_row = QWidget(group)
        dir_layout = QHBoxLayout(dir_row)
        dir_layout.setContentsMargins(0, 0, 0, 0)
        dir_layout.addWidget(self.plugin_dir_edit)
        dir_layout.addWidget(browse)
        form.addRow("插件注册码:", self.plugin_reg_code_edit)
        form.addRow("插件目录:", dir_row)
        return group

    def _browse_plugin_dir(self):
        start = self.plugin_dir_edit.text().strip() if hasattr(self, "plugin_dir_edit") else ""
        chosen = QFileDialog.getExistingDirectory(self, "选择插件目录", start)
        if chosen:
            self.plugin_dir_edit.setText(chosen)

    def accept(self) -> None:
        try:
            config = dict(load_config() or {})
            config["plugin_reg_code"] = self.plugin_reg_code_edit.text()
            config["plugin_dir"] = self.plugin_dir_edit.text().strip()
            save_config(config)
        except Exception as exc:
            QMessageBox.warning(self, "保存失败", f"插件本机设置没有保存：{exc}")
            return
        super().accept()

    def settings_payload(self) -> Dict[str, Any]:
        def _hotkey(edit: QLineEdit) -> str:
            spec = normalize_hotkey(edit.text())
            return spec or str(edit.text() or "").strip()

        return {
            "start_hotkey": _hotkey(self._start_hotkey),
            "stop_hotkey": _hotkey(self._stop_hotkey),
            "pause_hotkey": _hotkey(self._pause_hotkey),
            "auto_start": self._auto_start.isChecked(),
            "exit_on_finish": self._exit_on_finish.isChecked(),
            "notify_on_finish": self._notify_on_finish.isChecked(),
        }

    def result_state(self) -> Dict[str, Any]:
        return {}
