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
            # 不再跳过非当前标签页：执行结果需要立即写回视图状态。
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
    def _on_card_deleted(self, card_id: int):
        """处理卡片删除事件 - 清理相关资源防止崩溃"""
        logger.info(f"处理卡片删除: {card_id}")
        try:
            # 1. 清理工作流上下文中的卡片数据
            from task_workflow.workflow_context import clear_card_ocr_data
            # 清理默认工作流上下文
            clear_card_ocr_data(card_id)
            # 也清理可能存在的其他工作流上下文
            try:
                from task_workflow.workflow_context import _context_manager
                for workflow_id in list(_context_manager.contexts.keys()):
                    clear_card_ocr_data(card_id, workflow_id)
            except Exception as multi_e:
                logger.debug(f"清理多工作流上下文时出错: {multi_e}")
            logger.debug(f"已清理卡片 {card_id} 的工作流上下文数据")
            # 2. 清理执行器中的持久化计数器
            if hasattr(self, 'executor') and self.executor:
                try:
                    if hasattr(self.executor, '_persistent_counters'):
                        # 清理与该卡片相关的计数器
                        keys_to_remove = []
                        for key in self.executor._persistent_counters.keys():
                            if str(card_id) in str(key):
                                keys_to_remove.append(key)
                        for key in keys_to_remove:
                            del self.executor._persistent_counters[key]
                            logger.debug(f"已清理执行器计数器: {key}")
                except Exception as exec_e:
                    logger.debug(f"清理执行器数据时出错: {exec_e}")
            # 4. 强制垃圾回收，清理可能的循环引用
            import gc
            gc.collect()
            logger.info(f"卡片 {card_id} 删除后清理完成")
        except Exception as e:
            logger.error(f"处理卡片 {card_id} 删除时发生错误: {e}", exc_info=True)
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
        result = dialog.exec()
        if result == QDialog.DialogCode.Accepted:
            task_type = dialog.selected_task_type()
        else:
            task_type = None
        dialog.deleteLater()
        if task_type is None:
            return
        if task_type:
            center_view = self.workflow_view.mapToScene(self.workflow_view.viewport().rect().center())
            self.workflow_view.add_task_card(center_view.x(), center_view.y(), task_type=task_type)
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
