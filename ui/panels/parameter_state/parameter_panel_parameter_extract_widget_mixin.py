from ..parameter_panel_support import *


class ParameterPanelParameterExtractWidgetMixin:
    def _extract_list_widget_parameter_value(
        self,
        name: str,
        widget: QListWidget,
        restore_property: bool,
    ):
        raw_data = widget.property('raw_color_data')
        if raw_data:
            return raw_data

        existing_value = self.current_parameters.get(name)
        if existing_value and str(existing_value).strip():
            logger.debug(f'[COLOR_PARAM] keep current_parameters value for {name}: {existing_value}')
            if restore_property:
                widget.setProperty('raw_color_data', existing_value)
            return existing_value

        param_def = self.param_definitions.get(name, {})
        return param_def.get('default', '')

    def _extract_button_group_parameter_value(
        self,
        name: str,
        widget,
        prefer_existing_when_unchecked: bool,
    ):
        checked_button = widget.button_group.checkedButton()
        if checked_button:
            return checked_button.property('value')

        if prefer_existing_when_unchecked and name in self.current_parameters:
            return self.current_parameters.get(name)

        param_def = self.param_definitions.get(name, {})
        return param_def.get('default')

    @staticmethod
    def _extract_layout_parameter_value(widget):
        layout = widget.layout()
        if not layout or layout.count() <= 0:
            return None
        line_edit = layout.itemAt(0).widget()
        if not hasattr(line_edit, 'text'):
            return None
        return line_edit.text()
