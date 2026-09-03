# -*- coding: utf-8 -*-
"""自定义脚本卡片的资源栏：导入文件、改路径、插入命令。"""

from __future__ import annotations

from typing import Any, Dict, Optional

from task_workflow.script_resources import (
    AUDIO_EXTS,
    IMAGE_EXTS,
    MODEL_EXTS,
    card_filename_prefixes,
    constrain_script_path,
    delete_resource_file,
    extract_string_literals,
    import_resource_file,
    is_allowed_script_path,
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
from tasks.script_task import command_name_from_snippet, plan_snippet_insert
from ui.dialogs.script_capture_text import apply_script_capture, script_string_literal

_MODEL_HOSTS = ("检测", "持续检测", "等检测", "等检测消失")
_AUDIO_HOSTS = ("播放",)
_REPLAY_HOSTS = ("回放",)

__all__ = [
    "AUDIO_EXTS",
    "IMAGE_EXTS",
    "MODEL_EXTS",
    "card_filename_prefixes",
    "constrain_script_path",
    "delete_resource_file",
    "extract_string_literals",
    "import_resource_file",
    "is_allowed_script_path",
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


def plan_insert_resource(
    source: str,
    line_index: int,
    item: Dict[str, Any],
    column: Optional[int] = None,
) -> Dict[str, Any]:
    kind = str((item or {}).get("kind") or "")
    path = str((item or {}).get("path") or "")
    abs_path = str((item or {}).get("abs_path") or "")
    if kind == "image":
        return apply_script_capture(source, line_index, "image", abs_path or path)
    literal = script_string_literal(path)
    lines = str(source or "").splitlines() or [""]
    safe_index = max(0, min(int(line_index), len(lines) - 1))
    if kind == "audio":
        updated = _rewrite_audio_arg(lines[safe_index], literal)
        if updated is not None:
            return {"mode": "replace", "line": safe_index, "text": updated}
        return plan_snippet_insert(f"播放({literal})", source, safe_index, column)
    if kind == "replay":
        updated = _rewrite_replay_arg(lines[safe_index], literal)
        if updated is not None:
            return {"mode": "replace", "line": safe_index, "text": updated}
        return plan_snippet_insert(f"回放({literal})", source, safe_index, column)
    updated = _rewrite_model_arg(lines[safe_index], literal)
    if updated is not None:
        return {"mode": "replace", "line": safe_index, "text": updated}
    name = command_name_from_snippet(lines[safe_index])
    snippet = f"检测({literal})" if name != "持续检测" else f"持续检测({literal}, 间隔=0.3)"
    return plan_snippet_insert(snippet, source, safe_index, column)
