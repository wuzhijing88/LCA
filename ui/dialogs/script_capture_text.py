# -*- coding: utf-8 -*-
"""把截图、取色、取坐标、拾取元素的结果写回脚本行。"""

from __future__ import annotations

import re
import inspect
from typing import Any, Dict, Optional, Sequence, Tuple

from tasks.script_task import command_name_from_snippet, plan_snippet_insert, source_lines
from utils.app_paths import normalize_workflow_image_path

CAPTURE_SNIPPETS = {
    "image": "找图",
    "color": "找色",
    "coord": "点击",
    "element": "点元素",
    "offset": "点击",
    "region": "区域.设置",
}

_HOSTS = {
    "image": ("找图", "找所有图", "等图", "等图消失", "持续找图"),
    "color": ("找色", "等色", "等色消失"),
    "coord": ("点击", "移动", "拖拽", "滚轮", "按下", "松开", "按住", "连点", "取色", "比色"),
    "element": ("点元素",),
    "offset": ("点击", "找图", "点文字", "点字库", "找色", "等图", "等色", "等图消失", "等色消失"),
    "region": (
        "区域.设置",
        "持续检测",
        "等检测消失",
        "等检测",
        "持续找图",
        "找所有图",
        "等图消失",
        "等文字消失",
        "等字库消失",
        "等色消失",
        "找字库",
        "点字库",
        "等字库",
        "点文字",
        "等文字",
        "等图",
        "等色",
        "找图",
        "找字",
        "找色",
        "检测",
    ),
}

_REGION_AUTO_NAME_RE = re.compile(r'区域\.设置\s*\(\s*(["\'])区域(\d+)\1')


def script_string_literal(value: Any) -> str:
    text = str(value or "").replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def script_image_literal(path: Any) -> str:
    from task_workflow.resource_context import current_images_dir

    return normalize_workflow_image_path(
        str(path or "").strip(),
        images_dir=current_images_dir(),
    )


def build_capture_snippet(kind: str, value: Any) -> str:
    if kind == "image":
        return f"找图({script_string_literal(script_image_literal(value))})"
    if kind == "color":
        return f"找色({script_string_literal(value)})"
    if kind == "coord":
        x, y = _as_xy(value)
        return f"点击({x}, {y})"
    if kind == "element":
        if isinstance(value, dict):
            return f"点元素({_element_arguments(value)})"
        return f"点元素({script_string_literal(value)})"
    if kind == "offset":
        dx, dy = _as_xy(value)
        return f"点击(目标, 偏移x={dx}, 偏移y={dy})"
    if kind == "region":
        left, top, width, height = _as_region(value)
        return f'区域.设置("区域1", {left}, {top}, {width}, {height})'
    raise ValueError(f"未知采集类型: {kind}")


def apply_script_capture(
    source: str, line_index: int, kind: str, value: Any, *, column: Optional[int] = None,
) -> Dict[str, Any]:
    """按当前行改参数；对不上命令就按插入规则写下一条。"""
    lines = source_lines(source)
    safe_index = max(0, min(int(line_index), len(lines) - 1))
    if kind == "region":
        return _apply_region_capture(source, lines, safe_index, value, column=column)
    updated = rewrite_capture_line(lines[safe_index], kind, value, column=column)
    if updated is not None:
        plan = {"mode": "replace", "line": safe_index, "text": updated}
        if kind == "coord":
            found = _find_host_call(lines[safe_index], _HOSTS["coord"], column=column)
            if found is not None and found[0] == "拖拽":
                open_index = found[1]
                close_index = _match_paren(updated, open_index)
                plan["selection"] = _drag_coord_selection(updated, open_index, close_index)
        return plan
    snippet = build_capture_snippet(kind, value)
    if kind == "coord":
        snippet = _coord_snippet_for_line(lines[safe_index], value)
    elif kind == "offset":
        snippet = _offset_snippet_for_line(lines[safe_index], value)
    return plan_snippet_insert(snippet, source, safe_index)


