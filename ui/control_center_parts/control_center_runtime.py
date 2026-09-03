import threading
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QThread, Signal

from .control_center_runtime_control_mixin import WindowTaskRunnerControlMixin
from .control_center_runtime_execution_mixin import WindowTaskRunnerExecutionMixin
from .control_center_runtime_slots_mixin import WindowTaskRunnerSlotsMixin
from .control_center_runtime_state_mixin import WindowTaskRunnerStateMixin
from .control_center_runtime_types import TaskState


class WindowTaskRunner(
    WindowTaskRunnerSlotsMixin,
    WindowTaskRunnerStateMixin,
    WindowTaskRunnerExecutionMixin,
    WindowTaskRunnerControlMixin,
    QThread,
):
    """Runner thread for executing a workflow on one window."""
    _execution_slot_lock = threading.Lock()
    _execution_slot_limit = None
    _execution_slot_semaphore = None

    status_updated = Signal(str, str)
    step_updated = Signal(str, str)
    task_completed = Signal(str, bool)
    runtime_alert = Signal(str, str)

    def __init__(
        self,
        window_info,
        workflow_data,
        task_modules,
        workflow_file_path: Optional[str] = None,
        workflow_slot: int = 0,
        start_gate_event: Optional[threading.Event] = None,
        bound_windows: Optional[List[Dict[str, Any]]] = None,
        execution_mode: Optional[str] = None,
        runtime_config: Optional[Dict[str, Any]] = None,
    ):
        super().__init__()
        self.window_info = dict(window_info) if isinstance(window_info, dict) else {}
        self.workflow_data = dict(workflow_data) if isinstance(workflow_data, dict) else workflow_data
        self.task_modules = task_modules
        self.workflow_file_path = workflow_file_path
        self._start_gate_event = start_gate_event
        self._configured_execution_mode = str(execution_mode or "").strip() or None
        self._runtime_config = dict(runtime_config) if isinstance(runtime_config, dict) else {}
        try:
            self.workflow_slot = int(workflow_slot or 0)
        except Exception:
            self.workflow_slot = 0
        self.bound_windows = list(bound_windows) if isinstance(bound_windows, list) else []
        self._card_step_labels: Dict[str, str] = {}

        # 状态管理
        self._current_state = TaskState.IDLE
        self._is_running = False
        self._should_stop = False
        self._is_cleaned = False  # 防止重复清理
        self._cleanup_deferred_until_finish = False
        self._task_completed_emitted = False
        self._execution_slot_acquired = False
        self._execution_slot_ref = None
        self._queued_for_start = False
        self._thread_start_requested = False
        self._last_status_message = ""
        self._last_execution_message = ""
        self._last_execution_success: Optional[bool] = None

        # 执行器相关
        self.executor = None
        self.executor_thread = None

        bind_id = str(self.window_info.get("bind_id") or "").strip()
        try:
            from utils.window.hwnd_utils import as_hwnd

            self.hwnd = as_hwnd(self.window_info.get("hwnd"))
        except Exception:
            self.hwnd = 0
        self.job_id = bind_id or (str(self.hwnd) if self.hwnd else "unknown")
        self.window_id = self.job_id
        self.finished.connect(self._on_thread_finished, Qt.ConnectionType.QueuedConnection)
