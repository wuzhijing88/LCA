# -*- coding: utf-8 -*-
"""自定义脚本输入时的参数格式提示，类似 IDE 签名帮助。"""

from __future__ import annotations

import html
from typing import Any, Dict, List, Optional, Sequence, Tuple

from tasks.script_task import catalog_snippet, iter_script_insert_items

KEYWORD_HINTS = {
    "如果": {
        "overloads": (("条件",),),
        "display": ("如果 条件:",),
        "note": "条件成立时执行缩进里的命令。",
    },
    "否则如果": {
        "overloads": (("条件",),),
        "display": ("否则如果 条件:",),
        "note": "上一个条件不成立时再判断。",
    },
    "否则": {
        "overloads": ((),),
        "display": ("否则:",),
        "note": "前面的条件都不成立时执行。",
    },
    "循环": {
        "overloads": (("次数",),),
        "display": ("循环 i 在 范围(次数):",),
        "note": "按次数重复。",
    },
    "当": {
        "overloads": (("条件",),),
        "display": ("当 条件:",),
        "note": "条件成立就继续。",
    },
    "中断": {
        "overloads": ((),),
        "display": ("中断",),
        "note": "立刻跳出当前循环。",
    },
    "继续": {
        "overloads": ((),),
        "display": ("继续",),
        "note": "跳过本轮，进入下一轮循环。",
    },
    "子程序": {
        "overloads": (("名字",),),
        "display": ("子程序 点确定():",),
        "note": "定义一段可复用命令，里面可以用 返回。",
    },
    "函数": {
        "overloads": (("名字",),),
        "display": ("函数 点确定():",),
        "note": "和 子程序 相同。",
    },
    "if": {
        "overloads": (("条件",),),
        "display": ("if 条件:",),
        "note": "条件成立时执行缩进里的命令。",
    },
    "elif": {
        "overloads": (("条件",),),
        "display": ("elif 条件:",),
        "note": "上一个条件不成立时再判断。",
    },
    "else": {
        "overloads": ((),),
        "display": ("else:",),
        "note": "前面的条件都不成立时执行。",
    },
    "for": {
        "overloads": (("次数",),),
        "display": ("for i in range(次数):",),
        "note": "按次数重复。",
    },
    "while": {
        "overloads": (("条件",),),
        "display": ("while 条件:",),
        "note": "条件成立就继续。",
    },
}

_FIELD_HINTS = {
    "上次": "上次.通过  上次.成功  上次.分数  上次.阈值  上次.x  上次.y",
    "文字": "文字.内容  文字.通过",
    "找图": "找图.分数  找图.路径  找图.x  找图.y  找图.通过",
    "检测": "检测.类别  检测.分数  检测.列表  检测.x  检测.y  检测.宽  检测.高  检测.点()  检测.随机点()  持续检测(模型)  停止检测()",
    "卡片": "卡片[编号].内容  卡片[编号].分数  卡片[编号].通过",
    "剪贴板": "剪贴板.获取()  剪贴板.设置(文本)",
    "窗口": "窗口.宽  窗口.高",
}

_BUILTIN_HINTS = {
    "长度": (("对象",),),
    "整数": (("值",),),
    "小数": (("值",),),
    "到文本": (("值",),),
    "真假": (("值",),),
    "最小": (("值1", "值2"),),
    "最大": (("值1", "值2"),),
    "绝对值": (("值",),),
    "开方": (("值",),),
    "平方根": (("值",),),
    "角度": (("点1", "点2"), ("x1", "y1", "x2", "y2")),
    "正弦": (("角度",),),
    "余弦": (("角度",),),
    "限制": (("值", "下限", "上限"),),
    "范围": (("次数",), ("起点", "终点"), ("起点", "终点", "步长")),
    "随机": ((), ("次数",), ("起点", "终点")),
    "包含": (("文本", "片段"),),
    "截取": (("文本", "起点", "字数"),),
    "替换": (("文本", "旧", "新"),),
    "分割": (("文本", "分隔符"),),
    "时间": ((),),
    "去空格": (("文本",),),
    "查找": (("文本", "片段"),),
    "提取数字": (("文本",),),
    "持续检测": (("模型", "间隔=0.3"), ("模型", '类别="敌人"', "间隔=0.3", "阈值=0.5")),
    "停止检测": ((),),
    "持续找图": (("图片", "间隔=0.3"),),
    "停止找图": ((),),
    "多线程": (("按W",),),
    "关闭线程": ((), ("按W",)),
    "len": (("对象",),),
    "int": (("值",),),
    "float": (("值",),),
    "str": (("值",),),
    "bool": (("值",),),
    "min": (("值1", "值2"),),
    "max": (("值1", "值2"),),
    "abs": (("值",),),
    "range": (("次数",), ("起点", "终点"), ("起点", "终点", "步长")),
}

