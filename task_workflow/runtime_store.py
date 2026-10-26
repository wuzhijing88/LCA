# -*- coding: utf-8 -*-
"""工作流运行时命名空间：用户变量、最近一次感知结果。"""

from __future__ import annotations

import threading
import copy
from typing import Any, Dict, Iterable, Optional

from task_workflow.script_parameters import add_numeric_values

PERCEPTION_FIELDS = (
    "ok",
    "query_ok",
    "error",
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


def normalize_var_value(value: Any) -> Any:
    """复制并校验用户变量；容量错误不能改写或截短原数据。"""
    active = set()
    nodes = 0

    def visit(item, depth):
        nonlocal nodes
        nodes += 1
        if depth > 32 or nodes > 10000:
            raise ValueError("变量嵌套不能超过32层，总元素不能超过10000项")
        if item is None or isinstance(item, (bool, int)):
            return item
        if isinstance(item, float):
            import math

            if not math.isfinite(item):
                raise ValueError("变量数值必须是有限数字")
            return item
        if isinstance(item, str):
            if len(item) > MAX_VAR_TEXT_LEN:
                raise ValueError(f"变量文本不能超过{MAX_VAR_TEXT_LEN}个字符")
            return item
        if not isinstance(item, (list, tuple, dict)):
            raise TypeError("变量值只支持无、真假、数字、文本、列表和字典")
        if len(item) > MAX_ITEMS:
            raise ValueError(f"变量列表或字典不能超过{MAX_ITEMS}项")
        identity = id(item)
        if identity in active:
            raise ValueError("变量不能包含循环引用")
        active.add(identity)
        try:
            if isinstance(item, dict):
                result = {}
                for key, child in item.items():
                    if not isinstance(key, str):
                        raise TypeError("变量字典的键必须是文本")
                    visit(key, depth + 1)
                    result[key] = visit(child, depth + 1)
                return result
            return [visit(child, depth + 1) for child in item]
        finally:
            active.remove(identity)

    return visit(value, 0)


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
        # 跨线程记录“最近一次发布”的整体快照与各 kind 快照，供 copy_for_debug
        # 把它们播种到调试线程名下：单调递增的发布序号用来判定谁最新。
        self._publish_seq: int = 0
        self._recent_payload: Optional[Dict[str, Any]] = None
        self._recent_by_kind: Dict[str, Dict[str, Any]] = {}

    def reset(self) -> None:
        with self._lock:
            self._vars.clear()
            self._last_by_thread.clear()
            self._last_by_kind.clear()
            self._card_results.clear()
            self._current_card_id = None
            self._publish_seq = 0
            self._recent_payload = None
            self._recent_by_kind.clear()

    def bind_counters(self, counters: Optional[Dict[str, int]]) -> None:
        self._counters = counters if isinstance(counters, dict) else {}

    def set_current_card_id(self, card_id: Any) -> None:
        try:
            self._current_card_id = int(card_id)
        except (TypeError, ValueError):
            self._current_card_id = None

    def get_var(self, name: Any, default: Any = None) -> Any:
        key = normalize_var_name(name)
        with self._lock:
            return self._vars.get(key, default)

    def set_var(self, name: Any, value: Any) -> Any:
        key = normalize_var_name(name)
        stored = normalize_var_value(value)
        with self._lock:
            self._vars[key] = stored
        return stored

    def has_var(self, name: Any) -> bool:
        key = normalize_var_name(name)
        with self._lock:
            return key in self._vars

    def delete_var(self, name: Any) -> bool:
        key = normalize_var_name(name)
        # Use a sentinel so deleting a variable whose value is actually ``None``
        # still reports success.  ``pop(key, None)`` used to conflate a missing
        # key with an existing key storing None.
        missing = object()
        with self._lock:
            return self._vars.pop(key, missing) is not missing

    def inc_var(self, name: Any, step: Any = 1) -> Any:
        key = normalize_var_name(name)
        with self._lock:
            current = self._vars.get(key, 0)
            next_value = add_numeric_values(current, step)
            self._vars[key] = next_value
            return next_value

    def snapshot_vars(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._vars)

    def copy_for_debug(self) -> "RuntimeStore":
        """返回一个用于编辑器调试运行的存储副本。

        深拷贝卡片结果表、``last`` 感知快照与变量，让调试脚本能读取上次真实
        运行的 ``卡片[...]``、``变量.全局获取`` 等数据；而计数器保持解绑、当前卡片
        置空、所有写入只落在副本里，不会污染正在运行的正式存储。
        """
        import copy as _copy

        clone = RuntimeStore()
        current = threading.get_ident()
        with self._lock:
            clone._vars = _copy.deepcopy(self._vars)
            clone._card_results = _copy.deepcopy(self._card_results)
            clone._last_by_thread = _copy.deepcopy(self._last_by_thread)
            clone._last_by_kind = _copy.deepcopy(self._last_by_kind)
            recent_payload = _copy.deepcopy(self._recent_payload)
            recent_by_kind = _copy.deepcopy(self._recent_by_kind)
            clone._publish_seq = self._publish_seq
            clone._recent_payload = recent_payload
            clone._recent_by_kind = _copy.deepcopy(self._recent_by_kind)
        # 正式运行发布 last 是按发布线程隔离的；调试脚本却在新线程里执行，
        # 若不播种，其 上次/文字（走 last）会读不到最后一次真实运行的结果。
        # 这里把“跨线程最近发布”的整体与各 kind 快照登记到当前（调试）线程名下。
        if recent_payload is not None:
            clone._last_by_thread[current] = recent_payload
        if recent_by_kind:
            clone._last_by_kind[current] = dict(recent_by_kind)
        return clone

    def publish(self, card_id: Any, perception: Optional[Dict[str, Any]] = None, **fields: Any) -> Dict[str, Any]:
        merged = dict(perception or {})
        merged.update(fields)
        payload = normalize_perception(**merged)
        if "outputs" in merged:
            if not isinstance(merged["outputs"], dict):
                raise TypeError("卡片输出必须是字典")
            payload["outputs"] = normalize_var_value(merged["outputs"])
        thread_id = threading.get_ident()
        with self._lock:
            self._last_by_thread[thread_id] = payload
            self._publish_seq += 1
            # 发布在锁内串行，最后一次发布即为全局最近的整体/各 kind 快照。
            self._recent_payload = payload
            kind = str(payload.get("kind") or "").strip()
            if kind in KIND_ALIASES:
                self._last_by_kind.setdefault(thread_id, {})[kind] = payload
                self._recent_by_kind[kind] = payload
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
                        return {**payload, "outputs": copy.deepcopy(payload["outputs"])} if "outputs" in payload else dict(payload)
            payload = self._last_by_thread.get(thread_id)
            if payload is not None:
                return {**payload, "outputs": copy.deepcopy(payload["outputs"])} if "outputs" in payload else dict(payload)
        return empty_perception(kind)

    def card_result(self, card_id: Any) -> Dict[str, Any]:
        try:
            numeric_card_id = int(card_id)
        except (TypeError, ValueError):
            return empty_perception()
        with self._lock:
            payload = self._card_results.get(numeric_card_id)
            if payload is not None:
                return {**payload, "outputs": copy.deepcopy(payload["outputs"])} if "outputs" in payload else dict(payload)
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
        return {**payload, "outputs": copy.deepcopy(payload["outputs"])} if "outputs" in payload else dict(payload)
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
    from task_workflow.card_payload import bounds_from_bbox

    items = []
    if isinstance(results, list):
        for item in results:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            score = item.get("confidence")
            box = item.get("bbox")
            x = item.get("x")
            y = item.get("y")
            x1 = y1 = x2 = y2 = None
            bounds = bounds_from_bbox(box)
            if bounds is not None:
                x1, y1, x2, y2 = bounds
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
        query_ok=True,
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
        query_ok=True,
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
