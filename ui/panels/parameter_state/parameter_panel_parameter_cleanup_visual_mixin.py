from ..parameter_panel_support import *


class ParameterPanelParameterCleanupVisualMixin:

    def _clear_image_previews(self):
        for widget_name, widget in list(self.widgets.items()):
            if widget_name.endswith('_preview') and isinstance(widget, QLabel):
                widget.setText("未选择图片")
                widget.setPixmap(QPixmap())
                widget.setProperty("image_path", "")

    def _cleanup_keyboard_parameters(self):
        keyboard_params = [
            'key', 'hotkey', 'key_combination', 'combo_keys', 'combo_seq_keys',
            'record_hotkey', 'replay_hotkey', 'trigger_key', 'stop_key',
        ]
        cleared_count = 0
        for param_name in keyboard_params:
            if param_name in self.current_parameters:
                self.current_parameters[param_name] = ""
                cleared_count += 1
            if param_name in self.widgets:
                widget = self.widgets[param_name]
                try:
                    self._reset_widget_to_default(widget, self.param_definitions.get(param_name, {}).get('default'), self.param_definitions.get(param_name, {}))
                except Exception as e:
                    logger.debug(f"重置键盘控件失败 {param_name}：{e}")
        if cleared_count > 0:
            logger.info(f"Cleared {cleared_count} keyboard-related parameters")

    def _cleanup_extra_hidden_params(self, extra_hidden_params):
        cleared_count = 0
        for param_name in extra_hidden_params:
            if param_name in self.current_parameters:
                del self.current_parameters[param_name]
                cleared_count += 1
            if param_name in self.widgets:
                widget = self.widgets[param_name]
                if isinstance(widget, QLineEdit):
                    widget.clear()
        if cleared_count > 0:
            logger.info(f"Cleared {cleared_count} extra hidden parameters")
