from ..parameter_panel_support import *


class ParameterPanelWidgetTableSelectorHintDispatchMixin:
    def _create_table_selector_widget_by_hint(self, name: str, param_def: Dict[str, Any], current_value: Any, label_text: str):
        _ = label_text
        widget_hint = param_def.get('widget_hint', '')
        if widget_hint == 'variable_sources_table':
            return self._create_variable_sources_table_widget(name, param_def, current_value)
        if widget_hint == 'conditions_table':
            return self._create_conditions_table_widget(name, param_def, current_value)
        return None
