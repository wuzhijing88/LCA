import os
import threading
from collections import deque
from typing import Dict, Any, List, Optional
from PySide6.QtWidgets import QMainWindow

from app_core.control_plane import JobScheduler
from utils.app_paths import get_user_data_dir
from ..control_center_parts.control_center_runner_mixin import ControlCenterRunnerMixin
from ..control_center_parts.control_center_timer_mixin import ControlCenterTimerMixin
from ..control_center_parts.control_center_pause_timer_mixin import ControlCenterPauseTimerMixin
from ..control_center_parts.control_center_timer_dialog_mixin import ControlCenterTimerDialogMixin
from ..control_center_parts.control_center_ui_layout_mixin import ControlCenterUiLayoutMixin
from ..control_center_parts.control_center_window_lifecycle_mixin import ControlCenterWindowLifecycleMixin
from ..control_center_parts.control_center_window_table_mixin import (
    ControlCenterWindowTableMixin,
    format_bound_window_display_title,
)
from ..control_center_parts.control_center_workflow_runtime_mixin import ControlCenterWorkflowRuntimeMixin
from ..control_center_parts.control_center_workflow_assignment_mixin import ControlCenterWorkflowAssignmentMixin
from ..control_center_parts.control_center_window_task_mixin import ControlCenterWindowTaskMixin
from ..control_center_parts.control_center_batch_ops_mixin import ControlCenterBatchOpsMixin
from ..control_center_parts.control_center_stability_test_mixin import ControlCenterStabilityTestMixin
from utils.window.window_coordinate_common import get_available_geometry_for_widget, clamp_preferred_window_size


class ControlCenterWindow(ControlCenterRunnerMixin, ControlCenterTimerMixin, ControlCenterPauseTimerMixin, ControlCenterTimerDialogMixin, ControlCenterUiLayoutMixin, ControlCenterWindowLifecycleMixin, ControlCenterWindowTableMixin, ControlCenterWorkflowRuntimeMixin, ControlCenterWorkflowAssignmentMixin, ControlCenterWindowTaskMixin, ControlCenterBatchOpsMixin, ControlCenterStabilityTestMixin, QMainWindow):
    """中控软件主窗口 - 多窗口工作流管理"""

    def __init__(self, bound_windows: List[Dict], task_modules: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.setObjectName("ControlCenterWindow")
        self.bound_windows = bound_windows
        self.task_modules = task_modules
        self.scheduler = JobScheduler()
        self.window_runners = {}  # job_id -> [runner1, runner2, ...]
        self.window_workflows = self.scheduler.assignments_view()
        self.scheduler.sync_targets(bound_windows)
        self.sorted_windows = []  # 存储排序后的窗口列表
        self.parent_window = parent  # 保存主窗口引用

        # UI更新节流：缓存待更新的步骤信息
        self._pending_step_updates = {}  # window_id -> step_info
        self._ui_update_timer = None
        self._orphaned_threads = []  # 防止线程仍在运行时被GC导致闪退

        # 窗口启动间隔延迟设置（秒）
        self._window_start_delay_sec = None

        # 非阻塞启动状态
        self._pending_windows = []  # 待启动的窗口列表
        self._pending_valid_windows = None
        self._started_count = 0  # 已启动的窗口数量
        self._start_all_in_progress = False  # 是否正在批量启动
        self._cancel_start_sequence = False
        self._is_closing = False  # 关闭标记：阻断OCR预创建与延迟启动链路
        self._batch_start_gate_event: Optional[threading.Event] = None  # 批量启动同步闸门
        self._window_workflow_results = {}  # window_id -> {workflow_index: success_bool}
        self._deferred_global_stop_cleanup_pending = False
        self._runner_start_queue = deque()
        self._runner_dispatch_suspended = False
        self._runner_dispatch_in_progress = False
        self._dead_hwnd_stopped = set()
        self._hwnd_watchdog_timer = None
        self._stability_test_active = False
        self._stability_test_snapshot = None

        # 临时工作流配置文件路径
        try:
            from utils.app_paths import get_runtime_state_dir

            runtime_dir = get_runtime_state_dir("LCA")
        except Exception:
            runtime_dir = os.path.join(get_user_data_dir("LCA"), "runtime")
        os.makedirs(runtime_dir, exist_ok=True)
        self.temp_workflow_config_file = os.path.join(runtime_dir, ".control_center_workflows.json")

        self.setWindowTitle("中控软件 - 多窗口工作流管理")
        available_geometry = get_available_geometry_for_widget(self.parentWidget() or self)
        initial_width, initial_height = clamp_preferred_window_size(1000, 500, available_geometry)
        if available_geometry and not available_geometry.isEmpty():
            initial_x = available_geometry.left() + max(0, (available_geometry.width() - initial_width) // 2)
            initial_y = available_geometry.top() + max(0, (available_geometry.height() - initial_height) // 2)
        else:
            initial_x, initial_y = 200, 200
        self.setGeometry(initial_x, initial_y, initial_width, initial_height)
        self.setMinimumSize(800, 400)

        # 不再使用硬编码样式，让全局主题控制窗口样式
        # 窗口样式现在由 themes/dark.qss 和 themes/light.qss 统一管理

        self.init_ui()
        self._load_workflow_config()
        self._refresh_all_window_workflow_cells()
        self._persist_bound_window_identities()
        self.setup_timer()
        self._setup_hwnd_watchdog()
        self._setup_shortcuts()

    def sort_windows_by_title(self, windows):
        """按窗口标题排序"""
        def get_sort_key(window):
            title = window.get('title', '')
            return (1, title)

        return sorted(windows, key=get_sort_key)

    def format_window_title(self, original_title, row_index):
        """格式化窗口标题显示。同名窗口才加编号。"""
        return format_bound_window_display_title(
            original_title,
            row_index,
            getattr(self, "sorted_windows", None),
        )
