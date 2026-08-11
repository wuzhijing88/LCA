from .parameter_panel_target_window_resolution_mixin import (
    ParameterPanelTargetWindowResolutionMixin,
)
from .parameter_panel_target_window_selection_mixin import (
    ParameterPanelTargetWindowSelectionMixin,
)


class ParameterPanelTargetWindowMixin(
    ParameterPanelTargetWindowSelectionMixin,
    ParameterPanelTargetWindowResolutionMixin,
):
    pass
