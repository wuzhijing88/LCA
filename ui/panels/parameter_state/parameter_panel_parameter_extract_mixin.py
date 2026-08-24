from .parameter_panel_parameter_extract_dispatch_mixin import (
    ParameterPanelParameterExtractDispatchMixin,
)
from .parameter_panel_parameter_extract_primitive_mixin import (
    ParameterPanelParameterExtractPrimitiveMixin,
)
from .parameter_panel_parameter_extract_widget_mixin import (
    ParameterPanelParameterExtractWidgetMixin,
)


class ParameterPanelParameterExtractMixin(
    ParameterPanelParameterExtractPrimitiveMixin,
    ParameterPanelParameterExtractWidgetMixin,
    ParameterPanelParameterExtractDispatchMixin,
):
    pass
