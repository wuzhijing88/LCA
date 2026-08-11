from .parameter_panel_workflow_selector_context_mixin import (
    ParameterPanelWorkflowSelectorContextMixin,
)
from .parameter_panel_workflow_selector_operation_mode_mixin import (
    ParameterPanelWorkflowSelectorOperationModeMixin,
)
from .parameter_panel_workflow_selector_prune_mixin import (
    ParameterPanelWorkflowSelectorPruneMixin,
)
from .parameter_panel_workflow_selector_thread_mixin import (
    ParameterPanelWorkflowSelectorThreadMixin,
)


class ParameterPanelWorkflowSelectorMixin(
    ParameterPanelWorkflowSelectorThreadMixin,
    ParameterPanelWorkflowSelectorContextMixin,
    ParameterPanelWorkflowSelectorOperationModeMixin,
    ParameterPanelWorkflowSelectorPruneMixin,
):
    pass
