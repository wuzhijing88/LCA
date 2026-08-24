from .parameter_panel_workflow_selector_thread_collect_mixin import (
    ParameterPanelWorkflowSelectorThreadCollectMixin,
)
from .parameter_panel_workflow_selector_thread_parse_mixin import (
    ParameterPanelWorkflowSelectorThreadParseMixin,
)
from .parameter_panel_workflow_selector_thread_refresh_mixin import (
    ParameterPanelWorkflowSelectorThreadRefreshMixin,
)
from .parameter_panel_workflow_selector_thread_target_mixin import (
    ParameterPanelWorkflowSelectorThreadTargetMixin,
)


class ParameterPanelWorkflowSelectorThreadMixin(
    ParameterPanelWorkflowSelectorThreadCollectMixin,
    ParameterPanelWorkflowSelectorThreadParseMixin,
    ParameterPanelWorkflowSelectorThreadTargetMixin,
    ParameterPanelWorkflowSelectorThreadRefreshMixin,
):
    pass