_CALL_INSERT_NAMES = frozenset(
    {
        "找图",
        "点击",
        "移动",
        "按键",
        "输入",
        "延时",
        "找字",
        "找字库",
        "等字库",
        "等字库消失",
        "点字库",
        "检测",
        "框内点",
        "随机点",
        "距离",
        "角度",
        "找色",
        "拖拽",
        "滚轮",
        "点文字",
        "点元素",
        "等图",
        "等色",
        "等文字",
        "等图消失",
        "等色消失",
        "等文字消失",
        "等检测",
        "等检测消失",
        "持续检测",
        "停止检测",
        "持续找图",
        "停止找图",
        "多线程",
        "关闭线程",
        "找所有图",
        "取色",
        "比色",
        "按下",
        "松开",
        "按住",
        "连点",
        "相对移动",
        "鼠标位置",
        "等毫秒",
        "激活",
        "播放",
        "停止播放",
        "记录",
        "成功",
        "失败",
        "变量.获取",
        "变量.设置",
        "变量.增加",
        "长度",
        "整数",
        "小数",
        "到文本",
        "真假",
        "时间",
        "去空格",
        "查找",
        "提取数字",
        "最小",
        "最大",
        "绝对值",
        "开方",
        "平方根",
        "正弦",
        "余弦",
        "限制",
        "范围",
        "len",
        "int",
        "float",
        "str",
        "bool",
        "min",
        "max",
        "abs",
        "range",
    }
)
_KEYWORD_INSERTS = {
    "如果": "如果 条件:",
    "否则如果": "否则如果 条件:",
    "否则": "否则:",
    "循环": "循环 i 在 范围(次数):",
    "当": "当 条件:",
    "中断": "中断",
    "继续": "继续",
    "if": "if 条件:",
    "elif": "elif 条件:",
    "else": "else:",
    "for": "for i in range(次数):",
    "while": "while 条件:",
}


def _normalize_overloads(params: Any) -> Tuple[Tuple[str, ...], ...]:
    if not params:
        return ((),)
    first = params[0]
    if isinstance(first, (tuple, list)):
        return tuple(tuple(str(part) for part in item) for item in params)
    return (tuple(str(part) for part in params),)


def script_hint_catalog() -> Dict[str, Dict[str, Any]]:
    catalog: Dict[str, Dict[str, Any]] = {}
    for item in iter_script_insert_items():
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        catalog[name] = {
            "overloads": _normalize_overloads(item.get("params")),
            "display": (str(item.get("signature") or name),),
            "note": str(item.get("note") or "").strip(),
        }
    for name, spec in KEYWORD_HINTS.items():
        catalog.setdefault(name, spec)
    for name, overloads in _BUILTIN_HINTS.items():
        catalog.setdefault(
            name,
            {
                "overloads": overloads,
                "display": (f"{name}({', '.join(overloads[0])})",),
                "note": "",
            },
        )
    return catalog


def completion_insert_text(name: str) -> str:
    token = str(name or "").strip()
    snippet = catalog_snippet(token)
    if snippet:
        return snippet
    if token in _KEYWORD_INSERTS:
        return _KEYWORD_INSERTS[token]
    if token in _CALL_INSERT_NAMES:
        return f"{token}("
    return token


def _is_name_char(char: str) -> bool:
    return bool(char) and (char.isalnum() or char in "._" or "\u4e00" <= char <= "\u9fff")


def _read_name_before(line: str, index: int) -> str:
    cursor = index
    while cursor > 0 and line[cursor - 1].isspace():
        cursor -= 1
    end = cursor
    while cursor > 0 and _is_name_char(line[cursor - 1]):
        cursor -= 1
    return line[cursor:end]


def _skip_string(line: str, start: int) -> int:
    quote = line[start]
    index = start + 1
    while index < len(line):
        char = line[index]
        if char == "\\" and index + 1 < len(line):
            index += 2
            continue
        if char == quote:
            return index + 1
        index += 1
    return len(line)


def find_call_at(line: str, column: int) -> Optional[Dict[str, Any]]:
    text = str(line or "")
    limit = max(0, min(int(column), len(text)))
    stack: List[Dict[str, Any]] = []
    index = 0
    while index < limit:
        char = text[index]
        if char in {'"', "'"}:
            index = _skip_string(text, index)
            continue
        if char == "(":
            stack.append({"name": _read_name_before(text, index), "args": 0, "arg_start": index + 1})
            index += 1
            continue
        if char == ")" and stack:
            stack.pop()
            index += 1
            continue
        if stack and char == ",":
            stack[-1]["args"] += 1
            stack[-1]["arg_start"] = index + 1
        index += 1
    for current in reversed(stack):
        name = str(current.get("name") or "").strip()
        if name:
            return {
                "name": name,
                "arg_index": int(current.get("args") or 0),
                "arg_start": int(current.get("arg_start") or 0),
            }
    return None


def _keyword_at(line: str, column: int) -> str:
    text = str(line or "")
    stripped = text.lstrip()
    if not stripped:
        return ""
    indent = len(text) - len(stripped)
    if int(column) < indent:
        return ""
    end = 0
    while end < len(stripped) and _is_name_char(stripped[end]) and stripped[end] not in ".":
        end += 1
    word = stripped[:end]
    if word not in KEYWORD_HINTS:
        return ""
    return word


