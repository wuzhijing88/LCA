from PySide6.QtCore import QTimer


class GlobalSettingsDialogVisibilityMixin:
    def _adjust_dialog_height_only(self):
        """切换执行模式时只改高度，不要按各页 sizeHint 把对话框拉宽。"""
        if not self.isVisible():
            return
        width = self.width()
        self.adjustSize()
        self.resize(width, min(max(self.height(), self.minimumHeight()), self.maximumHeight()))

    def _on_execution_driver_setting_changed(self, *_args):
        self._update_input_backend_visibility(resize_dialog=True)

    def _on_input_backend_changed(self, *_args):
        self._update_input_backend_visibility(resize_dialog=True)

    def _selected_input_backend(self) -> str:
        if hasattr(self, "plugin_input_enable_check"):
            return "plugin" if self.plugin_input_enable_check.isChecked() else "native"
        return "native"

    def _update_foreground_driver_visibility(self, *args, resize_dialog: bool = False):
        self._update_input_backend_visibility(resize_dialog=resize_dialog)

    def _update_input_backend_visibility(self, *args, resize_dialog: bool = False):
        """原生模式页：键鼠控件已并入执行模式分组，仅前台模式显示。"""
        if hasattr(self, "_update_plugin_mode_panels"):
            self._update_plugin_mode_panels()

        internal_mode = self.mode_combo.currentData()
        if not internal_mode:
            internal_mode = self.MODE_INTERNAL_MAP.get(self.mode_combo.currentText(), "")

        use_foreground_driver = internal_mode == "foreground_driver"
        use_foreground_py = internal_mode == "foreground_py"
        if hasattr(self, "foreground_driver_widget"):
            self.foreground_driver_widget.setVisible(use_foreground_driver)
        if hasattr(self, "foreground_keyboard_driver_widget"):
            self.foreground_keyboard_driver_widget.setVisible(use_foreground_driver)
        if hasattr(self, "foreground_py_backend_widget"):
            self.foreground_py_backend_widget.setVisible(use_foreground_py)

        mouse_backend = (
            self.foreground_driver_combo.currentData()
            if hasattr(self, "foreground_driver_combo")
            else ""
        )
        keyboard_backend = (
            self.foreground_keyboard_driver_combo.currentData()
            if hasattr(self, "foreground_keyboard_driver_combo")
            else ""
        )
        use_ib_driver = "ibinputsimulator" in {
            str(mouse_backend or "").strip().lower(),
            str(keyboard_backend or "").strip().lower(),
        }
        if hasattr(self, "ib_driver_widget"):
            self.ib_driver_widget.setVisible(use_foreground_driver and use_ib_driver)
        if hasattr(self, "ib_driver_combo"):
            self.ib_driver_combo.setEnabled(use_foreground_driver and use_ib_driver)

        if hasattr(self, "native_input_panel"):
            self.native_input_panel.setVisible(use_foreground_driver or use_foreground_py)

        if resize_dialog and self.isVisible():
            QTimer.singleShot(0, self._adjust_dialog_height_only)

    def _update_execution_mode_visibility(self):
        if hasattr(self, "exec_mode_group"):
            self.exec_mode_group.setVisible(True)
        if hasattr(self, "screenshot_engine_group"):
            self.screenshot_engine_group.setVisible(True)
        if hasattr(self, "_update_screenshot_engine_visibility"):
            self._update_screenshot_engine_visibility()
        self._update_input_backend_visibility()
