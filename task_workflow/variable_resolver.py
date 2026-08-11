# -*- coding: utf-8 -*-
"""Workflow variable template resolver."""

from __future__ import annotations

import json
import logging
import re
import time
from contextlib import nullcontext
from datetime import datetime
from typing import Any, Optional, Set, Tuple

from task_workflow.global_var_store import ensure_global_context_loaded
from task_workflow.workflow_context import get_workflow_context
from task_workflow.expression_evaluator import ExpressionError, evaluate_expression

logger = logging.getLogger(__name__)

_VAR_PATTERN = re.compile(r"\$\{([^{}]+)\}|\{\{([^{}]+)\}\}")
_INIT_PATTERN = re.compile(r"(?:(初始化|强制初始化)\.)?(\$\{([^{}]+)\}|\{\{([^{}]+)\}\})")
_INIT_CALL_PATTERN = re.compile(r"(初始化|强制初始化)\s*\(\s*([^()]+?)\s*\)")
_EXPR_VAR_PATTERN = re.compile(r"\$\{([^{}]+)\}|\{\{([^{}]+)\}\}")
_MISSING = object()


def _store_lock(store):
    lock = getattr(store, "_lock", None)
    if lock is None:
        return nullcontext()
    if callable(getattr(lock, "acquire", None)) and callable(getattr(lock, "release", None)):
        return lock
    return nullcontext()


def _get_store_variables(store):
    if not store:
        return None
    with _store_lock(store):
        data = getattr(store, "data", None)
        if not isinstance(data, dict):
            return None
        variables = data.get("variables", {})
        if not isinstance(variables, dict):
            return None
        return variables


def _workflow_is_thread_context(context) -> bool:
    workflow_id = str(getattr(context, "workflow_id", "") or "").strip().lower()
    return "#thread-" in workflow_id


def _expression_uses_self(config: Any) -> bool:
    expr = str((config or {}).get("expr") or "")
    if not expr:
        return False
    return bool(re.search(r"\b(self|this)\b", expr, flags=re.IGNORECASE))


def normalize_variable_name(name: Any) -> Tuple[str, bool]:
    """Normalize variable reference and detect explicit global prefix."""
    raw = str(name or "").strip()
    if not raw:
        return "", False

    lowered = raw.lower()
    for prefix in ("global:", "global."):
        if lowered.startswith(prefix):
            return raw[len(prefix):].strip(), True
    for prefix in ("全局:", "全局."):
        if raw.startswith(prefix):
            return raw[len(prefix):].strip(), True
    return raw, False


def _strip_wrapped_quotes(text: str) -> str:
    raw = str(text or "").strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ("'", '"'):
        return raw[1:-1].strip()
    return raw


def _normalize_variable_target(name: Any) -> str:
    raw = str(name or "").strip()
    if not raw:
        return ""
    full = _VAR_PATTERN.fullmatch(raw)
    if full:
        raw = (full.group(1) or full.group(2) or "").strip()
    raw = _strip_wrapped_quotes(raw)
    normalized, _ = normalize_variable_name(raw)
    return normalized


def _stringify_value(value: Any) -> str:
    if isinstance(value, (dict, list, tuple)):
        try:
            return json.dumps(value, ensure_ascii=False)
        except Exception:
            return str(value)
    return str(value)


def _normalize_refresh(value: Any, default: str = "manual") -> str:
    raw = str(value or default).lower()
    if raw not in ("manual", "on_read", "per_run"):
        return default
    return raw


def _get_allow_overwrite(context) -> bool:
    return bool(getattr(context, "allow_overwrite", True))


def _update_context_value(context, name: str, value: Any) -> None:
    try:
        setter = getattr(context, "set_global_var", None)
        if callable(setter):
            setter(name, value, card_id="global")
    except Exception:
        pass


def _get_init_flags(context):
    flags = getattr(context, "init_flags", None)
    if flags is None or not isinstance(flags, set):
        try:
            flags = set()
            setattr(context, "init_flags", flags)
        except Exception:
            return None
    return flags


def _reset_variable(name: str, context, store, *, force: bool = False) -> Any:
    variables = _get_store_variables(store)
    if not isinstance(variables, dict):
        return _MISSING
    flags = None
    is_expression = False
    value = _MISSING
    with _store_lock(store):
        entry = variables.get(name)
        if not isinstance(entry, dict):
            return _MISSING
        if entry.get("type") != "expression":
            value = entry.get("value")
        else:
            is_expression = True
            flags = _get_init_flags(context)
            if not force and flags is not None and name in flags:
                value = entry.get("value")
            else:
                config = entry.get("config") or {}
                value = config.get("initial")
                entry["value"] = value
                entry["ts"] = time.time()

    if not is_expression:
        getter = getattr(store, "get_value", None)
        if callable(getter):
            try:
                value = getter(name)
            except Exception:
                pass
        _update_context_value(context, name, value)
        return value

    _update_context_value(context, name, value)
    if flags is not None:
        flags.add(name)
    return value


