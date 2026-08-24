from .parameter_panel_widget_basic_selector_hint_dispatch_mixin import (
    ParameterPanelWidgetBasicSelectorHintDispatchMixin,
)
from .parameter_panel_widget_basic_selector_hint_simple_mixin import (
    ParameterPanelWidgetBasicSelectorHintSimpleMixin,
)
from .parameter_panel_widget_basic_selector_hint_workflow_mixin import (
    ParameterPanelWidgetBasicSelectorHintWorkflowMixin,
)


class ParameterPanelWidgetBasicSelectorHintMixin(
    ParameterPanelWidgetBasicSelectorHintDispatchMixin,
    ParameterPanelWidgetBasicSelectorHintWorkflowMixin,
    ParameterPanelWidgetBasicSelectorHintSimpleMixin,
):
    pass
