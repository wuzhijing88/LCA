import logging

logger = logging.getLogger(__name__)


class MainWindowExecutionFlowJumpMixin:

    def _prune_inactive_jump_timers(self):

        """清理已失效/已触发的跳转定时器引用，避免列表长期累积。"""

        timers = getattr(self, "_active_jump_timers", None)

        if not isinstance(timers, list):

            return

        active_timers = []

        for timer in timers:

            if timer is None:

                continue

            try:

                if timer.isActive():

                    active_timers.append(timer)

                else:

                    timer.deleteLater()

            except RuntimeError:

                continue

        self._active_jump_timers = active_timers

    def _discard_jump_timer(self, timer):

        """Stop and release a jump timer."""

        if not timer:

            return

        try:

            if timer.isActive():

                timer.stop()

        except RuntimeError:

            pass

        try:

            timer.deleteLater()

        except RuntimeError:

            pass

        if hasattr(self, '_active_jump_timers'):

            try:

                self._active_jump_timers.remove(timer)

            except ValueError:

                pass

    def _execute_jump_target(self, task_id: int, timer=None):

        """执行跳转目标任务

        Args:

            task_id: 目标任务ID

            timer: 触发此执行的定时器（用于清理）

        """

        logger.info("========== _execute_jump_target 被调用 ==========")

        logger.info(f"task_id={task_id}")

        logger.info(f"当前状态: _jump_cancelled={getattr(self, '_jump_cancelled', False)}, _is_jumping={getattr(self, '_is_jumping', False)}")

        try:

            # 立即检查是否已被取消（使用getattr安全访问）

            if getattr(self, '_jump_cancelled', False):

                logger.warning("检测到跳转执行已被取消（用户按下停止），终止执行")

                self._is_jumping = False

                self._check_and_reset_button_after_workflow()

                # 清理定时器

                if timer:

                    self._discard_jump_timer(timer)

                logger.info("========== _execute_jump_target 结束（已取消） ==========")

                return

            # 检查是否已经停止（跳转深度为0表示已停止）

            if self.task_manager._current_jump_depth == 0:

                logger.info("跳转执行已被取消（任务已停止）")

                self._is_jumping = False

                self._check_and_reset_button_after_workflow()

                # 清理定时器

                if timer:

                    self._discard_jump_timer(timer)

                return

            # 清理定时器（在执行前清理，因为马上就要执行了）

            if timer:

                self._discard_jump_timer(timer)

            task = self.task_manager.get_task(task_id)

            if task and task.can_execute():

                logger.info(f"执行跳转目标任务: {task.name}")

                # 重置当前标签页的卡片状态，防止显示错误的状态（如红色）

                current_workflow_view = self.workflow_tab_widget.task_views.get(task_id)

                if current_workflow_view:

                    logger.info(f"重置目标任务 '{task.name}' 的卡片状态")

                    current_workflow_view.reset_card_states()

                # 更新工具栏按钮为停止状态

                self._set_toolbar_to_stop_state()

                # 更新任务的窗口绑定

                self._update_task_window_binding(task)

                # 异步执行

                task.execute_async()

            else:

                logger.warning(f"目标任务无法执行: task_id={task_id}")

                self.task_manager._current_jump_depth = 0

                self._is_jumping = False

                # 检查是否需要重置按钮（考虑其他跳转）

                self._check_and_reset_button_after_workflow()

        except Exception as e:

            logger.error(f"执行跳转目标任务失败: {e}", exc_info=True)

            self.task_manager._current_jump_depth = 0

            self._is_jumping = False

            # 检查是否需要重置按钮（考虑其他跳转）

            self._check_and_reset_button_after_workflow()

    def _on_task_added_for_jump(self, task_id: int):

        """任务添加后，连接其信号以处理跳转和步骤显示"""

        task = self.task_manager.get_task(task_id)

        if not task:

            return

        existed_binding = self._task_signal_bindings.get(task_id)

        if existed_binding and existed_binding.get("task") is task:

            return

        if existed_binding:

            self._disconnect_task_runtime_signals(task_id)

        def execution_finished_handler(success, message, stop_reason):

            self._on_task_execution_finished(task_id, success, message, stop_reason)

        task.execution_finished.connect(execution_finished_handler)

        task.card_executing.connect(self._handle_card_executing)

        task.card_finished.connect(self._handle_card_finished)

        task.progress_updated.connect(self._update_step_details)

        step_log_connected = False

        if hasattr(task, "step_log") and hasattr(self, "_floating_window") and self._floating_window:

            task.step_log.connect(self._forward_step_log)

            step_log_connected = True

        if hasattr(task, "param_updated"):

            task.param_updated.connect(self._handle_param_updated)

        self._task_signal_bindings[task_id] = {

            "task": task,

            "execution_finished_handler": execution_finished_handler,

            "step_log_connected": step_log_connected,

        }

        logger.info(f"已连接任务 {task.name} 的卡片状态信号 (card_executing, card_finished, progress_updated)")

    def _on_task_removed_for_jump(self, task_id: int):

        """任务移除后，解绑运行时信号。"""

        self._disconnect_task_runtime_signals(task_id)
