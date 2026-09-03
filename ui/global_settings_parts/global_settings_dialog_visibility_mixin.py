from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QScrollArea


class GlobalSettingsDialogVisibilityMixin:
    # 与对话框默认打开高度对齐；插件模式不再强行抬高，只按滚动溢出补差
    _DIALOG_HEIGHT_FLOOR = 460

    def _adjust_dialog_height_only(self):
        """切换执行模式时只改高度：先回到紧凑基准，再按滚动溢出少量补高。"""
        if not self.isVisible():
            return
        width = self.width()
        # 先压回默认高度，避免插件保底过高留下大块空白
        self.resize(
            width,
            min(max(self._DIALOG_HEIGHT_FLOOR, self.minimumHeight()), self.maximumHeight()),
        )
        # 下一拍若仍有纵向溢出，再按溢出量补高
        QTimer.singleShot(0, self._grow_dialog_to_clear_exec_scrollbar)

    def _grow_dialog_to_clear_exec_scrollbar(self) -> None:
        """若执行模式页仍有纵向滚动溢出，按溢出量再拉高（受 maxHeight 限制）。"""
        if not self.isVisible():
            return
        scroll = getattr(self, "exec_tab", None)
        if not isinstance(scroll, QScrollArea):
            return
        vbar = scroll.verticalScrollBar()
        if vbar is None:
            return
        overflow = int(vbar.maximum())
        if overflow <= 0:
            return
        width = self.width()
        self.resize(
            width,
            min(
                max(self.height() + overflow + 12, self.minimumHeight()),
                self.maximumHeight(),
            ),
        )

    def _on_execution_driver_setting_changed(self, *_args):
        self._update_input_backend_visibility(resize_dialog=True)

    def _on_input_backend_changed(self, *_args):
        self._update_input_backend_visibility(resize_dialog=True)

    def _selected_input_backend(self) -> str:
        if hasattr(self, "runtime_backend_combo"):
            selected = str(self.runtime_backend_combo.currentData() or "").strip().lower()
            return "plugin" if selected == "plugin" else "native"
        return "native"

    def _update_foreground_driver_visibility(self, *args, resize_dialog: bool = False):
        self._update_input_backend_visibility(resize_dialog=resize_dialog)

    def _update_input_backend_visibility(self, *args, resize_dialog: bool = False):
        """按运行后端切换原生/插件面板；原生前台时再显示驱动选项。"""
        if hasattr(self, "_update_runtime_backend_panels"):
            self._update_runtime_backend_panels(resize_dialog=False)

        use_native = self._selected_input_backend() == "native"
        internal_mode = self.mode_combo.currentData() if hasattr(self, "mode_combo") else ""
        if not internal_mode and hasattr(self, "mode_combo"):
            internal_mode = self.MODE_INTERNAL_MAP.get(self.mode_combo.currentText(), "")

        use_foreground_driver = use_native and internal_mode == "foreground_driver"
        use_foreground_py = use_native and internal_mode == "foreground_py"
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
