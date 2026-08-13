from .workflow_view_common import *

operation_logger = logging.getLogger("workflow.operations")

# 撤回记录模块只输出明确错误，不输出逐步调试信息。
debug_print = lambda *args, **kwargs: None


class WorkflowViewUndoStateMixin:

    _UNDO_OPERATION_FIELDS = {
        'paste_cards': {'pasted_card_ids', 'paste_type'},
        'delete_card': {'card_state'},
        'delete_batch': {'card_states', 'connections'},
        'delete_connection': {'connection_data'},
        'add_connection': {'connection_data'},
        'modify_connection': {'old_connection_data', 'new_connection_data'},
        'add_card': {'card_data'},
        'change_card_ids': {'id_mapping'},
    }

    def _save_undo_state(self, operation_type: str, operation_data: Dict[str, Any]):
        """保存撤销状态到历史栈。"""
        if self._block_edit_if_running("保存撤销状态"):
            return

        # 注释已清理（原注释编码损坏）
        if self._loading_workflow:
            debug_print(f"  [UNDO] Skipping undo save during workflow loading: {operation_type}")
            return

        if self._undoing_operation:
            debug_print(f"  [UNDO] Skipping undo save during undo operation: {operation_type}")
            logger.info(f"  [UNDO] Skipping undo save during undo operation: {operation_type}")
            return

        if operation_type not in self._UNDO_OPERATION_FIELDS:
            raise ValueError(f"未知撤回操作类型: {operation_type}")
        if not isinstance(operation_data, dict):
            raise TypeError("撤回操作数据必须是字典")
        expected_fields = self._UNDO_OPERATION_FIELDS[operation_type]
        if set(operation_data) != expected_fields:
            raise ValueError(
                f"撤回操作 {operation_type} 字段错误: "
                f"期望 {sorted(expected_fields)}，实际 {sorted(operation_data)}"
            )

        undo_state = {
            'operation_type': operation_type,
            'operation_data': copy.deepcopy(operation_data),
            'timestamp': time.time()
        }

        self.undo_stack.append(undo_state)

        # 限制撤销历史的大小
        if len(self.undo_stack) > self.max_undo_steps:
            self.undo_stack.pop(0)

        debug_print(f"  [UNDO] Saved undo state: {operation_type}, stack size: {len(self.undo_stack)}")

    def _save_card_state_for_undo(self, card: TaskCard):
        """保存卡片的完整状态用于撤销删除操作"""
        debug_print(f"  [UNDO] _save_card_state_for_undo called for card {card.card_id}")
        try:
            # 收集卡片的所有连接信息
            connections_data = []
            debug_print(f"  [UNDO] Card {card.card_id} has {len(card.connections)} connections")
            for conn in card.connections:
                if isinstance(conn, ConnectionLine):
                    conn_data = {
                        'start_card_id': conn.start_item.card_id if conn.start_item else None,
                        'end_card_id': conn.end_item.card_id if conn.end_item else None,
                        'line_type': conn.line_type,
                        'is_outgoing': conn.start_item == card  # 是否是从该卡片发出的连接
                    }
                    connections_data.append(conn_data)

            # 保存卡片的完整状态
            card_state = {
                'card_id': card.card_id,
                'task_type': card.task_type,
                'parameters': copy.deepcopy(card.parameters),
                'custom_name': card.custom_name,
                'position': (card.pos().x(), card.pos().y()),
                'connections': connections_data
            }

            # 注释已清理（原注释编码损坏）
            self._save_undo_state('delete_card', {
                'card_state': card_state
            })

            debug_print(f"  [UNDO] Saved card state for undo: {card.card_id} with {len(connections_data)} connections")

        except Exception as e:
            operation_logger.error("[撤回记录] 保存卡片删除状态失败: %s", e, exc_info=True)
            logger.error(f"保存卡片状态失败: {e}", exc_info=True)

    def _save_connection_state_for_undo(self, connection):
        """保存连接状态用于撤销删除操作"""
        try:
            if isinstance(connection, ConnectionLine):
                conn_data = {
                    'start_card_id': connection.start_item.card_id if connection.start_item else None,
                    'end_card_id': connection.end_item.card_id if connection.end_item else None,
                    'line_type': connection.line_type
                }

                # 注释已清理（原注释编码损坏）
                self._save_undo_state('delete_connection', {
                    'connection_data': conn_data
                })

                debug_print(f"  [UNDO] Saved connection state for undo: {conn_data['start_card_id']} -> {conn_data['end_card_id']} ({conn_data['line_type']})")

        except Exception as e:
            operation_logger.error("[撤回记录] 保存连线删除状态失败: %s", e, exc_info=True)
            logger.error(f"保存连接状态失败: {e}", exc_info=True)

    def _save_add_connection_state_for_undo(self, start_card, end_card, line_type):
        """保存添加连接的状态用于撤销"""
        try:
            conn_data = {
                'start_card_id': start_card.card_id if start_card else None,
                'end_card_id': end_card.card_id if end_card else None,
                'line_type': line_type
            }

            # 注释已清理（原注释编码损坏）
            self._save_undo_state('add_connection', {
                'connection_data': conn_data
            })

            debug_print(f"  [UNDO] Saved add connection state for undo: {conn_data['start_card_id']} -> {conn_data['end_card_id']} ({conn_data['line_type']})")

        except Exception as e:
            operation_logger.error("[撤回记录] 保存连线新增状态失败: %s", e, exc_info=True)
            logger.error(f"保存添加连接状态失败: {e}", exc_info=True)

    def _save_modify_connection_state_for_undo(self, old_connection, new_start_card, new_end_card, new_line_type):
        """保存修改连接的状态用于撤销（包含删除旧连接和添加新连接）。"""
        try:
            # 注释已清理（原注释编码损坏）
            old_conn_data = {
                'start_card_id': old_connection.start_item.card_id if old_connection.start_item else None,
                'end_card_id': old_connection.end_item.card_id if old_connection.end_item else None,
                'line_type': old_connection.line_type if hasattr(old_connection, 'line_type') else 'unknown'
            }

            # 新连接数据
            new_conn_data = {
                'start_card_id': new_start_card.card_id if new_start_card else None,
                'end_card_id': new_end_card.card_id if new_end_card else None,
                'line_type': new_line_type
            }

            # 保存复合撤销操作
            self._save_undo_state('modify_connection', {
                'old_connection_data': old_conn_data,
                'new_connection_data': new_conn_data
            })

            debug_print("  [UNDO] Saved modify connection state for undo:")
            debug_print(f"    Old: {old_conn_data['start_card_id']} -> {old_conn_data['end_card_id']} ({old_conn_data['line_type']})")
            debug_print(f"    New: {new_conn_data['start_card_id']} -> {new_conn_data['end_card_id']} ({new_conn_data['line_type']})")

        except Exception as e:
            operation_logger.error("[撤回记录] 保存连线修改状态失败: %s", e, exc_info=True)
            logger.error(f"保存修改连接状态失败: {e}", exc_info=True)

    def _save_add_card_state_for_undo(self, card_id: int, task_type: str, x: float, y: float, parameters: Optional[dict]):
        """保存添加卡片的状态用于撤销"""
        try:
            card_data = {
                'card_id': card_id,
                'task_type': task_type,
                'position': (x, y),
                'parameters': copy.deepcopy(parameters) if parameters else {}
            }

            # 注释已清理（原注释编码损坏）
            self._save_undo_state('add_card', {
                'card_data': card_data
            })

            debug_print(f"  [UNDO] Saved add card state for undo: ID={card_id}, type={task_type}, pos=({x}, {y})")

        except Exception as e:
            operation_logger.error("[撤回记录] 保存卡片新增状态失败: %s", e, exc_info=True)
            logger.error(f"保存添加卡片状态失败: {e}", exc_info=True)

    def can_undo(self) -> bool:
        """检查是否可以撤销"""
        can_undo = len(self.undo_stack) > 0 and not self._is_workflow_running()
        debug_print(f"  [UNDO] can_undo check: stack_size={len(self.undo_stack)}, is_running={self._is_workflow_running()}, result={can_undo}")
        if len(self.undo_stack) > 0:
            last_op = self.undo_stack[-1]
            debug_print(f"  [UNDO] Last operation in stack: {last_op.get('operation_type', 'unknown')}")
        return can_undo
