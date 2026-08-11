import logging
import os

from PySide6.QtWidgets import QMessageBox

logger = logging.getLogger(__name__)


class MainWindowExecutionFlowTestMixin:

    def _try_update_failed_paths(self, selected_directory: str):

        """Attempts to find missing files in the selected directory and update card parameters."""

        logger.info(f"Attempting to update failed paths using directory: {selected_directory}")

        updated_count = 0

        still_failed = []

        # 【修复闪退】检查workflow_view是否存在

        if not self.workflow_view or not hasattr(self.workflow_view, 'cards'):

            logger.warning(f"workflow_view不存在或没有cards属性，无法更新失败的路径")

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

            logger.info(f"=== 测试卡片执行请求 ===")

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

            logger.info(f"=== 测试流程执行请求 ===")

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
