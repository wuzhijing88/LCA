from ..parameter_panel_support import *


class ParameterPanelWorkflowSelectorThreadCollectMixin:
    def _collect_workflow_cards_for_selector(self) -> List[tuple[int, str, str]]:
        """收集当前工作流卡片信息: (card_id, task_type, custom_name)?"""
        workflow_view = self._get_active_workflow_view()
        custom_name_map: Dict[int, str] = {}
        if workflow_view and hasattr(workflow_view, 'cards'):
            try:
                for card_id, card_obj in workflow_view.cards.items():
                    custom_name_map[int(card_id)] = str(
                        getattr(card_obj, 'custom_name', '') or ''
                    ).strip()
            except Exception:
                custom_name_map = {}

        results: List[tuple[int, str, str]] = []
        seen = set()
        for _, info in sorted((self.workflow_cards_info or {}).items(), key=lambda kv: kv[0]):
            if not isinstance(info, (tuple, list)) or len(info) < 2:
                continue
            task_type = str(info[0] or '未知任务')
            try:
                card_id = int(info[1])
            except Exception:
                continue
            if card_id in seen:
                continue
            seen.add(card_id)
            results.append((card_id, task_type, custom_name_map.get(card_id, '')))

        if not results and workflow_view and hasattr(workflow_view, 'cards'):
            try:
                for card_id, card_obj in workflow_view.cards.items():
                    cid = int(card_id)
                    task_type = str(getattr(card_obj, 'task_type', '') or '未知任务')
                    custom_name = str(getattr(card_obj, 'custom_name', '') or '').strip()
                    results.append((cid, task_type, custom_name))
            except Exception:
                pass

        results.sort(key=lambda item: item[0])
        return results

    def _collect_workflow_connections_for_selector(self) -> List[tuple[int, int]]:
        """收集当前工作流连接关系: (start_card_id, end_card_id)?"""
        workflow_view = self._get_active_workflow_view()
        if not workflow_view or not hasattr(workflow_view, 'connections'):
            return []

        connections: List[tuple[int, int]] = []
        for conn in list(getattr(workflow_view, 'connections', []) or []):
            try:
                start_item = getattr(conn, 'start_item', None)
                end_item = getattr(conn, 'end_item', None)
                if start_item is None or end_item is None:
                    continue
                start_id = int(getattr(start_item, 'card_id'))
                end_id = int(getattr(end_item, 'card_id'))
            except Exception:
                continue
            connections.append((start_id, end_id))
        return connections

    def _build_workflow_adjacency_for_selector(self) -> Dict[int, Set[int]]:
        adjacency: Dict[int, Set[int]] = {}
        for start_id, end_id in self._collect_workflow_connections_for_selector():
            adjacency.setdefault(start_id, set()).add(end_id)
        return adjacency