def initialize_variable(name: Any, *, context=None, store=None, force: bool = False) -> Tuple[bool, Any]:
    if context is None:
        context = get_workflow_context()
    if store is None:
        store = ensure_global_context_loaded()

    target = _normalize_variable_target(name)
    if not target:
        return False, None

    value = _reset_variable(target, context, store, force=force)
    if value is _MISSING:
        return False, None
    return True, value


def _resolve_expression_value(
    name: str,
    entry: dict,
    context,
    store,
    visited: Set[str],
) -> Any:
    with _store_lock(store):
        active_entry = entry
        variables = _get_store_variables(store)
        if isinstance(variables, dict):
            candidate = variables.get(name)
            if isinstance(candidate, dict):
                active_entry = candidate

        config = active_entry.get("config") or {}
        expr = str(config.get("expr") or "").strip()
        if not expr:
            return active_entry.get("value")

        expr_text = _rewrite_expression(expr)
        current = active_entry.get("value")
        self_value = 0 if current is None else current
        allow_overwrite = _get_allow_overwrite(context)
        if not allow_overwrite and current is not None:
            return current

        visited.add(name)

        def resolver(var_name: str) -> Any:
            if var_name in ("self", "this") or var_name == name:
                return self_value
            value = _lookup_var(var_name, context, store, visited)
            if value is _MISSING:
                raise ExpressionError(f"未找到变量: {var_name}")
            return value

        expr_var = _make_expr_var_lookup(name, self_value, context, store, visited)
        expr_exists = _make_expr_exists_lookup(name, self_value, context, store, visited)
        expr_init = _make_expr_init_lookup(context, store, force=False)
        expr_force_init = _make_expr_init_lookup(context, store, force=True)

        try:
            result = evaluate_expression(
                expr_text,
                resolver,
                functions={
                    "var": expr_var,
                    "get": expr_var,
                    "exists": expr_exists,
                    "init": expr_init,
                    "force_init": expr_force_init,
                    "to_number": _expr_to_number,
                    "to_str": _to_text,
                    "trim": _trim,
                    "lower": _lower,
                    "upper": _upper,
                    "contains": _contains,
                    "startswith": _starts_with,
                    "endswith": _ends_with,
                    "regex": _regex_match,
                    "now": _now_timestamp,
                    "to_date": _to_timestamp,
                    # 中文函数别名
                    "取值": expr_var,
                    "存在": expr_exists,
                    "初始化": expr_init,
                    "强制初始化": expr_force_init,
                    "转数字": _expr_to_number,
                    "转文本": _to_text,
                    "去空格": _trim,
                    "小写": _lower,
                    "大写": _upper,
                    "包含": _contains,
                    "开头是": _starts_with,
                    "结尾是": _ends_with,
                    "匹配正则": _regex_match,
                    "当前时间": _now_timestamp,
                    "转日期": _to_timestamp,
                    "长度": len,
                },
            )
        except ExpressionError as exc:
            logger.warning("[变量解析] 表达式执行失败 %s：%s", name, exc)
            result = current
        finally:
            visited.discard(name)

        if allow_overwrite or current is None:
            active_entry["value"] = result
            active_entry["ts"] = time.time()
            _update_context_value(context, name, result)
        return result


def _rewrite_expression(expr: str) -> str:
    if not expr:
        return ""

    def _replace(match: re.Match) -> str:
        raw = match.group(1) or match.group(2) or ""
        return f"var({json.dumps(raw, ensure_ascii=True)})"

    return _EXPR_VAR_PATTERN.sub(_replace, str(expr))


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _to_number(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = _to_text(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _expr_to_number(value: Any) -> float:
    number = _to_number(value)
    if number is None:
        raise ExpressionError("无法转换为数字")
    return float(number)


def _trim(value: Any) -> str:
    return _to_text(value).strip()


def _lower(value: Any) -> str:
    return _to_text(value).lower()


def _upper(value: Any) -> str:
    return _to_text(value).upper()


def _contains(value: Any, needle: Any) -> bool:
    return _to_text(needle) in _to_text(value)


def _starts_with(value: Any, prefix: Any) -> bool:
    return _to_text(value).startswith(_to_text(prefix))


def _ends_with(value: Any, suffix: Any) -> bool:
    return _to_text(value).endswith(_to_text(suffix))


def _regex_match(value: Any, pattern: Any) -> bool:
    try:
        return bool(re.search(str(pattern), _to_text(value)))
    except re.error as exc:
        raise ExpressionError(str(exc)) from exc


def _now_timestamp() -> float:
    return datetime.now().timestamp()


def _to_timestamp(value: Any, fmt: Optional[str] = None) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, datetime):
        return value.timestamp()
    text = _to_text(value).strip()
    if not text:
        raise ExpressionError("日期为空")
    if fmt:
        return datetime.strptime(text, str(fmt)).timestamp()
    for pattern in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y/%m/%d",
    ):
        try:
            return datetime.strptime(text, pattern).timestamp()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError as exc:
        raise ExpressionError("日期格式不支持") from exc


