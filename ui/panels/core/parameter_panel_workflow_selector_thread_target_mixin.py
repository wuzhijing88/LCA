from ..parameter_panel_support import *


class ParameterPanelWorkflowSelectorThreadTargetMixin:
    def _resolve_current_thread_start_card_id(
        self,
        start_card_ids: List[int],
        adjacency: Dict[int, Set[int]],
    ) -> Optional[int]:
        current_card_id = self.current_card_id
        if current_card_id is None:
            return None

        owner_start_ids: List[int] = []
        for start_id in start_card_ids:
            reachable = self._collect_reachable_card_ids(start_id, adjacency)
            if int(current_card_id) in reachable:
                owner_start_ids.append(start_id)

        if len(owner_start_ids) == 1:
            return owner_start_ids[0]
        return None

    def _collect_workflow_cards_for_target_thread(self, target_value: Any) -> List[tuple[int, str, str]]:
        all_cards = self._collect_workflow_cards_for_selector()
        if not all_cards:
            return []

        start_card_ids = [
            card_id for card_id, task_type, _ in all_cards if is_thread_start_task_type(task_type)
        ]
        if not start_card_ids:
            return all_cards

        target_text = str(target_value or '').strip()
        if not target_text or target_text == '全部线程':
            return all_cards

        adjacency = self._build_workflow_adjacency_for_selector()
        selected_start_id = self._parse_thread_start_id_from_target(target_value)
        if selected_start_id is not None and selected_start_id not in start_card_ids:
            selected_start_id = None

        if selected_start_id is None and target_text == '当前线程':
            selected_start_id = self._resolve_current_thread_start_card_id(start_card_ids, adjacency)

        if selected_start_id is None:
            return all_cards

        allowed_ids = self._collect_reachable_card_ids(selected_start_id, adjacency)
        filtered_cards = [item for item in all_cards if item[0] in allowed_ids]
        return filtered_cards if filtered_cards else all_cards
