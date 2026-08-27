import logging
import os
from PySide6.QtWidgets import QMessageBox
from .main_window_support import normalize_execution_mode_setting
from ..main_window_parts.main_window_pause_orchestrator import (
    main_window_pause_workflow,
    main_window_resume_workflow,
    main_window_toggle_pause_workflow,
)
from ..main_window_parts.main_window_start_orchestrator import (
    main_window_safe_start_tasks,
    main_window_start_tasks,
)
from ..main_window_parts.main_window_stop_orchestrator import (
    main_window_safe_stop_tasks,
    main_window_stop_tasks,
)

logger = logging.getLogger(__name__)

class MainWindowExecutionFlowMixin:

    def _try_update_failed_paths(self, selected_directory: str):

        """Attempts to find missing files in the selected directory and update card parameters."""

        logger.info(f"Attempting to update failed paths using directory: {selected_directory}")

        updated_count = 0

        still_failed = []

        # 【修复闪退】检查workflow_view是否存在

        if not self.workflow_view or not hasattr(self.workflow_view, 'cards'):

            logger.warning("workflow_view不存在或没有cards属性，无法更新失败的路径")

            return

        for card_id, original_path in self.failed_paths:

            card = self.workflow_view.cards.get(card_id)

            if not card:

                logger.warning(f"  跳过更新卡片 {card_id}（UI 中未找到）。原始路径：{original_path}")

                still_failed.append((card_id, original_path))

                continue

            base_filename = os.path.basename(original_path)

            potential_new_path = os.path.normpath(os.path.join(selected_directory, base_filename))

            logger.debug(f"  Checking for '{base_filename}' in '{selected_directory}' -> '{potential_new_path}'")

            if os.path.exists(potential_new_path):

                logger.info(f"    Found! Updating Card {card_id} path to: {potential_new_path}")

                # Find the parameter key that holds the original_path

                # This is slightly tricky as we only stored the value. Iterate through params.

                param_key_to_update = None

                for key, value in card.parameters.items():

                    # Check if the current value matches the failed path (or just its basename?)

                    # Let's assume for now the stored original_path is what was in the param.

                    if value == original_path:

                         param_key_to_update = key

                         break 

                    # Fallback: Check if basename matches if full path doesn't

                    elif isinstance(value, str) and os.path.basename(value) == base_filename:

                         param_key_to_update = key

                         # Don't break here, maybe a more exact match exists

                if param_key_to_update:

                    card.parameters[param_key_to_update] = potential_new_path

                    updated_count += 1

                    self.unsaved_changes = True # Mark changes

                else:

                     logger.warning(f"    Could not find parameter key in Card {card_id} matching original path '{original_path}' or basename '{base_filename}'. Cannot update.")

                     still_failed.append((card_id, original_path)) # Treat as still failed

            else:

                logger.warning(f"    所选目录中未找到文件 '{base_filename}'。")

                still_failed.append((card_id, original_path))

        self._update_main_window_title() # Update title if changes were made

        if updated_count > 0:

            QMessageBox.information(self, "路径更新完成", f"成功更新了 {updated_count} 个图片路径。")

        if still_failed:

            QMessageBox.warning(self, "部分路径未更新", 

                                f"仍有 {len(still_failed)} 个图片路径未能找到或更新。请手动检查这些卡片的参数。")

    def _schedule_test_cleanup_if_not_started(self, reason: str):

        """测试入口：若未真正启动执行器，兜底触发OCR清理。"""

        from PySide6.QtCore import QTimer

        def _do_cleanup_check():

            try:

                if getattr(self, '_execution_started_flag', False):

                    return

                thread = getattr(self, 'executor_thread', None)

                if thread is not None:

                    try:

                        if thread.isRunning():

                            return

                    except Exception:

                        # 线程状态不可读时按未启动处理

                        pass

                self._confirm_test_ocr_cleanup(reason)

            except Exception:

                self._confirm_test_ocr_cleanup(reason)

        try:

            QTimer.singleShot(200, _do_cleanup_check)

        except Exception:

            self._confirm_test_ocr_cleanup(reason)

    def _handle_test_card_execution(self, card_id: int):

        """处理测试卡片的请求：只执行选中的单张卡片

        通过调用run_workflow并传入特殊参数来实现单卡片测试

        Args:

            card_id: 要测试的卡片ID

        """

        try:

            logger.info("=== 测试卡片执行请求 ===")

            logger.info(f"卡片ID: {card_id}")

            logger.info(f"当前workflow_view: {self.workflow_view}")

            # 【关键修复】明确记录当前标签页ID

            current_task_id = self.workflow_tab_widget.get_current_task_id()

            logger.info(f"当前标签页task_id: {current_task_id}")

            # 【关键修复】验证卡片是否在当前标签页中

            if self.workflow_view and card_id in self.workflow_view.cards:

                logger.info(f"✓ 卡片 {card_id} 在当前标签页 (task_id={current_task_id}) 中")

            else:

                logger.error(f"✗ 卡片 {card_id} 不在当前标签页中！")

                # 尝试找到卡片所在的标签页

                for task_id, wf_view in self.workflow_tab_widget.task_views.items():

                    if wf_view and card_id in wf_view.cards:

                        logger.error(f"  卡片实际在 task_id={task_id} 的标签页中")

                        break

            # 调用run_workflow，传入测试模式参数

            self.run_workflow(test_mode='single_card', test_card_id=card_id)

            self._schedule_test_cleanup_if_not_started("测试卡片未进入执行")

        except Exception as e:

            logger.error(f"测试卡片执行失败: {e}", exc_info=True)

            self._confirm_test_ocr_cleanup("测试卡片异常中断")

            from PySide6.QtWidgets import QMessageBox

            QMessageBox.critical(self, "测试失败", f"测试卡片时发生错误：\n{str(e)}")

    def _handle_test_flow_execution(self, card_id: int):

        """处理测试流程的请求：从指定卡片开始执行整个流程

        通过调用run_workflow并传入特殊参数来实现流程测试

        Args:

            card_id: 起始卡片ID

        """

        try:

            logger.info("=== 测试流程执行请求 ===")

            logger.info(f"起始卡片ID: {card_id}")

            logger.info(f"当前workflow_view: {self.workflow_view}")

            # 调用run_workflow，传入测试模式参数

            self.run_workflow(test_mode='flow', test_card_id=card_id)

            self._schedule_test_cleanup_if_not_started("测试流程未进入执行")

        except Exception as e:

            logger.error(f"测试流程执行失败: {e}", exc_info=True)

            self._confirm_test_ocr_cleanup("测试流程异常中断")

            from PySide6.QtWidgets import QMessageBox

            QMessageBox.critical(self, "测试失败", f"测试流程时发生错误：\n{str(e)}")

    def _confirm_test_ocr_cleanup(self, reason: str = ""):

        """测试链路兜底触发统一OCR清理。"""

        from ..workflow_parts import workflow_lifecycle

        manager = getattr(self, 'task_state_manager', None)

        if not manager:

            return

        success_log = "[测试清理] 已触发OCR清理"

        if reason:

            success_log = f"{success_log}（{reason}）"

        try:

            workflow_lifecycle.confirm_ocr_cleanup(

                manager,

                success_log=success_log,

                suppress_errors=True

            )

        except Exception:

            try:

                manager.confirm_stopped()

            except Exception:

                pass

    def _show_warning_dialog(self, title: str, message: str):

        """显示警告对话框"""

        from PySide6.QtWidgets import QMessageBox

        try:

            QMessageBox.warning(self, title, message)

        except Exception as e:

            logger.warning(f"显示警告对话框失败: {e}")

    def _force_confirm_stop(self):

        """强制确认停止状态（超时机制）"""

        logger.warning("停止操作超时，强制确认停止状态")

        if self.task_state_manager:

            self.task_state_manager.confirm_stopped()

            logger.info("已强制确认停止状态")

    def _handle_path_resolution_failed(self, card_id: int, original_path: str):

        """Stores information about paths that failed resolution."""

        if self._is_stale_executor_signal():

            return

        logger.warning(f"UI：收到卡片 {card_id} 的路径解析失败信号，原始路径：'{original_path}'")

        self.failed_paths.append((card_id, original_path))

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

    def safe_start_tasks(self, reset_jump_cancel=True, interactive=True):

        """安全启动任务，带状态检查和防重复调用保护 - 启动所有便签页的工作流

        Args:

            reset_jump_cancel: 是否重置跳转取消标志（True表示用户手动启动，False表示自动跳转启动）
            interactive: 是否允许弹窗。定时启动必须为 False。

        """

        return main_window_safe_start_tasks(
            self, reset_jump_cancel=reset_jump_cancel, interactive=interactive
        )

    def _resume_workflow(self, source="manual"):

        """恢复暂停的工作流"""

        return main_window_resume_workflow(self, source=source)

    def toggle_pause_workflow(self):

        """切换暂停/恢复工作流（快捷键调用）"""

        return main_window_toggle_pause_workflow(self)

    def _pause_workflow(self, source="manual"):

        """暂停工作流"""

        return main_window_pause_workflow(self, source=source)

    def safe_stop_tasks(self):

        """安全停止任务 - 精简版"""

        return main_window_safe_stop_tasks(self)

    def start_tasks(self):

        """传统启动方法，现在调用安全启动"""

        return main_window_start_tasks(self)

    def stop_tasks(self):

        """传统停止方法，现在调用安全停止"""

        return main_window_stop_tasks(self)
