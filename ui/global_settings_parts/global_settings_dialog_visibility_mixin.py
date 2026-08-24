from PySide6.QtCore import QTimer



class GlobalSettingsDialogVisibilityMixin:
    def _update_foreground_driver_visibility(self):
        internal_mode = self.mode_combo.currentData()
        if not internal_mode:
            internal_mode = self.MODE_INTERNAL_MAP.get(self.mode_combo.currentText(), "")

        use_foreground_driver = internal_mode == "foreground_driver"
        if hasattr(self, "foreground_driver_widget"):
            self.foreground_driver_widget.setVisible(use_foreground_driver)
        if hasattr(self, "foreground_keyboard_driver_widget"):
            self.foreground_keyboard_driver_widget.setVisible(use_foreground_driver)

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

        QTimer.singleShot(0, self.adjustSize)

    def _update_execution_mode_visibility(self):
        if hasattr(self, "exec_mode_group"):
            self.exec_mode_group.setVisible(True)
        if hasattr(self, "screenshot_engine_group"):
            self.screenshot_engine_group.setVisible(True)
        if hasattr(self, "_update_screenshot_engine_visibility"):
            self._update_screenshot_engine_visibility()
        self._update_foreground_driver_visibility()
