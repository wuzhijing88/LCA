from .workflow_view_common import *


class WorkflowViewUndoApplyMixin:

    def undo_last_operation(self):
        """撤销最后一个操作。"""
        debug_print(f"  [UNDO] undo_last_operation called")

        if not self.can_undo():
            debug_print("  [UNDO] Cannot undo: no operations in stack or workflow is running")
            return

        if self._block_edit_if_running("撤销操作"):
            return

        # 设置撤销操作标志，防止撤销过程中的操作触发新的撤销保存
        self._undoing_operation = True
        debug_print(f"  [UNDO] Set undoing operation flag to True")
        logger.info(f"  [UNDO] Set undoing operation flag to True")

        # 【闪退修复】双重检查undo_stack，防止竞态条件导致IndexError
        if not self.undo_stack:
            logger.error("  [UNDO] 撤销栈为空，无法执行撤销（竞态条件）")
            self._undoing_operation = False
            return

        last_operation = self.undo_stack.pop()
        operation_type = last_operation['operation_type']
        operation_data = last_operation['operation_data']

        debug_print(f"  [UNDO] Undoing operation: {operation_type}")
        debug_print(f"  [UNDO] Operation data: {operation_data}")

        try:
            if operation_type == 'paste_cards':
                self._undo_paste_cards(operation_data)
            elif operation_type == 'delete_card':
                self._undo_delete_card(operation_data)
            elif operation_type == 'delete_connection':
                self._undo_delete_connection(operation_data)
            elif operation_type == 'add_connection':
                self._undo_add_connection(operation_data)
            elif operation_type == 'modify_connection':
                self._undo_modify_connection(operation_data)
            elif operation_type == 'add_card':
                self._undo_add_card(operation_data)
            else:
                debug_print(f"  [UNDO] Unknown operation type: {operation_type}")
                return

            # 更新显示
            self.update_card_sequence_display()
            debug_print(f"  [UNDO] Successfully undone operation: {operation_type}")

        except Exception as e:
            debug_print(f"  [UNDO] Error undoing operation {operation_type}: {e}")
            logger.error(f"撤销操作失败: {e}", exc_info=True)

        finally:
            # 无论成功还是失败，都要清除撤销操作标志
            self._undoing_operation = False
            debug_print(f"  [UNDO] Cleared undoing operation flag")

    def _undo_paste_cards(self, operation_data: Dict[str, Any]):
        """撤销粘贴卡片操作"""
        pasted_card_ids = operation_data.get('pasted_card_ids', [])

        debug_print(f"  [UNDO] Undoing paste operation, removing {len(pasted_card_ids)} cards")

        for card_id in pasted_card_ids:
            if card_id in self.cards:
                card = self.cards[card_id]
                # 移除卡片的所有连接
                for conn in list(card.connections):
                    self.remove_connection(conn)

                # 注释已清理（原注释编码损坏）
                if card.scene() == self.scene:
                    self.scene.removeItem(card)
                del self.cards[card_id]

                debug_print(f"  [UNDO] Removed pasted card: {card_id}")

    def _undo_delete_card(self, operation_data: Dict[str, Any]):
        """撤销删除卡片操作"""
        card_state = operation_data.get('card_state')
        if not card_state:
            debug_print("  [UNDO] No card state found for undo")
            return

        card_id = card_state['card_id']
        task_type = card_state['task_type']
        parameters = card_state['parameters']
        custom_name = card_state['custom_name']
        position = card_state['position']
        connections_data = card_state['connections']

        debug_print(f"  [UNDO] Restoring deleted card: {card_id} ({task_type})")
        debug_print(f"  [UNDO] Card state to restore:")
        debug_print(f"    - Position: {position}")
        debug_print(f"    - Parameters: {parameters}")
        debug_print(f"    - Custom name: {custom_name}")
        debug_print(f"    - Connections: {len(connections_data)} connections")

        # 注释已清理（原注释编码损坏）
        if card_id in self.cards:
            debug_print(f"  [撤销] 错误：卡片 ID {card_id} 已存在，当前卡片：{list(self.cards.keys())}")
            return

        # 重新创建卡片
        debug_print(f"  [UNDO] Calling add_task_card with: pos=({position[0]}, {position[1]}), type={task_type}, id={card_id}")
        restored_card = self.add_task_card(position[0], position[1], task_type, card_id, parameters)
        if not restored_card:
            debug_print(f"  [撤销] 错误：恢复卡片失败 {card_id}")
            return

        debug_print(f"  [UNDO] Card {card_id} created successfully")
        debug_print(f"  [UNDO] Restored card parameters: {restored_card.parameters}")

        # 恢复自定义名称
        if custom_name:
            debug_print(f"  [UNDO] Setting custom name: '{custom_name}'")
            restored_card.set_custom_name(custom_name)
        else:
            debug_print(f"  [UNDO] No custom name to restore")

        # 注释已清理（原注释编码损坏）
        debug_print(f"  [UNDO] Scheduling connection restoration for card {card_id} in 500ms")
        QTimer.singleShot(500, lambda: self._restore_card_connections(card_id, connections_data))

        debug_print(f"  [UNDO] Successfully restored card {card_id}")

    def _restore_card_connections(self, card_id: int, connections_data: List[Dict[str, Any]]):
        """恢复卡片的连接"""
        debug_print(f"  [UNDO] Starting connection restoration for card {card_id}")
        debug_print(f"  [UNDO] Current cards in workflow: {list(self.cards.keys())}")

        # 设置撤销操作标志，防止连接恢复过程中的操作触发新的撤销保存
        was_undoing = getattr(self, '_undoing_operation', False)
        self._undoing_operation = True
        debug_print(f"  [UNDO] Set undoing operation flag to True for connection restoration")

        restored_card = self.cards.get(card_id)
        if not restored_card:
            debug_print(f"  [撤销] 错误：无法恢复连线，未找到卡片 {card_id}")
            debug_print(f"  [UNDO] Available cards: {list(self.cards.keys())}")
            return

        debug_print(f"  [UNDO] Restoring {len(connections_data)} connections for card {card_id}")

        successful_restorations = 0
        failed_restorations = 0

        for i, conn_data in enumerate(connections_data):
            start_card_id = conn_data['start_card_id']
            end_card_id = conn_data['end_card_id']
            line_type = conn_data['line_type']

            debug_print(f"    [CONN {i+1}/{len(connections_data)}] Restoring: {start_card_id} -> {end_card_id} ({line_type})")

            start_card = self.cards.get(start_card_id)
            end_card = self.cards.get(end_card_id)

            if not start_card:
                debug_print(f"      错误：未找到起始卡片 {start_card_id}")
                failed_restorations += 1
                continue

            if not end_card:
                debug_print(f"      错误：未找到结束卡片 {end_card_id}")
                failed_restorations += 1
                continue

            # 检查连接是否已存在
            existing_conn = None
            for conn in self.connections:
                if (isinstance(conn, ConnectionLine) and
                    conn.start_item == start_card and
                    conn.end_item == end_card and
                    conn.line_type == line_type):
                    existing_conn = conn
                    break

            if existing_conn:
                debug_print(f"      Connection already exists, skipping")
                successful_restorations += 1
            else:
                new_conn = self.add_connection(start_card, end_card, line_type)
                if new_conn:
                    debug_print(f"      SUCCESS: Restored connection")
                    successful_restorations += 1
                else:
                    debug_print("      错误：创建连线失败")
                    failed_restorations += 1

        debug_print(f"  [UNDO] Connection restoration completed: {successful_restorations} success, {failed_restorations} failed")

        # 如果有连接恢复，触发更新
        if successful_restorations > 0:
            debug_print(f"  [UNDO] Triggering sequence update after connection restoration")
            self.update_card_sequence_display()

        # 恢复撤销操作标志状态
        self._undoing_operation = was_undoing
        debug_print(f"  [UNDO] Restored undoing operation flag to {was_undoing} after connection restoration")

    def _undo_delete_connection(self, operation_data: Dict[str, Any]):
        """撤销删除连接操作"""
        conn_data = operation_data.get('connection_data')
        if not conn_data:
            debug_print("  [UNDO] No connection data found for undo")
            return

        start_card_id = conn_data['start_card_id']
        end_card_id = conn_data['end_card_id']
        line_type = conn_data['line_type']

        start_card = self.cards.get(start_card_id)
        end_card = self.cards.get(end_card_id)

        if start_card and end_card:
            new_conn = self.add_connection(start_card, end_card, line_type)
            if new_conn:
                debug_print(f"  [UNDO] Restored connection: {start_card_id} -> {end_card_id} ({line_type})")
            else:
                debug_print(f"  [撤销] 恢复连线失败：{start_card_id} -> {end_card_id} ({line_type})")
        else:
            debug_print(f"  [UNDO] Cannot restore connection: missing cards {start_card_id} or {end_card_id}")

    def _undo_add_connection(self, operation_data: Dict[str, Any]):
        """撤销添加连接操作"""
        conn_data = operation_data.get('connection_data')
        if not conn_data:
            debug_print("  [UNDO] No connection data found for undo")
            return

        start_card_id = conn_data['start_card_id']
        end_card_id = conn_data['end_card_id']
        line_type = conn_data['line_type']

        debug_print(f"  [UNDO] Removing added connection: {start_card_id} -> {end_card_id} ({line_type})")

        # 查找并删除对应的连接
        connection_to_remove = None
        for conn in self.connections:
            if (hasattr(conn, 'start_item') and hasattr(conn, 'end_item') and
                conn.start_item and conn.end_item and
                conn.start_item.card_id == start_card_id and
                conn.end_item.card_id == end_card_id and
                conn.line_type == line_type):
                connection_to_remove = conn
                break

        if connection_to_remove:
            self.remove_connection(connection_to_remove)
            debug_print(f"  [UNDO] Added connection removed successfully")
        else:
            debug_print("  [撤销] 未找到要移除的连线")

    def _undo_modify_connection(self, operation_data: Dict[str, Any]):
        """撤销修改连接操作"""
        old_conn_data = operation_data.get('old_connection_data')
        new_conn_data = operation_data.get('new_connection_data')

        if not old_conn_data or not new_conn_data:
            debug_print("  [UNDO] Missing connection data for modify undo")
            return

        debug_print(f"  [UNDO] Undoing connection modification:")
        debug_print(f"    Removing new: {new_conn_data['start_card_id']} -> {new_conn_data['end_card_id']} ({new_conn_data['line_type']})")
        debug_print(f"    Restoring old: {old_conn_data['start_card_id']} -> {old_conn_data['end_card_id']} ({old_conn_data['line_type']})")

        # 1. 删除新连接
        new_connection_to_remove = None
        for conn in self.connections:
            if (hasattr(conn, 'start_item') and hasattr(conn, 'end_item') and
                conn.start_item and conn.end_item and
                conn.start_item.card_id == new_conn_data['start_card_id'] and
                conn.end_item.card_id == new_conn_data['end_card_id'] and
                conn.line_type == new_conn_data['line_type']):
                new_connection_to_remove = conn
                break

        if new_connection_to_remove:
            self.remove_connection(new_connection_to_remove)
            debug_print(f"  [UNDO] Removed new connection")
        else:
            debug_print("  [撤销] 未找到要移除的新连线")

        # 注释已清理（原注释编码损坏）
        old_start_card = self.cards.get(old_conn_data['start_card_id'])
        old_end_card = self.cards.get(old_conn_data['end_card_id'])

        if old_start_card and old_end_card:
            restored_conn = self.add_connection(old_start_card, old_end_card, old_conn_data['line_type'])
            if restored_conn:
                debug_print(f"  [UNDO] Successfully restored old connection")
            else:
                debug_print("  [撤销] 恢复旧连线失败")
        else:
            debug_print(f"  [UNDO] Cannot restore old connection: missing cards {old_conn_data['start_card_id']} or {old_conn_data['end_card_id']}")

    def _undo_add_card(self, operation_data: Dict[str, Any]):
        """撤销添加卡片操作"""
        card_data = operation_data.get('card_data')
        if not card_data:
            debug_print("  [UNDO] No card data found for undo")
            return

        card_id = card_data.get('card_id')
        if card_id and card_id in self.cards:
            self.delete_card(card_id)
            debug_print(f"  [UNDO] Removed added card: {card_id}")
        else:
            debug_print(f"  [撤销] 未找到要移除的卡片：{card_id}")
