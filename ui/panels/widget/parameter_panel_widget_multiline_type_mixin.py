from .parameter_panel_widget_multiline_type_connected_targets_mixin import (
    ParameterPanelWidgetMultilineTypeConnectedTargetsMixin,
)
from .parameter_panel_widget_multiline_type_default_mixin import (
    ParameterPanelWidgetMultilineTypeDefaultMixin,
)
from .parameter_panel_widget_multiline_type_dispatch_mixin import (
    ParameterPanelWidgetMultilineTypeDispatchMixin,
)
from .parameter_panel_widget_multiline_type_path_points_mixin import (
    ParameterPanelWidgetMultilineTypePathPointsMixin,
)
from .parameter_panel_widget_multiline_type_template_preset_mixin import (
    ParameterPanelWidgetMultilineTypeTemplatePresetMixin,
)


class ParameterPanelWidgetMultilineTypeMixin(
    ParameterPanelWidgetMultilineTypeDispatchMixin,
    ParameterPanelWidgetMultilineTypeConnectedTargetsMixin,
    ParameterPanelWidgetMultilineTypePathPointsMixin,
    ParameterPanelWidgetMultilineTypeTemplatePresetMixin,
    ParameterPanelWidgetMultilineTypeDefaultMixin,
):
    pass
