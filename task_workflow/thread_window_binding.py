"""Thread-level window binding resolution."""

from typing import Any, Dict, List, Optional
import logging

from utils.thread_start_utils import is_thread_start_task_type

logger = logging.getLogger(__name__)

THREAD_WINDOW_LIMIT_TASK_TYPE = "线程窗口限制"
THREAD_WINDOW_LIMIT_PARAM = "bound_window_index"


def _parse_int(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(str(value).strip())
    except Exception:
        return None


def is_start_task_type(task_type: Any) -> bool:
    return is_thread_start_task_type(task_type)


def is_thread_window_limit_task_type(task_type: Any) -> bool:
    return str(task_type or "").strip() == THREAD_WINDOW_LIMIT_TASK_TYPE


def is_valid_thread_window_limit_connection(
    start_task_type: Any,
    end_task_type: Any,
    line_type: Any,
) -> bool:
    if not is_thread_window_limit_task_type(start_task_type):
        return True
    return str(line_type or "").strip() == "sequential" and is_start_task_type(end_task_type)


def get_enabled_bound_windows(bound_windows: Any) -> List[Dict[str, Any]]:
    enabled_windows: List[Dict[str, Any]] = []
    if not isinstance(bound_windows, list):
        return enabled_windows

    for window_info in bound_windows:
        if not isinstance(window_info, dict):
            continue
        if not window_info.get("enabled", True):
            continue
        enabled_windows.append(window_info)
    return enabled_windows


def _normalize_cards(cards_data: Any) -> Dict[int, Dict[str, Any]]:
    normalized: Dict[int, Dict[str, Any]] = {}

    if isinstance(cards_data, dict):
        items = cards_data.items()
    elif isinstance(cards_data, list):
        items = enumerate(cards_data)
    else:
        return normalized

    for raw_key, card in items:
        if not isinstance(card, dict):
            continue
        card_id = _parse_int(card.get("id"))
        if card_id is None:
            card_id = _parse_int(raw_key)
        if card_id is None:
            continue
        normalized[card_id] = card
    return normalized


def _build_incoming_map(connections_data: Any) -> Dict[int, List[Dict[str, Any]]]:
    incoming_map: Dict[int, List[Dict[str, Any]]] = {}
    if not isinstance(connections_data, list):
        return incoming_map

    for connection in connections_data:
        if not isinstance(connection, dict):
            continue
        start_id = _parse_int(connection.get("start_card_id"))
        end_id = _parse_int(connection.get("end_card_id"))
        if start_id is None or end_id is None:
            continue
        incoming_map.setdefault(end_id, []).append(connection)
    return incoming_map


def resolve_thread_window_configs(
    cards_data: Any,
    connections_data: Any,
    start_card_ids: Any,
    bound_windows: Any,
    logger_obj: Optional[logging.Logger] = None,
) -> Dict[int, Dict[str, Any]]:
    active_logger = logger_obj or logger
    normalized_cards = _normalize_cards(cards_data)
    incoming_map = _build_incoming_map(connections_data)
    enabled_windows = get_enabled_bound_windows(bound_windows)
    resolved: Dict[int, Dict[str, Any]] = {}

    for raw_start_id in start_card_ids or []:
        start_id = _parse_int(raw_start_id)
        if start_id is None:
            continue

        incoming_connections = incoming_map.get(start_id, [])
        limit_card_ids: List[int] = []
        for connection in incoming_connections:
            if str(connection.get("type") or "").strip() != "sequential":
                continue
            candidate_id = _parse_int(connection.get("start_card_id"))
            if candidate_id is None:
                continue
            candidate_card = normalized_cards.get(candidate_id)
            if not isinstance(candidate_card, dict):
                continue
            if is_thread_window_limit_task_type(candidate_card.get("task_type")):
                limit_card_ids.append(candidate_id)

        if not limit_card_ids:
            continue

        if len(limit_card_ids) > 1:
            active_logger.warning(
                "thread window limit duplicated before start %s: %s",
                start_id,
                limit_card_ids,
            )

        limit_card_id = limit_card_ids[0]
        limit_card = normalized_cards.get(limit_card_id) or {}
        parameters = limit_card.get("parameters") if isinstance(limit_card, dict) else {}
        if not isinstance(parameters, dict):
            parameters = {}

        window_index = _parse_int(parameters.get(THREAD_WINDOW_LIMIT_PARAM))
        if window_index is None or window_index <= 0:
            continue

        if window_index > len(enabled_windows):
            active_logger.warning(
                "thread start %s requested window index %s but only %s enabled windows are available",
                start_id,
                window_index,
                len(enabled_windows),
            )
            continue

        selected_window = enabled_windows[window_index - 1]
        target_hwnd = _parse_int(selected_window.get("hwnd"))
        if target_hwnd is None or target_hwnd <= 0:
            active_logger.warning(
                "thread start %s requested window index %s but hwnd is invalid",
                start_id,
                window_index,
            )
            continue

        resolved[start_id] = {
            "window_index": window_index,
            "target_hwnd": target_hwnd,
            "target_window_title": str(selected_window.get("title") or "").strip(),
            "source_card_id": limit_card_id,
        }

    return resolved
