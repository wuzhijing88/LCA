import logging

from .control_center_runtime_types import TaskState

logger = logging.getLogger(__name__)


class WindowTaskRunnerStateMixin:

    def _set_state(self, new_state: TaskState, step_info: str = None):
        """设置任务状态并发送信号"""
        step_text = step_info
        if self._current_state != new_state:
            logger.info(f"窗口{self.window_id}状态变更: {self._current_state.value} -> {new_state.value}")
            self._current_state = new_state

            # 发送状态更新信号
            self.status_updated.emit(self.window_id, new_state.value)

            # 发送步骤更新信号
            if step_text:
                self.step_updated.emit(self.window_id, step_text)
            else:
                # 使用默认步骤信息
                default_steps = {
                    TaskState.IDLE: "等待开始",
                    TaskState.STARTING: "正在启动工作流",
                    TaskState.RUNNING: "工作流运行中",
                    TaskState.STOPPING: "正在停止工作流",
                    TaskState.STOPPED: "工作流已中断",
                    TaskState.COMPLETED: "工作流已完成",
                    TaskState.FAILED: "工作流执行失败"
                }
                step_text = default_steps.get(new_state, "未知状态")
                self.step_updated.emit(self.window_id, step_text)

        self._last_status_message = str(step_text or "").strip()

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
            self._set_state(TaskState.STOPPED, "工作流已中断")
            self._emit_task_completed_once(False)
        if self._cleanup_deferred_until_finish and not self._is_cleaned:
            self._cleanup_thread()

    def _can_transition_to(self, new_state: TaskState) -> bool:
        """检查是否可以转换到新状态"""
        valid_transitions = {
            TaskState.IDLE: [TaskState.STARTING],
            TaskState.STARTING: [TaskState.RUNNING, TaskState.FAILED, TaskState.STOPPING],
            TaskState.RUNNING: [TaskState.STOPPING, TaskState.COMPLETED, TaskState.FAILED],
            TaskState.STOPPING: [TaskState.STOPPED, TaskState.FAILED],
            TaskState.STOPPED: [TaskState.STARTING],  # 可以重新启动
            TaskState.COMPLETED: [TaskState.STARTING],  # 可以重新启动
            TaskState.FAILED: [TaskState.STARTING]  # 可以重新启动
        }

        allowed = valid_transitions.get(self._current_state, [])
        return new_state in allowed

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
            or self._current_state in [TaskState.STARTING, TaskState.RUNNING, TaskState.STOPPING]
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
        return self._current_state in [TaskState.STARTING, TaskState.RUNNING]

    def _abort_if_stop_requested(self, step_info: str = "启动前已取消") -> bool:
        """启动阶段检测停止请求，防止竞态下继续创建执行器。"""
        if not self._should_stop:
            return False
        self._set_state(TaskState.STOPPED, step_info)
        self._emit_task_completed_once(False)
        return True

