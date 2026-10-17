import logging

from PySide6.QtCore import Qt, Slot

from ..main_window_parts.main_window_pause_orchestrator import main_window_toggle_pause_workflow_compact_log

logger = logging.getLogger(__name__)


class MainWindowExecutionLogMixin:
    def _init_execution_log_panel(self):
        """初始化主窗口缩小日志模式。"""
        try:
            from ..widgets.execution_log_panel import ExecutionLogPanel

            self._execution_log_panel = ExecutionLogPanel(self.central_container)
            self._execution_log_panel.hide()
            self.main_layout.addWidget(self._execution_log_panel)
            self._execution_log_panel.request_start.connect(self.safe_start_tasks)
            self._execution_log_panel.request_pause.connect(self._toggle_pause_workflow)
            self._execution_log_panel.request_stop.connect(self.safe_stop_tasks)
            self._execution_log_panel.request_restore.connect(self.toggle_compact_log_mode)
            self._execution_log_panel.request_auto_log_enter.connect(self._enter_execution_log_for_run)
            self._compact_log_mode = False
            self._normal_window_geometry = None
        except Exception as exc:
            logger.error(f"初始化执行日志面板失败: {exc}")
            self._execution_log_panel = None

    def _execution_log_on_run_enabled(self) -> bool:
        config = getattr(self, "config", {})
        return bool(config.get("enable_execution_log_on_run", True))

    def _enter_execution_log_for_run(self) -> None:
        if not self._execution_log_on_run_enabled() or self._compact_log_mode:
            return
        self.toggle_compact_log_mode()

    def _toggle_pause_workflow(self):
        return main_window_toggle_pause_workflow_compact_log(self)

    def toggle_compact_log_mode(self):
        panel = getattr(self, "_execution_log_panel", None)
        if panel is None:
            self.showMinimized()
            return
        if self._compact_log_mode:
            self._compact_log_mode = False
            panel.reset_window_opacity()
            if hasattr(self, "parameter_panel"):
                self.parameter_panel.sync_window_state(Qt.WindowState.WindowNoState)
            panel.hide()
            self.workflow_tab_widget.show()
            self.step_detail_label.show()
            self.dpi_notification.setVisible(getattr(self, "_normal_dpi_notification_visible", False))
            if self._normal_window_geometry is not None:
                self.setGeometry(self._normal_window_geometry)
            self.title_bar.show()
            self.title_bar.set_file_actions_visible(self.file_actions_visible)
            self.title_bar.setWindowTitle(self.windowTitle())
            self.title_bar.minimize_button.setToolTip("缩小")
            return

        self._normal_window_geometry = self.geometry()
        self._normal_dpi_notification_visible = self.dpi_notification.isVisible()
        self._compact_log_mode = True
        if hasattr(self, "parameter_panel"):
            self.parameter_panel.sync_window_state(Qt.WindowState.WindowMinimized)
        self.workflow_tab_widget.hide()
        self.step_detail_label.hide()
        self.dpi_notification.hide()
        self.title_bar.hide()
        self.title_bar.set_file_actions_visible(False)
        self.title_bar.minimize_button.setToolTip("恢复")
        panel.show_logs()
        saved_size = panel.saved_window_size()
        if saved_size is None:
            self.resize(panel.PANEL_WIDTH, panel.EXPANDED_HEIGHT)
        else:
            self.resize(saved_size)
        normal_center = self._normal_window_geometry.center()
        self.move(
            normal_center.x() - self.width() // 2,
            normal_center.y() - self.height() // 2,
        )
        panel.show()
        self.activateWindow()

    @Slot(str, str, bool)
    def _forward_step_log(self, card_type: str, message: str, success: bool):
        if self._is_stale_executor_signal():
            return
        panel = getattr(self, "_execution_log_panel", None)
        if panel is not None:
            panel.on_step_log(card_type, message, success)




