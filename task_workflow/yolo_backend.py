from __future__ import annotations

from typing import Any, Iterable, List, Mapping

YOLO_TASK_TYPE = "YOLO目标检测"
YOLO_BACKEND_NATIVE = "原生"


def normalize_yolo_backend(value: Any) -> str:
    return YOLO_BACKEND_NATIVE


def _iter_cards(cards: Any) -> Iterable[Any]:
    if isinstance(cards, Mapping):
        return cards.values()
    if isinstance(cards, (list, tuple)):
        return cards
    return ()


def _card_task_type(card: Any) -> str:
    if card is None:
        return ""
    if hasattr(card, "task_type"):
        return str(getattr(card, "task_type", "") or "").strip()
    if isinstance(card, Mapping):
        return str(card.get("task_type") or "").strip()
    return ""


def _card_parameters(card: Any) -> Mapping[str, Any]:
    if card is None:
        return {}
    if hasattr(card, "parameters"):
        params = getattr(card, "parameters", None)
    elif isinstance(card, Mapping):
        params = card.get("parameters")
    else:
        params = None
    return params if isinstance(params, Mapping) else {}


def first_yolo_card_parameters(cards: Any) -> dict:
    for card in _iter_cards(cards):
        if _card_task_type(card) == YOLO_TASK_TYPE:
            return dict(_card_parameters(card))
    return {}


def collect_yolo_backends(cards: Any) -> List[str]:
    backends: List[str] = []
    for card in _iter_cards(cards):
        if _card_task_type(card) != YOLO_TASK_TYPE:
            continue
        backends.append(normalize_yolo_backend(_card_parameters(card).get("yolo_backend")))
    return backends


def resolve_workflow_yolo_backend(cards: Any) -> str:
    backends = collect_yolo_backends(cards)
    if not backends:
        raise ValueError("检测要先放一张 YOLO目标检测 卡")
    return YOLO_BACKEND_NATIVE
