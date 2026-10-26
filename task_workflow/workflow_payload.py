from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from app_core.lca_format.project_io import (
    is_lca_path,
    load_lca_project,
    save_lca_project,
    workflow_from_session,
)
from task_workflow.thread_start import THREAD_START_TASK_TYPE, is_thread_start_task_type
from app_core.lca_format.session import LcaPackageSession
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


def _memory_workflow_bytes(
    path_text: str,
    parent_workflow_file: str | Path | None = None,
) -> bytes:
    from app_core.lca_format.project_io import ensure_registered_lca_session, is_lca_path
    from app_core.lca_format.session import get_active, get_for_path

    parent_text = str(parent_workflow_file or "").strip()
    session = None
    if parent_text and not parent_text.startswith("memory://"):
        session = get_for_path(parent_text)
        if session is None and is_lca_path(parent_text):
            session = ensure_registered_lca_session(parent_text)
        if session is None and is_lca_path(parent_text):
            raise FileNotFoundError(f"父工程不存在: {parent_text}")
    if session is None:
        session = get_active()
    if session is not None:
        payload_bytes = session.get_bytes(path_text)
        if payload_bytes is not None:
            return payload_bytes
        raise FileNotFoundError(f"包内工作流文件不存在: {path_text}")
    from app_core.player.memory_store import get_player_memory_file

    player_bytes = get_player_memory_file(path_text)
    if player_bytes is None:
        raise FileNotFoundError(f"包内工作流文件不存在: {path_text}")
    return player_bytes


def load_workflow_package(
    path: str | Path,
    *,
    parent_workflow_file: str | Path | None = None,
):
    from app_core.lca_format.project_io import load_lca_from_bytes

    path_text = str(path)
    if path_text.startswith("memory://"):
        return load_lca_from_bytes(_memory_workflow_bytes(path_text, parent_workflow_file))
    return load_lca_project(path_text)


def load_workflow_file(
    path: str | Path,
    *,
    parent_workflow_file: str | Path | None = None,
) -> Dict[str, Any]:
    path_text = str(path)
    registered = None
    if not path_text.startswith("memory://"):
        from app_core.lca_format.session import clear_path, get_for_path

        registered = get_for_path(path_text)
        if registered is not None:
            if registered.matches_source(path_text):
                from app_core.lca_format.session import activate

                activate(path_text)
                return workflow_from_session(registered)
            clear_path(path_text)
    payload, session = load_workflow_package(
        path_text,
        parent_workflow_file=parent_workflow_file,
    )
    if not path_text.startswith("memory://"):
        from app_core.lca_format.session import activate, register

        register_path = session.source_path
        if register_path is None:
            session.close()
            raise ValueError("磁盘工程未提供现行文件路径")
        register(register_path, session)
        activate(register_path)
    return payload


def save_workflow_file(
    path: str | Path, data: dict, *, source_session: Optional[LcaPackageSession] = None,
) -> Path:
    source = Path(path)
    if not is_lca_path(source):
        raise ValueError("只能保存现行 .lca 工程，旧格式须先经工程转换")
    return save_lca_project(source, data, display_name=source.stem, source_session=source_session)
