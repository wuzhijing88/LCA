from __future__ import annotations

from typing import Any, Dict, Iterable


def parameter_values_equal(left: Any, right: Any) -> bool:
    if type(left) is not type(right):
        return _is_number(left) and _is_number(right) and left == right
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(parameter_values_equal(left[key], right[key]) for key in left)
    if isinstance(left, (list, tuple)):
        return len(left) == len(right) and all(parameter_values_equal(a, b) for a, b in zip(left, right))
    return left == right


def collect_changed_parameters(
    old_parameters: Dict[str, Any],
    new_parameters: Dict[str, Any],
    *,
    ignore_prefixes: Iterable[str] = ("_",),
) -> Dict[str, Any]:
    changed: Dict[str, Any] = {}
    for key, value in (new_parameters or {}).items():
        name = str(key)
        if any(name.startswith(prefix) for prefix in ignore_prefixes):
            continue
        if not parameter_values_equal((old_parameters or {}).get(key), value):
            changed[key] = value
    return changed


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
