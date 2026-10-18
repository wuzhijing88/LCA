"""Pure script helpers shared by embedded and isolated interpreters."""

from __future__ import annotations

import json
import math
import random
import time
from typing import Any

from .script_parameters import (
    boolean_parameter as _as_bool,
)
from .script_parameters import (
    integer_parameter,
    number_parameter,
)
from .script_parameters import (
    text_parameter as _text,
)


def _is_int_range_bound(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return value.is_integer()
    if isinstance(value, str):
        text = value.strip()
        if text.startswith(("+", "-")):
            text = text[1:]
        return bool(text) and text.isdigit()
    return False


def script_for_iterable(value: Any) -> Any:
    """数字当循环次数；其它值保持原样交给 for。"""
    if isinstance(value, bool):
        raise ValueError("循环次数不能是真假")  # noqa: TRY004 -- preserve the script language's numeric validation contract
    if isinstance(value, range):
        return value
    if _is_int_range_bound(value):
        count = int(value) if not isinstance(value, str) else int(str(value).strip())
        if count < 0:
            raise ValueError("循环次数不能是负数")
        return range(count)
    return value


def script_random(*args: Any, 起点: Any = None, 终点: Any = None) -> Any:
    if 起点 is not None or 终点 is not None:
        if args:
            raise ValueError("随机的位置范围与起点、终点不能同时传入")
        if 起点 is None or 终点 is None:
            raise ValueError("随机的起点和终点必须同时传入")
        args = (起点, 终点)
    if len(args) > 2:
        raise ValueError("随机最多接受两个参数")
    if not args:
        return random.random()
    if len(args) == 1:
        return random.randrange(integer_parameter(args[0], "随机上限", minimum=1))
    start, end = (
        number_parameter(item, label)
        for item, label in zip(args, ("随机起点", "随机终点"))
    )
    if end < start:
        raise ValueError("随机终点不能小于起点")
    if isinstance(start, int) and isinstance(end, int):
        return random.randint(start, end)
    if not math.isfinite(float(end) - float(start)):
        raise ValueError("随机区间跨度必须是有限数字")
    return random.uniform(float(start), float(end))


def script_sqrt(值: Any) -> float:
    number = float(值)
    if number < 0:
        raise ValueError("开方不能是负数")
    return number**0.5


def script_sin(角度: Any) -> float:
    return math.sin(math.radians(float(角度)))


def script_cos(角度: Any) -> float:
    return math.cos(math.radians(float(角度)))


def script_clamp(值: Any, 下限: Any, 上限: Any) -> float:
    number = float(值)
    low = float(下限)
    high = float(上限)
    if low > high:
        low, high = high, low
    return min(high, max(low, number))


def script_contains(文本: Any, 片段: Any) -> bool:
    return _text(片段) in _text(文本)


def script_slice(文本: Any, 起点: Any, 字数: Any = None) -> str:
    source = _text(文本)
    begin = integer_parameter(起点, "截取起点", minimum=1) - 1
    if 字数 is None:
        return source[begin:]
    return source[begin : begin + integer_parameter(字数, "截取字数", minimum=0)]


def script_replace(文本: Any, 旧: Any, 新: Any, 次数: Any = None) -> str:
    source = _text(文本)
    if 次数 is None:
        return source.replace(_text(旧), _text(新))
    return source.replace(
        _text(旧), _text(新), integer_parameter(次数, "替换次数", minimum=0)
    )


def script_strip(文本: Any) -> str:
    return _text(文本).strip()


def script_find(文本: Any, 片段: Any) -> int:
    index = _text(文本).find(_text(片段))
    return 0 if index < 0 else index + 1


def script_extract_number(文本: Any) -> Any:
    import re

    match = re.search(r"-?\d+(?:\.\d+)?", _text(文本))
    if not match:
        return 0
    raw = match.group(0)
    return float(raw) if "." in raw else int(raw)


def script_split(文本: Any, 分隔符: Any = None) -> list:
    source = _text(文本)
    if 分隔符 is None or 分隔符 == "":
        return source.split()
    return source.split(str(分隔符))


def script_now_ms() -> int:
    return int(time.monotonic() * 1000)


def script_json_parse(文本: Any) -> Any:
    try:
        return json.loads(_text(文本))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"JSON解析失败: {exc}") from exc


