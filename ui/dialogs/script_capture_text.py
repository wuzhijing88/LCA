# -*- coding: utf-8 -*-
"""把截图、取色、取坐标、拾取元素的结果写回脚本行。"""

from __future__ import annotations

from typing import Any, Dict, Optional, Sequence, Tuple

from tasks.script_task import command_name_from_snippet, plan_snippet_insert
from utils.app_paths import normalize_workflow_image_path

CAPTURE_SNIPPETS = {
    "image": "找图",
    "color": "找色",
    "coord": "点击",
    "element": "点元素",
    "offset": "点击",
    "region": "找图",
}

_HOSTS = {
    "image": ("找图",),
    "color": ("找色",),
    "coord": ("点击", "移动", "拖拽", "滚轮"),
    "element": ("点元素",),
    "offset": ("点击", "找图", "点文字", "找色", "检测"),
    "region": ("找图", "找字", "找字库", "找色", "检测", "点文字", "点字库", "等图", "等文字", "等字库"),
}


def script_string_literal(value: Any) -> str:
    text = str(value or "").replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def script_image_literal(path: Any) -> str:
    return normalize_workflow_image_path(str(path or "").strip())


def build_capture_snippet(kind: str, value: Any) -> str:
    if kind == "image":
        return f"找图({script_string_literal(script_image_literal(value))})"
    if kind == "color":
        return f"找色({script_string_literal(value)})"
    if kind == "coord":
        x, y = _as_xy(value)
        return f"点击({x}, {y})"
    if kind == "element":
        return f"点元素({script_string_literal(value)})"
    if kind == "offset":
        dx, dy = _as_xy(value)
        return f"点击(目标, 偏移x={dx}, 偏移y={dy})"
    if kind == "region":
        left, top, width, height = _as_region(value)
        return f"找图(图片, 区域=({left}, {top}, {width}, {height}))"
    raise ValueError(f"未知采集类型: {kind}")


def apply_script_capture(source: str, line_index: int, kind: str, value: Any) -> Dict[str, Any]:
    """按当前行改参数；对不上命令就按插入规则写下一条。"""
    lines = str(source or "").splitlines() or [""]
    safe_index = max(0, min(int(line_index), len(lines) - 1))
    updated = rewrite_capture_line(lines[safe_index], kind, value)
    if updated is not None:
        return {"mode": "replace", "line": safe_index, "text": updated}
    snippet = build_capture_snippet(kind, value)
    if kind == "coord":
        snippet = _coord_snippet_for_line(lines[safe_index], value)
    elif kind == "offset":
        snippet = _offset_snippet_for_line(lines[safe_index], value)
    elif kind == "region":
        snippet = _region_snippet_for_line(lines[safe_index], value)
    return plan_snippet_insert(snippet, source, safe_index)


def rewrite_capture_line(line: str, kind: str, value: Any) -> Optional[str]:
    names = _HOSTS.get(kind)
    if not names:
        return None
    found = _find_host_call(line, names)
    if found is None:
        return None
    name, open_index, close_index = found
    inside = line[open_index + 1 : close_index]
    rewritten = _rewrite_call_args(name, inside, kind, value)
    return f"{line[: open_index + 1]}{rewritten}{line[close_index:]}"


def _rewrite_call_args(name: str, inside: str, kind: str, value: Any) -> str:
    if kind == "image":
        return _append_or_replace_image_arg(inside, script_string_literal(script_image_literal(value)))
    if kind == "color":
        return _replace_first_value(inside, script_string_literal(value))
    if kind == "element":
        return _replace_first_value(inside, script_string_literal(value))
    if kind == "offset":
        dx, dy = _as_xy(value)
        return _set_offset_kwargs(inside, int(dx), int(dy))
    if kind == "region":
        left, top, width, height = _as_region(value)
        return _set_kwargs(inside, 区域=f"({left}, {top}, {width}, {height})")
    x, y = _as_xy(value)
    if name == "滚轮":
        return _set_coord_kwargs(inside, x, y)
    return _replace_leading_xy(inside, x, y, pairs=1)


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
    if not args:
        return literal
    index = 0
    while index < len(args) and _is_image_arg_token(args[index]):
        index += 1
    images = args[:index]
    rest = args[index:]
    if not images or all(_is_image_placeholder(token) for token in images):
        return ", ".join([literal, *rest])
    if images[-1] == literal:
        return ", ".join([*images, *rest])
    return ", ".join([*images, literal, *rest])


