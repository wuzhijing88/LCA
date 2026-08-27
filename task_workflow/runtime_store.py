# -*- coding: utf-8 -*-
"""工作流运行时命名空间：用户变量、最近一次感知结果。"""

from __future__ import annotations

import threading
from typing import Any, Dict, Iterable, Optional

PERCEPTION_FIELDS = (
    "ok",
    "kind",
    "text",
    "x",
    "y",
    "x1",
    "y1",
    "x2",
    "y2",
    "width",
    "height",
    "score",
    "threshold",
    "class_name",
    "path",
    "items",
)

KIND_ALIASES = {
    "ocr": "ocr",
    "image": "image",
    "yolo": "yolo",
    "click": "click",
}

MAX_VAR_NAME_LEN = 64
MAX_VAR_TEXT_LEN = 4096
MAX_ITEMS = 50


def empty_perception(kind: Optional[str] = None) -> Dict[str, Any]:
    payload = {field: None for field in PERCEPTION_FIELDS}
    payload["ok"] = False
    payload["kind"] = kind
    payload["items"] = []
    return payload


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) > MAX_VAR_TEXT_LEN:
            return value[:MAX_VAR_TEXT_LEN]
        return value
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in list(value)[:MAX_ITEMS]]
    if isinstance(value, dict):
        trimmed = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= MAX_ITEMS:
                break
            trimmed[str(key)] = _json_safe(item)
        return trimmed
    return str(value)


def normalize_perception(**fields: Any) -> Dict[str, Any]:
    payload = empty_perception(fields.get("kind"))
    for key, value in fields.items():
        if key not in payload:
            continue
        if key == "ok":
            payload["ok"] = bool(value)
        elif key == "items":
            payload["items"] = _json_safe(value) if value else []
        elif key in {"x", "y", "x1", "y1", "x2", "y2", "width", "height", "score", "threshold"}:
            payload[key] = _as_number(value)
        else:
            payload[key] = _json_safe(value)
    _fill_perception_box(payload)
    return payload


def _fill_perception_box(payload: Dict[str, Any]) -> None:
    x1, y1, x2, y2 = payload.get("x1"), payload.get("y1"), payload.get("x2"), payload.get("y2")
    if None not in (x1, y1, x2, y2):
        if payload.get("x") is None:
            payload["x"] = (int(x1) + int(x2)) // 2
        if payload.get("y") is None:
            payload["y"] = (int(y1) + int(y2)) // 2
        if payload.get("width") is None:
            payload["width"] = int(x2) - int(x1)
        if payload.get("height") is None:
            payload["height"] = int(y2) - int(y1)
        return
    x, y = payload.get("x"), payload.get("y")
    width, height = payload.get("width"), payload.get("height")
    if None in (x, y, width, height):
        return
    if payload.get("x1") is None:
        payload["x1"] = int(x) - int(width) // 2
        payload["y1"] = int(y) - int(height) // 2
        payload["x2"] = payload["x1"] + int(width)
        payload["y2"] = payload["y1"] + int(height)


def _as_number(value: Any) -> Any:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number.is_integer():
        return int(number)
    return number


def normalize_var_name(name: Any) -> str:
    text = str(name or "").strip()
    if not text or len(text) > MAX_VAR_NAME_LEN:
        raise ValueError("变量名无效")
    if text.startswith("__"):
        raise ValueError("变量名不能以双下划线开头")
    first = text[0]
    if not (first.isalpha() or first == "_"):
        raise ValueError("变量名必须以字母或下划线开头")
    for char in text[1:]:
        if not (char.isalnum() or char == "_"):
            raise ValueError("变量名只能包含字母、数字和下划线")
    return text


