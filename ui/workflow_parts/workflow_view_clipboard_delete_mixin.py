from .workflow_view_common import *

operation_logger = logging.getLogger("workflow.operations")


class WorkflowViewClipboardDeleteMixin:

    def _delete_selected_cards(self, selected_cards: List[TaskCard]):
        """删除选中的多个卡片"""
        if not selected_cards:
            return

        if self._block_edit_if_running("删除选中卡片"):
            return

        operation_logger.info("[批量删除] 请求删除卡片数量=%s", len(selected_cards))

        # 注释已清理（原注释编码损坏）
        deleted_count = self._delete_cards_batch(selected_cards)

        operation_logger.info("[批量删除] 完成，实际删除数量=%s", deleted_count)

    def _delete_cards_batch(self, selected_cards: List[TaskCard], selected_connections=None) -> int:
        """将选中的卡片和连线作为一个撤回事务删除。"""
        selected_connections = list(selected_connections or [])
        if not selected_cards and not selected_connections:
            return 0

        has_start_card = False
        candidate_ids: List[int] = []
        for card in selected_cards:
            if not isinstance(card, TaskCard):
                continue
            card_id = getattr(card, "card_id", None)
            if card_id is None or card_id not in self.cards:
                continue
            candidate_ids.append(card_id)
            if not has_start_card and self._is_start_task_type(getattr(card, "task_type", "")):
                has_start_card = True

        if not candidate_ids and not selected_connections:
            return 0

        deleted_count = 0
        unique_ids = sorted(set(candidate_ids), reverse=True)

        card_states = []
        connection_states = {}
        for card_id in unique_ids:
            card = self.cards[card_id]
            card_states.append({
                'card_id': card.card_id,
                'task_type': card.task_type,
                'parameters': copy.deepcopy(card.parameters),
                'custom_name': card.custom_name,
                'position': (card.pos().x(), card.pos().y()),
            })
            for connection in card.connections:
                key = id(connection)
                connection_states[key] = {
                    'start_card_id': connection.start_item.card_id,
                    'end_card_id': connection.end_item.card_id,
                    'line_type': connection.line_type,
                }

        standalone_connections = []
        selected_card_objects = {self.cards[card_id] for card_id in unique_ids}
        for connection in selected_connections:
            if (
                getattr(connection, 'start_item', None) in selected_card_objects
                or getattr(connection, 'end_item', None) in selected_card_objects
            ):
                continue
            self._validate_connection_contract(connection)
            standalone_connections.append(connection)
            connection_states[id(connection)] = {
                'start_card_id': connection.start_item.card_id,
                'end_card_id': connection.end_item.card_id,
                'line_type': connection.line_type,
            }

        updates_enabled = self.updatesEnabled()
        was_undoing = self._undoing_operation
        self.setUpdatesEnabled(False)
        self._undoing_operation = True
        try:
            for connection in standalone_connections:
                if not self.remove_connection(connection):
                    raise RuntimeError("批量删除中的连线删除失败")
            for card_id in unique_ids:
                if card_id not in self.cards:
                    continue
                self.delete_card(card_id, defer_view_refresh=True)
                if card_id in self.cards:
                    raise RuntimeError(f"批量删除卡片失败: {card_id}")
                deleted_count += 1
        finally:
            self._undoing_operation = was_undoing
            self.setUpdatesEnabled(updates_enabled)

        if deleted_count > 0 or standalone_connections:
            self._save_undo_state('delete_batch', {
                'card_states': card_states,
                'connections': list(connection_states.values()),
            })
            self.update_card_sequence_display()
            if has_start_card:
                self._refresh_thread_start_custom_names()
            self.viewport().update()

        return deleted_count
