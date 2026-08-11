from ..parameter_panel_support import *
from .parameter_panel_widget_numeric_type_mixin import ParameterPanelWidgetNumericTypeMixin
from .parameter_panel_widget_text_type_mixin import ParameterPanelWidgetTextTypeMixin


class ParameterPanelWidgetTypeFactoryMixin(
    ParameterPanelWidgetNumericTypeMixin,
    ParameterPanelWidgetTextTypeMixin,
):

    def _create_widget_by_param_type(self, name: str, param_def: Dict[str, Any], current_value: Any, label_text: str):
        widget = self._create_numeric_widget_by_type(name, param_def, current_value, label_text)
        if widget is not None:
            return widget
        return self._create_textual_widget_by_type(name, param_def, current_value, label_text)
