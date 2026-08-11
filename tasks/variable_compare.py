# -*- coding: utf-8 -*-
"""
变量比较卡片 - 对变量提取结果进行比较判断
支持类型：数值比较、表达式比较（可从字典/列表/变量本身取值）
"""

import ast
import json
import logging
import re
from datetime import datetime
from typing import Dict, Any, Optional, Tuple

from tasks import task_utils
from task_workflow.expression_evaluator import ExpressionError, evaluate_expression
from task_workflow.variable_resolver import lookup_variable_entry, initialize_variable

logger = logging.getLogger(__name__)

TASK_NAME = "变量比较"

_SIMPLE_OPERATOR_MAP = {
    "大于等于": "大于等于",
    "小于等于": "小于等于",
    "不等于": "不等于",
    "等于": "等于",
    "大于": "大于",
    "小于": "小于",
    "表达式": "表达式",
    ">=": "大于等于",
    "<=": "小于等于",
    "!=": "不等于",
    "==": "等于",
    "=": "等于",
    ">": "大于",
    "<": "小于",
    "expr": "表达式",
    "expression": "表达式",
}

_EXPR_VAR_PATTERN = re.compile(r"\$\{([^{}]+)\}|\{\{([^{}]+)\}\}")
_SIMPLE_HUMAN_TEXT_OP_PATTERN = re.compile(
    r"^\s*(.+?)\s*(包含|不包含|开头是|结尾是|匹配正则)\s*(.+?)\s*$"
)
_SIMPLE_HUMAN_COMPARE_PATTERN = re.compile(
    r"^\s*(.+?)\s*(大于等于|小于等于|不等于|等于|大于|小于)\s*(.+?)\s*$"
)
_SIMPLE_HUMAN_EXISTS_PATTERN = re.compile(r"^\s*(.+?)\s*(存在|不存在)\s*$")
_EXPR_MISSING = object()



def get_params_definition() -> Dict[str, Dict[str, Any]]:
    default_conditions_json = json.dumps([], ensure_ascii=True)

    base_params = {
        "source_workflow_id": {
            "label": "来源工作流",
            "type": "select",
            "default": None,
            "widget_hint": "workflow_selector",
            "tooltip": "选择变量来源的工作流（只读）"
        },
        "simple_conditions_logic": {
            "label": "\u6761\u4ef6\u903b\u8f91",
            "type": "select",
            "options": ["\u5168\u90e8\u6ee1\u8db3", "\u4efb\u4e00\u6ee1\u8db3"],
            "default": "\u5168\u90e8\u6ee1\u8db3"
        },
        "simple_conditions_json": {
            "label": "\u6761\u4ef6\u5217\u8868",
            "type": "textarea",
            "default": default_conditions_json,
            "widget_hint": "conditions_table",
            "workflow_filter_param": "source_workflow_id",
            "tooltip": "选择变量来源的工作流（只读）"
        },
    }
    return task_utils.merge_params_definitions(
        base_params,
        task_utils.get_standard_action_params()
    )


def _get_context_var(context, counters: Dict[str, Any], name: str) -> Optional[Any]:
    found, value = _get_context_var_entry(context, counters, name)
    if found:
        return value
    return None


def _get_context_var_entry(context, counters: Dict[str, Any], name: str) -> Tuple[bool, Any]:
    raw_name = str(name or "").strip()
    if not raw_name:
        return False, None

    found, value = lookup_variable_entry(raw_name, context=context)
    if found:
        return True, value

    if counters is not None:
        try:
            if raw_name in counters:
                return True, counters.get(raw_name)
        except Exception as exc:
            logger.debug(f"[变量比较] 读取计数器变量失败: name={raw_name}, err={exc}")
    return False, None


def _get_dict_field(value: dict, key: str) -> Tuple[Optional[Any], Optional[str]]:
    key = key.strip()
    if not key:
        return None, "字段名为空"
    current = value
    for part in key.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None, f"字段不存在: {key}"
    return current, None


