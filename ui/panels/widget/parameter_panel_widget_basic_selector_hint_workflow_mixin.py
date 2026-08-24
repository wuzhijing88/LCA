from .parameter_panel_widget_basic_selector_hint_workflow_bound_window_mixin import (
    ParameterPanelWidgetBasicSelectorHintWorkflowBoundWindowMixin,
)
from .parameter_panel_widget_basic_selector_hint_workflow_card_mixin import (
    ParameterPanelWidgetBasicSelectorHintWorkflowCardMixin,
)
from .parameter_panel_widget_basic_selector_hint_workflow_jump_target_mixin import (
    ParameterPanelWidgetBasicSelectorHintWorkflowJumpTargetMixin,
)
from .parameter_panel_widget_basic_selector_hint_workflow_selector_mixin import (
    ParameterPanelWidgetBasicSelectorHintWorkflowSelectorMixin,
)
from .parameter_panel_widget_basic_selector_hint_workflow_thread_mixin import (
    ParameterPanelWidgetBasicSelectorHintWorkflowThreadMixin,
)


class ParameterPanelWidgetBasicSelectorHintWorkflowMixin(
    ParameterPanelWidgetBasicSelectorHintWorkflowJumpTargetMixin,
    ParameterPanelWidgetBasicSelectorHintWorkflowThreadMixin,
    ParameterPanelWidgetBasicSelectorHintWorkflowBoundWindowMixin,
    ParameterPanelWidgetBasicSelectorHintWorkflowCardMixin,
    ParameterPanelWidgetBasicSelectorHintWorkflowSelectorMixin,
):
    pass
