from ..parameter_panel_support import *
from .parameter_panel_widget_multiline_type_mixin import ParameterPanelWidgetMultilineTypeMixin
from .parameter_panel_widget_standard_text_type_mixin import ParameterPanelWidgetStandardTextTypeMixin


class ParameterPanelWidgetTextTypeMixin(
    ParameterPanelWidgetMultilineTypeMixin,
    ParameterPanelWidgetStandardTextTypeMixin,
):

    def _create_textual_widget_by_type(self, name: str, param_def: Dict[str, Any], current_value: Any, label_text: str):
        widget = self._create_multiline_widget_by_type(name, param_def, current_value, label_text)
        if widget is not None:
            return widget
        return self._create_standard_text_widget_by_type(name, param_def, current_value, label_text)