def _select_value(raw_value: Any, selector: str, dict_key: str, list_index: Any) -> Tuple[Optional[Any], Optional[str]]:
    if selector == "变量本身":
        return raw_value, None
    if selector == "字典字段":
        if not isinstance(raw_value, dict):
            return None, "变量不是字典"
        return _get_dict_field(raw_value, dict_key)
    if selector == "列表索引":
        if not isinstance(raw_value, (list, tuple)):
            return None, "变量不是列表/元组"
        try:
            idx = int(list_index)
        except (TypeError, ValueError):
            return None, "索引不是有效整数"
        if idx < 0:
            idx = len(raw_value) + idx
        if idx < 0 or idx >= len(raw_value):
            return None, "索引超出范围"
        return raw_value[idx], None
    return None, "未知取值方式"


def _to_number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _to_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("true", "1", "yes", "on", "是", "真", "成功"):
            return True
        if text in ("false", "0", "no", "off", "否", "假", "失败"):
            return False
    return None


def _parse_fixed_literal(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return ""

    bool_value = _to_bool(text)
    if bool_value is not None:
        return bool_value

    lower_text = text.lower()
    if lower_text in ("null", "none"):
        return None

    # 优先识别标准数字，避免把普通字符串误转为数字
    if re.fullmatch(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", text):
        if re.fullmatch(r"[-+]?\d+", text):
            try:
                return int(text)
            except ValueError:
                pass
        number = _to_number(text)
        if number is not None:
            return number

    # 支持 JSON/字面量输入（如 [1,2], {"k":1}, "abc", 'abc'）
    if text[:1] in ('[', '{', '"', "'", '('):
        try:
            return ast.literal_eval(text)
        except Exception:
            return text
    return text


def _try_parse_timestamp(value: Any) -> Optional[float]:
    try:
        return _to_timestamp(value)
    except Exception:
        return None


def _compare_values(left: Any, right: Any, op: str) -> Tuple[bool, str]:
    if op in ("等于", "不等于"):
        left_bool = _to_bool(left)
        right_bool = _to_bool(right)
        if left_bool is not None and right_bool is not None:
            result = left_bool == right_bool
            return (result, "") if op == "等于" else (not result, "")

        left_num = _to_number(left)
        right_num = _to_number(right)
        if left_num is not None and right_num is not None:
            result = left_num == right_num
            return (result, "") if op == "等于" else (not result, "")

        result = left == right
        return (result, "") if op == "等于" else (not result, "")

    left_num = _to_number(left)
    right_num = _to_number(right)
    if left_num is not None and right_num is not None:
        if op == "大于":
            return left_num > right_num, ""
        if op == "小于":
            return left_num < right_num, ""
        if op == "大于等于":
            return left_num >= right_num, ""
        if op == "小于等于":
            return left_num <= right_num, ""
        return False, "未知比较运算符"

    left_ts = _try_parse_timestamp(left)
    right_ts = _try_parse_timestamp(right)
    if left_ts is not None and right_ts is not None:
        if op == "大于":
            return left_ts > right_ts, ""
        if op == "小于":
            return left_ts < right_ts, ""
        if op == "大于等于":
            return left_ts >= right_ts, ""
        if op == "小于等于":
            return left_ts <= right_ts, ""
        return False, "未知比较运算符"

    if isinstance(left, str) and isinstance(right, str):
        if op == "大于":
            return left > right, ""
        if op == "小于":
            return left < right, ""
        if op == "大于等于":
            return left >= right, ""
        if op == "小于等于":
            return left <= right, ""
        return False, "未知比较运算符"

    return False, "比较失败：类型不兼容，建议使用表达式并显式转换类型"


def _compare_numbers(left: Any, right: Any, op: str) -> Tuple[bool, str]:
    return _compare_values(left, right, op)


def _lookup_var_value(name: Any, context, counters: Dict[str, Any]):
    raw = str(name or "").strip()
    if not raw:
        return _EXPR_MISSING

    found, value = lookup_variable_entry(raw, context=context)
    if found:
        return value

    if counters is not None:
        try:
            if raw in counters:
                return counters.get(raw)
        except Exception as exc:
            logger.debug(f"[变量比较] 表达式读取计数器失败: name={raw}, err={exc}")
    return _EXPR_MISSING


def _is_number_literal(text: str) -> bool:
    return bool(re.fullmatch(r"[-+]?\d+(?:\.\d+)?", str(text or "").strip()))


def _is_function_like_expression(text: str) -> bool:
    raw = str(text or "").strip()
    if not raw:
        return False
    return bool(
        re.fullmatch(
            r"[A-Za-z_\u4e00-\u9fff][A-Za-z0-9_\u4e00-\u9fff]*\s*\(.*\)",
            raw,
        )
    )


def _strip_wrapped_var_name(text: str) -> str:
    raw = str(text or "").strip()
    if raw.startswith("@"):
        raw = raw[1:].strip()
    if raw.startswith("${") and raw.endswith("}"):
        return raw[2:-1].strip()
    if raw.startswith("{{") and raw.endswith("}}"):
        return raw[2:-2].strip()
    return raw


def _build_human_operand(token: str, side: str) -> str:
    raw = str(token or "").strip()
    if not raw:
        return "\"\""

    if raw.startswith("@"):
        var_name = _strip_wrapped_var_name(raw)
        return f"var({json.dumps(var_name, ensure_ascii=True)})" if var_name else "\"\""

    if raw.startswith("${") and raw.endswith("}"):
        return raw
    if raw.startswith("{{") and raw.endswith("}}"):
        return raw
    if raw in ("self", "this"):
        return raw
    if _is_number_literal(raw):
        return raw

    lower = raw.lower()
    if lower in ("true", "false"):
        return "True" if lower == "true" else "False"
    if lower in ("none", "null"):
        return "None"

    if (raw.startswith("\"") and raw.endswith("\"")) or (raw.startswith("'") and raw.endswith("'")):
        return raw
    if _is_function_like_expression(raw):
        return raw

    if side == "left":
        return f"var({json.dumps(raw, ensure_ascii=True)})"
    return json.dumps(raw, ensure_ascii=True)


def _rewrite_human_friendly_expression(expr: str) -> str:
    text = str(expr or "").strip()
    if not text:
        return ""

    text_op_match = _SIMPLE_HUMAN_TEXT_OP_PATTERN.match(text)
    if text_op_match:
        left_raw, op, right_raw = (
            text_op_match.group(1),
            text_op_match.group(2),
            text_op_match.group(3),
        )
        left_expr = _build_human_operand(left_raw, side="left")
        right_expr = _build_human_operand(right_raw, side="right")
        if op == "不包含":
            return f"not contains({left_expr}, {right_expr})"
        func_map = {
            "包含": "contains",
            "开头是": "startswith",
            "结尾是": "endswith",
            "匹配正则": "regex",
        }
        func_name = func_map.get(op)
        if func_name:
            return f"{func_name}({left_expr}, {right_expr})"

    compare_match = _SIMPLE_HUMAN_COMPARE_PATTERN.match(text)
    if compare_match:
        left_raw, op, right_raw = (
            compare_match.group(1),
            compare_match.group(2),
            compare_match.group(3),
        )
        left_expr = _build_human_operand(left_raw, side="left")
        right_expr = _build_human_operand(right_raw, side="right")
        symbol_map = {
            "等于": "==",
            "不等于": "!=",
            "大于": ">",
            "小于": "<",
            "大于等于": ">=",
            "小于等于": "<=",
        }
        symbol = symbol_map.get(op)
        if symbol:
            return f"{left_expr} {symbol} {right_expr}"

    exists_match = _SIMPLE_HUMAN_EXISTS_PATTERN.match(text)
    if exists_match:
        var_name = _strip_wrapped_var_name(exists_match.group(1))
        if var_name:
            exists_expr = f"存在({json.dumps(var_name, ensure_ascii=True)})"
            if exists_match.group(2) == "不存在":
                return f"not {exists_expr}"
            return exists_expr

    return text


def _rewrite_expression(expr: str) -> str:
    if not expr:
        return ""

    expr = _rewrite_human_friendly_expression(expr)

    def _replace(match: re.Match) -> str:
        raw = match.group(1) or match.group(2) or ""
        return f"var({json.dumps(raw, ensure_ascii=True)})"

    return _EXPR_VAR_PATTERN.sub(_replace, str(expr))


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


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


def _evaluate_expression_condition(
    expr: str,
    left_value: Any,
    context,
    counters: Dict[str, Any],
) -> Tuple[bool, str]:
    expr_text = _rewrite_expression(str(expr or "").strip())
    if not expr_text:
        return False, "表达式为空"

    def _resolver(name: str) -> Any:
        if name in ("self", "this"):
            return left_value
        value = _lookup_var_value(name, context, counters)
        if value is _EXPR_MISSING:
            raise ExpressionError(f"未找到变量: {name}")
        return value

    def _var(name: Any) -> Any:
        value = _lookup_var_value(name, context, counters)
        if value is _EXPR_MISSING:
            raise ExpressionError(f"未找到变量: {name}")
        return value

    def _exists(name: Any) -> bool:
        return _lookup_var_value(name, context, counters) is not _EXPR_MISSING

    def _init(name: Any) -> Any:
        ok, value = initialize_variable(name, context=context, force=False)
        if not ok:
            raise ExpressionError(f"未找到变量: {name}")
        return value

    def _force_init(name: Any) -> Any:
        ok, value = initialize_variable(name, context=context, force=True)
        if not ok:
            raise ExpressionError(f"未找到变量: {name}")
        return value

    functions = {
        "var": _var,
        "get": _var,
        "exists": _exists,
        "init": _init,
        "force_init": _force_init,
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
        # 中文函数别名（面向中文用户）
        "取值": _var,
        "存在": _exists,
        "初始化": _init,
        "强制初始化": _force_init,
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
    }
    try:
        result = evaluate_expression(expr_text, _resolver, functions=functions)
    except ExpressionError as exc:
        return False, f"表达式解析失败: {exc}"
    return bool(result), ""


def _parse_conditions_json(raw_value: Any) -> list:
    if not raw_value:
        return []
    if isinstance(raw_value, list):
        return raw_value
    if not isinstance(raw_value, str):
        return []
    text = raw_value.strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    if isinstance(data, list):
        return data
    return []


def _normalize_operator(op: str) -> Optional[str]:
    if not op:
        return None
    op = op.strip()
    if op in _SIMPLE_OPERATOR_MAP:
        return _SIMPLE_OPERATOR_MAP[op]
    return None


def _resolve_source_context(params: Dict[str, Any]):
    try:
        from task_workflow.workflow_context import get_workflow_context
        default_context = get_workflow_context()
    except Exception:
        default_context = None

    try:
        from task_workflow.workflow_vars import get_context_for_task, normalize_workflow_task_id
    except Exception:
        return default_context

    source_workflow_id = normalize_workflow_task_id(params.get("source_workflow_id"))
    if source_workflow_id is None:
        return default_context

    return get_context_for_task(source_workflow_id)


def _resolve_condition_left_value(
    left_source: str,
    left_value: str,
    context,
    counters: Dict[str, Any],
) -> Tuple[Optional[Any], Optional[str]]:
    if left_source in ("\u53d8\u91cf", "\u53d8\u91cf\u540d", ""):
        if not left_value:
            return None, "\u53d8\u91cf\u540d\u4e3a\u7a7a"
        found, value = _get_context_var_entry(context, counters, left_value)
        if not found:
            return None, f"\u672a\u627e\u5230\u53d8\u91cf '{left_value}'"
        return value, None
    return None, "\u53ea\u652f\u6301\u53d8\u91cf\u540d\u6bd4\u8f83"


def _resolve_condition_right_value(right_source: str, right_value: str, context, counters: Dict[str, Any]) -> Tuple[Optional[Any], Optional[str]]:
    if right_source in ("\u53d8\u91cf", "\u53d8\u91cf\u540d"):
        if not right_value:
            return None, "目标变量名为空"
        found, value = _get_context_var_entry(context, counters, right_value)
        if not found:
            return None, f"未找到变量 '{right_value}'"
        return value, None

    return _parse_fixed_literal(right_value), None


def _evaluate_condition_row(row: Dict[str, Any], context, counters: Dict[str, Any]) -> Tuple[bool, str]:
    if not isinstance(row, dict):
        return False, "条件格式无效（非对象）"

    left_source = str(row.get("left_source", "\u53d8\u91cf")).strip()
    left_value = str(row.get("left_value", "")).strip()
    operator = _normalize_operator(str(row.get("operator", "等于")))
    right_source = str(row.get("right_source", "固定值")).strip()
    right_value = str(row.get("right_value", "")).strip()

    if not operator:
        return False, "比较运算符无效"

    if operator == "表达式":
        left_actual = None
        if left_value:
            left_actual, left_error = _resolve_condition_left_value(left_source, left_value, context, counters)
            if left_error:
                return False, left_error
        return _evaluate_expression_condition(right_value, left_actual, context, counters)

    left_actual, left_error = _resolve_condition_left_value(left_source, left_value, context, counters)
    if left_error:
        return False, left_error

    right_actual, right_error = _resolve_condition_right_value(right_source, right_value, context, counters)
    if right_error:
        return False, right_error

    return _compare_values(left_actual, right_actual, operator)


def _resolve_list_index(raw_value: Any, idx: int) -> Tuple[Optional[Any], Optional[str]]:
    if not isinstance(raw_value, (list, tuple)):
        return None, "变量不是列表/元组"
    if idx < 0:
        idx = len(raw_value) + idx
    if idx < 0 or idx >= len(raw_value):
        return None, "索引超出范围"
    return raw_value[idx], None


def _execute_simple_multi_compare(params: Dict[str, Any], counters: Dict[str, Any], card_id: Optional[int]) -> Tuple[bool, str, Optional[int]]:
    on_success = params.get('on_success', '\u6267\u884c\u4e0b\u4e00\u6b65')
    success_jump_id = params.get('success_jump_target_id')
    on_failure = params.get('on_failure', '\u6267\u884c\u4e0b\u4e00\u6b65')
    failure_jump_id = params.get('failure_jump_target_id')

    context = _resolve_source_context(params)

    logic = params.get('simple_conditions_logic', '\u5168\u90e8\u6ee1\u8db3')
    require_all = logic != '\u4efb\u4e00\u6ee1\u8db3'

    conditions = _parse_conditions_json(params.get('simple_conditions_json', ''))
    if conditions:
        for index, row in enumerate(conditions, start=1):
            result, message = _evaluate_condition_row(row, context, counters)
            if message:
                logger.warning(f"\u53d8\u91cf\u6bd4\u8f83\u5931\u8d25\uff1a\u6761\u4ef6{index} {message}")
                return task_utils._handle_failure(on_failure, failure_jump_id, card_id)

            if require_all and not result:
                logger.info(f"[\u53d8\u91cf\u6bd4\u8f83-\u7b80\u6613-\u591a\u6761\u4ef6] \u6761\u4ef6{index} \u4e0d\u6ee1\u8db3")
                return task_utils._handle_failure(on_failure, failure_jump_id, card_id)

            if not require_all and result:
                logger.info(f"[\u53d8\u91cf\u6bd4\u8f83-\u7b80\u6613-\u591a\u6761\u4ef6] \u6761\u4ef6{index} \u6ee1\u8db3")
                return task_utils._handle_success(on_success, success_jump_id, card_id)

        if require_all:
            logger.info("[\u53d8\u91cf\u6bd4\u8f83-\u7b80\u6613-\u591a\u6761\u4ef6] \u5168\u90e8\u6761\u4ef6\u6ee1\u8db3")
            return task_utils._handle_success(on_success, success_jump_id, card_id)

        logger.info("[\u53d8\u91cf\u6bd4\u8f83-\u7b80\u6613-\u591a\u6761\u4ef6] \u65e0\u6761\u4ef6\u6ee1\u8db3")
        return task_utils._handle_failure(on_failure, failure_jump_id, card_id)

    logger.warning("\u53d8\u91cf\u6bd4\u8f83\u5931\u8d25\uff1a\u6761\u4ef6\u5217\u8868\u4e3a\u7a7a")
    return task_utils._handle_failure(on_failure, failure_jump_id, card_id)


def execute_task(params: Dict[str, Any], counters: Dict[str, Any],
                 execution_mode: str = 'foreground', **kwargs) -> Tuple[bool, str, Optional[int]]:
    card_id = kwargs.get('card_id')
    on_failure = params.get('on_failure', '\u6267\u884c\u4e0b\u4e00\u6b65')
    failure_jump_id = params.get('failure_jump_target_id')

    try:
        ui_mode = params.get('ui_mode', '\u7b80\u6613')
        if ui_mode == '\u5b8c\u6574':
            on_success = params.get('on_success', '\u6267\u884c\u4e0b\u4e00\u6b65')
            success_jump_id = params.get('success_jump_target_id')

            context = _resolve_source_context(params)

            variable_name = str(params.get('variable_name', '') or '').strip()
            selector = str(params.get('value_selector', '\u53d8\u91cf\u672c\u8eab') or '\u53d8\u91cf\u672c\u8eab').strip()
            dict_key = str(params.get('dict_key', '') or '')
            list_index = params.get('list_index', 0)
            compare_mode = str(params.get('compare_mode', '\u6570\u503c\u6bd4\u8f83') or '\u6570\u503c\u6bd4\u8f83').strip()
            number_op = str(params.get('number_operator', '\u7b49\u4e8e') or '\u7b49\u4e8e').strip()
            target_source = str(params.get('target_source', '\u56fa\u5b9a\u503c') or '\u56fa\u5b9a\u503c').strip()

            if compare_mode != "\u6570\u503c\u6bd4\u8f83":
                logger.info(f"[\u53d8\u91cf\u6bd4\u8f83] \u5df2\u9650\u5236\u4e3a\u6570\u503c\u6bd4\u8f83\uff0c\u5ffd\u7565\u6bd4\u8f83\u7c7b\u578b: {compare_mode}")
                compare_mode = "\u6570\u503c\u6bd4\u8f83"

            raw_value = _get_context_var(context, counters, variable_name)
            if raw_value is None:
                logger.warning(f"\u53d8\u91cf\u6bd4\u8f83\u5931\u8d25\uff1a\u672a\u627e\u5230\u53d8\u91cf '{variable_name}'")
                return task_utils._handle_failure(on_failure, failure_jump_id, card_id)

            selected_value, error = _select_value(raw_value, selector, dict_key, list_index)
            if error:
                logger.warning(f"\u53d8\u91cf\u6bd4\u8f83\u5931\u8d25\uff1a{error}")
                return task_utils._handle_failure(on_failure, failure_jump_id, card_id)

            target_value = None
            if target_source == "\u53d8\u91cf":
                target_var = str(params.get('target_variable', '') or '').strip()
                if not target_var:
                    logger.warning("\u53d8\u91cf\u6bd4\u8f83\u5931\u8d25\uff1a\u76ee\u6807\u53d8\u91cf\u540d\u4e3a\u7a7a")
                    return task_utils._handle_failure(on_failure, failure_jump_id, card_id)
                target_value = _get_context_var(context, counters, target_var)
                if target_value is None:
                    logger.warning(f"\u53d8\u91cf\u6bd4\u8f83\u5931\u8d25\uff1a\u672a\u627e\u5230\u76ee\u6807\u53d8\u91cf '{target_var}'")
                    return task_utils._handle_failure(on_failure, failure_jump_id, card_id)
            else:
                target_value = params.get('target_value', '')
                if isinstance(target_value, str) and not target_value.strip():
                    logger.warning("\u53d8\u91cf\u6bd4\u8f83\u5931\u8d25\uff1a\u76ee\u6807\u503c\u4e3a\u7a7a")
                    return task_utils._handle_failure(on_failure, failure_jump_id, card_id)

            logger.info(
                f"[\u53d8\u91cf\u6bd4\u8f83] \u53d8\u91cf={variable_name}, \u53d6\u503c\u65b9\u5f0f={selector}, \u6bd4\u8f83\u7c7b\u578b={compare_mode}, "
                f"\u6570\u503c\u8fd0\u7b97={number_op}, \u76ee\u6807\u6765\u6e90={target_source}"
            )

            result, message = _compare_numbers(selected_value, target_value, number_op)

            if message:
                logger.info(f"[\u53d8\u91cf\u6bd4\u8f83] \u8bf4\u660e: {message}")

            if result:
                logger.info("[\u53d8\u91cf\u6bd4\u8f83] \u6761\u4ef6\u6ee1\u8db3")
                return task_utils._handle_success(on_success, success_jump_id, card_id)
            logger.info("[\u53d8\u91cf\u6bd4\u8f83] \u6761\u4ef6\u4e0d\u6ee1\u8db3")
            return task_utils._handle_failure(on_failure, failure_jump_id, card_id)

        return _execute_simple_multi_compare(params, counters, card_id)
    except Exception as exc:
        logger.error(f"[变量比较] 执行异常: {exc}", exc_info=True)
        return task_utils._handle_failure(on_failure, failure_jump_id, card_id)
