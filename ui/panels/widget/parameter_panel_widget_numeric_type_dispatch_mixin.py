from ..parameter_panel_support import *


class ParameterPanelWidgetNumericTypeDispatchMixin:
    def _create_numeric_widget_by_type(self, name: str, param_def: Dict[str, Any], current_value: Any, label_text: str):
        _ = label_text
        param_type = param_def.get('type', 'text')
        if param_type in ('bool', 'checkbox'):
            return self._create_numeric_checkbox_widget(name, current_value)
        if param_type in ('int', 'integer'):
            return self._create_numeric_int_widget(param_def, current_value)
        if param_type in ('float', 'double'):
            return self._create_numeric_float_widget(param_def, current_value)
        if param_type == 'radio':
            return self._create_numeric_radio_widget(param_def, current_value)
        if param_type in ('choice', 'select', 'combo'):
            return self._create_numeric_choice_widget(name, param_def, current_value)
        return None
