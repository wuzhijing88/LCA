# -*- coding: utf-8 -*-
"""多图识别记忆：只在同一轮「继续执行本步骤」里排除已处理图片。"""

from typing import Any, Dict, Iterable, List, Optional, Set

from tasks.task_utils import coerce_bool

CLICKED_IMAGES_KEY = "clicked_images"
SUCCESS_IMAGES_KEY = "success_images"
ROUND_ACTIVE_KEY = "multi_image_round_active"


def resolve_multi_image_flag(params: Optional[Dict[str, Any]], key: str, default: bool = False) -> bool:
    payload = params or {}
    if key not in payload:
        return bool(default)
    return coerce_bool(payload.get(key, default))


def as_path_set(value: Any) -> Set[str]:
    if isinstance(value, set):
        return {str(item) for item in value if str(item)}
    if isinstance(value, (list, tuple)):
        return {str(item) for item in value if str(item)}
    if isinstance(value, dict):
        if value.get("__trimmed__"):
            return set()
        return {str(key) for key in value if str(key) and not str(key).startswith("_")}
    if isinstance(value, str) and value:
        return {value}
    return set()


def finish_multi_image_round(context: Any, card_id: Optional[int]) -> None:
    if context is None or card_id is None:
        return
    context.set_card_data(card_id, CLICKED_IMAGES_KEY, set())
    context.set_card_data(card_id, SUCCESS_IMAGES_KEY, set())
    context.set_card_data(card_id, ROUND_ACTIVE_KEY, False)


def mark_multi_image_round_active(context: Any, card_id: Optional[int]) -> None:
    if context is None or card_id is None:
        return
    context.set_card_data(card_id, ROUND_ACTIVE_KEY, True)


def resolve_multi_image_remaining(
    image_paths: Iterable[str],
    card_id: Optional[int],
    click_all_found: bool,
    context: Any,
    clear_clicked_on_next_run: bool = False,
) -> List[str]:
    paths = [str(path) for path in image_paths if str(path)]
    if not paths:
        return []
    if context is None or card_id is None:
        return list(paths)

    if clear_clicked_on_next_run:
        finish_multi_image_round(context, card_id)

    round_active = coerce_bool(context.get_card_data(card_id, ROUND_ACTIVE_KEY, False))
    if not round_active:
        finish_multi_image_round(context, card_id)
        if click_all_found:
            mark_multi_image_round_active(context, card_id)
        return list(paths)

    if click_all_found:
        success_images = as_path_set(context.get_card_data(card_id, SUCCESS_IMAGES_KEY, set()))
        remaining = [path for path in paths if path not in success_images]
    else:
        clicked_images = as_path_set(context.get_card_data(card_id, CLICKED_IMAGES_KEY, set()))
        remaining = [path for path in paths if path not in clicked_images]

    if remaining:
        return remaining

    finish_multi_image_round(context, card_id)
    if click_all_found:
        mark_multi_image_round_active(context, card_id)
    return list(paths)
