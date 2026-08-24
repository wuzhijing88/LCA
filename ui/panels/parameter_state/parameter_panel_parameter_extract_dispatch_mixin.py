from ..parameter_panel_support import *


class ParameterPanelParameterExtractDispatchMixin:
    def _extract_parameter_value_from_widget(
        self,
        name: str,
        widget,
        *,
        normalize_operation_mode: bool,
        convert_image_paths: bool,
        prefer_existing_on_empty: bool,
        prefer_existing_on_invalid: bool,
        prefer_existing_when_unchecked: bool,
        allow_layout_widget: bool,
        allow_coordinate_selector: bool,
        restore_list_widget_property: bool,
        log_invalid_numeric: bool,
    ):
        if isinstance(widget, QCheckBox):
            return True, widget.isChecked()
        if isinstance(widget, QSpinBox):
            return True, widget.value()
        if isinstance(widget, QDoubleSpinBox):
            return True, widget.value()
        if isinstance(widget, QComboBox):
            return True, self._extract_combobox_parameter_value(
                name,
                widget,
                normalize_operation_mode,
            )
        if isinstance(widget, QPlainTextEdit):
            return True, widget.toPlainText()
        if isinstance(widget, QTextEdit):
            text_value = widget.toPlainText()
            if convert_image_paths and name == 'image_paths':
                text_value = self._convert_display_to_full_paths(text_value)
            return True, text_value
        if isinstance(widget, QLineEdit):
            return True, self._extract_line_edit_parameter_value(
                name,
                widget,
                prefer_existing_on_empty=prefer_existing_on_empty,
                prefer_existing_on_invalid=prefer_existing_on_invalid,
                log_invalid=log_invalid_numeric,
            )
        if hasattr(widget, 'button_group'):
            return True, self._extract_button_group_parameter_value(
                name,
                widget,
                prefer_existing_when_unchecked=prefer_existing_when_unchecked,
            )
        if isinstance(widget, QListWidget):
            return True, self._extract_list_widget_parameter_value(
                name,
                widget,
                restore_property=restore_list_widget_property,
            )
        if allow_layout_widget and hasattr(widget, 'layout'):
            layout_value = self._extract_layout_parameter_value(widget)
            if layout_value is not None:
                return True, layout_value
        if allow_coordinate_selector:
            param_def = self.param_definitions.get(name, {})
            if (
                param_def.get('widget_hint', '') == 'coordinate_selector'
                and hasattr(widget, 'get_coordinate')
            ):
                coord_x, coord_y = widget.get_coordinate()
                return True, {'coordinate_x': coord_x, 'coordinate_y': coord_y}
        return False, None
