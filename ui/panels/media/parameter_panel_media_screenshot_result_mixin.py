from ..parameter_panel_support import *
from utils.window_activation_utils import show_and_activate_overlay, show_and_raise_widget


class ParameterPanelMediaScreenshotResultMixin:

    def _invalidate_screenshot_template_cache(self, filepath: str):
        try:
            from utils.template_preloader import get_global_preloader

            get_global_preloader().invalidate_template(filepath)
        except Exception as exc:
            logger.debug(f"使截图模板缓存失效失败: {exc}")

    def _refresh_screenshot_preview(self, filepath: str, target_input):
        try:
            preview_key = target_input.property('preview_key')
            if not preview_key or preview_key not in self.widgets:
                return
            preview_label = self.widgets[preview_key]
            if isinstance(preview_label, QLabel):
                self._update_image_preview(filepath, preview_label)
        except Exception as exc:
            logger.warning(f"刷新截图预览失败: {exc}")

    def _clear_screenshot_runtime_state(self):
        self._current_screenshot_target = None
        self._screenshot_overlay = None

    def _on_screenshot_path_ready(self, filepath: str):
        try:
            if hasattr(self, '_current_screenshot_target') and self._current_screenshot_target:
                target_input = self._current_screenshot_target
                param_name = self._get_registered_widget_name(target_input)
                normalized_path = self._normalize_single_image_parameter_value(param_name, filepath)
                target_input.setText(normalized_path)
                logger.info(f"截图路径已就绪: {normalized_path}")
                self._invalidate_screenshot_template_cache(filepath)
                self._refresh_screenshot_preview(normalized_path, target_input)
                self._update_current_parameter_from_widget(target_input, normalized_path)
                self._apply_parameters(auto_close=False)
                self._clear_screenshot_runtime_state()
            self._restore_windows_after_screenshot()
        except Exception as exc:
            logger.error(f"处理截图路径失败: {exc}", exc_info=True)
            self._restore_windows_after_screenshot()

    def _restore_windows_after_screenshot(self):
        if hasattr(self, 'main_window') and self.main_window:
            show_and_raise_widget(self.main_window, log_prefix='主窗口恢复')
        show_and_activate_overlay(self, log_prefix='参数面板恢复', focus=True)
        logger.debug('截图完成后已恢复参数面板和主窗口')

    def _on_screenshot_cancelled(self):
        logger.info('截图已取消')
        self._clear_screenshot_runtime_state()
        self._restore_windows_after_screenshot()
