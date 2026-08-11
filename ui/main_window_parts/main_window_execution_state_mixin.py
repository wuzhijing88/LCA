from .main_window_execution_persistence_mixin import MainWindowExecutionPersistenceMixin
from .main_window_execution_runtime_mixin import MainWindowExecutionRuntimeMixin
from .main_window_execution_status_mixin import MainWindowExecutionStatusMixin
from .main_window_execution_toolbar_mixin import MainWindowExecutionToolbarMixin


class MainWindowExecutionStateMixin(
    MainWindowExecutionRuntimeMixin,
    MainWindowExecutionPersistenceMixin,
    MainWindowExecutionStatusMixin,
    MainWindowExecutionToolbarMixin,
):
    pass
