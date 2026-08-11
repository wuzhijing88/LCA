from .workflow_view_common import *


class WorkflowViewContextMenuMixin:

    def show_context_menu(self, pos: QPointF):
        """Shows a context menu at the given view position provided by the signal."""
        # --- CORRECTED: Use the signal's QPoint 'pos' directly ---
        scene_pos = self.mapToScene(pos) # mapToScene accepts QPoint
        # ----------------------------------------------------------

        # 注释已清理（原注释编码损坏）
        is_running = not self.editing_enabled or self._is_workflow_running()
        # 同步更新 editing_enabled
        if self._is_workflow_running():
            self.editing_enabled = False
        logger.info(f"[右键菜单] editing_enabled={self.editing_enabled}, is_running={is_running}")

        # --- REMOVED: No longer rely on manually stored _last_right_click_view_pos_f ---
        # ... (removed commented out block) ...
        # -----------------------------------------------------------------------------

        item = self.itemAt(pos) # itemAt uses QPoint
        debug_print(f"\n--- [DEBUG] WorkflowView.show_context_menu --- ") # DEBUG
        debug_print(f"  [DEBUG] Signal click position (view): {pos}") # DEBUG
        debug_print(f"  [DEBUG] Calculated click position (scene): {scene_pos}") # DEBUG
        debug_print(f"  [DEBUG] Item at position: {type(item).__name__}") # DEBUG
        if item:
             # Try accessing attributes common to QGraphicsItem or specific ones
             if isinstance(item, TaskCard):
                  debug_print(f"  [DEBUG] Item is TaskCard with ID: {item.card_id}, Type: {item.task_type}") # DEBUG
             elif isinstance(item, ConnectionLine):
                  debug_print(f"  [DEBUG] Item is ConnectionLine") # DEBUG
             else:
                  debug_print(f"  [DEBUG] Item exists but is not TaskCard or ConnectionLine.") # DEBUG

        menu = apply_unified_menu_style(QMenu(self), frameless=True)

        # 检查是否有多个卡片被选中
        selected_items = self.scene.selectedItems()
        selected_cards = [item for item in selected_items if isinstance(item, TaskCard)]
        is_multi_selection = len(selected_cards) > 1

        # --- Restore logic to handle clicks on items OR background ---
        if isinstance(item, TaskCard):
            # --- Card Context Menu ---
            debug_print(f"  [DEBUG] Creating context menu for TaskCard {item.card_id}.") # DEBUG

            # 如果有多个卡片被选中，显示多选菜单
            if is_multi_selection:
                debug_print(f"  [DEBUG] Multi-selection detected: {len(selected_cards)} cards selected")

                copy_multi_action = menu.addAction(f"复制选中卡片 ({len(selected_cards)}个)")
                copy_multi_action.setEnabled(not is_running)
                if is_running:
                    copy_multi_action.setToolTip("工作流运行期间无法复制卡片")

                menu.addSeparator()

                delete_multi_action = menu.addAction(f"删除选中卡片 ({len(selected_cards)}个)")
                delete_multi_action.setEnabled(not is_running)
                if is_running:
                    delete_multi_action.setToolTip("工作流运行期间无法删除卡片")

                action = menu.exec(self.mapToGlobal(pos))

                if action == copy_multi_action:
                    debug_print(f"  [DEBUG] '复制选中卡片' action selected")
                    self.handle_copy_selected_cards()
                elif action == delete_multi_action:
                    debug_print(f"  [DEBUG] '删除选中卡片' action selected")
                    self._delete_selected_cards(selected_cards)
                return

            # 单个卡片的菜单
            settings_action = menu.addAction("参数设置")
            settings_action.setEnabled(not is_running)
            if is_running:
                settings_action.setToolTip("工作流运行期间无法修改参数")
            
            menu.addSeparator()

            # 添加备注名称选项
            rename_action = menu.addAction("备注卡片名称")
            rename_action.setEnabled(not is_running)
            if is_running:
                rename_action.setToolTip("工作流运行期间无法修改备注")

            # 添加修改ID选项
            change_id_action = menu.addAction("修改卡片ID")
            change_id_action.setEnabled(not is_running)
            if is_running:
                change_id_action.setToolTip("工作流运行期间无法修改ID")

            menu.addSeparator()

            copy_action = menu.addAction("复制卡片")
            copy_action.setEnabled(not is_running)
            if is_running:
                copy_action.setToolTip("工作流运行期间无法复制卡片")

            menu.addSeparator()

            # 添加测试功能菜单项
            test_card_action = menu.addAction("测试卡片")
            test_card_action.setEnabled(not is_running)
            if is_running:
                test_card_action.setToolTip("工作流运行期间无法测试卡片")

            test_flow_action = menu.addAction("测试流程")
            test_flow_action.setEnabled(not is_running)
            if is_running:
                test_flow_action.setToolTip("工作流运行期间无法测试流程")

            menu.addSeparator()

            delete_action = menu.addAction("删除卡片")
            delete_action.setEnabled(not is_running)
            if is_running:
                delete_action.setToolTip("工作流运行期间无法删除卡片")
            
            debug_print(f"  [DEBUG] Executing card menu...") # DEBUG
            action = menu.exec(self.mapToGlobal(pos))
            debug_print(f"  [DEBUG] Card menu finished. Selected action: {action.text() if action else 'None'}") # DEBUG

            if action == settings_action:
                debug_print(f"  [DEBUG] '参数设置' action selected for card {item.card_id}.") # DEBUG
                if hasattr(item, 'open_parameter_dialog') and callable(item.open_parameter_dialog):
                    debug_print(f"  [DEBUG] Calling item.open_parameter_dialog()...") # DEBUG
                    item.open_parameter_dialog()
                    debug_print(f"  [DEBUG] Returned from item.open_parameter_dialog().") # DEBUG
                else:
                    debug_print(f"  [调试] 错误：项目 {item.card_id} 没有可调用的 open_parameter_dialog 方法！") # DEBUG
                    QMessageBox.warning(self, "错误", f"任务卡片 '{item.title}' 缺少参数设置功能。")
            elif action == rename_action:
                debug_print(f"  [DEBUG] '备注卡片名称' action selected for card {item.card_id}.") # DEBUG
                self.handle_rename_card(item)
            elif action == change_id_action:
                debug_print(f"  [DEBUG] '修改卡片ID' action selected for card {item.card_id}.") # DEBUG
                self.handle_change_card_id(item)
            elif action == copy_action:
                debug_print(f"  [DEBUG] '复制卡片' action selected.") # DEBUG
                item.copy_card()
            elif action == test_card_action:
                debug_print(f"  [DEBUG] '测试卡片' action selected for card {item.card_id}.") # DEBUG
                self._handle_test_card(item.card_id)
            elif action == test_flow_action:
                debug_print(f"  [DEBUG] '测试流程' action selected for card {item.card_id}.") # DEBUG
                self._handle_test_flow(item.card_id)
            elif action == delete_action:
                # <<< MODIFIED: Call the central delete_card method >>>
                debug_print(f"  [DEBUG] '删除卡片' action selected for card {item.card_id}. Calling self.delete_card...")
                self.delete_card(item.card_id)
                # --- REMOVED manual cleanup code --- 
                # card_to_delete = item
                # debug_print(f"  [DEBUG] '删除卡片' action selected for card {card_to_delete.card_id}.") # DEBUG
                # # --- ADDED: Also check connections during card deletion ---
                # for conn in list(card_to_delete.connections): # Iterate over a copy
                #     self.remove_connection(conn) # Use the modified remove_connection logic
                #     # --- REMOVED redundant logic now handled by remove_connection ---
                #     # self.scene.removeItem(conn)
                #     # other_card = conn.start_item if conn.end_item == card_to_delete else conn.end_item
                #     # if other_card and hasattr(other_card, 'remove_connection'):
                #     #     other_card.remove_connection(conn)
                #     # ----------------------------------------------------------
                # self.scene.removeItem(card_to_delete)
                # if card_to_delete.card_id in self.cards:
                #     del self.cards[card_to_delete.card_id]
                # debug_print(f"卡片 {card_to_delete.card_id} 已删除")
                # --- END REMOVED manual cleanup code ---

        elif isinstance(item, ConnectionLine):
             # --- Connection Context Menu ---
            debug_print(f"  [DEBUG] Creating context menu for ConnectionLine.") # DEBUG

            delete_conn_action = menu.addAction("删除连接")
            delete_conn_action.setEnabled(not is_running)
            if is_running:
                delete_conn_action.setToolTip("工作流运行期间无法删除连接")

            action = menu.exec(self.mapToGlobal(pos))
            if action == delete_conn_action and not is_running:
                conn_to_delete = item # Keep reference
                debug_print(f"  [DEBUG] '删除连接' (context menu) action selected for {conn_to_delete}. Calling self.remove_connection...") # DEBUG (Fixed string escaping)
                # remove_connection will trigger update_card_sequence_display if needed
                self.remove_connection(conn_to_delete) # <-- Use the centralized method
                debug_print("连接已通过 remove_connection 删除。") # DEBUG

        elif item is None: # Explicitly check for None for background
            # --- View Context Menu ---
            debug_print("  [DEBUG] Clicked on background. Showing view context menu.") # DEBUG

            add_card_action = menu.addAction("添加步骤")
            add_card_action.setEnabled(not is_running)
            if is_running:
                add_card_action.setToolTip("工作流运行期间无法添加步骤")
            
            # --- Corrected Paste Action --- 
            paste_action = menu.addAction("粘贴卡片")
            # Use lambda to pass the correct scene_pos where the menu was requested
            paste_action.triggered.connect(lambda: self.handle_paste_card(scene_pos)) 
            # --- ADDED: Set enabled state based on clipboard and running status --- 
            can_paste = self.is_paste_available() and not is_running
            paste_action.setEnabled(can_paste)
            if is_running:
                paste_action.setToolTip("工作流运行期间无法粘贴卡片")
            elif not self.is_paste_available():
                paste_action.setToolTip("剪贴板中没有可粘贴的卡片数据")

            # 添加撤销选项
            undo_action = menu.addAction("撤销 (Ctrl+Z)")
            can_undo = self.can_undo() and not is_running
            undo_action.setEnabled(can_undo)
            if is_running:
                undo_action.setToolTip("工作流运行期间无法撤销")
            elif not self.can_undo():
                undo_action.setToolTip("没有可撤销的操作")
            # ---------------------------------------------------
            menu.addSeparator()

            save_action = menu.addAction("保存工作流")

            menu.addSeparator()
            fit_view_action = menu.addAction("适应视图")

            # --- REMOVED: Auto Arrange Action ---
            # (Code was already removed in previous step)
            # -------------------------------------

            action = menu.exec(self.mapToGlobal(pos))

            if action == add_card_action:
                self.prompt_and_add_card_at(scene_pos) # <-- RESTORED: Call original function
            elif action == save_action:
                # Need access to main window or a way to trigger save from there
                logger.warning("保存工作流功能应由主窗口处理。")
            elif action == undo_action:
                self.undo_last_operation()
            elif action == fit_view_action:
                 self.fit_view_to_items()
        else: # Should not be reached if item is not None, Card, or Line
            debug_print(f"  [DEBUG] Clicked on unhandled item type ({type(item).__name__}), no menu shown.") # DEBUG

    def prompt_and_add_card_at(self, scene_pos: QPointF):
        """Opens the custom task selection dialog and adds the selected card."""
        # Import the function to get primary task types for UI display
        from tasks import get_available_tasks
        task_types = get_available_tasks()
        if not task_types:
            QMessageBox.warning(self, "错误", "没有可用的任务类型！")
            return

        # Use the custom dialog instead of QInputDialog
        dialog = SelectTaskDialog(task_types, self) # Pass self as parent
        result = dialog.exec()

        if result == QDialog.DialogCode.Accepted:
            task_type = dialog.selected_task_type()
            if task_type:
                # Add the card (won't trigger update by itself)
                new_card = self.add_task_card(scene_pos.x(), scene_pos.y(), task_type=task_type)
                # Manually trigger update after adding card via context menu
                if new_card:
                    debug_print("  [CONTEXT_ADD_DEBUG] Card added via context menu, triggering sequence update.")
                    # self.update_card_sequence_display() # <<< REMOVED Direct Call
                    # QTimer.singleShot(0, self.update_card_sequence_display) # <<< REMOVED Deferred Call
                    self.update_card_sequence_display() # <<< RESTORED Direct Call
                    debug_print(f"  Direct sequence update called after adding card via context menu.")
            else:
                debug_print("警告：选择的任务类型为空。") # Should not happen if list is populated
                dialog.deleteLater()
