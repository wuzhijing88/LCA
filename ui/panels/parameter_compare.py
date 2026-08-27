from __future__ import annotations

from typing import Any, Dict, Iterable


def parameter_values_equal(left: Any, right: Any) -> bool:
    if left is right:
        return True
    if left in (None, "") and right in (None, ""):
        return True
    if isinstance(left, bool) or isinstance(right, bool):
        return _as_bool(left) == _as_bool(right)
    if _is_number(left) and _is_number(right):
        return float(left) == float(right)
    if _is_number(left) and isinstance(right, str):
        parsed = _parse_number(right)
        return parsed is not None and float(left) == parsed
    if _is_number(right) and isinstance(left, str):
        parsed = _parse_number(left)
        return parsed is not None and parsed == float(right)
    if isinstance(left, str) and isinstance(right, str):
        return left == right
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


def _parse_number(value: str):
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("1", "true", "yes", "y", "on", "是", "真"):
            return True
        if text in ("0", "false", "no", "n", "off", "否", "假", ""):
            return False
    return bool(value)
