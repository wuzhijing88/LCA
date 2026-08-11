from .parameter_panel_widget_standard_text_type_button_mixin import (
    ParameterPanelWidgetStandardTextTypeButtonMixin,
)
from .parameter_panel_widget_standard_text_type_coordinate_mixin import (
    ParameterPanelWidgetStandardTextTypeCoordinateMixin,
)
from .parameter_panel_widget_standard_text_type_default_mixin import (
    ParameterPanelWidgetStandardTextTypeDefaultMixin,
)
from .parameter_panel_widget_standard_text_type_dispatch_mixin import (
    ParameterPanelWidgetStandardTextTypeDispatchMixin,
)
from .parameter_panel_widget_standard_text_type_file_mixin import (
    ParameterPanelWidgetStandardTextTypeFileMixin,
)


class ParameterPanelWidgetStandardTextTypeMixin(
    ParameterPanelWidgetStandardTextTypeDispatchMixin,
    ParameterPanelWidgetStandardTextTypeButtonMixin,
    ParameterPanelWidgetStandardTextTypeFileMixin,
    ParameterPanelWidgetStandardTextTypeCoordinateMixin,
    ParameterPanelWidgetStandardTextTypeDefaultMixin,
):
    pass
