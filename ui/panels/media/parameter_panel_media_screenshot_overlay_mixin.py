from ..parameter_panel_support import *


class ParameterPanelMediaScreenshotOverlayMixin:

    def _resolve_screenshot_save_dir(self) -> str:
        images_dir = str(getattr(self, "images_dir", "") or "").strip()
        return images_dir or "images"

    def _load_screenshot_format(self):
        screenshot_format = 'bmp'
        try:
            from app_core.config_store import load_config

            config = load_config()
            screenshot_format = config.get('screenshot_format', 'bmp')
        except Exception as exc:
            logger.warning(f"加载截图格式失败，已回退到 BMP: {exc}")
        return screenshot_format

    def _create_screenshot_overlay(self, target_hwnd):
        from ...selectors.screenshot_tool import ScreenshotOverlay

        return ScreenshotOverlay(
            target_hwnd=target_hwnd,
            save_dir=self._resolve_screenshot_save_dir(),
            parent=None,
            screenshot_format=self._load_screenshot_format(),
            card_id=self.current_card_id,
            workflow_id=self._get_active_workflow_file_token(),
        )

    def _connect_screenshot_overlay_signals(self):
        self._screenshot_overlay.screenshot_taken.connect(self._on_screenshot_path_ready)
        self._screenshot_overlay.screenshot_cancelled.connect(self._on_screenshot_cancelled)

    def _start_screenshot_delayed(self, line_edit: QLineEdit, hwnd=None):
        try:
            self._current_screenshot_target = line_edit
            target_hwnd = hwnd if hwnd is not None else self.target_window_hwnd
            self._screenshot_overlay = self._create_screenshot_overlay(target_hwnd)
            self._connect_screenshot_overlay_signals()
            if self._screenshot_overlay.capture_and_show():
                return

            logger.error('显示截图覆盖层失败')
            self._screenshot_overlay = None
            self._restore_windows_after_screenshot()
            logger.info('截图覆盖层显示失败后已恢复窗口')
        except Exception as exc:
            from PySide6.QtWidgets import QMessageBox

            logger.error(f"启动延迟截图工具失败: {exc}", exc_info=True)
            self._restore_windows_after_screenshot()
            QMessageBox.critical(self, "错误", f"启动截图工具失败: {str(exc)}")
