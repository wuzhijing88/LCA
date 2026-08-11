from .workflow_view_common import *


class WorkflowViewEditInteractionMixin:

    def edit_card_settings(self, card_id: int):
        """Opens the parameter dialog for the specified card."""
        card = self.cards.get(card_id)
        if card and hasattr(card, 'open_parameter_dialog'):
            card.open_parameter_dialog()

    def _handle_jump_target_change(self, param_name: str, old_target_id: Optional[int], new_target_id: Optional[int]):
        """Handles changes in jump target parameters to update connections."""
        source_card = self.sender() 
        logger.debug(f"--- [HANDLE_JUMP_DEBUG] Received jump signal from Card ID: {source_card.card_id if source_card else 'None'} ---")
        logger.debug(f"    Param Name: {param_name}, Old Target ID: {old_target_id}, New Target ID: {new_target_id}")
        
        if not isinstance(source_card, TaskCard):
            logger.error("_handle_jump_target_change called by non-TaskCard sender.")
            return
        if param_name not in ['success_jump_target_id', 'failure_jump_target_id']:
            logger.error(f"Unknown parameter name in _handle_jump_target_change: {param_name}")
            return
            
        # Determine line type based on parameter name
        line_type = ConnectionType.SUCCESS.value if param_name == 'success_jump_target_id' else ConnectionType.FAILURE.value
        action_param_name = 'on_success' if line_type == ConnectionType.SUCCESS.value else 'on_failure'
        current_action = source_card.parameters.get(action_param_name)

        logger.debug(f"  Source Card: {source_card.card_id} ({source_card.task_type}), Line Type: {line_type}")
        logger.debug(f"  Current Action ('{action_param_name}') on Card: '{current_action}'")
        logger.debug(f"  New Target ID for '{param_name}': {new_target_id}")

        # No direct connection manipulation here anymore.
        # The parameters on the source_card are already updated by the dialog.
        # We just need to refresh the view to reflect these parameter changes.

        logger.debug(f"--- [HANDLE_JUMP_DEBUG] Parameters on card {source_card.card_id} have changed. Scheduling full view update. ---")
        
        # Optional: Explicitly call update on the source card if its visual state (not connections)
        # needs changing due to the parameter (e.g. if it displays the target ID directly).
        # source_card.update() 

        self.update_card_sequence_display()
        logger.debug(f"  [HANDLE_JUMP_DEBUG] Called update_card_sequence_display to redraw connections based on new parameters.")

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
            from PySide6.QtWidgets import QMessageBox

            # 使用全局logger，不要重新定义
            logger.info(f"  [UNDO] ===== Ctrl+Z pressed =====")
            logger.info(f"  [UNDO] Stack size: {len(self.undo_stack)}")
            logger.info(f"  [UNDO] Workflow running: {self._is_workflow_running()}")

            debug_print(f"  [UNDO] ===== Ctrl+Z pressed =====")
            debug_print(f"  [UNDO] Stack size: {len(self.undo_stack)}")
            debug_print(f"  [UNDO] Workflow running: {self._is_workflow_running()}")

            # 打印撤销栈内容
            if len(self.undo_stack) > 0:
                logger.info(f"  [UNDO] Stack contents:")
                debug_print(f"  [UNDO] Stack contents:")
                for i, op in enumerate(self.undo_stack):
                    logger.info(f"    {i}: {op.get('operation_type', 'unknown')} - {op.get('timestamp', 'no_time')}")
                    debug_print(f"    {i}: {op.get('operation_type', 'unknown')} - {op.get('timestamp', 'no_time')}")
            else:
                logger.info(f"  [UNDO] Stack is empty")
                debug_print(f"  [UNDO] Stack is empty")

            # 注释已清理（原注释编码损坏）
            if len(self.undo_stack) == 0:
                logger.info("  [UNDO] RESULT: No operations to undo - showing empty message")
                debug_print("  [UNDO] RESULT: No operations to undo - showing empty message")
                QMessageBox.information(self, "无法撤销", "没有可撤销的操作")
            elif self._is_workflow_running():
                logger.info("  [UNDO] RESULT: Cannot undo - workflow is running")
                debug_print("  [UNDO] RESULT: Cannot undo - workflow is running")
                QMessageBox.warning(self, "无法撤销", "工作流运行期间无法执行撤销操作")
            else:
                # 有可撤销操作
                # 注释已清理（原注释编码损坏）
                last_operation = self.undo_stack[-1]
                operation_type = last_operation.get('operation_type', '未知操作')

                logger.info(f"  [UNDO] RESULT: About to undo operation: {operation_type}")
                logger.info(f"  [UNDO] Operation data: {last_operation}")
                debug_print(f"  [UNDO] RESULT: About to undo operation: {operation_type}")
                debug_print(f"  [UNDO] Operation data: {last_operation}")

                self.undo_last_operation()

                # 记录撤销结果到日志（不再弹出提示框）
                operation_names = {
                    'paste_cards': '粘贴卡片',
                    'delete_card': '删除卡片',
                    'delete_connection': '删除连线',
                    'add_connection': '添加连线',
                    'modify_connection': '修改连线',
                    'add_card': '添加卡片'
                }
                operation_name = operation_names.get(operation_type, operation_type)

                logger.info(f"  [UNDO] RESULT: 已撤销: {operation_name}")
                debug_print(f"  [UNDO] RESULT: 已撤销: {operation_name}")

            logger.info(f"  [UNDO] ===== End Ctrl+Z =====")
            debug_print(f"  [UNDO] ===== End Ctrl+Z =====")
            event.accept()
            return

        # Delete key - 删除选中项目
        if key == Qt.Key.Key_Delete:
            logger.info("Delete key pressed in WorkflowView!")

            # 注释已清理（原注释编码损坏）
            if not self.editing_enabled:
                logger.info("  Deletion blocked - editing disabled (workflow running)")
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
                logger.info("  Deletion blocked - workflow is running")
                event.accept()
                return

            # 获取选中的项目
            items_to_delete = self.scene.selectedItems()
            logger.info(f"  Selected items count: {len(items_to_delete)}")

            if not items_to_delete:
                logger.info("  No items selected for deletion.")
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
                    logger.debug(f"    Selected card: ID={item.card_id}")
                elif hasattr(item, '__class__') and 'ConnectionLine' in item.__class__.__name__:
                    connections_to_delete.append(item)
                    logger.debug(f"    Selected connection")

            # 注释已清理（原注释编码损坏）
            total_items = len(cards_to_delete) + len(connections_to_delete)
            logger.info(f"  准备删除: {len(cards_to_delete)} 个卡片, {len(connections_to_delete)} 个连接")

            if total_items > 3:  # 只有超过3个项目才显示确认对话框
                try:
                    from PySide6.QtWidgets import QMessageBox
                    reply = QMessageBox.question(
                        None,  # 使用None作为父窗口，避免焦点问题
                        "确认批量删除",
                        f"确定要删除 {len(cards_to_delete)} 个卡片和 {len(connections_to_delete)} 个连接吗？",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No
                    )

                    if reply != QMessageBox.StandardButton.Yes:
                        logger.info("  User cancelled batch deletion")
                        event.accept()
                        return
                except Exception as e:
                    logger.warning(f"确认对话框显示失败: {e}")
                    # 注释已清理（原注释编码损坏）

            # 继续执行删除，不因对话框失败而中断
            logger.info(f"  Starting deletion of {total_items} items...")

            try:
                # 先删除连接（更简单，不容易出错）
                for item in connections_to_delete:
                    try:
                        self.remove_connection(item)
                        logger.debug(f"    Connection deleted")
                    except Exception as e:
                        logger.warning(f"    删除连线失败：{e}")

                # 再删除卡片
                deleted_cards = self._delete_cards_batch(cards_to_delete)
                logger.debug(f"    Cards deleted in batch: {deleted_cards}")

                logger.info(f"  Deletion completed successfully")

            except Exception as e:
                logger.error(f"删除过程中发生错误: {e}")
                # 即使出错也要接受事件，避免传递给父组件

            event.accept() # We handled the delete event
        else:
            super().keyPressEvent(event) # Pass other keys to base class
