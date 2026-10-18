# -*- coding: utf-8 -*-
"""自定义脚本输入时的参数格式提示，类似 IDE 签名帮助。"""

from __future__ import annotations

import html
from typing import Any, Dict, List, Optional, Sequence, Tuple

from tasks.script_task import catalog_snippet, iter_script_insert_items, script_catalog_call_paths

_KEYWORD_NAMES = frozenset({"如果", "否则如果", "否则", "循环", "当", "中断", "继续", "子程序", "函数", "返回", "略过", "导入", "从", "作为", "尝试", "捕获", "最终", "抛出", "匿名", "使用", "就是"})
KEYWORD_HINTS = {item["name"]: {"display": (item["signature"],)}
                 for item in iter_script_insert_items() if item["name"] in _KEYWORD_NAMES}

_FIELD_HINTS = {
    "上次": "上次.通过  上次.成功  上次.分数  上次.阈值  上次.x  上次.y",
    "文字": "文字.内容  文字.通过",
    "找图": "找图.分数  找图.路径  找图.x  找图.y  找图.通过",
    "检测": "检测.类别  检测.分数  检测.列表  检测.x  检测.y  检测.宽  检测.高  检测.点()  检测.随机点()  持续检测(模型)  停止检测()",
    "卡片": "卡片[编号].内容  卡片[编号].分数  卡片[编号].通过",
    "剪贴板": "剪贴板.获取()  剪贴板.设置(文本)",
    "窗口": "窗口.宽  窗口.高  窗口.设置分辨率(宽, 高)  窗口.兼容性()  结果.DirectX  结果.OpenGL  结果.窗口管理员  结果.截图诊断",
    "组件": "组件.加载()  组件.调用()  组件.读取()  组件.写入()  组件.运行()  组件.关闭()",
    "色": "色.颜色  色.红  色.绿  色.蓝  色.x  色.y  色.通过",
    "结果": "结果.通过  结果.x  结果.y  结果.宽  结果.高  结果.分数  结果.类别  结果.内容  结果.列表  结果.截断",
    "变量": "变量.获取(名字, 默认值)  变量.设置(名字, 值)  变量.增加(名字, 步长)  变量.存在(名字)  变量.删除(名字)  变量.全局获取(名字, 默认值)  变量.全局设置(名字, 值)  变量.全局增加(名字, 步长)  变量.全局存在(名字)  变量.全局删除(名字)",
    "数据": "数据.读取(文件名, 默认值)  数据.写入(文件名, 内容)  数据.JSON读取(文件名, 默认值)  数据.JSON写入(文件名, 对象)  数据.INI读取(文件名, 节, 键)  数据.INI写入(文件名, 节, 键, 值)  数据.CSV读取(文件名)  数据.SQLite查询(文件名, SQL)  数据.存在(文件名)  数据.删除(文件名)",
    "性能": "性能.快照()  性能.快照().rss_mb  性能.快照().cpu_percent  性能.快照().script_threads",
}

_CALL_INSERT_NAMES = frozenset(script_catalog_call_paths(include_result_methods=False))


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
    return catalog


def completion_insert_text(name: str) -> str:
    token = str(name or "").strip()
    snippet = catalog_snippet(token)
    if snippet:
        return snippet
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
