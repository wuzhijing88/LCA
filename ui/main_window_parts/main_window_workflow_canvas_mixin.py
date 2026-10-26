import logging

from PySide6.QtWidgets import QDialog, QMessageBox

logger = logging.getLogger(__name__)


class MainWindowWorkflowCanvasMixin:
    def _handle_card_finished(self, card_id: int, success: bool):
        if self._is_stale_executor_signal():
            return
        # print(f"UI: 收到 card_finished 信号 for ID {card_id}, Success: {success}")  # 性能优化：移除print
        if self.parameter_panel and self.parameter_panel.current_card_id == card_id:
            self.parameter_panel.refresh_runtime_parameters(card_id)
        # 【参考中控】更新底部状态栏显示执行结果
        self._update_step_detail_for_card(card_id, is_executing=False, success=success)
        target_workflow_view = self._execution_workflow_view()
        if target_workflow_view is None:
            return
        state = 'success' if success else 'failure'
        try:
            target_workflow_view.set_card_state(card_id, state)
        except Exception as e:
            logger.debug(f"设置卡片 {card_id} 完成状态失败: {e}")
    def confirm_and_clear_workflow(self):
        """Shows a confirmation dialog before clearing the workflow scene."""
        # 首先检查是否有任务正在运行
        if (self.executor is not None and 
            self.executor_thread is not None and 
            self.executor_thread.isRunning()):

            logger.warning("尝试在任务运行期间清空工作流")
            reply = QMessageBox.question(
                self, 
                "任务正在运行", 
                "检测到工作流正在执行中。\n\n继续清空会导致正在运行的任务失去界面显示，可能造成状态混乱。\n\n是否要先停止任务再清空？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Yes
            )

            if reply == QMessageBox.StandardButton.Yes:
                # 用户选择先停止任务
                logger.info("用户选择先停止任务再清空工作流")
                self.request_stop_workflow()
                QMessageBox.information(
                    self, 
                    "操作说明", 
                    "已发送停止请求。请等待任务停止后再次尝试清空工作流。"
                )
                return
            elif reply == QMessageBox.StandardButton.No:
                # 用户选择强制清空，继续询问确认
                logger.warning("用户选择在任务运行期间强制清空工作流")
                pass  # 继续下面的确认对话框
            else:
                # 用户取消操作
                logger.info("用户取消了清空工作流操作")
                return

        # 正常的清空确认对话框
        reply = QMessageBox.question(self, 
                                     "确认清空", 
                                     "您确定要清空当前工作流吗？\n所有未保存的更改将丢失，此操作无法撤销。",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, 
                                     QMessageBox.StandardButton.No) # Default to No
        if reply == QMessageBox.StandardButton.Yes:
            logger.info("用户确认清空工作流。")
            self.workflow_view.clear_workflow()
            # Optionally reset save path and unsaved changes flag after clearing
            self.current_save_path = None
            self.unsaved_changes = False # A new scene is not 'unsaved' initially
            self._update_main_window_title()
        else:
            logger.info("用户取消了清空工作流操作。") 
    def add_new_task_card(self):
        """Prompts the user to select a task type and adds a new card for it."""
        # 检查是否有当前工作流
        if not self.workflow_view:
            QMessageBox.warning(self, "无法添加", "请先导入或创建一个工作流任务")
            return
        # Import the function to get primary task types for UI display
        from tasks import get_available_tasks
        task_types = get_available_tasks()
        if not task_types:
            QMessageBox.warning(self, "错误", "没有可用的任务类型！")
            return
        # 使用两列按钮布局的对话框选择任务类型
        from ui.dialogs.select_task_dialog import SelectTaskDialog
        dialog = SelectTaskDialog(task_types, self)
        try:
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            task_type = dialog.selected_task_type()
            if task_type:
                center_view = self.workflow_view.mapToScene(self.workflow_view.viewport().rect().center())
                if task_type == "脚本卡片":
                    self.workflow_view.add_task_card(center_view.x(), center_view.y(), task_type=task_type, parameters=dialog.selected_task_parameters())
                else:
                    self.workflow_view.add_task_card(center_view.x(), center_view.y(), task_type=task_type)
        except Exception as exc:
            QMessageBox.warning(self, "无法添加卡片", str(exc))
        finally:
            dialog.deleteLater()

    def _reset_all_workflow_card_states(self, reason: str = ""):
        """执行前重置所有工作流卡片状态"""
        if reason:
            logger.info(f"{reason}，重置所有卡片状态")
        else:
            logger.info("重置所有卡片状态")
        try:
            if hasattr(self, 'workflow_tab_widget') and self.workflow_tab_widget:
                for task_id, workflow_view in self.workflow_tab_widget.task_views.items():
                    if workflow_view:
                        workflow_view.reset_card_states()
                        # 【修复闪退】安全访问cards字典
                        if hasattr(workflow_view, 'cards'):
                            cards_snapshot = dict(workflow_view.cards)
                            for card_id, card in cards_snapshot.items():
                                if card and hasattr(card, 'stop_flash'):
                                    try:
                                        card.stop_flash()
                                    except (RuntimeError, AttributeError):
                                        pass
            logger.info("已清除所有卡片状态")
        except Exception as e:
            logger.warning(f"清除卡片状态时出错: {e}")
    def safe_delete_card(self, card_id=None):
        """删除卡片（安全检查已移除）"""
        logger.info(f"删除卡片 {card_id}")
        return True