def rewrite_capture_line(
    line: str, kind: str, value: Any, *, column: Optional[int] = None,
) -> Optional[str]:
    names = _HOSTS.get(kind)
    if not names:
        return None
    found = _find_host_call(line, names, column=column)
    if found is None:
        return None
    name, open_index, close_index = found
    inside = line[open_index + 1 : close_index]
    if kind == "coord" and name == "拖拽":
        relative_column = column - open_index - 1 if column is not None else None
        x, y = _as_xy(value)
        rewritten = _rewrite_drag_xy(inside, x, y, relative_column)
    else:
        rewritten = _rewrite_call_args(name, inside, kind, value)
    return f"{line[: open_index + 1]}{rewritten}{line[close_index:]}"


def _rewrite_call_args(name: str, inside: str, kind: str, value: Any) -> str:
    if kind == "image":
        return _append_or_replace_image_arg(inside, script_string_literal(script_image_literal(value)))
    if kind == "color":
        return _set_command_arguments(name, inside, 颜色=script_string_literal(value))
    if kind == "element":
        if isinstance(value, dict):
            _element_arguments(value)
            selectors = {key: script_string_literal(value[key]) if value[key] else "无"
                         for key in ("名称", "自动化ID", "类名")}
            return _set_command_arguments(name, inside, **selectors)
        return _set_command_arguments(name, inside, 名称=script_string_literal(value))
    if kind == "offset":
        dx, dy = _as_xy(value)
        _set_offset_kwargs(inside, int(dx), int(dy))  # 拒绝旧参数名。
        return _set_command_arguments(name, inside, 偏移x=str(dx), 偏移y=str(dy))
    if kind == "region":
        left, top, width, height = _as_region(value)
        if name == "区域.设置":
            args = _split_top_level(inside)
            if not any(_keyword_name(arg) == "名字" for arg in args) and not any(not _is_kwarg(arg) for arg in args):
                raise ValueError("请先填写区域名字，再框选区域")
            return _set_command_arguments(name, inside, x=str(left), y=str(top), 宽=str(width), 高=str(height))
        return _set_command_arguments(name, inside, 区域=f"({left}, {top}, {width}, {height})")
    x, y = _as_xy(value)
    if name == "滚轮":
        return _rewrite_scroll_xy(inside, x, y)
    return _replace_leading_xy(inside, x, y, name=name)


def _element_arguments(selector: dict) -> str:
    if set(selector) != {"名称", "自动化ID", "类名"} or not any(selector.values()):
        raise ValueError("元素采集结果缺少选择条件")
    return ", ".join(f"{key}={script_string_literal(value)}" for key, value in selector.items() if value)


def _rewrite_drag_xy(inside: str, x: int, y: int, column: Optional[int]) -> str:
    """取一次坐标只改拖拽的一端；未指定端点时填写尚未完成的坐标对。"""
    labels = ("x1", "y1", "x2", "y2")
    coords = list(labels)
    spans = {}
    positionals = []
    keywords = {}
    named_coords = False
    search_start = 0
    for arg in _split_top_level(inside):
        start = inside.index(arg, search_start)
        end = start + len(arg)
        search_start = end
        if _is_kwarg(arg):
            key, raw = (part.strip() for part in arg.split("=", 1))
            if key not in {*labels, "模式"}:
                raise ValueError(f"拖拽取坐标不支持参数：{key}")
            if key in keywords:
                raise ValueError(f"拖拽参数重复：{key}")
            keywords[key] = raw
            spans[key] = (start, end)
            named_coords = named_coords or key in labels
        else:
            if keywords:
                raise ValueError("拖拽的位置参数必须写在关键字参数前面")
            positionals.append(arg)
            if len(positionals) <= 4:
                spans[labels[len(positionals) - 1]] = (start, end)
    if len(positionals) > 4:
        raise ValueError("拖拽取坐标只支持四坐标写法：拖拽(x1, y1, x2, y2)")
    if len(positionals) in {1, 2, 3} and not all(_is_xy_token(arg) for arg in positionals):
        raise ValueError("结果起点、终点不能直接改成数字；取坐标请使用四坐标写法：拖拽(x1, y1, x2, y2)")
    for index, raw in enumerate(positionals):
        label = labels[index]
        if label in keywords:
            raise ValueError(f"拖拽参数重复：{label}")
        coords[index] = raw
    for index, label in enumerate(labels):
        if label in keywords:
            coords[index] = keywords[label]

    pair = None
    if column is not None:
        for index, label in enumerate(labels):
            span = spans.get(label)
            if span is not None and span[0] <= column <= span[1]:
                pair = index // 2
                break
    if pair is None:
        for index in (0, 2):
            if any(_is_coord_placeholder(raw) for raw in coords[index:index + 2]):
                pair = index // 2
                break
    if pair is None:
        raise ValueError("拖拽坐标已填写，请先点选起点 x1/y1 或终点 x2/y2，再取坐标")
    coords[pair * 2:pair * 2 + 2] = [str(int(x)), str(int(y))]
    args = [f"{label}={raw}" for label, raw in zip(labels, coords)] if named_coords else coords
    if "模式" in keywords:
        args.append(f'模式={keywords["模式"]}')
    return ", ".join(args)


