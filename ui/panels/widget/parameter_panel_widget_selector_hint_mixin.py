from ..parameter_panel_support import *
from .parameter_panel_widget_basic_selector_hint_mixin import ParameterPanelWidgetBasicSelectorHintMixin
from .parameter_panel_widget_table_selector_hint_mixin import ParameterPanelWidgetTableSelectorHintMixin
from .parameter_panel_widget_variable_selector_hint_mixin import ParameterPanelWidgetVariableSelectorHintMixin


class ParameterPanelWidgetSelectorHintMixin(
    ParameterPanelWidgetBasicSelectorHintMixin,
    ParameterPanelWidgetVariableSelectorHintMixin,
    ParameterPanelWidgetTableSelectorHintMixin,
):

    def _create_selector_widget_by_hint(self, name: str, param_def: Dict[str, Any], current_value: Any, label_text: str):
        widget = self._create_basic_selector_widget_by_hint(name, param_def, current_value, label_text)
        if widget is not None:
            return widget
        widget = self._create_variable_selector_widget_by_hint(name, param_def, current_value, label_text)
        if widget is not None:
            return widget
        return self._create_table_selector_widget_by_hint(name, param_def, current_value, label_text)
