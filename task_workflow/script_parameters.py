"""脚本公开参数的统一校验；非法值不截断、不钳制、不切换含义。"""

from decimal import Decimal, InvalidOperation
import math
from typing import Any, Optional


def boolean_parameter(value: Any, label: str = "布尔参数") -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label}必须是真或假")
    return value


def number_parameter(value: Any, label: str) -> Any:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"{label}必须是有限数字")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{label}必须是有限数字")
        return value
    try:
        number = Decimal(value.strip())
        if not number.is_finite():
            raise InvalidOperation
        if number == number.to_integral_value():
            return int(number)
        result = float(number)
        if not math.isfinite(result) or (result == 0 and number != 0):
            raise InvalidOperation
        return result
    except (InvalidOperation, ValueError, OverflowError) as exc:
        raise ValueError(f"{label}必须是有限数字") from exc


def integer_parameter(value: Any, label: str, *, minimum: Optional[int] = None, maximum: Optional[int] = None) -> int:
    try:
        if isinstance(value, str):
            decimal = Decimal(value.strip())
            if not decimal.is_finite() or decimal != decimal.to_integral_value():
                raise ValueError
            number = int(decimal)
        else:
            number = number_parameter(value, label)
    except (ValueError, InvalidOperation, OverflowError) as exc:
        raise ValueError(f"{label}必须是整数") from exc
    if isinstance(number, float) and not number.is_integer():
        raise ValueError(f"{label}必须是整数")
    number = int(number)
    if minimum is not None and number < minimum:
        raise ValueError(f"{label}必须是大于等于{minimum}的整数")
    if maximum is not None and number > maximum:
        raise ValueError(f"{label}必须是小于等于{maximum}的整数")
    return number


def finite_seconds(value: Any, label: str, *, positive: bool = False) -> float:
    try:
        seconds = float(number_parameter(value, label))
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{label}必须是有限数字") from exc
    if not math.isfinite(seconds) or seconds < 0 or (positive and seconds == 0):
        comparison = "大于0" if positive else "大于等于0"
        raise ValueError(f"{label}必须是{comparison}的有限数字")
    return seconds


def text_parameter(value: Any) -> str:
    return "" if value is None else str(value)


def add_numeric_values(current: Any, step: Any) -> Any:
    left = number_parameter(current, "变量原值")
    right = number_parameter(step, "步长")
    result = left + right
    if isinstance(result, float):
        if not math.isfinite(result):
            raise ValueError("变量累加结果必须是有限数字")
        if result.is_integer():
            return int(result)
    return result
