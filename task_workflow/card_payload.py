# -*- coding: utf-8 -*-
"""卡片执行态写入与数值字面量转换。"""

from __future__ import annotations

from typing import Any, Optional, Tuple


def coerce_number(value: Any, default: Any = 0, *, as_float: bool = True) -> Any:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value) if as_float else int(value)
    text = str(value or "").strip()
    if not text:
        return default
    try:
        number = float(text)
        return number if as_float else int(number)
    except (TypeError, ValueError):
        return default


def publish_card_payload(context: Any, card_id: Any, **fields: Any) -> None:
    if context is None or card_id is None:
        return
    setter = getattr(context, "set_card_data", None)
    if not callable(setter):
        return
    for key, value in fields.items():
        try:
            setter(card_id, key, value)
        except Exception:
            continue


def bounds_from_bbox(bbox: Any) -> Optional[Tuple[Any, Any, Any, Any]]:
    if not bbox:
        return None
    try:
        first = bbox[0]
        if isinstance(first, (list, tuple)):
            xs = [point[0] for point in bbox]
            ys = [point[1] for point in bbox]
        else:
            xs = list(bbox[0::2])
            ys = list(bbox[1::2])
        if not xs or not ys:
            return None
        return min(xs), min(ys), max(xs), max(ys)
    except (TypeError, IndexError, ValueError):
        return None


def publish_perception(card_id: Any, **fields: Any) -> None:
    try:
        from task_workflow.runtime_store import publish_perception as publish_runtime_perception

        publish_runtime_perception(card_id, **fields)
    except Exception:
        return


def publish_click_target(
    context: Any,
    card_id: Any,
    x: Any = None,
    y: Any = None,
    x1: Any = None,
    y1: Any = None,
    x2: Any = None,
    y2: Any = None,
    text: Any = None,
) -> None:
    fields = {
        "click_target_x": x,
        "click_target_y": y,
        "click_target_x1": x1,
        "click_target_y1": y1,
        "click_target_x2": x2,
        "click_target_y2": y2,
        "click_target_text": text,
    }
    publish_card_payload(context, card_id, **{key: value for key, value in fields.items() if value is not None})
    publish_perception(
        card_id,
        kind="click",
        ok=x is not None and y is not None,
        x=x,
        y=y,
        x1=x1,
        y1=y1,
        x2=x2,
        y2=y2,
        text=text,
    )