def script_json_dump(对象: Any) -> str:
    try:
        return json.dumps(对象, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"JSON生成失败: {exc}") from exc


def script_dict_get(字典: Any, 键: Any, 默认值: Any = None) -> Any:
    if not isinstance(字典, dict):
        raise TypeError("字典获取的目标必须是字典")
    return 字典.get(键, 默认值)


def script_dict_set(字典: Any, 键: Any, 值: Any) -> Any:
    if not isinstance(字典, dict):
        raise TypeError("字典设置的目标必须是字典")
    字典[键] = 值
    return 字典


def script_list_append(列表: Any, 值: Any) -> int:
    if not isinstance(列表, list):
        raise TypeError("列表追加的目标必须是列表")
    列表.append(值)
    return len(列表)


def script_list_pop(列表: Any, 索引: Any = -1) -> Any:
    if not isinstance(列表, list):
        raise TypeError("列表弹出的目标必须是列表")
    return 列表.pop(integer_parameter(索引, "列表索引"))


def script_list_clear(列表: Any) -> None:
    if not isinstance(列表, list):
        raise TypeError("列表清空的目标必须是列表")
    列表.clear()


def script_sum(数据: Any, 起值: Any = 0) -> Any:
    return sum(数据, 起值)


def script_nearest_int(数值: Any) -> int:
    return round(number_parameter(数值, "就近取整数值"))


def script_type(值: Any) -> str:
    return type(值).__name__


def script_assert(条件: Any, 错误信息: Any = "断言失败") -> bool:
    if not 条件:
        raise AssertionError(str(错误信息))
    return True


def script_dict_keys(字典: Any) -> list:
    if not isinstance(字典, dict):
        raise TypeError("字典键的目标必须是字典")
    return list(字典.keys())


def script_dict_values(字典: Any) -> list:
    if not isinstance(字典, dict):
        raise TypeError("字典值的目标必须是字典")
    return list(字典.values())


def script_list_extend(列表: Any, 数据: Any) -> int:
    if not isinstance(列表, list):
        raise TypeError("列表合并的目标必须是列表")
    if not isinstance(数据, (list, tuple, set)):
        raise TypeError("列表合并的数据必须是列表")
    列表.extend(数据)
    return len(列表)


def script_startswith(文本: Any, 前缀: Any) -> bool:
    return _text(文本).startswith(_text(前缀))


def script_endswith(文本: Any, 后缀: Any) -> bool:
    return _text(文本).endswith(_text(后缀))


def script_sort(列表: Any, 反向: Any = False, 依据: Any = None) -> list:
    if not isinstance(列表, (list, tuple, set)):
        raise TypeError("排序的目标必须是列表")
    if 依据 is not None and not callable(依据):
        raise TypeError("排序依据必须是函数或空")
    return sorted(列表, key=依据, reverse=_as_bool(反向, "排序反向"))


def script_round(数值: Any, 位数: Any = 0) -> Any:
    from decimal import ROUND_HALF_UP, Decimal, localcontext

    number = number_parameter(数值, "四舍五入数值")
    places = integer_parameter(位数, "四舍五入位数", minimum=-308, maximum=308)
    decimal = Decimal(str(number))
    with localcontext() as context:
        context.prec = max(
            32,
            len(decimal.as_tuple().digits) + abs(decimal.adjusted()) + abs(places) + 2,
        )
        result = decimal.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    if isinstance(number, int) and places <= 0:
        return int(result)
    rounded = float(result)
    if not math.isfinite(rounded):
        raise ValueError("四舍五入结果超出有限数值范围")
    return rounded
