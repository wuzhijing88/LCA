from ..parameter_panel_support import *
from .parameter_panel_widget_selector_hint_mixin import ParameterPanelWidgetSelectorHintMixin
from .parameter_panel_widget_tool_hint_mixin import ParameterPanelWidgetToolHintMixin


class ParameterPanelWidgetHintFactoryMixin(
    ParameterPanelWidgetSelectorHintMixin,
    ParameterPanelWidgetToolHintMixin,
):

    def _create_widget_by_hint(self, name: str, param_def: Dict[str, Any], current_value: Any, label_text: str):
        widget = self._create_selector_widget_by_hint(name, param_def, current_value, label_text)
        if widget is not None:
            return widget
        return self._create_tool_widget_by_hint(name, param_def, current_value, label_text)
