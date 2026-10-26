import logging

from ..control_center_parts.control_center_runtime import TaskState

logger = logging.getLogger(__name__)


class ControlCenterWindowLifecycleMixin:
    def _iter_all_window_runners(self):
        for runners in list(self.window_runners.values()):
            for runner in runners:
                if self._is_qt_runner_valid(runner):
                    yield runner

    def is_any_task_running(self) -> bool:
        """检查中控是否有任何任务正在运行

        Returns:
            True if any task is running in control center, False otherwise
        """
        if self._runner_start_queue:
            return True
        for window_id, runners in self.window_runners.items():
            for runner in runners:
                try:
                    if runner.has_pending_work:
                        return True
                except Exception:
                    continue
        return False


    def log_message(self, message):
        """Append a message to logger and on-screen log view."""
        import datetime
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        logger.info(f"[{timestamp}] {message}")
        if hasattr(self, "log_output") and self.log_output is not None:
            self.log_output.append(f"[{timestamp}] {message}")

    def closeEvent(self, event):
        """窗口关闭事件"""
        if self._is_closing:
            event.accept()
            return
        logger.info("中控窗口关闭，开始异步停止所有任务")
        self._is_closing = True
        try:
            self._stop_hwnd_watchdog()
        except Exception as e:
            logger.warning(f"关闭中控时停止句柄看门狗失败: {e}")
        try:
            self._release_control_center_hotkeys()
        except Exception as e:
            logger.warning(f"关闭中控时释放热键失败: {e}")
        try:
            self._stop_all_control_timers(reset_state=False, persist=False, resume_if_timed=False)
        except Exception as e:
            logger.warning(f"关闭中控时停止定时器失败: {e}")
        self._ocr_check_timer_active = False
        self._pending_valid_windows = None
        self._pending_windows = []
        self._start_all_in_progress = False
        self._cancel_start_sequence = True
        self._runner_dispatch_suspended = True

        for runner in self._iter_all_window_runners():
            self._disconnect_window_task_runner(runner)
        self._request_close_runners_stop()
        self._handoff_control_center_shutdown()
        self.window_runners.clear()
        self._window_workflow_results.clear()
        self._runner_start_queue.clear()

        if self.parent_window and hasattr(self.parent_window, "_on_control_center_closed"):
            self.parent_window._on_control_center_closed()
            logger.info("已恢复主窗口快捷键")

        event.accept()
        logger.info("中控窗口关闭事件已接受")

    def _request_close_runners_stop(self):
        for runner in list(self._iter_all_window_runners()):
            try:
                self._remove_runner_from_start_queue(runner)
                runner_thread_running = self._safe_runner_thread_running(runner)
                if runner.can_stop or runner_thread_running or runner.current_state == TaskState.IDLE:
                    runner.stop()
                    logger.debug("已请求停止runner: %s", self._safe_runner_window_id(runner))
                if not runner_thread_running:
                    runner.deleteLater()
            except Exception as stop_err:
                logger.warning("关闭中控时停止runner失败: %s", stop_err)

    def _handoff_control_center_shutdown(self):
        from .control_center_shutdown import (
            ControlCenterShutdownSession,
            collect_close_runners,
        )

        session = ControlCenterShutdownSession(collect_close_runners(self.window_runners))
        parent = self.parent_window
        if parent is None:
            raise RuntimeError("中控关闭收尾需要所属主窗口接管")
        parent._begin_control_center_shutdown(session)
        logger.info("已将中控关闭收尾交给主窗口，orphans=%s", len(session.orphans))
