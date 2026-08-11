from .parameter_panel_widget_numeric_type_checkbox_mixin import (
    ParameterPanelWidgetNumericTypeCheckboxMixin,
)
from .parameter_panel_widget_numeric_type_dispatch_mixin import (
    ParameterPanelWidgetNumericTypeDispatchMixin,
)
from .parameter_panel_widget_numeric_type_line_edit_mixin import (
    ParameterPanelWidgetNumericTypeLineEditMixin,
)
from .parameter_panel_widget_numeric_type_selection_mixin import (
    ParameterPanelWidgetNumericTypeSelectionMixin,
)


class ParameterPanelWidgetNumericTypeMixin(
    ParameterPanelWidgetNumericTypeDispatchMixin,
    ParameterPanelWidgetNumericTypeCheckboxMixin,
    ParameterPanelWidgetNumericTypeLineEditMixin,
    ParameterPanelWidgetNumericTypeSelectionMixin,
):
    pass
