from .parameter_panel_window_position_mixin import ParameterPanelWindowPositionMixin
from .parameter_panel_window_setup_mixin import ParameterPanelWindowSetupMixin
from .parameter_panel_window_style_mixin import ParameterPanelWindowStyleMixin


class ParameterPanelWindowLayoutMixin(
    ParameterPanelWindowSetupMixin,
    ParameterPanelWindowStyleMixin,
    ParameterPanelWindowPositionMixin,
):
    pass
