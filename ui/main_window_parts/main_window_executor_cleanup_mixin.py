import logging
import warnings

logger = logging.getLogger(__name__)


class MainWindowExecutorCleanupMixin:
    def _cleanup_references(self):
        """Slot connected to QThread.finished signal to clear references."""
        logging.info("_cleanup_references: QThread finished signal received. Clearing executor and thread references.")
        executor_ref = getattr(self, 'executor', None)
        thread_ref = getattr(self, 'executor_thread', None)
        # 幂等保护：重复进入时直接返回，避免重复断连/重复日志噪音
        if executor_ref is None and thread_ref is None:
            logging.debug("_cleanup_references: already cleaned, skip duplicate call.")
            return
        if executor_ref is not None:
            logging.debug("_cleanup_references: Executor reference was not None, cleaning up signals and deleting.")
            # 精确断连已知处理函数，避免无参 disconnect() 触发 RuntimeWarning
            for signal_name, handler in (
                ('execution_started', self._handle_execution_started),
                ('execution_finished', self._handle_execution_finished),
                ('step_details', self._update_step_details),
                ('card_executing', self._handle_card_executing),
                ('card_finished', self._handle_card_finished),
                ('error_occurred', self._handle_error_occurred),
                ('path_updated', self._handle_path_updated),
                ('param_updated', self._handle_param_updated),
                ('path_resolution_failed', self._handle_path_resolution_failed),
                ('show_warning', self._show_warning_dialog),
                ('step_log', self._forward_step_log),
            ):
                signal_obj = getattr(executor_ref, signal_name, None)
                if signal_obj is None:
                    continue
                try:
                    # PySide6 在未连接时可能抛 RuntimeWarning 而不是异常
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", RuntimeWarning)
                        signal_obj.disconnect(handler)
                except (RuntimeError, TypeError):
                    # 未连接、已断开或对象处于销毁流程，均可安全忽略
                    pass
            try:
                # 调用deleteLater确保对象被正确清理
                if hasattr(executor_ref, 'deleteLater'):
                    executor_ref.deleteLater()
            except (RuntimeError, AttributeError) as e:
                logging.warning(f"_cleanup_references: Error calling deleteLater on executor: {e}")
        self.executor = None
        self._active_execution_task_id = None
        if thread_ref is not None:
            self.executor_thread = None
            logging.info("_cleanup_references: References cleaned (executor and thread set to None).")
            logging.info("_cleanup_references: 调用 _reset_run_button...")
            self._reset_run_button()
            self.step_detail_label.setText("等待执行...")
        else:
            # 允许仅清理executor的路径，不再记录警告
            logging.debug("_cleanup_references: executor_thread already None when cleaning executor.")
    def _disconnect_task_runtime_signals(self, task_id: int):
        """断开任务运行时信号，避免残留回调。"""
        binding = self._task_signal_bindings.pop(task_id, None)
        if not binding:
            return
        task = binding.get("task")
        if task is None:
            return
        execution_finished_handler = binding.get("execution_finished_handler")
        if execution_finished_handler is not None:
            try:
                task.execution_finished.disconnect(execution_finished_handler)
            except (TypeError, RuntimeError):
                pass
        for signal_name, handler in (
            ("card_executing", self._handle_card_executing),
            ("card_finished", self._handle_card_finished),
            ("progress_updated", self._update_step_details),
            ("param_updated", self._handle_param_updated),
        ):
            try:
                signal_obj = getattr(task, signal_name, None)
                if signal_obj is not None:
                    signal_obj.disconnect(handler)
            except (TypeError, RuntimeError):
                pass
        if binding.get("step_log_connected", False):
            try:
                if hasattr(task, "step_log"):
                    task.step_log.disconnect(self._forward_step_log)
            except (TypeError, RuntimeError):
                pass
    def _shutdown_executor_on_close(self, timeout_ms: int = 3000) -> bool:
        """关闭窗口前确定性回收执行线程与执行器引用。"""
        thread_ref = getattr(self, 'executor_thread', None)
        executor_ref = getattr(self, 'executor', None)
        try:
            if executor_ref is not None and hasattr(executor_ref, 'request_stop'):
                try:
                    executor_ref.request_stop(force=True)
                except TypeError:
                    executor_ref.request_stop()
        except Exception as e:
            logger.warning(f"关闭前请求执行器停止失败: {e}")
        if thread_ref is None:
            self.executor = None
            self._active_execution_task_id = None
            return True
        try:
            if thread_ref.isRunning():
                try:
                    thread_ref.quit()
                except Exception:
                    pass
                if not thread_ref.wait(max(500, int(timeout_ms))):
                    try:
                        thread_ref.terminate()
                    except Exception:
                        return False
                    if not thread_ref.wait(1000):
                        return False
        except Exception as e:
            logger.error(f"关闭前等待执行线程失败: {e}")
            return False
        finally:
            try:
                thread_ref.deleteLater()
            except Exception:
                pass
        self.executor_thread = None
        self.executor = None
        self._active_execution_task_id = None
        return True
