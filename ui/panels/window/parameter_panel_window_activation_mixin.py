from .parameter_panel_window_activation_focus_mixin import (
    ParameterPanelWindowActivationFocusMixin,
)
from .parameter_panel_window_activation_main_mixin import (
    ParameterPanelWindowActivationMainMixin,
)
from .parameter_panel_window_activation_panel_mixin import (
    ParameterPanelWindowActivationPanelMixin,
)


class ParameterPanelWindowActivationMixin(
    ParameterPanelWindowActivationMainMixin,
    ParameterPanelWindowActivationFocusMixin,
    ParameterPanelWindowActivationPanelMixin,
):
    pass