def _drag_coord_selection(line: str, open_index: int, close_index: int) -> Tuple[int, int]:
    """选中下一项尚未填写的坐标值，不选关键字参数的名称。"""
    inside = line[open_index + 1:close_index]
    search_start = 0
    for arg in _split_top_level(inside):
        start = inside.index(arg, search_start)
        search_start = start + len(arg)
        raw = arg.split("=", 1)[1].strip() if _is_kwarg(arg) else arg
        if raw in {"x1", "y1", "x2", "y2"}:
            value_start = open_index + 1 + start + len(arg) - len(raw)
            return value_start, value_start + len(raw)
    return close_index + 1, close_index + 1


def _is_image_arg_token(token: str) -> bool:
    text = str(token or "").strip()
    if not text or _is_kwarg(text):
        return False
    if text == "图片":
        return True
    return text.startswith(("'", '"')) and len(text) >= 2


def _is_image_placeholder(token: str) -> bool:
    text = str(token or "").strip()
    if text == "图片":
        return True
    if text.startswith(("'", '"')) and len(text) >= 2:
        return text[1:-1] in {"", "图片"}
    return False


def _append_or_replace_image_arg(inside: str, literal: str) -> str:
    args = _split_top_level(inside)
    _validate_capture_args(args)
    if not args:
        return literal
    for index, arg in enumerate(args):
        if _keyword_name(arg) == "图片":
            value = arg.split("=", 1)[1].strip()
            updated = literal if _is_image_placeholder(value) else f"[{value}, {literal}]"
            args[index] = f"图片={updated}"
            return ", ".join(args)
    index = 0
    while index < len(args) and _is_image_arg_token(args[index]):
        index += 1
    images = args[:index]
    rest = args[index:]
    if not images and not _is_kwarg(args[0]):
        # 表达式形式的模板也必须保留，采集的新模板追加在关键字参数之前。
        return ", ".join([args[0], literal, *args[1:]])
    if not images or all(_is_image_placeholder(token) for token in images):
        return ", ".join([literal, *rest])
    if images[-1] == literal:
        return ", ".join([*images, *rest])
    return ", ".join([*images, literal, *rest])


def _set_command_arguments(name: str, inside: str, **values: str) -> str:
    """用运行接口定位参数，位置参数与关键字参数都只改一次。"""
    from task_workflow.script_commands import CommandHost
    from task_workflow.script_sandbox import _RegionApi

    callback = _RegionApi.设置 if name == "区域.设置" else getattr(CommandHost, name)
    signature = inspect.signature(callback)
    positional = [param.name for param in signature.parameters.values()
                  if param.name != "self" and param.kind in
                  {inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD}]
    args = _split_top_level(inside)
    _validate_capture_args(args)
    supplied = [index for index, arg in enumerate(args) if not _is_kwarg(arg)]
    for index, key in enumerate(positional[:len(supplied)]):
        if any(_keyword_name(arg) == key for arg in args):
            raise ValueError(f"参数 {key} 重复，请先修改脚本")
    for key, raw in values.items():
        existing = next((index for index, arg in enumerate(args) if _keyword_name(arg) == key), None)
        if existing is not None:
            args[existing] = f"{key}={raw}"
        elif key in positional and positional.index(key) < len(supplied):
            args[supplied[positional.index(key)]] = raw
        else:
            args.append(f"{key}={raw}")
    return ", ".join(args)


