from .parameter_panel_selector_coordinate_basic_apply_mixin import (
    ParameterPanelSelectorCoordinateBasicApplyMixin,
)
from .parameter_panel_selector_coordinate_basic_runtime_mixin import (
    ParameterPanelSelectorCoordinateBasicRuntimeMixin,
)


class ParameterPanelSelectorCoordinateBasicMixin(
    ParameterPanelSelectorCoordinateBasicRuntimeMixin,
    ParameterPanelSelectorCoordinateBasicApplyMixin,
):
    pass
