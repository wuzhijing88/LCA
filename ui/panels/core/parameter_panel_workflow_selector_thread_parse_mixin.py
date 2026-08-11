from ..parameter_panel_support import *


class ParameterPanelWorkflowSelectorThreadParseMixin:
    @staticmethod
    def _collect_reachable_card_ids(start_card_id: int, adjacency: Dict[int, Set[int]]) -> Set[int]:
        visited: Set[int] = set()
        stack: List[int] = [int(start_card_id)]
        while stack:
            current_id = stack.pop()
            if current_id in visited:
                continue
            visited.add(current_id)
            for next_id in adjacency.get(current_id, set()):
                if next_id not in visited:
                    stack.append(next_id)
        return visited

    @staticmethod
    def _parse_thread_start_id_from_target(target_value: Any) -> Optional[int]:
        if target_value is None or isinstance(target_value, bool):
            return None
        if isinstance(target_value, int):
            return target_value if target_value >= 0 else None

        text = str(target_value).strip()
        if not text or text in {'当前线程', '全部线程'}:
            return None

        try:
            value = int(text)
            return value if value >= 0 else None
        except Exception:
            pass

        match = re.search(r'ID\s*[:?]\s*(-?\d+)', text)
        if not match:
            match = re.search(r'\(\s*ID\s*[:?]\s*(-?\d+)\s*\)', text)
        if not match:
            return None
        try:
            value = int(match.group(1))
            return value if value >= 0 else None
        except Exception:
            return None

    @staticmethod
    def _parse_card_id_from_value(value: Any) -> Optional[int]:
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value

        text = str(value).strip()
        if not text:
            return None
        if text in {'使用线程默认起点', '默认起点', 'None', 'none', '-1'}:
            return None

        try:
            return int(text)
        except Exception:
            match = re.search(r'ID\s*[:?]\s*(-?\d+)', text)
            if not match:
                match = re.search(r'\(\s*ID\s*[:?]\s*(-?\d+)\s*\)', text)
            if match:
                try:
                    return int(match.group(1))
                except Exception:
                    return None
        return None
