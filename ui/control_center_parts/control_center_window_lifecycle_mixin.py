import logging
import os

from PySide6.QtCore import QTimer

from ..control_center_parts.control_center_runtime import TaskState

logger = logging.getLogger(__name__)


class ControlCenterWindowLifecycleMixin:
    def _iter_all_window_runners(self):
        for runners in list(self.window_runners.values()):
            if isinstance(runners, list):
                for runner in runners:
                    if self._is_qt_runner_valid(runner):
                        yield runner
                continue
            if self._is_qt_runner_valid(runners):
                yield runners

    def is_any_task_running(self) -> bool:
        """检查中控是否有任何任务正在运行

        Returns:
            True if any task is running in control center, False otherwise
        """
        if self._runner_start_queue:
            return True
        for window_id, runners in self.window_runners.items():
            if not isinstance(runners, list):
                runners = [runners]
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
        # 工具 关键修复：使用异步方式停止任务，避免阻塞主线程导致UI冻结
        logger.info("中控窗口关闭，开始异步停止所有任务")
        self._is_closing = True
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

        # 停止所有运行中的任务（不等待）
        for runners in list(self.window_runners.values()):
            if isinstance(runners, list):
                for runner in runners:
                    try:
                        self._remove_runner_from_start_queue(runner)
                        if not self._is_qt_runner_valid(runner):
                            continue
                        runner_thread_running = self._safe_runner_thread_running(runner)
                        if runner.can_stop or runner_thread_running or runner.current_state == TaskState.IDLE:
                            runner.stop()
                            logger.debug(f"已请求停止runner: {self._safe_runner_window_id(runner)}")
                    except Exception as stop_err:
                        logger.warning(f"关闭中控时停止runner失败: {stop_err}")
            else:
                # 兼容旧代码，如果存储的是单个runner
                try:
                    self._remove_runner_from_start_queue(runners)
                    if not self._is_qt_runner_valid(runners):
                        continue
                    runner_thread_running = self._safe_runner_thread_running(runners)
                    if runners.can_stop or runner_thread_running or runners.current_state == TaskState.IDLE:
                        runners.stop()
                        logger.debug(f"已请求停止runner: {self._safe_runner_window_id(runners)}")
                except Exception as stop_err:
                    logger.warning(f"关闭中控时停止runner失败: {stop_err}")

        from PySide6.QtCore import QTimer

        def delayed_cleanup():
            """延迟清理所有线程"""
            logger.info("开始延迟清理中控窗口资源")
            for runners in list(self.window_runners.values()):
                if isinstance(runners, list):
                    for runner in runners:
                        if not self._is_qt_runner_valid(runner):
                            continue
                        runner_id = self._safe_runner_window_id(runner)
                        if self._safe_runner_thread_running(runner):
                            logger.warning(f"线程仍在运行，尝试优雅停止: {runner_id}")
                            try:
                                if hasattr(runner, "stop"):
                                    runner.stop()
                                runner.requestInterruption()
                                runner.quit()
                                if runner.wait(3000):
                                    logger.debug(f"线程已停止: {runner_id}")
                                else:
                                    logger.error(f"线程未能在超时内停止(保留引用避免闪退): {runner_id}")
                                    self._orphaned_threads.append(runner)
                            except Exception as e:
                                logger.error(f"停止线程失败: {e}")
                else:
                    if not self._is_qt_runner_valid(runners):
                        continue
                    runner_id = self._safe_runner_window_id(runners)
                    if self._safe_runner_thread_running(runners):
                        logger.warning(f"线程仍在运行，尝试优雅停止: {runner_id}")
                        try:
                            if hasattr(runners, "stop"):
                                runners.stop()
                            runners.requestInterruption()
                            runners.quit()
                            if runners.wait(3000):
                                logger.debug(f"线程已停止: {runner_id}")
                            else:
                                logger.error(f"线程未能在超时内停止(保留引用避免闪退): {runner_id}")
                                self._orphaned_threads.append(runners)
                        except Exception as e:
                            logger.error(f"停止线程失败: {e}")

            self.window_runners.clear()
            self._window_workflow_results.clear()
            self._runner_start_queue.clear()
            alive_orphans = []
            for t in self._orphaned_threads:
                if self._safe_runner_thread_running(t):
                    alive_orphans.append(t)
            self._orphaned_threads = alive_orphans

            # 关闭中控时强制回收OCR子进程，覆盖预创建链路残留
            try:
                self._force_cleanup_ocr_processes()
            except Exception as e:
                logger.error(f"中控窗口关闭时OCR清理失败: {e}")

            logger.info("中控窗口资源清理完成")
            os.environ.pop('MULTI_WINDOW_MODE', None)
            self._refresh_multi_window_mode_env()

        # 2秒后执行清理（给线程足够时间优雅退出）
        QTimer.singleShot(2000, delayed_cleanup)
        logger.info("已启动清理定时器（2秒后执行）")

        # 清除临时工作流配置文件
        self._clear_workflow_config()

        # 恢复主窗口的快捷键
        if self.parent_window and hasattr(self.parent_window, '_on_control_center_closed'):
            self.parent_window._on_control_center_closed()
            logger.info("已恢复主窗口快捷键")

        # 立即接受关闭事件，不阻塞UI
        event.accept()
        logger.info("中控窗口关闭事件已接受")
