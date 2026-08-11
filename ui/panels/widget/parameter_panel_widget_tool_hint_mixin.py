from ..parameter_panel_support import *
from .parameter_panel_widget_interactive_tool_hint_mixin import ParameterPanelWidgetInteractiveToolHintMixin
from .parameter_panel_widget_recording_tool_hint_mixin import ParameterPanelWidgetRecordingToolHintMixin


class ParameterPanelWidgetToolHintMixin(
    ParameterPanelWidgetInteractiveToolHintMixin,
    ParameterPanelWidgetRecordingToolHintMixin,
):

    def _create_tool_widget_by_hint(self, name: str, param_def: Dict[str, Any], current_value: Any, label_text: str):
        widget = self._create_interactive_tool_widget_by_hint(name, param_def, current_value, label_text)
        if widget is not None:
            return widget
        return self._create_recording_tool_widget_by_hint(name, param_def, current_value, label_text)
