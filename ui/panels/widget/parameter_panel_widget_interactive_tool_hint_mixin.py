from .parameter_panel_widget_interactive_tool_hint_action_mixin import (
    ParameterPanelWidgetInteractiveToolHintActionMixin,
)
from .parameter_panel_widget_interactive_tool_hint_color_coordinate_mixin import (
    ParameterPanelWidgetInteractiveToolHintColorCoordinateMixin,
)
from .parameter_panel_widget_interactive_tool_hint_dispatch_mixin import (
    ParameterPanelWidgetInteractiveToolHintDispatchMixin,
)
from .parameter_panel_widget_interactive_tool_hint_region_mixin import (
    ParameterPanelWidgetInteractiveToolHintRegionMixin,
)


class ParameterPanelWidgetInteractiveToolHintMixin(
    ParameterPanelWidgetInteractiveToolHintDispatchMixin,
    ParameterPanelWidgetInteractiveToolHintActionMixin,
    ParameterPanelWidgetInteractiveToolHintColorCoordinateMixin,
    ParameterPanelWidgetInteractiveToolHintRegionMixin,
):
    pass
