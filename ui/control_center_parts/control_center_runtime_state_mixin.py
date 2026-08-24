import logging

from app_core.control_plane import can_transition, default_step_for

from .control_center_runtime_types import TaskState

logger = logging.getLogger(__name__)


class WindowTaskRunnerStateMixin:

    def _emit_step(self, step_info: str):
        text = str(step_info or "").strip()
        self._last_status_message = text
        self.step_updated.emit(self.window_id, text)

    def _set_state(self, new_state: TaskState, step_info: str = None, *, force: bool = False):
        """设置任务状态并发送信号"""
        step_text = step_info
        if self._current_state != new_state:
            if not force and not can_transition(self._current_state, new_state):
                logger.warning(
                    "窗口%s拒绝状态转换: %s -> %s",
                    self.window_id,
                    self._current_state.value,
                    new_state.value,
                )
                return
            logger.info(f"窗口{self.window_id}状态变更: {self._current_state.value} -> {new_state.value}")
            self._current_state = new_state
            if not step_text:
                step_text = default_step_for(new_state)
            self._last_status_message = str(step_text or "").strip()
            self.status_updated.emit(self.window_id, new_state.value)
            self.step_updated.emit(self.window_id, step_text)
            return
        if step_text:
            self._last_status_message = str(step_text).strip()

    def _emit_task_completed_once(self, success: bool):
        """任务完成信号只允许发出一次，避免停止竞态触发重复收尾。"""
        if self._task_completed_emitted:
            return
        self._task_completed_emitted = True
        self._last_execution_success = bool(success)
        if not str(getattr(self, "_last_execution_message", "") or "").strip():
            self._last_execution_message = str(getattr(self, "_last_status_message", "") or "").strip()
        self.task_completed.emit(self.window_id, success)

    def _defer_cleanup_until_thread_finished(self):
        """线程未退出前禁止清理运行中资源，避免停止时回收导致闪退。"""
        self._cleanup_deferred_until_finish = True

    def _on_thread_finished(self):
        """线程真正退出后再执行兜底收尾。"""
        logger.info(f"窗口{self.window_id}线程已退出，开始执行最终收尾检查")
        if self._current_state == TaskState.STOPPING and not self._task_completed_emitted:
            self._set_state(TaskState.STOPPED, "工作流已中断", force=True)
            self._emit_task_completed_once(False)
        if self._cleanup_deferred_until_finish and not self._is_cleaned:
            self._cleanup_thread()

    def _can_transition_to(self, new_state: TaskState) -> bool:
        return can_transition(self._current_state, new_state)

    @property
    def current_state(self) -> TaskState:
        """获取当前状态"""
        return self._current_state

    @property
    def is_running(self) -> bool:
        """检查是否正在运行"""
        try:
            thread_running = bool(self.isRunning())
        except Exception:
            thread_running = False
        return bool(
            thread_running
            or self._cleanup_deferred_until_finish
            or self._current_state in [TaskState.STARTING, TaskState.RUNNING, TaskState.PAUSED, TaskState.STOPPING]
        )

    @property
    def has_pending_work(self) -> bool:
        """检查是否仍有未完成的启动或执行流程。"""
        if self.is_running:
            return True
        if self._queued_for_start:
            return True
        return bool(not self._task_completed_emitted and self._current_state == TaskState.IDLE)

    @property
    def can_start(self) -> bool:
        """检查是否可以启动"""
        return self._current_state in [TaskState.IDLE, TaskState.STOPPED, TaskState.COMPLETED, TaskState.FAILED]

    @property
    def can_stop(self) -> bool:
        """检查是否可以停止"""
        return self._current_state in [TaskState.STARTING, TaskState.RUNNING, TaskState.PAUSED]

    def _abort_if_stop_requested(self, step_info: str = "启动前已取消") -> bool:
        """启动阶段检测停止请求，防止竞态下继续创建执行器。"""
        if not self._should_stop:
            return False
        self._set_state(TaskState.STOPPED, step_info, force=True)
        self._emit_task_completed_once(False)
        return True

