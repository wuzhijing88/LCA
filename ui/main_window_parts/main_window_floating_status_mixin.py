import logging

from PySide6.QtCore import Slot

from ..main_window_parts.main_window_pause_orchestrator import main_window_toggle_pause_workflow_floating

logger = logging.getLogger(__name__)


class MainWindowFloatingStatusMixin:
    def _init_floating_status_window(self):

        """初始化浮动状态窗口"""

        try:

            from ..widgets.floating_status_window import FloatingStatusWindow, FloatingWindowController

            self._floating_window = FloatingStatusWindow()

            self._floating_controller = FloatingWindowController(self, self._floating_window)

            self._floating_controller.set_enabled(getattr(self, 'enable_floating_status_window', True))

            # 连接浮动窗口的控制信号

            self._floating_window.request_start.connect(self.safe_start_tasks)

            self._floating_window.request_pause.connect(self._toggle_pause_workflow)

            self._floating_window.request_stop.connect(self.safe_stop_tasks)

            logger.info("浮动状态窗口初始化完成")

        except Exception as e:

            logger.error(f"初始化浮动状态窗口失败: {e}")

            self._floating_window = None

            self._floating_controller = None

    def _toggle_pause_workflow(self):

        """切换工作流暂停/恢复状态"""

        return main_window_toggle_pause_workflow_floating(self)

    @Slot(str, str, bool)
    def _forward_step_log(self, card_type: str, message: str, success: bool):

        """转发步骤日志到浮动窗口"""

        if self._is_stale_executor_signal():

            return

        try:

            if hasattr(self, '_floating_window') and self._floating_window:

                self._floating_window.on_step_log(card_type, message, success)

        except Exception as e:

            logger.error(f"转发步骤日志失败: {e}")
