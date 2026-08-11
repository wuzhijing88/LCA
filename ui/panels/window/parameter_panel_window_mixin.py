from .parameter_panel_window_activation_mixin import ParameterPanelWindowActivationMixin
from .parameter_panel_window_event_mixin import ParameterPanelWindowEventMixin
from .parameter_panel_window_interaction_mixin import ParameterPanelWindowInteractionMixin
from .parameter_panel_window_layout_mixin import ParameterPanelWindowLayoutMixin
from .parameter_panel_window_visual_mixin import ParameterPanelWindowVisualMixin


class ParameterPanelWindowMixin(
    ParameterPanelWindowEventMixin,
    ParameterPanelWindowInteractionMixin,
    ParameterPanelWindowLayoutMixin,
    ParameterPanelWindowActivationMixin,
    ParameterPanelWindowVisualMixin,
):
    pass
