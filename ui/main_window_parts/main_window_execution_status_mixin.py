import logging

logger = logging.getLogger(__name__)


class MainWindowExecutionStatusMixin:

    def _is_stale_executor_signal(self) -> bool:

        """过滤历史执行器残留信号，防止执行结束后继续触发UI更新。"""

        try:

            signal_sender = self.sender()

        except Exception:

            return False

        if signal_sender is None:

            return False

        # 仅拦截来自 WorkflowExecutor 的残留信号，任务级信号不受影响

        if not hasattr(signal_sender, "test_mode"):

            return False

        current_executor = getattr(self, "executor", None)

        if current_executor is None:

            return True

        return signal_sender is not current_executor

    def _auto_reset_after_completion(self, success: bool, message: str):

        """任务完成后自动重置状态"""

        # 防重复调用机制

        if hasattr(self, '_auto_reset_in_progress') and self._auto_reset_in_progress:

            logger.debug("自动重置已在进行中，跳过重复调用")

            return

        self._auto_reset_in_progress = True

        try:

            logger.info(f"自动重置状态: 成功={success}, 消息={message}")

            # 任务完成后不清除卡片状态，保留成功/失败的颜色

            # logger.info("重置所有卡片状态和停止闪烁效果")

            # self.workflow_view.reset_card_states()

            # 额外确保停止所有闪烁效果

            # 【修复闪退】安全访问cards字典

            try:

                if hasattr(self, 'workflow_view') and self.workflow_view and hasattr(self.workflow_view, 'cards'):

                    cards_snapshot = dict(self.workflow_view.cards)

                    for card_id, card in cards_snapshot.items():

                        if card and hasattr(card, 'stop_flash'):

                            try:

                                card.stop_flash()

                            except (RuntimeError, AttributeError):

                                pass

                    logger.debug("已确保停止所有卡片的闪烁效果")

            except Exception as e:

                logger.warning(f"停止卡片闪烁效果失败: {e}")

            # 重置运行按钮

            self._reset_run_button()

            try:

                from utils.runtime_image_cleanup import cleanup_yolo_runtime_on_stop

                cleanup_yolo_runtime_on_stop(

                    release_engine=True,

                    compact_memory=True,

                )

            except Exception:

                pass

            # --- ADDED: 确认任务停止状态 ---

            if self.task_state_manager:

                self.task_state_manager.confirm_stopped()

                logger.info("任务状态管理器已确认停止（多窗口完成）")

            # ----------------------------

            # 清理多窗口执行器

            if hasattr(self, 'multi_executor') and self.multi_executor:

                try:

                    # 如果有增强停止管理器，清理它

                    if hasattr(self.multi_executor, 'stop_integration'):

                        self.multi_executor.stop_integration.cleanup()

                    # 重置执行器状态

                    self.multi_executor.is_running = False

                    logger.debug("多窗口执行器状态已重置")

                except Exception as e:

                    logger.error(f"清理多窗口执行器失败: {e}")

            # 显示完成通知

            if success:

                logger.info(f"成功 任务执行完成: {message}")

            else:

                logger.warning(f"警告 任务执行失败: {message}")

        except Exception as e:

            logger.error(f"自动重置状态失败: {e}")

        finally:

            # 重置防重复调用标志

            self._auto_reset_in_progress = False

    def _on_task_status_changed(self, task_id: int, status: str):

        """任务状态变化处理（用于更新工具栏按钮）"""

        logging.debug(f"_on_task_status_changed: 任务 {task_id} 状态变为 {status}")

        # 通知浮动窗口任务状态变化

        if hasattr(self, '_floating_controller') and self._floating_controller:

            if status == 'running':

                self._floating_controller.on_workflow_started()

            elif status in ['completed', 'failed', 'stopped']:

                self._floating_controller.on_workflow_finished(status == 'completed', status)

        # 【修复】执行中时不更新状态栏，让详细步骤信息显示

        # 只在非执行状态时更新状态栏

        if status not in ['running', 'paused']:

            self._update_status_bar()

        # 检查是否还有运行中或暂停的任务

        running_or_paused_tasks = [t for t in self.task_manager.get_all_tasks() if t.status in ['running', 'paused']]
        has_active_runtime = False
        runtime_checker = getattr(self.task_manager, 'has_active_runtime_tasks', None)
        if callable(runtime_checker):
            try:
                has_active_runtime = bool(runtime_checker())
            except Exception:
                has_active_runtime = False

        # 检查是否正在跳转过程中

        is_jumping = getattr(self, '_is_jumping', False)

        # 检查是否有活动的跳转定时器

        has_active_timers = False

        if hasattr(self, '_active_jump_timers'):

            has_active_timers = any(timer.isActive() for timer in self._active_jump_timers if timer)

        # 统一由任务实时状态驱动连线动画暂停：

        # 只要仍处于执行链路（运行/暂停/跳转）就保持暂停，避免不同执行路径漏掉动画状态切换。

        should_pause_line_animation = bool(
            running_or_paused_tasks or has_active_runtime or is_jumping or has_active_timers
        )

        self._set_line_animation_paused("task_runtime", should_pause_line_animation)

        if not running_or_paused_tasks and not has_active_runtime and not is_jumping and not has_active_timers:

            # 没有运行中或暂停的任务，且不在跳转过程中，重置按钮

            logging.info("_on_task_status_changed: 没有运行中或暂停的任务且无跳转，重置工具栏按钮")

            self._reset_run_button()

        elif not running_or_paused_tasks and has_active_runtime:

            logging.debug("_on_task_status_changed: 任务状态已结束，但执行线程仍在清理中，保持当前按钮状态")

        elif not running_or_paused_tasks:

            logging.debug(f"_on_task_status_changed: 无运行任务但正在跳转中(is_jumping={is_jumping}, has_active_timers={has_active_timers})，保持按钮状态")

    def _on_all_tasks_completed(self, success: bool, result_type: str = ""):

        """所有任务完成处理（用于更新工具栏按钮）"""

        normalized_result = str(result_type or "").strip().lower()
        if normalized_result not in {"completed", "failed", "stopped"}:
            normalized_result = "completed" if success else "failed"

        logging.info(
            f"_on_all_tasks_completed: 所有任务已完成，成功={success}，结果类型={normalized_result}"
        )

        from .main_window_support import get_success_color, get_error_color, get_info_color

        # 更新底部状态栏显示完成状态

        if hasattr(self, 'step_detail_label'):

            if normalized_result == "stopped":

                status_text = "已停止"

                color = get_info_color()

            elif success:

                status_text = "全部完成"

                color = get_success_color()

            else:

                status_text = "执行失败"

                color = get_error_color()

            self.step_detail_label.setText(status_text)

            self._set_step_detail_style(text_color=color)

            # 3秒后恢复为正常状态

            from PySide6.QtCore import QTimer

            QTimer.singleShot(3000, lambda: self._update_status_bar())

        # 兜底恢复连线动画（防止异常链路未正确清理暂停原因）。

        if hasattr(self, "_clear_runtime_line_animation_pauses"):
            self._clear_runtime_line_animation_pauses()
        else:
            self._set_line_animation_paused("task_runtime", False)

        self._reset_run_button()

        if self.task_state_manager:
            try:
                self.task_state_manager.confirm_stopped()
                logging.info("_on_all_tasks_completed: task_state_manager confirmed stopped")
            except Exception as state_err:
                logging.warning(f"_on_all_tasks_completed: confirm_stopped failed: {state_err}")

        try:

            from utils.runtime_image_cleanup import cleanup_yolo_runtime_on_stop

            cleanup_yolo_runtime_on_stop(

                release_engine=True,

                compact_memory=True,

            )

        except Exception:

            pass

    def _on_multi_window_completed(self, success: bool, message: str):

        """处理多窗口执行完成 - 增强版本"""

        logger.info(f"多窗口执行完成: success={success}, message={message}")

        try:

            # 工具 关键修复：确保停止管理器正确清理

            if hasattr(self, 'multi_executor') and hasattr(self.multi_executor, 'stop_integration'):

                logger.info("清理增强停止管理器...")

                self.multi_executor.stop_integration.cleanup()

            # --- ADDED: 确认任务停止状态 ---

            if self.task_state_manager:

                self.task_state_manager.confirm_stopped()

                logger.info("多窗口任务完成，状态管理器已确认停止")

            # ----------------------------

            # 任务完成后自动调用停止按钮逻辑来初始化状态

            logger.info("任务完成，自动重置状态...")

            self._auto_reset_after_completion(success, message)

        except Exception as e:

            logger.error(f"多窗口完成处理失败: {e}", exc_info=True)

            # 确保UI状态重置

            self._reset_run_button()

            # 确保状态管理器重置

            if self.task_state_manager:

                self.task_state_manager.confirm_stopped()

                logger.info("多窗口完成异常后，状态管理器已确认停止")

            self._auto_reset_in_progress = False

    def handle_task_state_change(self, new_state: str):

        """处理任务状态变化的槽函数"""

        logger.info(f"任务状态变化: {new_state}")

        # 更新工作流编辑状态（运行时禁止编辑）

        is_running = new_state in ["starting", "running", "stopping"]

        if hasattr(self, 'workflow_tab_widget'):

            self.workflow_tab_widget.set_editing_enabled(not is_running)

        # 更新UI状态

        if hasattr(self, 'run_action'):

            if new_state in ["starting", "running"]:

                self.run_action.setEnabled(False)

                self.run_action.setText("运行中...")

            elif new_state == "stopping":

                self.run_action.setEnabled(False)

                self.run_action.setText("停止中...")

            else:  # stopped

                self.run_action.setEnabled(True)

                self.run_action.setText("运行所有任务")

        if new_state == "stopped":

            if hasattr(self, "_clear_runtime_line_animation_pauses"):
                self._clear_runtime_line_animation_pauses()
            else:
                self._set_line_animation_paused("task_runtime", False)
                self._set_line_animation_paused("executor", False)

        

        # 更新状态显示

        if hasattr(self, 'step_detail_label'):

            status_map = {

                "starting": "正在启动任务...",

                "running": "任务执行中...",

                "stopping": "正在停止任务...",

                "stopped": "等待执行..."

            }

            if new_state in status_map:

                self.step_detail_label.setText(status_map[new_state])

    def _on_multi_window_progress(self, window_title: str, status: str):

        """处理多窗口执行进度"""

        logger.info(f"多窗口进度 - {window_title}: {status}")

        self.step_detail_label.setText(f"多窗口执行: {window_title} - {status}")

    def _on_multi_window_error(self, window_title: str, window_hwnd: int, card_id: int, error_message: str):

        logger.warning(
            "多窗口错误 - window=%s, hwnd=%s, card_id=%s, error=%s",
            window_title,
            window_hwnd,
            card_id,
            error_message,
        )

        detail_text = f"{window_title} 失败: {error_message}"
