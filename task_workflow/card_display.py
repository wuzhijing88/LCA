from typing import Any, Optional, Tuple


def _card_id_candidates(card_id: Any) -> Tuple[Any, ...]:
    candidates = []
    for candidate in (card_id, str(card_id).strip() if card_id is not None else None):
        if candidate is None or candidate in candidates:
            continue
        candidates.append(candidate)
        try:
            numeric_candidate = int(candidate)
        except (TypeError, ValueError):
            continue
        if numeric_candidate not in candidates:
            candidates.append(numeric_candidate)
        numeric_text = str(numeric_candidate)
        if numeric_text not in candidates:
            candidates.append(numeric_text)
    return tuple(candidates)


def find_card_by_id(cards_data: Any, card_id: Any) -> Any:
    if not isinstance(cards_data, dict):
        return None

    for candidate in _card_id_candidates(card_id):
        if candidate in cards_data:
            return cards_data[candidate]
    return None


def _read_card_value(card: Any, attr_name: str, key_name: Optional[str] = None) -> Any:
    if card is None:
        return None

    if hasattr(card, attr_name):
        try:
            return getattr(card, attr_name)
        except Exception:
            return None

    if isinstance(card, dict):
        return card.get(key_name or attr_name)

    return None


def _normalize_card_id_text(card_id: Any) -> str:
    if card_id is None:
        return ""

    try:
        return str(int(card_id))
    except (TypeError, ValueError):
        return str(card_id).strip()


def normalize_card_display_meta(
    card: Any = None,
    card_id: Any = None,
    task_type: Any = None,
    custom_name: Any = None,
) -> Tuple[str, str, str]:
    raw_card_id = card_id if card_id is not None else _read_card_value(card, "card_id", "id")
    raw_task_type = task_type if str(task_type or "").strip() else _read_card_value(card, "task_type")
    raw_custom_name = custom_name if str(custom_name or "").strip() else _read_card_value(card, "custom_name")

    normalized_card_id = _normalize_card_id_text(raw_card_id)
    normalized_task_type = str(raw_task_type or "").strip() or "未知任务"
    normalized_custom_name = str(raw_custom_name or "").strip()
    return normalized_card_id, normalized_task_type, normalized_custom_name


def format_card_identity(
    card: Any = None,
    card_id: Any = None,
    task_type: Any = None,
    custom_name: Any = None,
) -> str:
    normalized_card_id, normalized_task_type, normalized_custom_name = normalize_card_display_meta(
        card=card,
        card_id=card_id,
        task_type=task_type,
        custom_name=custom_name,
    )

    if normalized_custom_name:
        if normalized_card_id:
            return f"{normalized_custom_name} [{normalized_task_type}] (ID: {normalized_card_id})"
        return f"{normalized_custom_name} [{normalized_task_type}]"

    if normalized_card_id:
        return f"{normalized_task_type} (ID: {normalized_card_id})"
    return normalized_task_type


def format_step_detail(
    prefix: str,
    card: Any = None,
    card_id: Any = None,
    task_type: Any = None,
    custom_name: Any = None,
) -> str:
    normalized_prefix = str(prefix or "").strip()
    identity_text = format_card_identity(
        card=card,
        card_id=card_id,
        task_type=task_type,
        custom_name=custom_name,
    )
    if normalized_prefix and identity_text:
        return f"{normalized_prefix}: {identity_text}"
    return identity_text or normalized_prefix