def _make_expr_var_lookup(name: str, self_value: Any, context, store, visited: Set[str]):
    def _var(var_name: Any) -> Any:
        raw = str(var_name or "").strip()
        if raw in ("self", "this") or raw == name:
            return self_value
        value = _lookup_var(raw, context, store, visited)
        if value is _MISSING:
            raise ExpressionError(f"未找到变量: {raw}")
        return value

    return _var


def _make_expr_exists_lookup(name: str, self_value: Any, context, store, visited: Set[str]):
    def _exists(var_name: Any) -> bool:
        raw = str(var_name or "").strip()
        if raw in ("self", "this") or raw == name:
            return True
        return _lookup_var(raw, context, store, visited) is not _MISSING

    return _exists


def _make_expr_init_lookup(context, store, *, force: bool = False):
    def _init(var_name: Any) -> Any:
        ok, value = initialize_variable(var_name, context=context, store=store, force=force)
        if not ok:
            raise ExpressionError(f"未找到变量: {var_name}")
        return value

    return _init


def _lookup_var(name: str, context, store, visited: Optional[Set[str]] = None):
    if not name:
        return _MISSING
    raw, force_global = normalize_variable_name(name)
    if not raw:
        return _MISSING
    if visited is None:
        visited = set()
    if raw in visited:
        logger.warning("[var_resolver] recursive reference: %s", raw)
        return _MISSING
    in_thread_context = _workflow_is_thread_context(context)

    if not force_global:
        value = context.get_global_var(raw, _MISSING)
        if value is not _MISSING:
            entry = None
            variables = _get_store_variables(store)
            if isinstance(variables, dict):
                with _store_lock(store):
                    candidate = variables.get(raw)
                    if isinstance(candidate, dict):
                        entry = candidate
            if isinstance(entry, dict):
                entry_type = entry.get("type")
                if hasattr(context, "snapshot_variable_state"):
                    state = context.snapshot_variable_state()
                    sources = dict((state or {}).get("var_sources", {}) or {})
                else:
                    sources = getattr(context, "var_sources", {})
                is_global = isinstance(sources, dict) and sources.get(raw) == "global"
                if entry_type == "random":
                    config = entry.get("config") or {}
                    refresh = str(config.get("refresh", "")).lower()
                    if refresh == "on_read" and is_global:
                        new_value = store.get_value(raw)
                        _update_context_value(context, raw, new_value)
                        return new_value
                if entry_type == "expression":
                    config = entry.get("config") or {}
                    refresh = _normalize_refresh(config.get("refresh"), "manual")
                    uses_self = _expression_uses_self(config)
                    # 多线程上下文下，self 计数表达式按读取刷新，避免线程间共享同值。
                    if in_thread_context and uses_self:
                        refresh = "on_read"
                    if refresh == "on_read" and (is_global or (in_thread_context and uses_self)):
                        return _resolve_expression_value(raw, entry, context, store, visited)
            return value

    variables = _get_store_variables(store)
    if isinstance(variables, dict):
        with _store_lock(store):
            entry = variables.get(raw, None)
        if entry is None:
            return _MISSING
        if isinstance(entry, dict) and entry.get("type") == "expression":
            config = entry.get("config") or {}
            refresh = _normalize_refresh(config.get("refresh"), "manual")
            if in_thread_context and _expression_uses_self(config):
                refresh = "on_read"
            # per_run 由执行器在每次运行开始时统一刷新，读取阶段只回传当前值。
            if refresh == "on_read" or entry.get("value") is None:
                return _resolve_expression_value(raw, entry, context, store, visited)
            return entry.get("value")
        value = store.get_value(raw)
        if value is None and store.is_locked() and store.is_secret(raw):
            logger.warning("[var_resolver] global variable locked: %s", raw)
        return value

    return _MISSING


