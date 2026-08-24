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


def normalize_yolo_item(item: Any) -> dict:
    if not isinstance(item, dict):
        return {}
    payload = dict(item)
    class_name = payload.get("文字")
    if class_name is None:
        class_name = payload.get("class_name")
    x = payload.get("坐标X")
    if x is None:
        x = payload.get("x")
    y = payload.get("坐标Y")
    if y is None:
        y = payload.get("y")
    x1 = payload.get("范围X1")
    if x1 is None:
        x1 = payload.get("x1")
    y1 = payload.get("范围Y1")
    if y1 is None:
        y1 = payload.get("y1")
    x2 = payload.get("范围X2")
    if x2 is None:
        x2 = payload.get("x2")
    y2 = payload.get("范围Y2")
    if y2 is None:
        y2 = payload.get("y2")
    payload["文字"] = class_name
    payload["坐标X"] = x
    payload["坐标Y"] = y
    payload["范围X1"] = x1
    payload["范围Y1"] = y1
    payload["范围X2"] = x2
    payload["范围Y2"] = y2
    if "class_name" not in payload:
        payload["class_name"] = class_name
    if "x" not in payload:
        payload["x"] = x
    if "y" not in payload:
        payload["y"] = y
    return payload


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


def first_card_data(context: Any, card_id: Any, keys: Tuple[str, ...]) -> Optional[Any]:
    getter = getattr(context, "get_card_data", None)
    if not callable(getter):
        return None
    for key in keys:
        value = getter(card_id, key)
        if value is not None:
            return value
    return None
