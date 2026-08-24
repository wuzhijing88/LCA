from ..parameter_panel_support import *


class ParameterPanelMediaScreenshotStartMixin:

    def _resolve_validated_screenshot_hwnd(self):
        validated_hwnd = self.target_window_hwnd
        if not self.target_window_hwnd or not self.main_window:
            return validated_hwnd
        if self.main_window.is_hwnd_bound(self.target_window_hwnd):
            return validated_hwnd

        logger.warning(
            f"当前 hwnd 已不再绑定，尝试回退: {self.target_window_hwnd}"
        )
        validated_hwnd, _ = self.main_window.validate_hwnd_or_get_first(self.target_window_hwnd)
        return validated_hwnd

    def _warn_no_available_screenshot_window(self):
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.warning(
            self,
            "警告",
            "没有可用的绑定窗口。\n\n"
            "请先在全局设置中绑定窗口后再使用截图工具。",
        )

    def _hide_windows_before_screenshot(self):
        self.hide()
        if hasattr(self, 'main_window') and self.main_window:
            self.main_window.hide()
            logger.debug('截图前已隐藏主窗口和参数面板')

    def _schedule_screenshot_overlay_start(self, line_edit: QLineEdit, hwnd):
        from PySide6.QtCore import QTimer

        QTimer.singleShot(
            200,
            lambda edit=line_edit, target_hwnd=hwnd: self._start_screenshot_delayed(edit, target_hwnd),
        )

    def _start_screenshot_for_param(self, line_edit: QLineEdit):
        try:
            logger.info(f"启动截图工具, hwnd={self.target_window_hwnd}")
            validated_hwnd = self._resolve_validated_screenshot_hwnd()
            if not validated_hwnd:
                self._warn_no_available_screenshot_window()
                return

            self._hide_windows_before_screenshot()
            self._schedule_screenshot_overlay_start(line_edit, validated_hwnd)
        except Exception as exc:
            from PySide6.QtWidgets import QMessageBox

            logger.error(f"启动截图工具失败: {exc}", exc_info=True)
            QMessageBox.critical(self, "错误", f"启动截图工具失败: {str(exc)}")