def _field_root_at(line: str, column: int) -> str:
    text = str(line or "")
    limit = max(0, min(int(column), len(text)))
    start = limit
    while start > 0 and _is_name_char(text[start - 1]):
        start -= 1
    token = text[start:limit]
    if "." not in token:
        return ""
    root = token.split(".", 1)[0]
    return root if root in _FIELD_HINTS else ""


def _pick_overload(overloads: Sequence[Sequence[str]], arg_index: int) -> Tuple[str, ...]:
    items = [tuple(item) for item in overloads] or [()]
    for item in items:
        if arg_index < len(item) or (not item and arg_index == 0):
            return item
    return items[-1]


def format_overload(name: str, params: Sequence[str], active: int) -> str:
    if name in KEYWORD_HINTS:
        display = KEYWORD_HINTS[name]["display"][0]
        if params and 0 <= active < len(params):
            token = html.escape(params[active])
            return html.escape(display).replace(token, f"<b>{token}</b>", 1)
        return html.escape(display)
    if not params:
        return html.escape(f"{name}()")
    parts = []
    for index, param in enumerate(params):
        escaped = html.escape(param)
        if index == active:
            parts.append(f"<b>{escaped}</b>")
        else:
            parts.append(escaped)
    return html.escape(name) + "(" + ", ".join(parts) + ")"


def resolve_script_hint(line: str, column: int) -> Optional[Dict[str, Any]]:
    catalog = script_hint_catalog()
    call = find_call_at(line, column)
    if call and call["name"] in catalog:
        name = call["name"]
        arg_index = int(call["arg_index"])
        spec = catalog[name]
        overload = _pick_overload(spec.get("overloads") or ((),), arg_index)
        active = arg_index if overload and arg_index < len(overload) else -1
        return {
            "name": name,
            "kind": "call",
            "overloads": spec.get("overloads") or ((),),
            "active_overload": overload,
            "active": active,
            "note": str(spec.get("note") or ""),
        }
    field_root = _field_root_at(line, column)
    if field_root:
        return {
            "name": field_root,
            "kind": "field",
            "overloads": ((_FIELD_HINTS[field_root],),),
            "active_overload": (_FIELD_HINTS[field_root],),
            "active": 0,
            "note": "",
        }
    keyword = _keyword_at(line, column)
    if keyword:
        spec = catalog[keyword]
        overload = tuple((spec.get("overloads") or (("条件",),))[0])
        return {
            "name": keyword,
            "kind": "keyword",
            "overloads": spec.get("overloads") or (overload,),
            "active_overload": overload,
            "active": 0 if overload else -1,
            "note": str(spec.get("note") or ""),
        }
    return None


EMPTY_PARAM_LABEL = "（不写参数）"
_PARAM_VALUE_CHOICES = {
    "点击": ("点击=假", "点击=真"),
    "双击": ("双击=假", "双击=真"),
    "键": ('键="左键"', '键="右键"'),
    "方向": ('方向="向下"', '方向="向上"'),
}


def _param_key(param: str) -> str:
    return str(param or "").split("=", 1)[0].strip()


def parameter_choices(line: str, column: int) -> List[str]:
    call = find_call_at(line, column)
    if not call:
        return []
    spec = script_hint_catalog().get(call["name"])
    if not spec:
        return []
    arg_index = int(call["arg_index"])
    items: List[str] = []
    seen = set()

    def add(label: str) -> None:
        text = str(label or "")
        if text and text not in seen:
            seen.add(text)
            items.append(text)

    overloads = [tuple(item) for item in (spec.get("overloads") or ((),))]
    if arg_index == 0 and any(not item for item in overloads):
        add(EMPTY_PARAM_LABEL)
    for overload in overloads:
        if arg_index >= len(overload):
            continue
        remaining = overload[arg_index:]
        add(remaining[0])
        if len(remaining) > 1:
            add(", ".join(remaining))
        for extra in _PARAM_VALUE_CHOICES.get(_param_key(remaining[0]), ()):
            add(extra)
    return items


def format_script_hint_html(hint: Optional[Dict[str, Any]]) -> str:
    if not hint:
        return ""
    name = str(hint.get("name") or "")
    active_overload = tuple(hint.get("active_overload") or ())
    active = int(hint.get("active") if hint.get("active") is not None else -1)
    overloads = [tuple(item) for item in (hint.get("overloads") or (active_overload,))]
    lines = []
    if hint.get("kind") == "field":
        lines.append(html.escape(active_overload[0] if active_overload else name))
    elif hint.get("kind") == "keyword":
        lines.append(format_overload(name, active_overload, active))
    else:
        for item in overloads:
            if item == active_overload:
                lines.append(format_overload(name, item, active))
            else:
                lines.append(
                    '<span style="opacity:0.55">' + format_overload(name, item, -1) + "</span>"
                )
    note = str(hint.get("note") or "").strip()
    if note:
        lines.append(f'<div style="margin-top:4px;opacity:0.72">{html.escape(note)}</div>')
    return "".join(f"<div>{line}</div>" for line in lines)
