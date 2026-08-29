from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from app_core.lca_format.project_io import is_lca_path, load_lca_project, save_lca_project
from task_workflow.thread_start import THREAD_START_TASK_TYPE, is_thread_start_task_type
from task_workflow.workflow_sanitize import sanitize_card_parameters


def workflow_body(workflow_data: Mapping[str, Any]) -> Dict[str, Any]:
    if not isinstance(workflow_data, Mapping):
        raise TypeError("工作流数据必须是字典")
    if "workflow" in workflow_data and "cards" not in workflow_data:
        body = workflow_data["workflow"]
        if not isinstance(body, Mapping):
            raise TypeError("工作流主体必须是字典")
        return dict(body)
    return dict(workflow_data)


def cards_dict_from_workflow(workflow_data: Mapping[str, Any]) -> Dict[int, Dict[str, Any]]:
    body = workflow_body(workflow_data)
    cards = body.get("cards")
    if not isinstance(cards, list):
        raise TypeError("工作流 cards 必须是列表")

    cards_dict: Dict[int, Dict[str, Any]] = {}
    for card_data in cards:
        if not isinstance(card_data, Mapping):
            continue
        card_id = card_data.get("id")
        if isinstance(card_id, bool) or not isinstance(card_id, int) or card_id < 0:
            continue
        cards_dict[card_id] = {
            "id": card_id,
            "task_type": str(card_data.get("task_type") or "未知"),
            "parameters": sanitize_card_parameters(
                copy.deepcopy(card_data.get("parameters") or {}),
                card_data.get("task_type"),
            ),
            "custom_name": card_data.get("custom_name"),
            "pos_x": card_data.get("pos_x", 0),
            "pos_y": card_data.get("pos_y", 0),
        }
    return cards_dict


def connections_from_workflow(workflow_data: Mapping[str, Any]) -> List[Dict[str, Any]]:
    body = workflow_body(workflow_data)
    connections = body.get("connections")
    if not isinstance(connections, list):
        raise TypeError("工作流 connections 必须是列表")
    return [dict(item) for item in connections if isinstance(item, Mapping)]


def start_card_ids_from_cards(cards_data: Mapping[Any, Any]) -> List[int]:
    start_ids: List[int] = []
    for card_id, card in cards_data.items():
        task_type = ""
        if isinstance(card, Mapping):
            task_type = str(card.get("task_type") or "")
        else:
            task_type = str(getattr(card, "task_type", "") or "")
        if is_thread_start_task_type(task_type):
            if isinstance(card_id, bool) or not isinstance(card_id, int):
                continue
            start_ids.append(card_id)
    return sorted(set(start_ids))


def thread_labels_from_cards(
    cards_data: Mapping[Any, Any],
    start_card_ids: Iterable[int],
) -> Dict[int, str]:
    labels: Dict[int, str] = {}
    for start_id in start_card_ids:
        card = cards_data.get(start_id)
        label_text = ""
        if isinstance(card, Mapping):
            label_text = str(card.get("custom_name") or "").strip()
        else:
            label_text = str(getattr(card, "custom_name", "") or "").strip()
        if label_text:
            labels[int(start_id)] = label_text
    return labels


def require_start_card_ids(cards_data: Mapping[Any, Any]) -> Tuple[List[int], Dict[int, str]]:
    start_ids = start_card_ids_from_cards(cards_data)
    if not start_ids:
        raise ValueError(f"工作流中必须包含至少一个类型为 '{THREAD_START_TASK_TYPE}' 的卡片")
    return start_ids, thread_labels_from_cards(cards_data, start_ids)


def load_workflow_json(path: str | Path) -> Dict[str, Any]:
    import json
    import os

    if not path or not os.path.isfile(path):
        raise FileNotFoundError(f"工作流文件不存在: {path}")
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise TypeError("工作流文件根节点必须是对象")
    return payload


def load_workflow_file(path: str | Path) -> Dict[str, Any]:
    path_text = str(path)
    if path_text.startswith("memory://"):
        import json

        from app_core.lca_format.session import get_active

        session = get_active()
        payload_bytes = session.get_bytes(path_text) if session is not None else None
        if payload_bytes is None:
            raise FileNotFoundError(f"包内工作流文件不存在: {path_text}")
        payload = json.loads(payload_bytes.decode("utf-8"))
        if not isinstance(payload, dict):
            raise TypeError("工作流文件根节点必须是对象")
        return payload
    if is_lca_path(path):
        from app_core.lca_format.session import activate, register

        payload, session = load_lca_project(path)
        register(path, session)
        activate(path)
        return payload
    from app_core.lca_format.session import deactivate

    deactivate()
    return load_workflow_json(path)


def save_workflow_file(path: str | Path, data: dict) -> Path:
    destination = Path(path)
    if not is_lca_path(destination):
        destination = destination.with_suffix(".lca")
    return save_lca_project(destination, data, display_name=destination.stem)
