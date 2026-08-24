import logging

from .main_window_support import normalize_execution_mode_setting

from PySide6.QtWidgets import QMessageBox

logger = logging.getLogger(__name__)


class MainWindowExecutionFlowRuntimeMixin:

    def _on_task_execution_finished(self, task_id: int, success: bool, message: str, stop_reason: str):

        """

        任务执行完成后的跳转处理

        Args:

            task_id: 完成的任务ID

            success: 是否成功

            message: 执行结果消息

            stop_reason: 停止原因 ('success', 'failed', 'no_next')

        """

        logger.info("========== _on_task_execution_finished 被调用 ==========")

        logger.info(f"task_id={task_id}, success={success}, stop_reason={stop_reason}")

        logger.info(f"当前状态: _jump_cancelled={getattr(self, '_jump_cancelled', False)}, _is_jumping={getattr(self, '_is_jumping', False)}")

        task = self.task_manager.get_task(task_id)

        if not task:

            logger.warning(f"无法找到task_id={task_id}的任务")

            logger.info("========== _on_task_execution_finished 结束（任务不存在） ==========")

            return

        self._last_finished_task_id = task_id

        logger.info(f"任务 '{task.name}' 执行完成，停止原因: {stop_reason}")

        if not success and stop_reason == 'failed':

            try:

                error_text = str(message or f"任务 '{task.name}' 执行失败").strip()


                QMessageBox.warning(self, "执行失败", error_text)

            except Exception as popup_error:

                logger.warning(f"任务失败弹窗提示失败: {popup_error}")

        # 用户停止只取消后续跳转，不再启动新的跳转。

        if getattr(self, '_jump_cancelled', False):

            logger.warning("检测到跳转已被取消（用户按下停止），不启动新的跳转")

            self._is_jumping = False

            self._check_and_reset_button_after_workflow()

            logger.info("========== _on_task_execution_finished 结束（已取消） ==========")

            return

        running_count = self.task_manager.get_running_count() if hasattr(self, 'task_manager') else 0
        has_active_runtime = False
        if hasattr(self, 'task_manager'):
            runtime_checker = getattr(self.task_manager, 'has_active_runtime_tasks', None)
            if callable(runtime_checker):
                try:
                    has_active_runtime = bool(runtime_checker())
                except Exception:
                    has_active_runtime = False
        has_active_timers = False
        if hasattr(self, '_active_jump_timers'):
            try:
                has_active_timers = any(timer.isActive() for timer in self._active_jump_timers if timer)
            except Exception:
                has_active_timers = False
        is_jumping = getattr(self, '_is_jumping', False)
        # 检查执行模式 - 非跳转模式下不进行跳转

        self._check_and_reset_button_after_workflow()

        return

    def _update_task_execution_mode(self, task):

        """更新任务的执行模式（前台/后台）"""

        # 判断是否可以使用前台模式

        # 规则:

        #   - 单窗口 + 单工作流: 可以使用任意模式(前台/后台/模拟器)

        #   - 单窗口 + 多工作流: 可以使用后台/模拟器模式(前台模式强制改为后台)

        #   - 多窗口 + 任意工作流: 可以使用后台/模拟器模式(前台模式强制改为后台)

        executable_tasks_count = len(self.task_manager.get_executable_tasks())

        is_multi_window = self.window_binding_mode == 'multiple'

        is_multi_workflow = executable_tasks_count > 1

        # Execution mode selection

        configured_mode = getattr(self, 'current_execution_mode', None)

        if not configured_mode:

            configured_mode = normalize_execution_mode_setting(

                self.config.get('execution_mode', 'background_sendmessage')

            )

        # 检查是否选择了前台模式

        if configured_mode.startswith('foreground'):

            # 前台模式需要满足: 单窗口 + 单工作流

            reasons = []

            if is_multi_window:

                reasons.append("多窗口绑定")

            if is_multi_workflow:

                reasons.append(f"{executable_tasks_count}个工作流")

            if reasons:

                # 不满足前台模式条件,强制切换为后台模式

                reason_str = " + ".join(reasons)

                task.execution_mode = configured_mode

                logger.warning(f"任务 '{task.name}': {reason_str}，前台模式条件不满足，保持 {configured_mode}")

            else:

                # 满足前台模式条件(单窗口+单工作流),使用用户选择的前台模式

                task.execution_mode = configured_mode

                logger.info(f"任务 '{task.name}': 单窗口+单工作流，使用前台模式 {configured_mode}")

        else:

            # 后台模式或模拟器模式,没有窗口/工作流数量限制,直接使用

            if is_multi_window or is_multi_workflow:

                conditions = []

                if is_multi_window:

                    conditions.append("多窗口")

                if is_multi_workflow:

                    conditions.append(f"{executable_tasks_count}个工作流")

                condition_str = " + ".join(conditions)

                logger.info(f"任务 '{task.name}': {condition_str}，使用后台/模拟器模式 {configured_mode}")

            else:

                logger.info(f"任务 '{task.name}': 单窗口+单工作流，使用 {configured_mode} 模式")

            task.execution_mode = configured_mode

        logger.info(f"任务 '{task.name}' 执行模式: {task.execution_mode}")

    def _check_and_reset_button_after_workflow(self):

        """检查工作流和跳转状态，如果都已完成则重置按钮"""

        try:

            # 检查是否有任务正在运行

            running_count = self.task_manager.get_running_count() if hasattr(self, 'task_manager') else 0
            has_active_runtime = False
            if hasattr(self, 'task_manager'):
                runtime_checker = getattr(self.task_manager, 'has_active_runtime_tasks', None)
                if callable(runtime_checker):
                    try:
                        has_active_runtime = bool(runtime_checker())
                    except Exception:
                        has_active_runtime = False

            # 检查是否有活动的跳转定时器

            has_active_timers = False

            if hasattr(self, '_active_jump_timers'):

                has_active_timers = any(timer.isActive() for timer in self._active_jump_timers if timer)

            # 检查是否正在跳转（使用getattr以避免AttributeError）

            is_jumping = getattr(self, '_is_jumping', False)

            logger.info(f"检查工作流状态: running_count={running_count}, _is_jumping={is_jumping}, has_active_timers={has_active_timers}")

            # 如果没有任务运行、没有跳转、也没有活动的定时器，才重置按钮

            if running_count == 0 and not has_active_runtime and not is_jumping and not has_active_timers:

                logger.info("工作流和跳转都已完成，重置启动/停止按钮")

                self._reset_run_button()

                try:

                    from utils.runtime_image_cleanup import cleanup_yolo_runtime_on_stop

                    cleanup_yolo_runtime_on_stop(

                        release_engine=True,

                        compact_memory=True,

                    )

                except Exception as yolo_cleanup_err:

                    logger.debug(f"工作流完成后清理YOLO运行态失败: {yolo_cleanup_err}")

                if self.task_state_manager:

                    try:

                        self.task_state_manager.confirm_stopped()

                        logger.info("任务状态管理器已确认停止（检查流程完成）")

                    except Exception as state_err:

                        logger.warning(f"任务状态管理器确认停止失败: {state_err}")

            else:

                logger.info("工作流或跳转仍在进行中，保持停止按钮状态")

        except Exception as e:

            logger.error(f"检查工作流状态时出错: {e}", exc_info=True)

            # 出错时安全地重置按钮

            try:

                self._reset_run_button()

            except Exception:

                pass

    # ========================================

    # 全局定时器功能























            logger.error(f"恢复任务时出错: {e}")

    def _execute_single_task(self, task_id: int):

        """执行单个指定的任务"""

        try:

            task = self.task_manager.get_task(task_id)

            if not task:

                logger.warning(f"找不到任务: task_id={task_id}")

                return

            logger.info(f"执行单个任务: {task.name}, task_id={task_id}")

            # 执行前重置卡片状态

            self._reset_all_workflow_card_states("执行单个任务前重置卡片状态")

            # 切换到对应的标签页

            tab_index = self.workflow_tab_widget.task_to_tab.get(task_id)

            if tab_index is not None:

                self.workflow_tab_widget.setCurrentIndex(tab_index)

            # 检查并设置执行模式

            self._update_task_execution_mode(task)

            # 启动单个任务

            task.execute_async()

            # 更新主窗口按钮状态为“停止”

            self._set_toolbar_to_stop_state()

        except Exception as e:

            logger.error(f"执行单个任务失败: {e}")

    def _stop_all_tasks(self):

        """停止所有任务"""

        from PySide6.QtWidgets import QMessageBox

        try:

            is_running = bool(self._is_any_workflow_running())

        except Exception:

            is_running = False

        if not is_running:

            QMessageBox.information(self, "提示", "没有正在运行的任务")

            return

        # 确认停止

        reply = QMessageBox.question(

            self,

            "确认停止",

            "确定要停止正在运行的任务吗？",

            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No

        )

        if reply == QMessageBox.StandardButton.No:

            return

        logger.info("停止所有任务")

        self.safe_stop_tasks()

    def _on_run_stop_button_clicked(self):

        """运行/停止/恢复按钮点击处理"""

        try:

            # 根据按钮当前显示的文本判断应该执行什么操作

            button_text = self.run_action.text()

            logger.info(f"=== 按钮点击：当前按钮文本='{button_text}' ===")

            if button_text == "运行所有任务":

                # 停止状态 → 启动任务

                self.safe_start_tasks()

            elif button_text == "停止":

                # 运行状态 → 停止任务

                self.safe_stop_tasks()

            elif button_text == "恢复":

                # 暂停状态 → 恢复任务

                self._resume_workflow()

        except Exception as e:

            logger.error(f"按钮点击处理失败: {e}")

            import traceback

            logger.error(traceback.format_exc())

    def request_stop_workflow(self):

        """Requests the running workflow to stop."""

        # 统一走 safe_stop_tasks，确保所有执行链路（任务管理器/旧执行器/多窗口）都被停止。

        self.safe_stop_tasks()

        return
