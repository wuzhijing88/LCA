import logging
from PySide6.QtWidgets import QFileDialog, QMessageBox
from task_workflow.card_display import format_step_detail
from .main_window_support import create_media_control_icon

logger = logging.getLogger(__name__)

class MainWindowExecutionStateMixin:

    def _handle_execution_started(self):

        from .main_window_support import create_media_control_icon, get_info_color
        # print("UI: 收到 execution_started 信号")  # 性能优化：移除print避免主线程阻塞

        # --- ADDED: 重置重复处理标志 ---

        self._execution_finished_processed = False

        self._execution_started_flag = True  # 标记任务已启动

        # ----------------------------

        # 通知浮动窗口控制器

        if hasattr(self, '_floating_controller') and self._floating_controller:

            self._floating_controller.on_workflow_started()

        # 【参考中控】更新底部状态栏显示执行开始

        if hasattr(self, 'step_detail_label'):

            self.step_detail_label.setText("开始执行工作流...")

            self._set_step_detail_style(text_color=get_info_color())

        # 【关键修复】暂停连线动画，避免动画update与卡片状态update竞争导致UI卡顿

        self._set_line_animation_paused("executor", True)

        # --- ADDED: Change button to 'Stop' state and connect signal ---

        logging.info("_handle_execution_started: Setting button to 'Stop' state.")

        self.run_action.setEnabled(True) # Enable the stop button

        self.run_action.setText("停止")

        self.run_action.setIcon(create_media_control_icon('stop', 20))

        self.run_action.setToolTip("停止所有任务执行 (F10)") # Add F10 hint

        # 修改：连接到停止所有任务的方法

        try:

            self.run_action.triggered.disconnect() # Disconnect previous

            self._signal_connected_to_start = False  # 重置标志

        except (TypeError, RuntimeError):

            pass

        try:

            self.run_action.triggered.connect(self.safe_stop_tasks)

            logging.debug("_handle_execution_started: Reconnected triggered signal to self.safe_stop_tasks.")

        except Exception as e:

            logging.error(f"_handle_execution_started: Error connecting signal to safe_stop_tasks: {e}")

        # --------------------------------------------------------------

        # 重置卡片状态前，先验证workflow_view是否正确

        current_task_id = self.workflow_tab_widget.get_current_task_id()

        logger.info(f"[执行开始] 当前标签页task_id: {current_task_id}")

        logger.info(f"[执行开始] self.workflow_view的卡片数量: {len(self.workflow_view.cards) if self.workflow_view else 0}")

        if self.workflow_view:

            logger.info(f"[执行开始] self.workflow_view的卡片ID列表: {list(self.workflow_view.cards.keys())}")

            # 【修复闪退】检查workflow_view是否存在再调用

            self.workflow_view.reset_card_states()

    def _handle_card_executing(self, card_id: int):

        if self._is_stale_executor_signal():

            return

        # 【参考中控】更新底部状态栏显示详细步骤信息

        self._update_step_detail_for_card(card_id, is_executing=True)

        # 通知浮动窗口当前执行的步骤

        if hasattr(self, '_floating_window') and self._floating_window:

            try:

                card = self.workflow_view.cards.get(card_id) if self.workflow_view else None

                if card:

                    card_type = card.task_type if hasattr(card, 'task_type') else "未知"

                    card_name = ""

                    if hasattr(card, 'parameters') and card.parameters:

                        card_name = card.parameters.get('name', '') or card.parameters.get('description', '')

                    self._floating_window.on_step_started(card_type, card_name)

            except Exception as e:

                logger.debug(f"更新浮动窗口步骤信息失败: {e}")

        # 获取当前标签页ID

        current_task_id = self.workflow_tab_widget.get_current_task_id()

        # 优先使用当前活动的workflow_view（适用于测试模式和正常执行）

        target_workflow_view = self.workflow_view

        # 验证卡片是否在当前视图中

        if target_workflow_view and card_id in target_workflow_view.cards:

            logger.debug(f"[卡片状态] 卡片 {card_id} 在当前标签页 (task_id={current_task_id}) 中")

        else:

            # 卡片不在当前视图，遍历查找（适用于后台执行的情况）

            logger.debug(f"[卡片状态] 卡片 {card_id} 不在当前标签页，搜索其他标签页")

            target_workflow_view = None

            for task_id, workflow_view in self.workflow_tab_widget.task_views.items():

                if workflow_view and card_id in workflow_view.cards:

                    target_workflow_view = workflow_view

                    logger.debug(f"[卡片状态] 找到卡片 {card_id} 所在的工作流视图: task_id={task_id}")

                    break

            if not target_workflow_view:

                logger.debug(f"[卡片状态] 未找到包含卡片 {card_id} 的工作流视图")

                return

            # 不再跳过非当前标签页：执行态必须实时可见，避免“运行中不变色，停止后才更新”。

        # 正常模式与测试模式统一更新卡片状态：

        # 线程会话/直接执行路径都可能走到这里，统一由主窗口兜底设置，避免卡片不变色。

        try:

            target_workflow_view.set_card_state(card_id, 'executing')

        except Exception as e:

            logger.debug(f"设置卡片 {card_id} 执行中状态失败: {e}")

    def _handle_error_occurred(self, card_id: int, error_message: str):

        if self._is_stale_executor_signal():

            return

        # print(f"UI: 收到 error_occurred 信号 for ID {card_id}: {error_message}")  # 性能优化：移除print

        # 工具 修复：找到包含此卡片的正确工作流视图

        target_workflow_view = None

        target_task_id = None

        for task_id, workflow_view in self.workflow_tab_widget.task_views.items():

            if workflow_view and card_id in workflow_view.cards:

                target_workflow_view = workflow_view

                target_task_id = task_id

                logger.debug(f"找到卡片 {card_id} 所在的工作流视图: task_id={task_id}")

                break

        if not target_workflow_view:

            logger.debug(f"未找到包含卡片 {card_id} 的工作流视图，使用当前活动视图")

            target_workflow_view = self.workflow_view

            # 【修复闪退】检查fallback的workflow_view是否也为None

            if not target_workflow_view:

                logger.warning(f"当前活动视图也为None，无法设置卡片 {card_id} 的状态")

                return

        # 性能优化：只有当标签页可见时才更新UI

        current_task_id = self.workflow_tab_widget.get_current_task_id()

        if target_task_id is not None and target_task_id != current_task_id:

            logger.debug(f"[性能优化] 跳过不可见标签页的UI更新: task_id={target_task_id}")

            # 仍然需要停止闪烁效果（内存清理）

            try:

                if target_workflow_view and hasattr(target_workflow_view, 'cards'):

                    card = target_workflow_view.cards.get(card_id)

                    if card and hasattr(card, 'stop_flash'):

                        card.stop_flash()

            except Exception:

                pass

            return

        valid_card = isinstance(card_id, int) and not isinstance(card_id, bool)

        if valid_card:

            try:

                target_workflow_view.set_card_state(card_id, 'failure')

            except Exception as e:

                logger.warning(f"设置卡片 {card_id} 失败状态失败: {e}")

            try:

                card = target_workflow_view.cards.get(card_id)

                if card and hasattr(card, 'stop_flash'):

                    card.stop_flash()

                    logger.debug(f"停止 错误时停止卡片 {card_id} 闪烁效果")

            except Exception as e:

                logger.warning(f"错误 错误时停止卡片 {card_id} 闪烁效果失败: {e}")

        detail = str(error_message or "").strip() or "没有更具体原因"

        if valid_card:

            QMessageBox.warning(self, "工作流错误", f"执行卡片 {card_id} 时出错:\n{detail}")

        else:

            QMessageBox.warning(self, "工作流错误", detail)

    def _handle_execution_finished(self, success: bool, status_message: str):

        """Handles the execution_finished signal from the executor."""

        logger.info(f"_handle_execution_finished: Received success={success}, status='{status_message}'")

        # 防御：忽略历史执行器（尤其测试执行器）残留发出的完成信号

        signal_sender = None

        try:

            signal_sender = self.sender()

        except Exception:

            signal_sender = None

        current_executor = getattr(self, 'executor', None)

        if signal_sender is not None and current_executor is not None and signal_sender is not current_executor:

            logger.warning("_handle_execution_finished: ignore stale execution_finished signal (sender mismatch)")

            return

        if signal_sender is not None and current_executor is None:

            logger.warning(

                "_handle_execution_finished: executor reference already cleared, "

                "using the signal sender as the authoritative completion source"

            )

        # 通知浮动窗口控制器

        if hasattr(self, '_floating_controller') and self._floating_controller:

            self._floating_controller.on_workflow_finished(success, status_message)

        # 【关键修复】恢复连线动画

        self._set_line_animation_paused("executor", False)

        # 工具 关键修复：清理强制指定的窗口句柄

        if hasattr(self, '_forced_target_hwnd'):

            logger.info(f"刷新 清理强制指定的窗口句柄: {self._forced_target_hwnd}")

            delattr(self, '_forced_target_hwnd')

        if hasattr(self, '_forced_target_title'):

            delattr(self, '_forced_target_title')

        # --- ADDED: 防止重复处理 ---

        if hasattr(self, '_execution_finished_processed') and self._execution_finished_processed:

            logger.warning("_handle_execution_finished: Already processed, ignoring duplicate call")

            return

        self._execution_finished_processed = True

        # -------------------------

        finished_task_id = getattr(self, "_active_execution_task_id", None)
        if finished_task_id is not None:
            self._last_finished_task_id = finished_task_id

        # 执行完成后不清除卡片状态，保留成功/失败的颜色，只在启动任务时清除

        # logger.info("工作流执行完成，重置所有卡片状态为idle")

        # self.workflow_view.reset_card_states()

        # 工具 停止所有卡片的闪烁效果 - 增强版本

        # 【修复闪退】检查workflow_view是否存在，并复制字典避免迭代时修改

        try:

            if hasattr(self, 'workflow_view') and self.workflow_view and hasattr(self.workflow_view, 'cards'):

                # 复制字典以避免迭代时修改导致的RuntimeError

                cards_snapshot = dict(self.workflow_view.cards)

                for card_id, card in cards_snapshot.items():

                    if card and hasattr(card, 'stop_flash'):

                        try:

                            card.stop_flash()

                            logger.debug(f"停止卡片 {card_id} 的闪烁效果")

                        except (RuntimeError, AttributeError) as card_err:

                            logger.debug(f"停止卡片 {card_id} 闪烁时出错（可能已被删除）: {card_err}")

                logger.info("已停止所有卡片的闪烁效果")

        except Exception as e:

            logger.warning(f"错误 停止所有卡片闪烁效果失败: {e}")

        # ----------------------------------

        # --- 确保执行器和线程存在 ---

        # 【修复闪退】检查executor是否已被deleteLater标记删除

        executor_valid = False

        try:

            if self.executor and hasattr(self.executor, 'execution_finished'):

                executor_valid = True

        except (RuntimeError, AttributeError):

            logger.warning("_handle_execution_finished: Executor已被删除，跳过信号断开")

        if not executor_valid or not self.executor_thread:

            logger.warning("_handle_execution_finished: Executor or thread is None/deleted, cannot clean up properly.")

            self._reset_run_button() # Still try to reset UI

            try:

                from utils.runtime_image_cleanup import cleanup_yolo_runtime_on_stop

                cleanup_yolo_runtime_on_stop(

                    release_engine=True,

                    compact_memory=True,

                )

            except Exception:

                pass

            # 执行器异常路径也要触发停止清理，避免状态卡住

            if self.task_state_manager:

                try:

                    current_state = self.task_state_manager.get_current_state()

                except Exception:

                    current_state = None

                if current_state != "stopped":

                    self.task_state_manager.confirm_stopped()

                    logger.info("任务状态管理器已确认停止（执行器异常路径）")

            self._execution_finished_processed = False  # 重置标志

            return

        # --------------------------

        # --- ADDED: Check for failed paths and offer to fix ---

        if self.failed_paths:

            num_failed = len(self.failed_paths)

            reply = QMessageBox.question(self,

                                         "图片路径问题",

                                         f"工作流执行期间有 {num_failed} 个图片文件无法找到。\n\n" 

                                         "是否现在选择一个包含这些图片的文件夹来尝试自动修复路径？",

                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,

                                         QMessageBox.StandardButton.No)

            if reply == QMessageBox.StandardButton.Yes:

                selected_directory = QFileDialog.getExistingDirectory(self, "选择包含缺失图片的文件夹", self.images_dir) # Start in default images dir

                if selected_directory:

                    self._try_update_failed_paths(selected_directory)

        # -----------------------------------------------------

        # Always reset the UI and clean up regardless of path failures

        self._reset_run_button()

        # --- ADDED: 确认任务停止状态 ---

        if self.task_state_manager:

            self.task_state_manager.confirm_stopped()

            logger.info("任务状态管理器已确认停止")

        # ----------------------------

        # 工具 修复：将内部状态消息转换为用户友好的消息

        user_friendly_message = self._convert_status_message_to_user_friendly(status_message)

        QMessageBox.information(self, "执行完成", user_friendly_message)

        # Clear the list AFTER potential fix attempt

        self.failed_paths.clear()

        # --- ADDED: 重置重复处理标志 ---

        self._execution_finished_processed = False

        self._execution_started_flag = False  # 重置任务启动标志

        # ----------------------------

        # 停止超时定时器（如果存在）

        if hasattr(self, '_stop_timeout_timer') and self._stop_timeout_timer.isActive():

            self._stop_timeout_timer.stop()

        # 检查是否需要重置按钮（考虑跳转状态）

        self._check_and_reset_button_after_workflow()

        logger.debug("_handle_execution_finished: Processed.")

    def _update_step_detail_for_card(self, card_id: int, is_executing: bool = True, success: bool = True):

        """

        【参考中控】更新底部状态栏显示详细的卡片执行步骤信息

        Args:

            card_id: 卡片ID

            is_executing: True表示正在执行，False表示执行完成

            success: 执行结果（仅当is_executing=False时有效）

        """

        if not hasattr(self, 'step_detail_label'):

            logger.warning("[步骤显示] step_detail_label 不存在")

            return

        # 查找卡片信息

        card_info = None

        task_type = "未知任务"

        custom_name = None

        # 遍历所有工作流视图查找卡片

        for task_id, workflow_view in self.workflow_tab_widget.task_views.items():

            if workflow_view and card_id in workflow_view.cards:

                card = workflow_view.cards.get(card_id)

                if card:

                    # 获取卡片的任务类型和自定义名称

                    task_type = getattr(card, 'task_type', '未知任务')

                    custom_name = getattr(card, 'custom_name', None)

                    card_info = card

                    break

        # 如果在工作流视图中找不到，尝试从当前视图查找

        if not card_info and self.workflow_view:

            card = self.workflow_view.cards.get(card_id)

            if card:

                task_type = getattr(card, 'task_type', '未知任务')

                custom_name = getattr(card, 'custom_name', None)

                card_info = card

        # 构建步骤信息文本

        if is_executing:
            step_info = format_step_detail(
                "正在执行",
                card=card_info,
                card_id=card_id,
                task_type=task_type,
                custom_name=custom_name,
            )

        else:
            if success:
                step_info = format_step_detail(
                    "执行成功",
                    card=card_info,
                    card_id=card_id,
                    task_type=task_type,
                    custom_name=custom_name,
                )

            else:
                step_info = format_step_detail(
                    "执行失败",
                    card=card_info,
                    card_id=card_id,
                    task_type=task_type,
                    custom_name=custom_name,
                )

        # 执行态更新优先级高，清理限频队列并立即应用

        self._pending_step_details = None

        flush_timer = getattr(self, "_step_detail_flush_timer", None)

        if flush_timer is not None:

            try:

                if flush_timer.isActive():

                    flush_timer.stop()

            except Exception:

                pass

        self._apply_step_detail_text(step_info)

    def _handle_path_updated(self, card_id: int, param_name: str, new_path: str):

        """Updates the path parameter of a card when resolved to the default dir."""

        if self._is_stale_executor_signal():

            return

        logger.info(f"UI: Received path_updated for Card {card_id}, Param '{param_name}', New Path: '{new_path}'")

        # 【修复闪退】检查workflow_view是否存在

        if not self.workflow_view or not hasattr(self.workflow_view, 'cards'):

            logger.warning("workflow_view不存在或没有cards属性，无法更新路径")

            return

        card = self.workflow_view.cards.get(card_id)

        if card:

            if param_name in card.parameters:

                card.parameters[param_name] = new_path

                logger.debug(f"  Card {card_id} parameter '{param_name}' updated in UI model.")

                self.unsaved_changes = True # Mark changes as unsaved

                self._update_main_window_title() # Update title to show unsaved state

            else:

                logger.warning(f"  卡片 {card_id} 中未找到参数 '{param_name}'，无法更新。")

        else:

            logger.warning(f"  UI 中未找到卡片 ID {card_id}，无法更新路径。")

    def _update_step_details(self, step_details: str):

        """Updates the step_details label with the received step details and sets color based on status."""

        import time

        from PySide6.QtCore import QTimer

        if self._is_stale_executor_signal():

            return

        if not hasattr(self, 'step_detail_label'):

            return

        now = time.monotonic()

        last_update_ts = float(getattr(self, "_step_detail_last_update_ts", 0.0))

        min_interval_s = 0.08

        if (now - last_update_ts) < min_interval_s:

            self._pending_step_details = step_details

            flush_timer = getattr(self, "_step_detail_flush_timer", None)

            if flush_timer is None:

                flush_timer = QTimer(self)

                flush_timer.setSingleShot(True)

                flush_timer.timeout.connect(self._flush_pending_step_details)

                self._step_detail_flush_timer = flush_timer

            remaining_ms = max(1, int((min_interval_s - (now - last_update_ts)) * 1000))

            flush_timer.start(remaining_ms)

            return

        self._apply_step_detail_text(step_details)

    def _convert_status_message_to_user_friendly(self, status_message: str) -> str:
        text = str(status_message or "")
        if "STOP_WORKFLOW" in text:
            return "工作流执行已停止"
        if "用户手动停止" in text:
            return "工作流已被用户停止"
        if "正常停止" in text:
            return "工作流执行正常结束"
        if "执行完成" in text:
            return "工作流执行完成"
        if "执行成功" in text:
            return "工作流执行成功"
        if "执行失败" in text:
            return "工作流执行失败"
        if "错误" in text or "异常" in text:
            return f"工作流执行出现问题：{text}"
        return text

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

    def _reset_run_button(self):
        """Resets the run button to its initial 'Run' state and connects its signal."""
        # --- MODIFIED: Check button text and ensure signal is correct ---
        logging.debug("_reset_run_button: Attempting to reset button to 'Run' state.")
        # 设置为停止状态
        self._set_button_to_stopped_state()
        # 性能优化：检查当前状态，避免重复更新
        if (self.run_action.text() == "启动所有任务" and
            self.run_action.isEnabled() and
            hasattr(self, '_signal_connected_to_start') and
            self._signal_connected_to_start):
            logging.debug("_reset_run_button: 按钮已处于启动状态且信号已连接，跳过重复更新")
            return
        # Ensure correct signal connection
        try:
            self.run_action.triggered.disconnect() # Disconnect all first
            logging.debug("_reset_run_button: Disconnected existing signals.")
        except (TypeError, RuntimeError): # Handle case where no signals are connected or object deleted
            logging.debug("_reset_run_button: No signals to disconnect or error disconnecting.")

        try:
            # 修复：统一使用 _on_run_stop_button_clicked 处理按钮点击
            # 该方法会根据按钮文本判断执行启动/停止/恢复操作
            self.run_action.triggered.connect(self._on_run_stop_button_clicked)
            self._signal_connected_to_start = True  # 标记信号已连接
            logging.debug("_reset_run_button: Reconnected triggered signal to _on_run_stop_button_clicked.")
        except Exception as e:
            logging.error(f"_reset_run_button: Error connecting signal: {e}")

    def _set_line_animation_paused(self, reason: str, paused: bool):
        """统一管理连线动画暂停状态，避免并发执行路径下误恢复。"""
        if not reason:
            return
        pause_reasons = getattr(self, "_line_animation_pause_reasons", None)
        if pause_reasons is None or not isinstance(pause_reasons, set):
            pause_reasons = set()
            self._line_animation_pause_reasons = pause_reasons
        if paused:
            pause_reasons.add(reason)
        else:
            pause_reasons.discard(reason)
        should_pause = bool(pause_reasons)
        last_paused_state = bool(getattr(self, "_line_animation_is_paused", False))
        if should_pause == last_paused_state:
            return
        try:
            if should_pause:
                from ..workflow_parts.connection_line import pause_line_animation
                pause_line_animation()
            else:
                from ..workflow_parts.connection_line import resume_line_animation
                resume_line_animation()
            self._line_animation_is_paused = should_pause
        except Exception as e:
            logging.warning(f"切换连线动画暂停状态失败: {e}")

    def _clear_runtime_line_animation_pauses(self):
        """统一清理运行态产生的连线动画暂停原因。"""
        self._set_line_animation_paused("executor", False)
        self._set_line_animation_paused("task_runtime", False)

    def _setup_multi_window_stop_button(self):
        """设置多窗口执行时的停止按钮"""
        try:
            self.run_action.triggered.disconnect()
        except (TypeError, RuntimeError) as e:
            logger.debug(f"断开 run_action 信号时出现可忽略异常: {e}")
        self.run_action.setEnabled(True)
        self.run_action.setText("停止多窗口执行")
        self.run_action.setIcon(create_media_control_icon('stop', 20))
        self.run_action.setToolTip("停止所有窗口的执行 (F10)")
        self.run_action.triggered.connect(self.safe_stop_tasks)

    def _set_button_to_paused_state(self):
        """设置按钮为暂停状态：显示⏸恢复按钮"""
        logging.debug("设置按钮为暂停状态")
        self.run_action.setEnabled(True)
        self.run_action.setText("恢复")
        self.run_action.setToolTip("恢复工作流执行")
        self.run_action.setIcon(create_media_control_icon('pause', 20))

    def _set_button_to_stopped_state(self):
        """设置按钮为停止状态：显示▶运行按钮"""
        logging.debug("设置按钮为停止状态")
        self.run_action.setEnabled(True)
        self.run_action.setText("运行所有任务")
        self.run_action.setToolTip("开始执行所有工作流 (F9)")
        self.run_action.setIcon(create_media_control_icon('play', 20))

    def _set_button_to_running_state(self):
        """设置按钮为运行状态：显示■停止按钮"""
        logging.debug("设置按钮为运行状态")
        self.run_action.setEnabled(True)
        self.run_action.setText("停止")
        self.run_action.setToolTip("停止所有任务执行 (F10)")
        self.run_action.setIcon(create_media_control_icon('stop', 20))

    def _set_toolbar_to_stop_state(self):
        """兼容旧代码：设置为运行状态"""
        self._set_button_to_running_state()