def _coord_snippet_for_line(line: str, value: Any) -> str:
    x, y = _as_xy(value)
    name = command_name_from_snippet(str(line or "").strip())
    if name == "移动":
        return f"移动({x}, {y})"
    if name == "拖拽":
        return f"拖拽({x}, {y}, x2, y2)"
    if name == "滚轮":
        return f"滚轮(x={x}, y={y})"
    return f"点击({x}, {y})"


def _offset_snippet_for_line(line: str, value: Any) -> str:
    dx, dy = _as_xy(value)
    name = command_name_from_snippet(str(line or "").strip())
    if name == "点击":
        return f"点击(目标, 偏移x={dx}, 偏移y={dy})"
    if name in _HOSTS["offset"]:
        return f"{name}(偏移x={dx}, 偏移y={dy})"
    return f"点击(目标, 偏移x={dx}, 偏移y={dy})"


def _region_snippet_for_line(value: Any, source: str = "") -> str:
    left, top, width, height = _as_region(value)
    return f'区域.设置("{_next_auto_region_name(source)}", {left}, {top}, {width}, {height})'


def _apply_region_capture(source: str, lines: Sequence[str], line_index: int, value: Any, *, column=None) -> Dict[str, Any]:
    current = lines[line_index]
    if _find_host_call(current, ("区域.设置",), column=column) is not None:
        updated = rewrite_capture_line(current, "region", value, column=column)
        if updated is not None:
            return {"mode": "replace", "line": line_index, "text": updated}
    found = _find_host_call(current, _HOSTS["region"], column=column)
    if found is not None:
        _name, open_index, close_index = found
        region_name = _named_region_arg(current[open_index + 1 : close_index])
        if region_name:
            set_index = _find_region_set_line(lines, region_name)
            if set_index is not None:
                updated = rewrite_capture_line(lines[set_index], "region", value)
                if updated is not None:
                    return {"mode": "replace", "line": set_index, "text": updated}
        updated = rewrite_capture_line(current, "region", value, column=column)
        if updated is not None:
            return {"mode": "replace", "line": line_index, "text": updated}
    snippet = _region_snippet_for_line(value, source)
    return plan_snippet_insert(snippet, source, line_index)


def _next_auto_region_name(source: str) -> str:
    used = {int(match.group(2)) for match in _REGION_AUTO_NAME_RE.finditer(str(source or ""))}
    index = 1
    while index in used:
        index += 1
    return f"区域{index}"


def _named_region_arg(inside: str) -> Optional[str]:
    for arg in _split_top_level(inside):
        if _keyword_name(arg) != "区域":
            continue
        raw = arg.split("=", 1)[1].strip()
        if len(raw) >= 2 and raw[0] in {'"', "'"} and raw[-1] == raw[0]:
            return raw[1:-1]
    return None


def _find_region_set_line(lines: Sequence[str], name: str) -> Optional[int]:
    matches = []
    for index, line in enumerate(lines):
        found = _find_host_call(line, ("区域.设置",))
        if found is None:
            continue
        _call, open_index, close_index = found
        args = _split_top_level(line[open_index + 1 : close_index])
        if not args:
            continue
        raw = args[0].strip()
        if _keyword_name(raw) == "名字":
            raw = raw.split("=", 1)[1].strip()
        if len(raw) >= 2 and raw[0] in {'"', "'"} and raw[-1] == raw[0] and raw[1:-1] == name:
            matches.append(index)
    if len(matches) > 1:
        raise ValueError("该区域有多处定义，请点选要修改的 区域.设置 再框选")
    return matches[0] if matches else None


def peek_find_image_path(line: str) -> Optional[str]:
    found = _find_host_call(str(line or ""), ("找图",))
    if found is None:
        return None
    _name, open_index, close_index = found
    args = _split_top_level(line[open_index + 1 : close_index])
    if not args:
        return None
    first = args[0]
    if first.startswith(("'", '"')) and len(first) >= 2:
        return first[1:-1]
    return None


