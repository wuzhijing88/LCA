from .workflow_view_common import *


class WorkflowViewClipboardDeleteMixin:

    def _delete_selected_cards(self, selected_cards: List[TaskCard]):
        """删除选中的多个卡片"""
        if not selected_cards:
            return

        if self._block_edit_if_running("删除选中卡片"):
            return

        debug_print(f"  [DELETE] Deleting {len(selected_cards)} selected cards")

        # 注释已清理（原注释编码损坏）
        deleted_count = self._delete_cards_batch(selected_cards)

        logger.info(f"已删除 {deleted_count} 个卡片")

    def _delete_cards_batch(self, selected_cards: List[TaskCard]) -> int:
        """Delete cards in one batch and refresh once."""
        if not selected_cards:
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

        if not candidate_ids:
            return 0

        deleted_count = 0
        unique_ids = sorted(set(candidate_ids), reverse=True)

        updates_enabled = self.updatesEnabled()
        self.setUpdatesEnabled(False)
        try:
            for card_id in unique_ids:
                if card_id not in self.cards:
                    continue
                self.delete_card(card_id, defer_view_refresh=True)
                if card_id not in self.cards:
                    deleted_count += 1
        finally:
            self.setUpdatesEnabled(updates_enabled)

        if deleted_count > 0:
            self.update_card_sequence_display()
            if has_start_card:
                self._refresh_thread_start_custom_names()
            self.viewport().update()

        return deleted_count
