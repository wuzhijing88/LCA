import threading
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QThread, QTimer, Signal

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
    card_executing = Signal(int)
    card_finished = Signal(int, bool)
    error_occurred = Signal(str, int, int, str)
    show_warning = Signal(str, str)

    def __init__(
        self,
        window_info,
        workflow_data,
        task_modules,
        workflow_file_path: Optional[str] = None,
        workflow_slot: int = 0,
        bound_windows: Optional[List[Dict[str, Any]]] = None,
        execution_mode: Optional[str] = None,
        runtime_config: Optional[Dict[str, Any]] = None,
    ):
        super().__init__()
        if not isinstance(window_info, dict):
            raise TypeError("窗口配置必须是字典")
        if runtime_config is not None and not isinstance(runtime_config, dict):
            raise TypeError("运行配置必须是字典")
        if isinstance(workflow_slot, bool) or not isinstance(workflow_slot, int) or workflow_slot < 0:
            raise ValueError("工作流槽位必须是非负整数")
        if bound_windows is not None and not isinstance(bound_windows, list):
            raise TypeError("绑定窗口必须是列表")
        self.window_info = dict(window_info)
        self.workflow_data = dict(workflow_data) if isinstance(workflow_data, dict) else workflow_data
        self.task_modules = task_modules
        self.workflow_file_path = workflow_file_path
        self._configured_execution_mode = str(execution_mode or "").strip() or None
        self._runtime_config = dict(runtime_config) if isinstance(runtime_config, dict) else {}
        self.workflow_slot = workflow_slot
        self.bound_windows = list(bound_windows) if bound_windows is not None else []
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
        self._stop_completion_timer = QTimer(self)
        self._stop_completion_timer.setSingleShot(True)
        self._stop_completion_timer.setInterval(1000)
        self._stop_completion_timer.timeout.connect(self._force_stop_completion)

        # 执行器相关
        self.executor = None
        self.executor_thread = None

        from utils.window.hwnd_utils import as_hwnd

        bind_id = self.window_info.get("bind_id")
        if not isinstance(bind_id, str) or not bind_id.strip():
            raise ValueError("窗口缺少有效绑定标识")
        raw_hwnd = self.window_info.get("hwnd")
        if isinstance(raw_hwnd, bool) or not isinstance(raw_hwnd, int):
            raise TypeError("窗口句柄必须是整数")
        self.hwnd = as_hwnd(raw_hwnd)
        self.job_id = bind_id
        self.window_id = self.job_id
        self.finished.connect(self._on_thread_finished, Qt.ConnectionType.QueuedConnection)

    def apply_hwnd_lease(self, hwnd: int) -> None:
        from utils.window.hwnd_utils import as_hwnd

        if isinstance(hwnd, bool) or not isinstance(hwnd, int):
            raise TypeError("窗口句柄必须是整数")
        handle = as_hwnd(hwnd)
        if handle == 0:
            raise ValueError("窗口句柄不能为零")
        self.hwnd = handle
        bind_id = self.window_info["bind_id"]
        self.window_info["hwnd"] = handle
        executor = getattr(self, "executor", None)
        collections = [self.bound_windows]
        if executor is not None:
            if hasattr(executor, "bound_windows"):
                collections.append(executor.bound_windows)
            payload = getattr(executor, "_payload", None)
            if isinstance(payload, dict):
                if payload.get("target_bind_id") == bind_id:
                    payload["target_hwnd"] = handle
                collections.append(payload["bound_windows"])
                for config in payload.get("thread_window_configs", {}).values():
                    if config["bind_id"] == bind_id:
                        config["target_hwnd"] = handle
            if getattr(executor, "target_bind_id", None) == bind_id:
                executor.target_hwnd = handle
        for collection in collections:
            if not isinstance(collection, list):
                raise TypeError("绑定窗口必须是列表")
            for window_info in collection:
                if not isinstance(window_info, dict):
                    raise TypeError("绑定窗口配置必须是字典")
                if window_info["bind_id"] == bind_id:
                    window_info["hwnd"] = handle
