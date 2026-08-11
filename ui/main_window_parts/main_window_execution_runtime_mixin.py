import logging

from PySide6.QtWidgets import QFileDialog, QMessageBox
from task_workflow.card_display import format_step_detail

logger = logging.getLogger(__name__)


class MainWindowExecutionRuntimeMixin:

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

        target_task_id = current_task_id

        # 验证卡片是否在当前视图中

        if target_workflow_view and card_id in target_workflow_view.cards:

            logger.debug(f"[卡片状态] 卡片 {card_id} 在当前标签页 (task_id={current_task_id}) 中")

        else:

            # 卡片不在当前视图，遍历查找（适用于后台执行的情况）

            logger.debug(f"[卡片状态] 卡片 {card_id} 不在当前标签页，搜索其他标签页")

            target_workflow_view = None

            target_task_id = None

            for task_id, workflow_view in self.workflow_tab_widget.task_views.items():

                if workflow_view and card_id in workflow_view.cards:

                    target_workflow_view = workflow_view

                    target_task_id = task_id

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

            except:

                pass

            return

        target_workflow_view.set_card_state(card_id, 'failure') # Mark card as failed on error

        # 工具 停止闪烁效果

        try:

            card = target_workflow_view.cards.get(card_id)

            if card and hasattr(card, 'stop_flash'):

                card.stop_flash()  # 停止闪烁效果

                logger.debug(f"停止 错误时停止卡片 {card_id} 闪烁效果")

        except Exception as e:

            logger.warning(f"错误 错误时停止卡片 {card_id} 闪烁效果失败: {e}")

        # Display error message to user

        QMessageBox.warning(self, "工作流错误", f"执行卡片 {card_id} 时出错:\n{error_message}")

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

                "fallback to signal sender for final persistence"

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

        executor_for_persist = current_executor if current_executor is not None else signal_sender

        finished_task_id = self._persist_execution_runtime_variables(

            executor_obj=executor_for_persist,

            task_id=getattr(self, "_active_execution_task_id", None),

        )

        try:

            if finished_task_id is None and hasattr(self, "workflow_tab_widget") and self.workflow_tab_widget:

                finished_task_id = self.workflow_tab_widget.get_current_task_id()

            if finished_task_id is not None:

                self._last_finished_task_id = finished_task_id

        except Exception:

            pass

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

                                         f"是否现在选择一个包含这些图片的文件夹来尝试自动修复路径？",

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

            logger.warning(f"[步骤显示] step_detail_label 不存在")

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

            logger.warning(f"workflow_view不存在或没有cards属性，无法更新路径")

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
