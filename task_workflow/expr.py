# -*- coding: utf-8 -*-
"""简易路径、插值与比较表达式。"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from task_workflow.runtime_store import RuntimeStore

_INTERPOLATION = re.compile(r"\{\{\s*(.*?)\s*\}\}")
SKIP_INTERPOLATE_KEYS = frozenset(
    {
        "script_source",
        "recorded_actions",
        "input_map",
        "output_map",
    }
)


class ExprError(ValueError):
    """表达式或插值无法解析。"""


def split_path(text: str) -> List[str]:
    raw = str(text or "").strip()
    if not raw:
        raise ExprError("路径为空")
    if "__" in raw:
        raise ExprError("路径不能包含双下划线")
    parts: List[str] = []
    token = []
    index = 0
    while index < len(raw):
        char = raw[index]
        if char == ".":
            if not token:
                raise ExprError(f"路径无效: {raw}")
            parts.append("".join(token))
            token = []
            index += 1
            continue
        if char == "[":
            if token:
                parts.append("".join(token))
                token = []
            end = raw.find("]", index)
            if end < 0:
                raise ExprError(f"路径缺少右括号: {raw}")
            inner = raw[index + 1 : end].strip().strip("'\"")
            if not inner:
                raise ExprError(f"路径下标为空: {raw}")
            parts.append(inner)
            index = end + 1
            continue
        if char.isalnum() or char == "_":
            token.append(char)
            index += 1
            continue
        raise ExprError(f"路径含非法字符: {raw}")
    if token:
        parts.append("".join(token))
    if not parts:
        raise ExprError(f"路径无效: {raw}")
    return parts


def apply_filters(value: Any, filters: Sequence[str]) -> Any:
    current = value
    for raw_filter in filters:
        name, _, arg = raw_filter.partition(":")
        name = name.strip()
        arg = arg.strip()
        if name == "int":
            if current is None or current == "":
                raise ExprError("无法将空值转为整数")
            current = int(float(current))
        elif name == "float":
            if current is None or current == "":
                raise ExprError("无法将空值转为数字")
            current = float(current)
        elif name == "default":
            if current is None or current == "":
                current = _literal(arg) if arg else ""
        else:
            raise ExprError(f"未知过滤器: {name}")
    return current


def resolve_path(store: RuntimeStore, path_text: str) -> Any:
    body, filters = _split_filters(path_text)
    value = store.resolve_path(split_path(body))
    return apply_filters(value, filters)


def interpolate(text: Any, store: RuntimeStore) -> Any:
    if not isinstance(text, str) or "{{" not in text:
        return text
    matches = list(_INTERPOLATION.finditer(text))
    if not matches:
        return text
    if len(matches) == 1 and matches[0].span() == (0, len(text)):
        return resolve_path(store, matches[0].group(1))
    pieces: List[str] = []
    cursor = 0
    for match in matches:
        pieces.append(text[cursor : match.start()])
        value = resolve_path(store, match.group(1))
        pieces.append("" if value is None else str(value))
        cursor = match.end()
    pieces.append(text[cursor:])
    return "".join(pieces)


def resolve_params(params: Any, store: RuntimeStore, *, skip_keys: Optional[Sequence[str]] = None) -> Any:
    blocked = set(SKIP_INTERPOLATE_KEYS)
    if skip_keys:
        blocked.update(str(key) for key in skip_keys)
    return _resolve_value(params, store, blocked, parent_key="")


def _resolve_value(value: Any, store: RuntimeStore, blocked: set[str], parent_key: str) -> Any:
    if isinstance(value, dict):
        resolved = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text in blocked:
                resolved[key] = item
            else:
                resolved[key] = _resolve_value(item, store, blocked, key_text)
        return resolved
    if isinstance(value, list):
        return [_resolve_value(item, store, blocked, parent_key) for item in value]
    if isinstance(value, str):
        try:
            return interpolate(value, store)
        except (ExprError, KeyError, ValueError, TypeError) as exc:
            raise ExprError(f"参数 {parent_key or '未知'} 无法解析: {exc}") from exc
    return value


def evaluate_expression(text: Any, store: RuntimeStore) -> bool:
    source = str(text or "").strip()
    if not source:
        raise ExprError("表达式为空")
    tokens = _tokenize(source)
    value, index = _parse_or(tokens, 0, store)
    if index != len(tokens):
        raise ExprError(f"表达式多余内容: {source}")
    return bool(value)


def evaluate_comparison(
    store: RuntimeStore,
    left: Any,
    operator: str,
    right: Any = None,
) -> bool:
    left_value = _coerce_side(left, store)
    op = str(operator or "").strip()
    if op == "empty":
        return _is_empty(left_value)
    right_value = _coerce_side(right, store)
    if op == "contains":
        if left_value is None or right_value is None:
            return False
        return str(right_value) in str(left_value)
    if op in {"==", "!="}:
        equal = _values_equal(left_value, right_value)
        return equal if op == "==" else not equal
    left_number, right_number = _as_compare_numbers(left_value, right_value)
    if op == ">":
        return left_number > right_number
    if op == ">=":
        return left_number >= right_number
    if op == "<":
        return left_number < right_number
    if op == "<=":
        return left_number <= right_number
    raise ExprError(f"不支持的比较符: {op}")


def _split_filters(text: str) -> Tuple[str, List[str]]:
    raw = str(text or "").strip()
    if not raw:
        raise ExprError("路径为空")
    pieces = [piece.strip() for piece in raw.split("|")]
    path = pieces[0]
    filters = [piece for piece in pieces[1:] if piece]
    return path, filters


def _coerce_side(value: Any, store: RuntimeStore) -> Any:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ""
        if _looks_like_path(text):
            try:
                return resolve_path(store, text)
            except (ExprError, KeyError):
                return interpolate(text, store) if "{{" in text else _literal(text)
        if "{{" in text:
            return interpolate(text, store)
        return _literal(text)
    return value


def _looks_like_path(text: str) -> bool:
    root = text.split(".", 1)[0].split("|", 1)[0].split("[", 1)[0].strip()
    return root in {"vars", "last", "ocr", "image", "yolo", "click", "card", "count"}


def _literal(text: str) -> Any:
    raw = str(text).strip()
    if raw.lower() in {"true", "yes", "是"}:
        return True
    if raw.lower() in {"false", "no", "否"}:
        return False
    if raw.lower() in {"null", "none", "空"}:
        return None
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {"'", '"'}:
        return raw[1:-1]
    try:
        if "." in raw or "e" in raw.lower():
            return float(raw)
        return int(raw)
    except ValueError:
        return raw


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (str, list, dict, tuple)):
        return len(value) == 0
    return False


def _values_equal(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left is None and right is None
    try:
        return float(left) == float(right)
    except (TypeError, ValueError):
        return str(left) == str(right)


def _as_compare_numbers(left: Any, right: Any) -> Tuple[float, float]:
    try:
        return float(left), float(right)
    except (TypeError, ValueError) as exc:
        raise ExprError("该比较需要数字") from exc


_TOKEN = re.compile(
    r"""
    \s*(
        and|or|not|empty|contains|
        ==|!=|>=|<=|>|<|
        \(|\)|
        "(?:\\.|[^"\\])*"|
        '(?:\\.|[^'\\])*'|
        [A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+|\[\d+\])*
        (?:\|[A-Za-z_]+(?::[^\s|()]+)?)*|
        -?\d+(?:\.\d+)?
    )
    """,
    re.VERBOSE,
)


def _tokenize(source: str) -> List[str]:
    tokens: List[str] = []
    cursor = 0
    length = len(source)
    while cursor < length:
        match = _TOKEN.match(source, cursor)
        if not match:
            raise ExprError(f"表达式无法解析: {source[cursor:]}")
        tokens.append(match.group(1))
        cursor = match.end()
    return tokens


def _parse_or(tokens: List[str], index: int, store: RuntimeStore) -> Tuple[bool, int]:
    value, index = _parse_and(tokens, index, store)
    while index < len(tokens) and tokens[index] == "or":
        right, index = _parse_and(tokens, index + 1, store)
        value = bool(value) or bool(right)
    return value, index


def _parse_and(tokens: List[str], index: int, store: RuntimeStore) -> Tuple[bool, int]:
    value, index = _parse_not(tokens, index, store)
    while index < len(tokens) and tokens[index] == "and":
        right, index = _parse_not(tokens, index + 1, store)
        value = bool(value) and bool(right)
    return value, index


def _parse_not(tokens: List[str], index: int, store: RuntimeStore) -> Tuple[bool, int]:
    if index < len(tokens) and tokens[index] == "not":
        value, index = _parse_not(tokens, index + 1, store)
        return (not value), index
    return _parse_compare(tokens, index, store)


def _parse_compare(tokens: List[str], index: int, store: RuntimeStore) -> Tuple[bool, int]:
    left, index = _parse_term(tokens, index, store)
    if index >= len(tokens):
        return bool(left), index
    operator = tokens[index]
    if operator == "empty":
        return _is_empty(left), index + 1
    if operator in {"==", "!=", ">=", "<=", ">", "<", "contains"}:
        right, index = _parse_term(tokens, index + 1, store)
        return evaluate_comparison(store, left, operator, right), index
    return bool(left), index


def _parse_term(tokens: List[str], index: int, store: RuntimeStore) -> Tuple[Any, int]:
    if index >= len(tokens):
        raise ExprError("表达式不完整")
    token = tokens[index]
    if token == "(":
        value, index = _parse_or(tokens, index + 1, store)
        if index >= len(tokens) or tokens[index] != ")":
            raise ExprError("括号未闭合")
        return value, index + 1
    if _looks_like_path(token):
        return resolve_path(store, token), index + 1
    return _literal(token), index + 1
