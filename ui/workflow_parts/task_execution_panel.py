from PySide6.QtWidgets import (QWidget, QHBoxLayout, QPushButton, QLabel,
                               QComboBox, QProgressBar, QVBoxLayout, QFrame, QCheckBox)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon
import logging

from ..workflow_parts.workflow_task_manager import WorkflowTaskManager
# from ..widgets.custom_widgets import QComboBox  # 已弃用，使用原生 QComboBox

logger = logging.getLogger(__name__)


class TaskExecutionPanel(QWidget):
    """
    任务执行控制面板

    功能：
    1. 显示执行进度和任务状态
    """

    def __init__(self, task_manager: WorkflowTaskManager, parent=None):
        """
        初始化执行控制面板

        Args:
            task_manager: 任务管理器
            parent: 父控件
        """
        super().__init__(parent)

        self.task_manager = task_manager
        self._initialization_in_progress = False  # 添加：标记初始化状态
        self._init_ui()
        self._connect_signals()

    def _init_ui(self):
        """初始化UI"""
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(5, 3, 5, 3)
        main_layout.setSpacing(5)

        # 设置objectName以便QSS定位
        self.setObjectName("task_execution_panel")

        # === 状态显示 ===
        self.status_label = QLabel("就绪")
        self.status_label.setObjectName("exec_status_label")

        self.task_count_label = QLabel("任务: 0")
        self.task_count_label.setObjectName("exec_task_count_label")

        main_layout.addWidget(self.status_label)
        main_layout.addSpacing(8)
        main_layout.addWidget(self.task_count_label)

    def _connect_signals(self):
        """连接信号"""
        # 任务管理器信号
        self.task_manager.task_added.connect(self._update_ui_state)
        self.task_manager.task_removed.connect(self._update_ui_state)
        self.task_manager.task_status_changed.connect(self._update_ui_state)
        self.task_manager.all_tasks_completed.connect(self._on_all_tasks_completed)

    def _update_ui_state(self, *args):
        """更新UI状态"""
        # 获取任务统计
        total_count = self.task_manager.get_task_count()
        running_count = self.task_manager.get_running_count()

        # 更新任务计数
        self.task_count_label.setText(f"任务: {total_count} | 运行中: {running_count}")

        # 更新状态文本
        if running_count > 0:
            self.status_label.setText("执行中")
            self.status_label.setProperty("status", "running")
        else:
            self.status_label.setText("就绪")
            self.status_label.setProperty("status", "ready")
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def _on_all_tasks_completed(self, success: bool, result_type: str = ""):
        """所有任务执行完成"""
        normalized_result = str(result_type or "").strip().lower()

        if normalized_result == "stopped":
            self.status_label.setText("已停止")
            self.status_label.setProperty("status", "stopped")
        elif success:
            self.status_label.setText("全部完成")
            self.status_label.setProperty("status", "success")
        else:
            self.status_label.setText("执行失败")
            self.status_label.setProperty("status", "error")
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

        # 3秒后恢复状态
        from PySide6.QtCore import QTimer
        QTimer.singleShot(3000, lambda: self._update_ui_state())

    def set_status_message(self, message: str, status: str = "ready"):
        """
        设置状态消息

        Args:
            message: 消息文本
            status: 状态类型 (ready/running/success/error)
        """
        self.status_label.setText(message)
        self.status_label.setProperty("status", status)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def set_initialization_in_progress(self, in_progress: bool):
        """
        设置初始化进行中状态

        Args:
            in_progress: 是否正在初始化
        """
        self._initialization_in_progress = in_progress
        if in_progress:
            self.set_status_message("初始化中...", "#FF9800")
        self._update_ui_state()