def peek_click_coords(line: str) -> Optional[Tuple[int, int]]:
    found = _find_host_call(str(line or ""), ("点击", "移动"))
    if found is None:
        return None
    _name, open_index, close_index = found
    args = _split_top_level(line[open_index + 1 : close_index])
    numbers = [arg for arg in args if _is_int_token(arg)]
    if len(numbers) >= 2:
        return int(numbers[0]), int(numbers[1])
    return None


def _as_region(value: Any) -> Tuple[int, int, int, int]:
    if isinstance(value, (tuple, list)) and len(value) == 4:
        left, top, width, height = map(int, value)
        if width <= 0 or height <= 0:
            raise ValueError("区域宽和高必须大于0")
        return left, top, width, height
    raise ValueError("区域采集结果缺少横坐标、纵坐标、宽、高")


def _replace_leading_xy(inside: str, x: int, y: int, *, name: str) -> str:
    args = _split_top_level(inside)
    _validate_capture_args(args)
    if any(_keyword_name(arg) in {"横坐标", "纵坐标"} for arg in args):
        raise ValueError("坐标参数只接受 x、y，请先修改脚本")
    if name in {"按下", "松开", "按住"} and (
        any(_keyword_name(arg) == "按键" for arg in args)
        or (args and args[0].startswith(('"', "'")))
    ):
        raise ValueError("当前是键盘命令，不能写入鼠标坐标")
    targets = [arg for arg in args if _keyword_name(arg) == "目标"]
    if targets:
        if any(not _is_kwarg(arg) or _keyword_name(arg) in {"x", "y"} for arg in args):
            raise ValueError("目标和坐标不能同时填写，请先修改脚本")
        args = [arg for arg in args if _keyword_name(arg) != "目标"]
    positionals = [arg for arg in args if not _is_kwarg(arg)]
    if len(positionals) == 1:
        args.insert(1, str(y))
    if not positionals and not any(_keyword_name(arg) in {"x", "y"} for arg in args):
        return ", ".join([str(x), str(y), *args])
    return _set_command_arguments(name, ", ".join(args), x=str(x), y=str(y))


def _rewrite_scroll_xy(inside: str, x: int, y: int) -> str:
    args = _split_top_level(inside)
    _validate_capture_args(args)
    if any(_keyword_name(arg) in {"横坐标", "纵坐标"} for arg in args):
        raise ValueError("坐标参数只接受 x、y，请先修改脚本")
    positionals = [arg for arg in args if not _is_kwarg(arg)]
    if len(positionals) == 3 and all(_is_xy_token(arg) for arg in positionals):
        if any(_keyword_name(arg) in {"x", "y"} for arg in args):
            raise ValueError("滚轮坐标重复，请先修改脚本")
        args[1:3] = [str(x), str(y)]
        return ", ".join(args)
    if positionals and not positionals[0].startswith(('"', "'")) and not _is_int_token(positionals[0]):
        # 结果形式改成显式坐标，保留方向、步数和模式。
        args = [f"{key}={raw}" for key, raw in zip(("方向", "步数"), positionals[1:])] + [arg for arg in args if _is_kwarg(arg)]
    args = [arg for arg in args if _keyword_name(arg) != "目标"]
    return _set_coord_kwargs(", ".join(args), x, y)


def _set_offset_kwargs(inside: str, dx: int, dy: int) -> str:
    args = _split_top_level(inside)
    if any(arg.split("=", 1)[0].strip() in {"偏移横坐标", "偏移纵坐标"} for arg in args if _is_kwarg(arg)):
        raise ValueError("偏移参数只接受 偏移x、偏移y，请先修改脚本")
    return _set_kwargs(inside, 偏移x=str(dx), 偏移y=str(dy))


def _set_kwargs(inside: str, **kwargs: str) -> str:
    args = _split_top_level(inside)
    _validate_capture_args(args)
    for key, raw in kwargs.items():
        prefix = f"{key}="
        replaced = False
        for index, arg in enumerate(args):
            if _keyword_name(arg) == key:
                args[index] = f"{prefix}{raw}"
                replaced = True
                break
        if not replaced:
            args.append(f"{prefix}{raw}")
    return ", ".join(args)