def lookup_variable_entry(name: Any, *, context=None, store=None) -> Tuple[bool, Any]:
    """Unified variable lookup entry for tasks and UI components."""
    original = str(name or "").strip()
    raw, force_global = normalize_variable_name(original)
    if not raw:
        return False, None

    if isinstance(context, dict):
        if not force_global and raw in context:
            return True, context.get(raw)
        if store is None:
            store = ensure_global_context_loaded()
        variables = _get_store_variables(store)
        if isinstance(variables, dict):
            with _store_lock(store):
                has_raw = raw in variables
            if has_raw:
                return True, store.get_value(raw)
        return False, None

    if context is None:
        context = get_workflow_context()
    if store is None:
        store = ensure_global_context_loaded()
    # 传入原始引用，保留“全局:”前缀语义，避免被误当作本地变量读取。
    value = _lookup_var(original, context, store, visited=None)
    if value is _MISSING:
        return False, None
    return True, value


def resolve_template(text: Any, *, context=None, store=None) -> Any:
    if not isinstance(text, str) or not text:
        return text

    if context is None:
        context = get_workflow_context()
    if store is None:
        store = ensure_global_context_loaded()

    full_call = _INIT_CALL_PATTERN.fullmatch(text)
    if full_call:
        prefix = full_call.group(1) or ""
        target = full_call.group(2) or ""
        force = prefix == "强制初始化"
        ok, value = initialize_variable(target, context=context, store=store, force=force)
        if not ok:
            logger.warning("[变量解析] 未找到变量: %s", target)
            return ""
        return value

    full = _INIT_PATTERN.fullmatch(text)
    if full:
        prefix = full.group(1)
        raw = full.group(3) or full.group(4) or ""
        if prefix:
            ok, value = initialize_variable(raw, context=context, store=store, force=(prefix == "强制初始化"))
            if not ok:
                logger.warning("[变量解析] 未找到变量: %s", raw)
                return ""
            return value
        value = _lookup_var(raw, context, store)
        if value is _MISSING:
            logger.warning("[变量解析] 未找到变量: %s", raw)
            return ""
        return value

    def _replace_call(match: re.Match) -> str:
        prefix = match.group(1) or ""
        target = match.group(2) or ""
        ok, value = initialize_variable(target, context=context, store=store, force=(prefix == "强制初始化"))
        if not ok:
            logger.warning("[变量解析] 未找到变量: %s", target)
            return ""
        return _stringify_value(value)

    def _replace(match: re.Match) -> str:
        prefix = match.group(1)
        raw = match.group(3) or match.group(4) or ""
        if prefix:
            ok, value = initialize_variable(raw, context=context, store=store, force=(prefix == "强制初始化"))
            if not ok:
                logger.warning("[变量解析] 未找到变量: %s", raw)
                return ""
        else:
            value = _lookup_var(raw, context, store)
            if value is _MISSING:
                logger.warning("[变量解析] 未找到变量: %s", raw)
                return ""
        if value is _MISSING:
            logger.warning("[变量解析] 未找到变量: %s", raw)
            return ""
        return _stringify_value(value)

    resolved = _INIT_CALL_PATTERN.sub(_replace_call, text)
    return _INIT_PATTERN.sub(_replace, resolved)


def resolve_params(value: Any, *, context=None, store=None, skip_keys: Optional[Set[str]] = None) -> Any:
    if context is None:
        context = get_workflow_context()
    if store is None:
        store = ensure_global_context_loaded()

    if isinstance(value, dict):
        resolved = {}
        for key, item in value.items():
            if skip_keys and key in skip_keys:
                resolved[key] = item
            else:
                resolved[key] = resolve_params(item, context=context, store=store, skip_keys=skip_keys)
        return resolved
    if isinstance(value, list):
        return [resolve_params(v, context=context, store=store, skip_keys=skip_keys) for v in value]
    if isinstance(value, tuple):
        return tuple(resolve_params(v, context=context, store=store, skip_keys=skip_keys) for v in value)
    if isinstance(value, str):
        return resolve_template(value, context=context, store=store)
    return value


def refresh_expression_vars(*, refresh_mode: str = "per_run", context=None, store=None) -> int:
    if context is None:
        context = get_workflow_context()
    if store is None:
        store = ensure_global_context_loaded()
    variables = _get_store_variables(store)
    if not isinstance(variables, dict):
        return 0
    targets = []
    in_thread_context = _workflow_is_thread_context(context)
    with _store_lock(store):
        for name, entry in variables.items():
            if not isinstance(entry, dict):
                continue
            if entry.get("type") != "expression":
                continue
            config = entry.get("config") or {}
            refresh = _normalize_refresh(config.get("refresh"), "manual")
            if refresh != refresh_mode:
                continue
            # 多线程上下文下，self 表达式由读取阶段原子递增，避免每线程启动额外叠加。
            if refresh_mode == "per_run" and in_thread_context and _expression_uses_self(config):
                continue
            targets.append(str(name))
    count = 0
    for name in targets:
        with _store_lock(store):
            entry = variables.get(name)
        if not isinstance(entry, dict):
            continue
        _resolve_expression_value(name, entry, context, store, set())
        count += 1
    return count
