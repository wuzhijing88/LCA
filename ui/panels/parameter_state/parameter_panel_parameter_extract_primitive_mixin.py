from ..parameter_panel_support import *


class ParameterPanelParameterExtractPrimitiveMixin:
    _DATA_COMBO_WIDGET_HINTS = {
        'card_selector',
        'jump_target_selector',
        'thread_target_selector',
        'workflow_card_selector',
        'bound_window_selector',
    }

    def _extract_combobox_parameter_value(
        self,
        name: str,
        widget: QComboBox,
        normalize_operation_mode: bool = False,
    ):
        current_data = widget.currentData()
        param_def = self.param_definitions.get(name, {})
        widget_hint = param_def.get('widget_hint', '')
        if widget_hint in self._DATA_COMBO_WIDGET_HINTS:
            return current_data

        selected_value = current_data if current_data is not None else widget.currentText()
        if normalize_operation_mode and name == 'operation_mode':
            selected_value = self._normalize_operation_mode_value(
                selected_value,
                fallback_task_type=self.current_task_type or '',
            )
        return selected_value

    def _extract_line_edit_parameter_value(
        self,
        name: str,
        widget: QLineEdit,
        prefer_existing_on_empty: bool,
        prefer_existing_on_invalid: bool,
        log_invalid: bool,
    ):
        text_value = widget.text()
        param_def = self.param_definitions.get(name, {})
        param_type = param_def.get('type', 'text')

        if param_type in ['int', 'integer']:
            existing_value = self.current_parameters.get(name, param_def.get('default', 0))
            if not text_value:
                return existing_value if prefer_existing_on_empty else 0
            try:
                return int(text_value)
            except ValueError:
                if log_invalid:
                    logger.warning(f'Invalid int value for {name}: {text_value}')
                return existing_value if prefer_existing_on_invalid else param_def.get('default', 0)

        if param_type in ['float', 'double']:
            existing_value = self.current_parameters.get(name, param_def.get('default', 0.0))
            if not text_value:
                return existing_value if prefer_existing_on_empty else 0.0
            try:
                return float(text_value)
            except ValueError:
                if log_invalid:
                    logger.warning(f'Invalid float value for {name}: {text_value}')
                return existing_value if prefer_existing_on_invalid else param_def.get('default', 0.0)

        return self._normalize_single_image_parameter_value(name, text_value)
