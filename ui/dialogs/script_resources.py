# -*- coding: utf-8 -*-
"""自定义脚本卡片的资源栏：导入文件、改路径、插入命令。"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional, Tuple

from task_workflow.script_resources import (
    AUDIO_EXTS,
    COMPONENT_EXTS,
    IMAGE_EXTS,
    MODEL_EXTS,
    _is_module_offset_literal,
    enclosing_call_name,
    card_filename_prefixes,
    constrain_script_path,
    delete_resource_file,
    extract_string_literals,
    import_resource_file,
    is_allowed_script_path,
    is_managed_resource_file,
    list_card_files,
    list_script_resources,
    rename_resource_file,
    replace_resource_file,
    resolve_resource_path,
    resource_kind,
    rewrite_resource_literal,
    script_path_for_file,
    script_resource_roots,
)
from tasks.script_task import command_name_from_snippet, plan_snippet_insert, source_lines
from ui.dialogs.script_capture_text import apply_script_capture, script_string_literal

_MODEL_HOSTS = ("检测", "持续检测", "等检测", "等检测消失")
_AUDIO_HOSTS = ("播放",)
_REPLAY_HOSTS = ("回放",)
_COMPONENT_HOSTS = ("组件.加载", "组件.运行", "进程.启动", "进程.关闭")
_IMAGE_REWRITE_HOSTS = ("等图", "等图消失", "持续找图", "找所有图")
_DICT_HOSTS = ("找字库", "点字库", "等字库", "等字库消失")
_DM_ADDR_HOSTS = (
    "大漠内存.模块基址",
    "大漠内存.模块大小",
    "大漠内存.读取整数",
    "大漠内存.读取单精度",
    "大漠内存.读取双精度",
    "大漠内存.读取文本",
    "大漠内存.读取数据",
    "大漠内存.写入整数",
    "大漠内存.写入单精度",
    "大漠内存.写入双精度",
    "大漠内存.写入文本",
    "大漠内存.写入数据",
    "大漠内存.申请",
    "大漠内存.释放",
    "大漠汇编.基址调用",
)

__all__ = [
    "AUDIO_EXTS",
    "COMPONENT_EXTS",
    "IMAGE_EXTS",
    "MODEL_EXTS",
    "card_filename_prefixes",
    "constrain_script_path",
    "delete_resource_file",
    "extract_string_literals",
    "import_resource_file",
    "is_allowed_script_path",
    "is_managed_resource_file",
    "list_card_files",
    "list_script_resources",
    "plan_insert_resource",
    "rename_resource_file",
    "replace_resource_file",
    "resolve_resource_path",
    "resource_kind",
    "rewrite_resource_literal",
    "script_path_for_file",
    "script_resource_roots",
]


def _rewrite_model_arg(line: str, literal: str) -> Optional[str]:
    from ui.dialogs.script_capture_text import _find_host_call, _split_top_level

    found = _find_host_call(str(line or ""), _MODEL_HOSTS)
    if found is None:
        return None
    _name, open_index, close_index = found
    args = _split_top_level(line[open_index + 1 : close_index])
    if not args:
        inside = literal
    else:
        first = args[0]
        if first.split("=", 1)[0].strip() in {"模型"} or resource_kind(first.strip().strip("'\"")) == "model" or first in {"模型", '""', "''"}:
            args[0] = literal
        elif first.startswith(("'", '"')) or first == "模型":
            args[0] = literal
        else:
            args.insert(0, literal)
        inside = ", ".join(args)
    return f"{line[: open_index + 1]}{inside}{line[close_index:]}"


def _rewrite_audio_arg(line: str, literal: str) -> Optional[str]:
    from ui.dialogs.script_capture_text import _find_host_call, _split_top_level

    found = _find_host_call(str(line or ""), _AUDIO_HOSTS)
    if found is None:
        return None
    _name, open_index, close_index = found
    args = _split_top_level(line[open_index + 1 : close_index])
    if not args:
        inside = literal
    else:
        first = args[0]
        key = first.split("=", 1)[0].strip()
        if key == "文件":
            args[0] = f"文件={literal}" if "=" in first else literal
        elif first.startswith(("'", '"')) or first in {"文件", '""', "''"} or resource_kind(first.strip().strip("'\"")) == "audio":
            args[0] = literal
        else:
            args.insert(0, literal)
        inside = ", ".join(args)
    return f"{line[: open_index + 1]}{inside}{line[close_index:]}"


def _rewrite_replay_arg(line: str, literal: str) -> Optional[str]:
    from ui.dialogs.script_capture_text import _find_host_call, _split_top_level

    found = _find_host_call(str(line or ""), _REPLAY_HOSTS)
    if found is None:
        return None
    _name, open_index, close_index = found
    args = _split_top_level(line[open_index + 1 : close_index])
    if not args:
        inside = literal
    else:
        first = args[0]
        key = first.split("=", 1)[0].strip()
        if key == "文件":
            args[0] = f"文件={literal}" if "=" in first else literal
        elif first.startswith(("'", '"')) or first in {"文件", '""', "''"} or resource_kind(first.strip().strip("'\"")) == "replay":
            args[0] = literal
        else:
            args.insert(0, literal)
        inside = ", ".join(args)
    return f"{line[: open_index + 1]}{inside}{line[close_index:]}"


def _looks_like_resource_value(value: str) -> bool:
    text = str(value or "").strip()
    if not text or text in {"图片", "文件", "模型"}:
        return True
    if resource_kind(text):
        return True
    lowered = text.replace("\\", "/").lower()
    if lowered.startswith(("plugins/", "images/", "sounds/", "yolo/", "replays/", "dicts/", "assets/")):
        return True
    return _is_module_offset_literal(text)


def _looks_like_module_or_plugin(value: str) -> bool:
    text = str(value or "").replace("\\", "/").strip()
    if not text:
        return False
    if _is_module_offset_literal(text) or text.lower().startswith(("plugins/", "assets/components/")):
        return True
    ext = os.path.splitext(text.rsplit("/", 1)[-1])[1].lower()
    return ext in {".exe", ".dll", ".sys"}


def _inserted_literal(path: str, old_value: str, call_name: str) -> str:
    text = str(path or "").replace("\\", "/")
    if str(call_name or "").startswith(("大漠内存.", "大漠汇编.")):
        module = text.rsplit("/", 1)[-1]
        body = str(old_value or "").replace("\\", "/")
        leading = ""
        while body.startswith("["):
            leading += "["
            body = body[1:]
        plus = body.find("+")
        if plus >= 0:
            return script_string_literal(leading + module + body[plus:])
        return script_string_literal(leading + module)
    return script_string_literal(text)


def _literal_span_to_replace(
    line: str,
    column: Optional[int],
    select_start: Optional[int],
    select_end: Optional[int],
) -> Optional[Tuple[int, int, str]]:
    cursor = 0 if column is None else max(0, int(column))
    selected = (
        select_start is not None
        and select_end is not None
        and int(select_start) != int(select_end)
    )
    for value, start, end in extract_string_literals(line):
        overlaps_selection = selected and start < int(select_end) and end > int(select_start)
        inside = start < cursor < end
        if overlaps_selection or (not selected and inside and _looks_like_resource_value(value)):
            return start, end, value
    return None


def _rewrite_string_kind_arg(
    line: str,
    literal: str,
    hosts: Tuple[str, ...],
    keys: Tuple[str, ...],
    kind: str,
) -> Optional[str]:
    from ui.dialogs.script_capture_text import _find_host_call, _is_kwarg, _split_top_level

    found = _find_host_call(str(line or ""), hosts)
    if found is None:
        return None
    _name, open_index, close_index = found
    args = _split_top_level(line[open_index + 1 : close_index])
    if not args:
        return f"{line[: open_index + 1]}{literal}{line[close_index:]}"
    for index in range(len(args) - 1, -1, -1):
        token = args[index]
        key = token.split("=", 1)[0].strip() if _is_kwarg(token) else ""
        inner = ""
        if key and "=" in token:
            raw = token.split("=", 1)[1].strip()
            if raw.startswith(("'", '"')) and len(raw) >= 2:
                inner = raw[1:-1]
        elif token.startswith(("'", '"')) and len(token) >= 2:
            inner = token[1:-1]
        if key in keys or resource_kind(inner) == kind or (inner and _looks_like_resource_value(inner) and kind != "dict"):
            if kind == "dict" and key not in keys and resource_kind(inner) != "dict" and not str(inner).replace("\\", "/").lower().startswith("dicts/"):
                continue
            if key in keys:
                args[index] = f"{key}={literal}"
            else:
                args[index] = literal
            return f"{line[: open_index + 1]}{', '.join(args)}{line[close_index:]}"
    first = args[0]
    key = first.split("=", 1)[0].strip() if _is_kwarg(first) else ""
    if key in keys:
        args[0] = f"{key}={literal}"
    elif first.startswith(("'", '"')) or first in keys or first in {'""', "''"}:
        args[0] = literal
    else:
        args.insert(0, literal)
    return f"{line[: open_index + 1]}{', '.join(args)}{line[close_index:]}"


def _rewrite_dm_component_arg(line: str, path: str) -> Optional[str]:
    from ui.dialogs.script_capture_text import _find_host_call, _is_kwarg, _split_top_level

    found = _find_host_call(str(line or ""), _DM_ADDR_HOSTS)
    if found is None:
        return None
    name, open_index, close_index = found
    args = _split_top_level(line[open_index + 1 : close_index])
    if not args:
        return None
    for index, token in enumerate(args):
        key = token.split("=", 1)[0].strip() if _is_kwarg(token) else ""
        inner = ""
        if key and "=" in token:
            raw = token.split("=", 1)[1].strip()
            if raw.startswith(("'", '"')) and len(raw) >= 2:
                inner = raw[1:-1]
        elif token.startswith(("'", '"')) and len(token) >= 2:
            inner = token[1:-1]
        if not _looks_like_module_or_plugin(inner):
            continue
        new_literal = _inserted_literal(path, inner, name)
        args[index] = f"{key}={new_literal}" if key in {"地址", "模块", "基址"} else new_literal
        return f"{line[: open_index + 1]}{', '.join(args)}{line[close_index:]}"
    return None


def _rewrite_component_arg(line: str, literal: str, path: str) -> Optional[str]:
    from ui.dialogs.script_capture_text import _find_host_call, _is_kwarg, _split_top_level

    found = _find_host_call(str(line or ""), _COMPONENT_HOSTS)
    if found is None:
        return None
    name, open_index, close_index = found
    args = _split_top_level(line[open_index + 1 : close_index])
    ext = os.path.splitext(path)[1].lower()
    component_type = "python" if ext == ".py" else "process" if ext in {".exe", ".com"} else "dll"
    type_literal = script_string_literal(component_type)

    def _is_path_arg(token: str) -> bool:
        raw = str(token or "").strip()
        if not raw:
            return False
        if _is_kwarg(raw) and raw.split("=", 1)[0].strip() in {"入口", "程序"}:
            return True
        if raw.startswith(("'", '"')) and len(raw) >= 2:
            inner = raw[1:-1]
            return _looks_like_resource_value(inner) or inner.endswith((".dll", ".exe", ".com", ".py"))
        return False

    replaced = False
    for index in range(len(args) - 1, -1, -1):
        token = args[index]
        if not _is_path_arg(token):
            continue
        if _is_kwarg(token) and token.split("=", 1)[0].strip() in {"入口", "程序"}:
            args[index] = f"{token.split('=', 1)[0].strip()}={literal}"
        else:
            args[index] = literal
        replaced = True
        break
    if not replaced:
        if name == "组件.加载":
            if not args:
                args = [type_literal, literal]
            elif len(args) == 1:
                args.append(literal)
            else:
                args[1] = literal
        elif args:
            args[0] = literal
        else:
            args = [literal]
    if name == "组件.加载" and args:
        first = args[0]
        inner = first[1:-1] if first.startswith(("'", '"')) and len(first) >= 2 else ""
        if first.startswith("类型=") or inner in {"dll", "python", "process", "com"}:
            args[0] = f"类型={type_literal}" if first.startswith("类型=") else type_literal
    return f"{line[: open_index + 1]}{', '.join(args)}{line[close_index:]}"


def plan_insert_resource(
    source: str,
    line_index: int,
    item: Dict[str, Any],
    column: Optional[int] = None,
    select_start: Optional[int] = None,
    select_end: Optional[int] = None,
) -> Dict[str, Any]:
    kind = str((item or {}).get("kind") or "")
    path = str((item or {}).get("path") or "")
    abs_path = str((item or {}).get("abs_path") or "")
    lines = source_lines(source)
    safe_index = max(0, min(int(line_index), len(lines) - 1))
    current = lines[safe_index]
    insert_path = path or abs_path
    literal = script_string_literal(path)
    span = _literal_span_to_replace(current, column, select_start, select_end)
    if span is not None:
        start, end, old_value = span
        call = enclosing_call_name(current, start)
        new_literal = _inserted_literal(insert_path, old_value, call)
        return {"mode": "replace", "line": safe_index, "text": current[:start] + new_literal + current[end:]}
    if kind == "image":
        updated = _rewrite_string_kind_arg(current, literal, _IMAGE_REWRITE_HOSTS, ("图片",), "image")
        if updated is not None:
            return {"mode": "replace", "line": safe_index, "text": updated}
        # 脚本中优先写入资源相对路径，避免把机器绝对路径写进卡片；
        # 绝对路径仅作为旧资源对象缺少 path 时的兼容回退。
        return apply_script_capture(source, line_index, "image", insert_path)
    if kind == "audio":
        updated = _rewrite_audio_arg(current, literal)
        if updated is not None:
            return {"mode": "replace", "line": safe_index, "text": updated}
        return plan_snippet_insert(f"播放({literal})", source, safe_index, column)
    if kind == "replay":
        updated = _rewrite_replay_arg(current, literal)
        if updated is not None:
            return {"mode": "replace", "line": safe_index, "text": updated}
        return plan_snippet_insert(f"回放({literal})", source, safe_index, column)
    if kind == "dict":
        updated = _rewrite_string_kind_arg(current, literal, _DICT_HOSTS, ("字库",), "dict")
        if updated is not None:
            return {"mode": "replace", "line": safe_index, "text": updated}
        return plan_snippet_insert(f"找字库(字库={literal})", source, safe_index, column)
    if kind == "component":
        updated = _rewrite_component_arg(current, literal, path)
        if updated is None:
            updated = _rewrite_dm_component_arg(current, path)
        if updated is not None:
            return {"mode": "replace", "line": safe_index, "text": updated}
        ext = os.path.splitext(path)[1].lower()
        component_type = "python" if ext == ".py" else "process" if ext in {".exe", ".com"} else "dll"
        snippet = (
            f"结果 = 进程.启动({literal})"
            if component_type == "process"
            else f'插件 = 组件.加载("{component_type}", {literal})'
        )
        return plan_snippet_insert(snippet, source, safe_index, column)
    updated = _rewrite_model_arg(current, literal)
    if updated is not None:
        return {"mode": "replace", "line": safe_index, "text": updated}
    name = command_name_from_snippet(current)
    snippet = f"检测({literal})" if name != "持续检测" else f"持续检测({literal}, 间隔=0.3)"
    return plan_snippet_insert(snippet, source, safe_index, column)
