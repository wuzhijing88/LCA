from .main_window_workflow_switch_loading_mixin import MainWindowWorkflowSwitchLoadingMixin
from .main_window_workflow_switch_reference_mixin import MainWindowWorkflowSwitchReferenceMixin
from .main_window_workflow_switch_tabs_mixin import MainWindowWorkflowSwitchTabsMixin


class MainWindowWorkflowSwitchMixin(
    MainWindowWorkflowSwitchTabsMixin,
    MainWindowWorkflowSwitchLoadingMixin,
    MainWindowWorkflowSwitchReferenceMixin,
):
    pass
