"""Resolve explicit per-thread window bindings."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from utils.window.hwnd_utils import as_hwnd
from task_workflow.thread_start import is_thread_start_task_type


THREAD_WINDOW_LIMIT_TASK_TYPE = "线程窗口限制"
THREAD_WINDOW_LIMIT_PARAM = "bound_window_id"


def bound_window_selector_choices(windows: Any) -> List[Tuple[str, str]]:
    choices: List[Tuple[str, str]] = []
    if not isinstance(windows, list):
        raise TypeError("绑定窗口必须是列表")
    seen: set[str] = set()
    for idx, window_info in enumerate(windows, 1):
        if not isinstance(window_info, dict):
            raise TypeError(f"绑定窗口配置必须是字典: index={idx}")
        bind_id = _require_bind_id(window_info.get("bind_id"))
        if bind_id in seen:
            raise ValueError(f"窗口绑定标识重复: {bind_id}")
        seen.add(bind_id)
        title = window_info.get("title", "")
        if not isinstance(title, str):
            raise TypeError(f"绑定窗口标题必须是字符串: index={idx}")
        title = title.strip()
        choices.append((f"窗口{idx}: {title}", bind_id))
    return choices


def is_thread_window_limit_task_type(task_type: Any) -> bool:
    return isinstance(task_type, str) and task_type.strip() == THREAD_WINDOW_LIMIT_TASK_TYPE


def is_valid_thread_window_limit_connection(
    start_task_type: Any,
    end_task_type: Any,
    line_type: Any,
) -> bool:
    if is_thread_window_limit_task_type(end_task_type):
        return False
    if not is_thread_window_limit_task_type(start_task_type):
        return True
    return (
        isinstance(line_type, str)
        and line_type.strip() == "sequential"
        and is_thread_start_task_type(end_task_type)
    )


def _require_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} 必须是整数: {value!r}")
    return value


def _require_bind_id(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("窗口绑定标识必须是非空字符串")
    return value


def require_window_dimension(value: Any, field_name: str) -> int:
    if value is None:
        return 0
    dimension = _require_int(value, field_name)
    if dimension < 0:
        raise ValueError(f"{field_name} 不能为负数")
    return dimension


def _normalize_cards(cards_data: Any) -> Dict[int, Dict[str, Any]]:
    if not isinstance(cards_data, dict) or not cards_data:
        raise ValueError("cards_data 必须是非空字典")

    normalized: Dict[int, Dict[str, Any]] = {}
    for raw_key, card in cards_data.items():
        _require_int(raw_key, "卡片字典键")
        if not isinstance(card, dict):
            raise TypeError(f"卡片数据必须是字典: key={raw_key!r}")
        card_id = _require_int(card.get("id"), f"卡片ID(key={raw_key!r})")
        if card_id < 0 or raw_key != card_id:
            raise ValueError(f"卡片字典键与非负整数ID不一致: {raw_key!r}, {card_id}")
        normalized[card_id] = card
    return normalized


def _normalize_start_card_ids(
    start_card_ids: Any,
    cards: Dict[int, Dict[str, Any]],
) -> List[int]:
    if not isinstance(start_card_ids, list) or not start_card_ids:
        raise ValueError("start_card_ids 必须是非空整数列表")

    normalized: List[int] = []
    seen: set[int] = set()
    for index, raw_start_id in enumerate(start_card_ids):
        start_id = _require_int(raw_start_id, f"线程起点ID(index={index})")
        if start_id in seen:
            raise ValueError(f"线程起点ID重复: {start_id}")
        start_card = cards.get(start_id)
        if start_card is None:
            raise ValueError(f"线程起点卡片不存在: {start_id}")
        if not is_thread_start_task_type(start_card.get("task_type")):
            raise ValueError(f"卡片不是线程起点: {start_id}")
        seen.add(start_id)
        normalized.append(start_id)
    return normalized


def _normalize_connections(
    connections_data: Any,
    cards: Dict[int, Dict[str, Any]],
) -> Dict[int, List[Dict[str, Any]]]:
    if not isinstance(connections_data, list):
        raise TypeError("connections_data 必须是列表")

    incoming_map: Dict[int, List[Dict[str, Any]]] = {}
    seen: set[tuple[int, int, str]] = set()
    for index, connection in enumerate(connections_data):
        if not isinstance(connection, dict):
            raise TypeError(f"连接数据必须是字典: index={index}")
        start_id = _require_int(connection.get("start_card_id"), f"连接起点ID(index={index})")
        end_id = _require_int(connection.get("end_card_id"), f"连接终点ID(index={index})")
        line_type = connection.get("type")
        if not isinstance(line_type, str) or not line_type.strip():
            raise ValueError(f"连接类型不能为空: index={index}")
        line_type = line_type.strip()

        start_card = cards.get(start_id)
        end_card = cards.get(end_id)
        if start_card is None or end_card is None:
            raise ValueError(f"连接引用了不存在的卡片: index={index}, {start_id}->{end_id}")
        if is_thread_window_limit_task_type(end_card.get("task_type")):
            raise ValueError(f"线程窗口限制卡 {end_id} 不允许输入连线")

        connection_key = (start_id, end_id, line_type)
        if connection_key in seen:
            raise ValueError(f"连接重复: {start_id}->{end_id} ({line_type})")
        seen.add(connection_key)

        if not is_valid_thread_window_limit_connection(
            start_card.get("task_type"),
            end_card.get("task_type"),
            line_type,
        ):
            raise ValueError(
                f"线程窗口限制卡 {start_id} 只能用顺序连线连接到线程起点"
            )
        incoming_map.setdefault(end_id, []).append(connection)
    return incoming_map


def enabled_bound_windows(bound_windows: Any) -> List[Dict[str, Any]]:
    if not isinstance(bound_windows, list):
        raise TypeError("bound_windows 必须是列表")

    enabled_windows: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for index, window_info in enumerate(bound_windows):
        if not isinstance(window_info, dict):
            raise TypeError(f"绑定窗口配置必须是字典: index={index}")
        enabled = window_info.get("enabled", True)
        if not isinstance(enabled, bool):
            raise TypeError(f"绑定窗口 enabled 必须是布尔值: index={index}")
        bind_id = _require_bind_id(window_info.get("bind_id"))
        if bind_id in seen:
            raise ValueError(f"窗口绑定标识重复: {bind_id}")
        seen.add(bind_id)
        if not enabled:
            continue

        raw_hwnd = window_info.get("hwnd")
        _require_int(raw_hwnd, f"绑定窗口句柄(index={index})")
        hwnd = as_hwnd(raw_hwnd)
        if hwnd == 0:
            raise ValueError(f"绑定窗口句柄必须大于0: index={index}")
        title = window_info.get("title", "")
        if not isinstance(title, str):
            raise TypeError(f"绑定窗口标题必须是字符串: index={index}")
        enabled_windows.append({**window_info, "hwnd": hwnd})
    return enabled_windows


def resolve_thread_window_configs(
    *,
    cards_data: Dict[Any, Dict[str, Any]],
    connections_data: List[Dict[str, Any]],
    start_card_ids: List[int],
    bound_windows: List[Dict[str, Any]],
) -> Dict[int, Dict[str, Any]]:
    """Return explicit window overrides for the requested thread starts.

    A missing limit card, or a limit card whose selector is explicitly unset,
    means that the workflow-level target remains authoritative. Invalid binding
    data is rejected instead of being skipped or replaced.
    """

    cards = _normalize_cards(cards_data)
    normalized_start_ids = _normalize_start_card_ids(start_card_ids, cards)
    incoming_map = _normalize_connections(connections_data, cards)
    enabled_windows = enabled_bound_windows(bound_windows)
    resolved: Dict[int, Dict[str, Any]] = {}

    for start_id in normalized_start_ids:
        limit_card_ids = [
            connection["start_card_id"]
            for connection in incoming_map.get(start_id, [])
            if is_thread_window_limit_task_type(
                cards[connection["start_card_id"]].get("task_type")
            )
        ]
        if len(limit_card_ids) > 1:
            raise ValueError(
                f"线程起点 {start_id} 存在多个窗口限制卡: {limit_card_ids}"
            )
        if not limit_card_ids:
            continue

        limit_card_id = limit_card_ids[0]
        parameters = cards[limit_card_id].get("parameters")
        if not isinstance(parameters, dict):
            raise TypeError(f"线程窗口限制卡参数必须是字典: {limit_card_id}")

        raw_bind_id = parameters.get(THREAD_WINDOW_LIMIT_PARAM)
        if raw_bind_id is None:
            continue
        bind_id = _require_bind_id(raw_bind_id)

        selected_window = None
        for window_info in enabled_windows:
            if window_info["bind_id"] == bind_id:
                selected_window = window_info
                break
        if selected_window is None:
            raise ValueError("指定窗口不存在或未启用")

        resolved[start_id] = {
            "bind_id": bind_id,
            "target_hwnd": selected_window["hwnd"],
            "target_window_title": selected_window.get("title", "").strip(),
            "source_card_id": limit_card_id,
        }

    return resolved