def _set_coord_kwargs(inside: str, x: int, y: int) -> str:
    args = _split_top_level(inside)
    if any(arg.split("=", 1)[0].strip() in {"横坐标", "纵坐标"} for arg in args if _is_kwarg(arg)):
        raise ValueError("坐标参数只接受 x、y，请先修改脚本")
    return _set_kwargs(inside, x=str(x), y=str(y))


def _find_host_call(
    line: str, names: Sequence[str], *, column: Optional[int] = None,
) -> Optional[Tuple[str, int, int]]:
    index = 0
    quote = None
    escape = False
    first = None
    selected = None
    while index < len(line):
        char = line[index]
        if quote:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == quote:
                quote = None
            index += 1
            continue
        if char in {'"', "'"}:
            quote = char
            index += 1
            continue
        if char == "#":
            break
        for name in names:
            if not line.startswith(name, index):
                continue
            if index > 0 and (_is_ident_char(line[index - 1]) or line[index - 1] == "."):
                continue
            cursor = index + len(name)
            while cursor < len(line) and line[cursor].isspace():
                cursor += 1
            if cursor >= len(line) or line[cursor] != "(":
                continue
            close = _match_paren(line, cursor)
            if close is not None:
                found = (name, cursor, close)
                if column is None:
                    return found
                if index <= column <= close + 1:
                    selected = found
                if first is None:
                    first = found
        index += 1
    return selected or first


def _match_paren(text: str, open_index: int) -> Optional[int]:
    depth = 0
    quote = None
    escape = False
    for index in range(open_index, len(text)):
        char = text[index]
        if quote:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == quote:
                quote = None
            continue
        if char in {'"', "'"}:
            quote = char
            continue
        if char == "(":
            depth += 1
            continue
        if char == ")":
            depth -= 1
            if depth == 0:
                return index
    return None


def _split_top_level(text: str) -> list:
    args = []
    buf = []
    depth = 0
    quote = None
    escape = False
    for char in str(text or ""):
        if quote:
            buf.append(char)
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == quote:
                quote = None
            continue
        if char in {'"', "'"}:
            quote = char
            buf.append(char)
            continue
        if char in "([{":
            depth += 1
            buf.append(char)
            continue
        if char in ")]}":
            depth = max(0, depth - 1)
            buf.append(char)
            continue
        if char == "," and depth == 0:
            token = "".join(buf).strip()
            if token:
                args.append(token)
            buf = []
            continue
        buf.append(char)
    token = "".join(buf).strip()
    if token:
        args.append(token)
    return args


def _is_int_token(token: str) -> bool:
    text = str(token or "").strip()
    if text.startswith(("+", "-")):
        text = text[1:]
    return bool(text) and text.isdigit()


def _is_coord_placeholder(token: str) -> bool:
    return str(token or "").strip() in {
        "x",
        "y",
        "x1",
        "y1",
        "x2",
        "y2",
    }


def _is_xy_token(token: str) -> bool:
    return _is_int_token(token) or _is_coord_placeholder(token)


def _is_kwarg(token: str) -> bool:
    return bool(_keyword_name(token))


def _keyword_name(token: str) -> str:
    match = re.match(r"^\s*([^\W\d]\w*)\s*=(?!=)", str(token or ""))
    return match.group(1) if match else ""


def _validate_capture_args(args: list) -> None:
    keywords = set()
    for arg in args:
        key = _keyword_name(arg)
        if key:
            if key in keywords:
                raise ValueError(f"参数 {key} 重复，请先修改脚本")
            keywords.add(key)
        elif keywords:
            raise ValueError("位置参数不能写在关键字参数后面，请先修改脚本")


def _is_ident_char(char: str) -> bool:
    return char.isalnum() or char == "_" or ("\u4e00" <= char <= "\u9fff")


def _as_xy(value: Any) -> Tuple[int, int]:
    if isinstance(value, (tuple, list)) and len(value) == 2:
        return int(value[0]), int(value[1])
    raise ValueError("坐标采集结果缺少横坐标、纵坐标")
