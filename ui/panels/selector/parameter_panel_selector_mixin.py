from .parameter_panel_selector_binding_mixin import ParameterPanelSelectorBindingMixin
from .parameter_panel_selector_coordinate_mixin import ParameterPanelSelectorCoordinateMixin
from .parameter_panel_selector_picker_mixin import ParameterPanelSelectorPickerMixin
from .parameter_panel_selector_region_mixin import ParameterPanelSelectorRegionMixin


class ParameterPanelSelectorMixin(
    ParameterPanelSelectorPickerMixin,
    ParameterPanelSelectorBindingMixin,
    ParameterPanelSelectorCoordinateMixin,
    ParameterPanelSelectorRegionMixin,
):
    pass
