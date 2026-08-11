from ..parameter_panel_support import *


class ParameterPanelWidgetVariableSelectorHintDispatchMixin:
    def _create_variable_selector_widget_by_hint(self, name: str, param_def: Dict[str, Any], current_value: Any, label_text: str):
        _ = label_text
        widget_hint = param_def.get('widget_hint', '')
        if widget_hint == 'variable_card_selector':
            return self._create_variable_card_selector_widget(name, param_def, current_value)
        if widget_hint == 'variable_name_selector':
            return self._create_variable_name_selector_widget(name, param_def, current_value)
        return None