class RuntimeStore:
    """vars 工作流共享；last 按线程隔离。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._vars: Dict[str, Any] = {}
        self._last_by_thread: Dict[int, Dict[str, Any]] = {}
        self._last_by_kind: Dict[int, Dict[str, Dict[str, Any]]] = {}
        self._card_results: Dict[int, Dict[str, Any]] = {}
        self._counters: Dict[str, int] = {}
        self._current_card_id: Optional[int] = None

    def reset(self) -> None:
        with self._lock:
            self._vars.clear()
            self._last_by_thread.clear()
            self._last_by_kind.clear()
            self._card_results.clear()
            self._current_card_id = None

    def bind_counters(self, counters: Optional[Dict[str, int]]) -> None:
        self._counters = counters if isinstance(counters, dict) else {}

    def set_current_card_id(self, card_id: Any) -> None:
        try:
            self._current_card_id = int(card_id)
        except (TypeError, ValueError):
            self._current_card_id = None

    def get_var(self, name: Any, default: Any = None) -> Any:
        try:
            key = normalize_var_name(name)
        except ValueError:
            return default
        with self._lock:
            return self._vars.get(key, default)

    def set_var(self, name: Any, value: Any) -> Any:
        key = normalize_var_name(name)
        stored = _json_safe(value)
        with self._lock:
            self._vars[key] = stored
        return stored

    def inc_var(self, name: Any, step: Any = 1) -> Any:
        key = normalize_var_name(name)
        try:
            delta = float(step)
        except (TypeError, ValueError):
            delta = 1.0
        with self._lock:
            current = self._vars.get(key, 0)
            try:
                next_value = float(current) + delta
            except (TypeError, ValueError):
                next_value = delta
            if float(next_value).is_integer():
                next_value = int(next_value)
            self._vars[key] = next_value
            return next_value

    def snapshot_vars(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._vars)

    def publish(self, card_id: Any, perception: Optional[Dict[str, Any]] = None, **fields: Any) -> Dict[str, Any]:
        merged = dict(perception or {})
        merged.update(fields)
        payload = normalize_perception(**merged)
        thread_id = threading.get_ident()
        with self._lock:
            self._last_by_thread[thread_id] = payload
            kind = str(payload.get("kind") or "").strip()
            if kind in KIND_ALIASES:
                self._last_by_kind.setdefault(thread_id, {})[kind] = payload
            try:
                numeric_card_id = int(card_id)
            except (TypeError, ValueError):
                numeric_card_id = None
            if numeric_card_id is not None:
                self._card_results[numeric_card_id] = payload
        return payload

    def last(self, kind: Optional[str] = None) -> Dict[str, Any]:
        thread_id = threading.get_ident()
        with self._lock:
            if kind:
                alias = KIND_ALIASES.get(str(kind).strip())
                if alias:
                    payload = self._last_by_kind.get(thread_id, {}).get(alias)
                    if payload is not None:
                        return dict(payload)
            payload = self._last_by_thread.get(thread_id)
            if payload is not None:
                return dict(payload)
        return empty_perception(kind)

    def card_result(self, card_id: Any) -> Dict[str, Any]:
        try:
            numeric_card_id = int(card_id)
        except (TypeError, ValueError):
            return empty_perception()
        with self._lock:
            payload = self._card_results.get(numeric_card_id)
            if payload is not None:
                return dict(payload)
        return empty_perception()

    def current_count(self) -> int:
        card_id = self._current_card_id
        if card_id is None:
            return 0
        return int(self._counters.get(f"__card_exec_count_{card_id}", 0) or 0)

    def resolve_path(self, parts: Iterable[Any]) -> Any:
        tokens = [str(part).strip() for part in parts if str(part).strip() != ""]
        if not tokens:
            raise KeyError("空路径")
        root = tokens[0]
        rest = tokens[1:]

        if root == "vars":
            if not rest:
                return self.snapshot_vars()
            return self.get_var(rest[0])

        if root == "count":
            if rest:
                raise KeyError("count 没有子字段")
            return self.current_count()

        if root == "card":
            if not rest:
                raise KeyError("card 需要卡片 ID")
            payload = self.card_result(rest[0])
            return _read_perception(payload, rest[1:])

        if root in {"last", "ocr", "image", "yolo", "click"}:
            kind = None if root == "last" else root
            if rest and rest[0] in KIND_ALIASES and root == "last":
                kind = rest[0]
                rest = rest[1:]
            payload = self.last(kind)
            return _read_perception(payload, rest)

        raise KeyError(f"未知路径: {root}")


def _read_perception(payload: Dict[str, Any], parts: list[str]) -> Any:
    if not parts:
        return dict(payload)
    current: Any = payload
    for part in parts:
        if isinstance(current, dict):
            if part in current:
                current = current[part]
                continue
            if part.isdigit():
                current = current.get(part) if part in current else None
                continue
            raise KeyError(part)
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except (TypeError, ValueError, IndexError) as exc:
                raise KeyError(part) from exc
            continue
        raise KeyError(part)
    return current


def get_store_from_context(context: Any) -> Optional[RuntimeStore]:
    if context is None:
        return None
    store = getattr(context, "runtime_store", None)
    if isinstance(store, RuntimeStore):
        return store
    getter = getattr(context, "get_runtime_store", None)
    if callable(getter):
        candidate = getter()
        if isinstance(candidate, RuntimeStore):
            return candidate
    return None


def perception_from_ocr_results(results: Any, *, ok: Optional[bool] = None) -> Dict[str, Any]:
    items = []
    if isinstance(results, list):
        for item in results:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if text is None:
                text = item.get("文字")
            score = item.get("confidence")
            if score is None:
                score = item.get("score")
            box = item.get("bbox") or item.get("box")
            x = item.get("x")
            y = item.get("y")
            x1 = y1 = x2 = y2 = None
            if isinstance(box, (list, tuple)) and box:
                try:
                    first = box[0]
                    if isinstance(first, (list, tuple)):
                        xs = [float(point[0]) for point in box]
                        ys = [float(point[1]) for point in box]
                        x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)
                    elif len(box) >= 4:
                        x1, y1, x2, y2 = box[0], box[1], box[2], box[3]
                except (TypeError, ValueError, IndexError):
                    x1 = y1 = x2 = y2 = None
            if x is None and x1 is not None and x2 is not None:
                x = (float(x1) + float(x2)) / 2
            if y is None and y1 is not None and y2 is not None:
                y = (float(y1) + float(y2)) / 2
            items.append(
                {
                    "text": text,
                    "score": score,
                    "x": x,
                    "y": y,
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2,
                }
            )
    first = items[0] if items else {}
    matched = bool(items) if ok is None else bool(ok)
    return normalize_perception(
        ok=matched,
        kind="ocr",
        text=first.get("text"),
        x=first.get("x"),
        y=first.get("y"),
        x1=first.get("x1"),
        y1=first.get("y1"),
        x2=first.get("x2"),
        y2=first.get("y2"),
        score=first.get("score"),
        items=items,
    )


def perception_from_yolo_result(result: Any, *, ok: Optional[bool] = None) -> Dict[str, Any]:
    payload = result if isinstance(result, dict) else {}
    matched = bool(payload) if ok is None else bool(ok)
    return normalize_perception(
        ok=matched,
        kind="yolo",
        text=payload.get("class_name"),
        class_name=payload.get("class_name"),
        x=payload.get("target_x", payload.get("x")),
        y=payload.get("target_y", payload.get("y")),
        x1=payload.get("x1"),
        y1=payload.get("y1"),
        x2=payload.get("x2"),
        y2=payload.get("y2"),
        score=payload.get("confidence"),
        items=payload.get("all_detections") or [],
    )


def publish_perception(card_id: Any, **fields: Any) -> Optional[Dict[str, Any]]:
    try:
        from task_workflow.workflow_context import get_current_workflow_context

        context = get_current_workflow_context()
    except Exception:
        return None
    store = get_store_from_context(context)
    if store is None:
        return None
    return store.publish(card_id, fields)
