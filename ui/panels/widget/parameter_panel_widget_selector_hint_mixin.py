from ..parameter_panel_support import *
from .parameter_panel_widget_basic_selector_hint_mixin import ParameterPanelWidgetBasicSelectorHintMixin


class ParameterPanelWidgetSelectorHintMixin(
    ParameterPanelWidgetBasicSelectorHintMixin,
):

    def _create_selector_widget_by_hint(self, name: str, param_def: Dict[str, Any], current_value: Any, label_text: str):
        return self._create_basic_selector_widget_by_hint(name, param_def, current_value, label_text)
