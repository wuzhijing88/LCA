# -*- coding: utf-8 -*-
"""Safe expression evaluator for variable formulas."""

from __future__ import annotations

import ast
import math
import operator
from typing import Any, Callable, Dict, Iterable, Optional


class ExpressionError(Exception):
    pass


_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
    ast.Not: operator.not_,
}

_CMP_OPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
}

_DEFAULT_FUNCTIONS: Dict[str, Callable[..., Any]] = {
    "min": min,
    "max": max,
    "len": len,
    "round": round,
    "int": int,
    "float": float,
    "str": str,
    "abs": abs,
    "pow": pow,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "atan2": math.atan2,
    "sqrt": math.sqrt,
    "hypot": math.hypot,
    "floor": math.floor,
    "ceil": math.ceil,
    "copysign": math.copysign,
    "log": math.log,
    "exp": math.exp,
    "degrees": math.degrees,
    "radians": math.radians,
    "pi": math.pi,
}


def _clamp(value: Any, low: Any, high: Any) -> Any:
    if low is None or high is None:
        return value
    if low > high:
        low, high = high, low
    return max(low, min(high, value))


_DEFAULT_FUNCTIONS["clamp"] = _clamp


def _eval_bool_op(op: ast.boolop, values: Iterable[Any]) -> Any:
    if isinstance(op, ast.And):
        result = True
        for value in values:
            result = value
            if not value:
                return value
        return result
    if isinstance(op, ast.Or):
        result = False
        for value in values:
            result = value
            if value:
                return value
        return result
    raise ExpressionError("unsupported boolean operator")


def _coerce_status_literal(value: Any) -> Any:
    if isinstance(value, str):
        if value == "\u6210\u529f":
            return True
        if value == "\u5931\u8d25":
            return False
    return value


def _coerce_status_pair(left: Any, right: Any) -> tuple[Any, Any]:
    if isinstance(left, bool) and isinstance(right, str):
        return left, _coerce_status_literal(right)
    if isinstance(right, bool) and isinstance(left, str):
        return _coerce_status_literal(left), right
    return left, right


def _eval_compare(left: Any, ops: Iterable[ast.cmpop], comparators: Iterable[Any]) -> bool:
    current = left
    for op, right in zip(ops, comparators):
        func = _CMP_OPS.get(type(op))
        if func is None:
            raise ExpressionError("unsupported comparison operator")
        left_value, right_value = _coerce_status_pair(current, right)
        if not func(left_value, right_value):
            return False
        current = right_value
    return True


def _eval_node(
    node: ast.AST,
    resolver: Callable[[str], Any],
    functions: Dict[str, Callable[..., Any]],
) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return resolver(node.id)
    if isinstance(node, ast.BinOp):
        op = _BIN_OPS.get(type(node.op))
        if op is None:
            raise ExpressionError("unsupported binary operator")
        return op(_eval_node(node.left, resolver, functions), _eval_node(node.right, resolver, functions))
    if isinstance(node, ast.UnaryOp):
        op = _UNARY_OPS.get(type(node.op))
        if op is None:
            raise ExpressionError("unsupported unary operator")
        return op(_eval_node(node.operand, resolver, functions))
    if isinstance(node, ast.BoolOp):
        values = [_eval_node(value, resolver, functions) for value in node.values]
        return _eval_bool_op(node.op, values)
    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, resolver, functions)
        right_values = [_eval_node(comp, resolver, functions) for comp in node.comparators]
        return _eval_compare(left, node.ops, right_values)
    if isinstance(node, ast.IfExp):
        condition = _eval_node(node.test, resolver, functions)
        branch = node.body if condition else node.orelse
        return _eval_node(branch, resolver, functions)
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ExpressionError("only simple function calls are allowed")
        func = functions.get(node.func.id)
        if func is None:
            raise ExpressionError(f"function not allowed: {node.func.id}")
        args = [_eval_node(arg, resolver, functions) for arg in node.args]
        kwargs = {kw.arg: _eval_node(kw.value, resolver, functions) for kw in node.keywords if kw.arg}
        return func(*args, **kwargs)
    if isinstance(node, ast.Subscript):
        value = _eval_node(node.value, resolver, functions)
        slice_node = node.slice
        if isinstance(slice_node, ast.Slice):
            lower = _eval_node(slice_node.lower, resolver, functions) if slice_node.lower else None
            upper = _eval_node(slice_node.upper, resolver, functions) if slice_node.upper else None
            step = _eval_node(slice_node.step, resolver, functions) if slice_node.step else None
            return value[slice(lower, upper, step)]
        index = _eval_node(slice_node, resolver, functions)
        return value[index]
    if isinstance(node, ast.List):
        return [_eval_node(item, resolver, functions) for item in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_eval_node(item, resolver, functions) for item in node.elts)
    if isinstance(node, ast.Dict):
        keys = [_eval_node(key, resolver, functions) for key in node.keys]
        values = [_eval_node(value, resolver, functions) for value in node.values]
        return dict(zip(keys, values))
    raise ExpressionError(f"unsupported expression node: {type(node).__name__}")


def evaluate_expression(
    expr: str,
    resolver: Callable[[str], Any],
    *,
    functions: Optional[Dict[str, Callable[..., Any]]] = None,
) -> Any:
    if expr is None or str(expr).strip() == "":
        raise ExpressionError("empty expression")
    func_map = dict(_DEFAULT_FUNCTIONS)
    if functions:
        func_map.update(functions)
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(str(exc)) from exc
    return _eval_node(tree.body, resolver, func_map)
