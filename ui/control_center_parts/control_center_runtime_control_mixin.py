import logging

from .control_center_runtime_types import TaskState

logger = logging.getLogger(__name__)


class WindowTaskRunnerControlMixin:

    def _cleanup_thread(self):
        """清理执行器线程和相关资源"""
        if self._is_cleaned:
            return
        if self.isRunning():
            self._defer_cleanup_until_thread_finished()
            return
        self._stop_completion_timer.stop()
        self._is_cleaned = True
        self._cleanup_deferred_until_finish = False
        errors = []
        if self.hwnd:
            try:
                from services.multiprocess_ocr_pool import get_existing_multiprocess_ocr_pool

                pool = get_existing_multiprocess_ocr_pool()
                if pool is not None:
                    pool.unregister_window(self.hwnd)
            except Exception as exc:
                errors.append(f"注销窗口 OCR 服务失败: {exc}")
            try:
                from utils.capture.screenshot_helper import cleanup_screenshot_engine

                cleanup_screenshot_engine(self.hwnd)
            except Exception as exc:
                errors.append(f"清理窗口截图引擎失败: {exc}")
        for runtime_object in (self.executor, self.executor_thread):
            if runtime_object is not None:
                try:
                    runtime_object.deleteLater()
                except Exception as exc:
                    errors.append(f"销毁工作流运行对象失败: {exc}")
        self.executor = None
        self.executor_thread = None
        self._is_running = False
        self._queued_for_start = False
        if errors:
            message = "; ".join(errors)
            self._last_execution_success = False
            self._last_execution_message = message
            self._set_state(TaskState.FAILED, message, force=True)
            self.runtime_alert.emit(self.window_id, message)
            logger.error(message)

    def stop(self):
        """停止工作流执行"""
        logger.info(f"收到停止请求，当前状态: {self._current_state.value}")

        # 无论当前状态如何，先记录停止意图，供 run() 启动阶段检查。
        self._should_stop = True

        # 检查是否可以停止
        if not self.can_stop:
            if self._current_state == TaskState.IDLE:
                logger.info(f"窗口{self.window_id}启动前收到停止请求，已标记取消")
                self._queued_for_start = False
                self._set_state(TaskState.STOPPED, "工作流已中断", force=True)
                self._emit_task_completed_once(False)
            else:
                logger.warning(f"窗口{self.window_id}当前状态{self._current_state.value}不允许停止")
            return

        # 立即设置停止状态
        self._set_state(TaskState.STOPPING, "正在停止工作流")

        # 停止执行器（使用强制停止模式）
        if hasattr(self, 'executor') and self.executor:
            try:
                # 这里不能用QueuedConnection：
                # WindowTaskRunner.run()没有启动Qt事件循环，排队信号不会被处理。
                self.executor.request_stop(force=True)
                logger.info(f"窗口{self.window_id}工作流强制停止请求已发送")
            except Exception as e:
                logger.warning(f"停止执行器时发生错误: {e}")

        # 缩短超时时间到1秒（原2秒）
        self._stop_completion_timer.start()

    def pause(self) -> bool:
        """暂停当前工作流。"""
        if not self._can_transition_to(TaskState.PAUSED):
            return False
        executor = getattr(self, "executor", None)
        if executor is None or not hasattr(executor, "pause"):
            return False
        if getattr(executor, "_paused", False) or self.current_state == TaskState.PAUSED:
            return False
        if not self.is_running:
            return False

        if executor.pause() is not True:
            return False
        self._set_state(TaskState.PAUSED, "工作流已暂停")
        return True

    def resume(self) -> bool:
        """恢复当前工作流。"""
        if self.current_state != TaskState.PAUSED:
            return False
        executor = getattr(self, "executor", None)
        if executor is None or not hasattr(executor, "resume"):
            return False
        if not getattr(executor, "_paused", False) and self.current_state != TaskState.PAUSED:
            return False

        if executor.resume() is not True:
            return False
        self._set_state(TaskState.RUNNING, "工作流已恢复")
        return True

    def _force_stop_completion(self):
        """强制完成停止操作（防止卡住）"""
        if self._current_state == TaskState.STOPPING:
            if self.isRunning():
                self._defer_cleanup_until_thread_finished()
                logger.warning(f"窗口{self.window_id}停止超时，但线程仍在运行，等待线程退出后再清理资源")
                return
            logger.warning(f"窗口{self.window_id}停止超时，强制设置为已停止状态")
            self._set_state(TaskState.STOPPED, "工作流已强制停止", force=True)
            self._emit_task_completed_once(False)
            self._cleanup_thread()

