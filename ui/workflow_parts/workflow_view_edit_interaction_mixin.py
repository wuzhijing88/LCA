from .workflow_view_common import *

operation_logger = logging.getLogger("workflow.operations")


class WorkflowViewEditInteractionMixin:

    def edit_card_settings(self, card_id: int):
        """Opens the parameter dialog for the specified card."""
        card = self.cards.get(card_id)
        if card and hasattr(card, 'open_parameter_dialog'):
            card.open_parameter_dialog()

    def _handle_jump_target_change(self, param_name: str, old_target_id: Optional[int], new_target_id: Optional[int]):
        """Handles changes in jump target parameters to update connections."""
        source_card = self.sender() 
        if not isinstance(source_card, TaskCard):
            raise TypeError("跳转参数变更信号必须由卡片发出")
        if param_name not in ['success_jump_target_id', 'failure_jump_target_id']:
            raise ValueError(f"未知跳转参数: {param_name}")
            
        # Determine line type based on parameter name
        line_type = ConnectionType.SUCCESS.value if param_name == 'success_jump_target_id' else ConnectionType.FAILURE.value

        # No direct connection manipulation here anymore.
        # The parameters on the source_card are already updated by the dialog.
        # We just need to refresh the view to reflect these parameter changes.

        
        # Optional: Explicitly call update on the source card if its visual state (not connections)
        # needs changing due to the parameter (e.g. if it displays the target ID directly).
        # source_card.update() 

        self.update_card_sequence_display()

    def keyPressEvent(self, event):
        """Handles key presses: Delete, Ctrl+C, Ctrl+V for selected items."""
        modifiers = event.modifiers()
        key = event.key()

        # Ctrl+C - 复制选中的卡片
        if modifiers == Qt.KeyboardModifier.ControlModifier and key == Qt.Key.Key_C:
            self.handle_copy_selected_cards()
            event.accept()
            return

        # Ctrl+V - 粘贴卡片到鼠标位置或视图中心
        if modifiers == Qt.KeyboardModifier.ControlModifier and key == Qt.Key.Key_V:
            # 获取当前鼠标位置（全局 -> viewport坐标），若不在视图内则退回到视图中心
            global_cursor_pos = QCursor.pos()
            viewport_cursor_pos = self.viewport().mapFromGlobal(global_cursor_pos)

            if self.viewport().rect().contains(viewport_cursor_pos):
                scene_pos = self.mapToScene(viewport_cursor_pos)
            else:
                # 使用视图中心
                view_center = self.viewport().rect().center()
                scene_pos = self.mapToScene(view_center)

            self.handle_paste_card(scene_pos)
            event.accept()
            return

        # 注释已清理（原注释编码损坏）
        if modifiers == Qt.KeyboardModifier.ControlModifier and key == Qt.Key.Key_Z:
            if not self.undo_stack:
                QMessageBox.information(self, "无法撤销", "没有可撤销的操作")
            elif self._is_workflow_running():
                QMessageBox.warning(self, "无法撤销", "工作流运行期间无法执行撤销操作")
            else:
                self.undo_last_operation()
            event.accept()
            return

        # Delete key - 删除选中项目
        if key == Qt.Key.Key_Delete:
            operation_logger.info("[删除] 收到 Delete 键，开始处理选中项目")

            # 注释已清理（原注释编码损坏）
            if not self.editing_enabled:
                operation_logger.info("[删除] 已阻止：当前禁止编辑")
                if hasattr(self.main_window, 'step_detail_label'):
                    self.main_window.step_detail_label.setText("【警告】工作流正在执行中，无法删除")
                    self.main_window.step_detail_label.setStyleSheet("""
                        #stepDetailLabel {
                            background-color: rgba(180, 180, 180, 180);
                            color: #FF0000;
                            font-weight: bold;
                            border-radius: 5px;
                            padding: 8px;
                        }
                    """)
                    from PySide6.QtCore import QTimer
                    QTimer.singleShot(3000, lambda: self.main_window.step_detail_label.setText("任务执行中..."))
                event.accept()
                return

            # 检查是否正在运行，如果是则阻止删除操作
            if self._block_edit_if_running("删除选中项目"):
                operation_logger.info("[删除] 已阻止：工作流正在运行")
                event.accept()
                return

            # 获取选中的项目
            items_to_delete = self.scene.selectedItems()
            operation_logger.info("[删除] 选中项目数量=%s", len(items_to_delete))

            if not items_to_delete:
                operation_logger.info("[删除] 没有选中项目")
                # 确保视图有焦点
                if not self.hasFocus():
                    self.setFocus()
                    logger.info("  Set focus to WorkflowView")
                event.accept()
                return

            # 分类选中的项目
            cards_to_delete = []
            connections_to_delete = []

            for item in items_to_delete:
                if isinstance(item, TaskCard):
                    cards_to_delete.append(item)
                elif hasattr(item, '__class__') and 'ConnectionLine' in item.__class__.__name__:
                    connections_to_delete.append(item)

            # 注释已清理（原注释编码损坏）
            total_items = len(cards_to_delete) + len(connections_to_delete)
            logger.info(f"  准备删除: {len(cards_to_delete)} 个卡片, {len(connections_to_delete)} 个连接")

            if total_items > 3:  # 只有超过3个项目才显示确认对话框
                try:
                    reply = QMessageBox.question(
                        None,  # 使用None作为父窗口，避免焦点问题
                        "确认批量删除",
                        f"确定要删除 {len(cards_to_delete)} 个卡片和 {len(connections_to_delete)} 个连接吗？",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No
                    )

                    if reply != QMessageBox.StandardButton.Yes:
                        operation_logger.info("[批量删除] 用户取消")
                        event.accept()
                        return
                except Exception as e:
                    logger.warning(f"确认对话框显示失败: {e}")
                    # 注释已清理（原注释编码损坏）

            # 继续执行删除，不因对话框失败而中断
            operation_logger.info("[删除] 开始处理项目总数=%s", total_items)

            try:
                # 卡片与连线统一交给批量删除处理（含独立选中的连线）
                deleted_cards = self._delete_cards_batch(cards_to_delete, connections_to_delete)
                operation_logger.info("[批量删除] 实际删除卡片数量=%s", deleted_cards)

                operation_logger.info("[删除] 处理完成")

            except Exception as e:
                logger.error(f"删除过程中发生错误: {e}")
                # 即使出错也要接受事件，避免传递给父组件

            event.accept() # We handled the delete event
        else:
            super().keyPressEvent(event) # Pass other keys to base class