def _replace_first_value(inside: str, literal: str) -> str:
    args = _split_top_level(inside)
    if not args:
        return literal
    first = args[0]
    if "=" in first and not first.lstrip().startswith(("'", '"', "(")):
        return ", ".join([literal, *args])
    args[0] = literal
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


def _region_snippet_for_line(line: str, value: Any) -> str:
    left, top, width, height = _as_region(value)
    region = f"区域=({left}, {top}, {width}, {height})"
    found = _find_host_call(str(line or ""), _HOSTS["region"])
    name = found[0] if found else command_name_from_snippet(str(line or "").strip())
    if name == "找图":
        return f"找图(图片, {region})"
    if name == "点文字":
        return f"点文字(目标, {region})"
    if name == "找色":
        return f"找色(颜色, {region})"
    if name == "检测":
        return f"检测({region})"
    if name in _HOSTS["region"]:
        return f"{name}({region})"
    return f"找图(图片, {region})"


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
    if isinstance(value, (tuple, list)) and len(value) >= 4:
        return int(value[0]), int(value[1]), int(value[2]), int(value[3])
    raise ValueError("区域采集结果缺少横坐标、纵坐标、宽、高")


def _replace_leading_xy(inside: str, x: int, y: int, pairs: int = 1) -> str:
    args = _split_top_level(inside)
    need = max(1, int(pairs)) * 2
    if args and not _is_xy_token(args[0]) and not _is_kwarg(args[0]):
        kwargs = [arg for arg in args if _is_kwarg(arg)]
        return ", ".join([str(int(x)), str(int(y)), *kwargs])
    taken = 0
    while args and taken < need and _is_xy_token(args[0]):
        args.pop(0)
        taken += 1
    return ", ".join([str(int(x)), str(int(y)), *args])


def _set_offset_kwargs(inside: str, dx: int, dy: int) -> str:
    args = _split_top_level(inside)
    pairs = (("偏移x", "偏移横坐标", str(int(dx))), ("偏移y", "偏移纵坐标", str(int(dy))))
    for new_key, old_key, raw in pairs:
        replaced = False
        for index, arg in enumerate(args):
            if arg.startswith(f"{new_key}=") or arg.startswith(f"{old_key}="):
                args[index] = f"{new_key}={raw}"
                replaced = True
                break
        if not replaced:
            args.append(f"{new_key}={raw}")
    return ", ".join(args)


def _set_kwargs(inside: str, **kwargs: str) -> str:
    args = _split_top_level(inside)
    for key, raw in kwargs.items():
        prefix = f"{key}="
        replaced = False
        for index, arg in enumerate(args):
            if arg.startswith(prefix):
                args[index] = f"{prefix}{raw}"
                replaced = True
                break
        if not replaced:
            args.append(f"{prefix}{raw}")
    return ", ".join(args)


def _set_coord_kwargs(inside: str, x: int, y: int) -> str:
    args = _split_top_level(inside)
    pairs = (("横坐标", "x", str(int(x))), ("纵坐标", "y", str(int(y))))
    for chinese, english, raw in pairs:
        replaced = False
        for index, arg in enumerate(args):
            if arg.startswith(f"{chinese}=") or arg.startswith(f"{english}="):
                key = chinese if arg.startswith(f"{chinese}=") else english
                args[index] = f"{key}={raw}"
                replaced = True
                break
        if not replaced:
            args.append(f"{english}={raw}")
    return ", ".join(args)


def _find_host_call(line: str, names: Sequence[str]) -> Optional[Tuple[str, int, int]]:
    index = 0
    quote = None
    escape = False
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
        for name in names:
            if not line.startswith(name, index):
                continue
            if index > 0 and _is_ident_char(line[index - 1]):
                continue
            cursor = index + len(name)
            while cursor < len(line) and line[cursor].isspace():
                cursor += 1
            if cursor >= len(line) or line[cursor] != "(":
                continue
            close = _match_paren(line, cursor)
            if close is not None:
                return name, cursor, close
        index += 1
    return None


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
        "横坐标",
        "纵坐标",
        "起点横坐标",
        "起点纵坐标",
        "终点横坐标",
        "终点纵坐标",
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
    text = str(token or "").strip()
    return "=" in text and not text.startswith(("'", '"', "("))


def _is_ident_char(char: str) -> bool:
    return char.isalnum() or char == "_" or ("\u4e00" <= char <= "\u9fff")


def _as_xy(value: Any) -> Tuple[int, int]:
    if isinstance(value, (tuple, list)) and len(value) >= 2:
        return int(value[0]), int(value[1])
    raise ValueError("坐标采集结果缺少横坐标、纵坐标")
