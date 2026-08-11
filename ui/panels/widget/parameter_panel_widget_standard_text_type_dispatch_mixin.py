from ..parameter_panel_support import *


class ParameterPanelWidgetStandardTextTypeDispatchMixin:
    def _create_standard_text_widget_by_type(self, name: str, param_def: Dict[str, Any], current_value: Any, label_text: str):
        param_type = param_def.get('type', 'text')
        widget_hint = param_def.get('widget_hint', '')
        if param_type == 'button':
            return self._create_standard_text_button_widget(name, param_def, label_text, widget_hint)
        if param_type == 'file':
            return self._create_standard_text_file_widget(name, param_def, current_value)
        if param_type == 'coordinate':
            return self._create_standard_text_coordinate_widget(name, current_value)
        return self._create_standard_text_default_widget(name, param_def, current_value)
