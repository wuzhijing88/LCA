from .parameter_panel_parameter_reset_flow_mixin import ParameterPanelParameterResetFlowMixin
from .parameter_panel_parameter_reset_widget_mixin import ParameterPanelParameterResetWidgetMixin


class ParameterPanelParameterResetMixin(
    ParameterPanelParameterResetWidgetMixin,
    ParameterPanelParameterResetFlowMixin,
):
    pass
