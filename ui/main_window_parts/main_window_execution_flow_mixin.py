from .main_window_execution_flow_jump_mixin import MainWindowExecutionFlowJumpMixin
from .main_window_execution_flow_lifecycle_mixin import MainWindowExecutionFlowLifecycleMixin
from .main_window_execution_flow_runtime_mixin import MainWindowExecutionFlowRuntimeMixin
from .main_window_execution_flow_test_mixin import MainWindowExecutionFlowTestMixin


class MainWindowExecutionFlowMixin(
    MainWindowExecutionFlowTestMixin,
    MainWindowExecutionFlowJumpMixin,
    MainWindowExecutionFlowRuntimeMixin,
    MainWindowExecutionFlowLifecycleMixin,
):
    pass
