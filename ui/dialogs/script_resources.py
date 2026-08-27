# -*- coding: utf-8 -*-
"""自定义脚本卡片的资源：扫脚本、导入文件、改路径。"""

from __future__ import annotations

import os
import shutil
from typing import Any, Dict, List, Optional, Tuple

from ui.dialogs.script_capture_text import apply_script_capture, script_string_literal
from tasks.script_task import command_name_from_snippet, plan_snippet_insert
from utils.app_paths import get_app_root, get_images_dir, get_sounds_dir, normalize_workflow_image_path

IMAGE_EXTS = {".bmp", ".png", ".jpg", ".jpeg", ".webp"}
MODEL_EXTS = {".onnx"}
AUDIO_EXTS = {".wav", ".mp3", ".wma", ".m4a", ".ogg", ".flac"}
_MODEL_HOSTS = ("检测", "持续检测", "等检测", "等检测消失")
_AUDIO_HOSTS = ("播放",)


def extract_string_literals(source: str) -> List[Tuple[str, int, int]]:
    text = str(source or "")
    items: List[Tuple[str, int, int]] = []
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char not in {'"', "'"}:
            index += 1
            continue
        quote = char
        start = index
        index += 1
        chars = []
        while index < length:
            current = text[index]
            if current == "\\" and index + 1 < length:
                chars.append(text[index + 1])
                index += 2
                continue
            if current == quote:
                items.append(("".join(chars), start, index + 1))
                index += 1
                break
            chars.append(current)
            index += 1
        else:
            break
    return items


def resource_kind(path: str) -> str:
    text = str(path or "").replace("\\", "/").strip()
    if not text:
        return ""
    ext = os.path.splitext(text)[1].lower()
    if ext in MODEL_EXTS or text.lower().startswith("yolo/"):
        return "model"
    if ext in AUDIO_EXTS or text.lower().startswith("sounds/"):
        return "audio"
    if ext in IMAGE_EXTS or text.lower().startswith("images/"):
        return "image"
    return ""


def card_filename_prefixes(card_id: Optional[int], workflow_token: str = "") -> List[str]:
    if not isinstance(card_id, int) or card_id < 0:
        return []
    prefixes = []
    token = str(workflow_token or "").strip()
    if token:
        prefixes.append(f"{token}_{card_id}_")
    prefixes.append(f"card_{card_id}_")
    return prefixes


def resolve_resource_path(path: str, images_dir: str = "", sounds_dir: str = "") -> str:
    text = str(path or "").replace("\\", "/").strip()
    if not text:
        return ""
    if os.path.isabs(text) and os.path.exists(text):
        return os.path.abspath(text)
    root = str(images_dir or "").strip() or get_images_dir("LCA")
    sounds = str(sounds_dir or "").strip()
    candidates = []
    lowered = text.lower()
    if lowered.startswith("images/"):
        candidates.append(os.path.join(root, text[7:]))
        parent = os.path.dirname(root)
        if parent:
            candidates.append(os.path.join(parent, text))
    if lowered.startswith("sounds/") or lowered.endswith(tuple(AUDIO_EXTS)):
        sounds = sounds or get_sounds_dir("LCA")
        if lowered.startswith("sounds/"):
            suffix = text[7:]
            candidates.append(os.path.join(sounds, suffix))
            candidates.append(os.path.join(get_app_root(), text))
        candidates.extend(
            (
                os.path.join(sounds, os.path.basename(text)),
                os.path.join(sounds, text),
                os.path.join(get_app_root(), "sounds", os.path.basename(text)),
            )
        )
    candidates.append(os.path.join(root, os.path.basename(text)))
    candidates.append(os.path.join(root, text))
    app_root = get_app_root()
    if lowered.endswith(".onnx") or lowered.startswith("yolo/"):
        candidates.extend(
            (
                os.path.join(app_root, text),
                os.path.join(app_root, "yolo", os.path.basename(text)),
                os.path.join(get_images_dir("LCA"), os.path.basename(text)),
            )
        )
    if os.path.isabs(text):
        candidates.append(text)
    try:
        from utils.image_paths import get_image_path_resolver

        resolved = get_image_path_resolver().resolve(text)
        if resolved:
            candidates.insert(0, str(resolved))
    except Exception:
        pass
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return os.path.abspath(candidate)
    return os.path.abspath(candidates[0]) if candidates else text


def script_path_for_file(abs_path: str, kind: str = "", images_dir: str = "", sounds_dir: str = "") -> str:
    text = str(abs_path or "").strip()
    if not text:
        return ""
    absolute = os.path.abspath(text)
    detected = kind or resource_kind(text)
    if detected == "model":
        app_root = os.path.abspath(get_app_root())
        try:
            relative = os.path.relpath(absolute, app_root).replace(os.sep, "/")
        except ValueError:
            relative = os.path.basename(absolute)
        if relative.startswith("yolo/") or relative.endswith(".onnx"):
            return relative
        return f"yolo/{os.path.basename(absolute)}"
    if detected == "audio":
        root = os.path.abspath(str(sounds_dir or "").strip() or get_sounds_dir("LCA"))
        root_prefix = os.path.normcase(root) + os.sep
        if os.path.normcase(absolute) == os.path.normcase(root):
            return "sounds"
        if os.path.normcase(absolute).startswith(root_prefix):
            relative = os.path.relpath(absolute, root).replace(os.sep, "/")
            return f"sounds/{relative}"
        return f"sounds/{os.path.basename(absolute)}"
    root = os.path.abspath(str(images_dir or "").strip() or get_images_dir("LCA"))
    root_prefix = os.path.normcase(root) + os.sep
    if os.path.normcase(absolute) == os.path.normcase(root):
        return "images"
    if os.path.normcase(absolute).startswith(root_prefix):
        relative = os.path.relpath(absolute, root).replace(os.sep, "/")
        return f"images/{relative}"
    return normalize_workflow_image_path(text)


def list_card_files(images_dir: str, card_id: Optional[int], workflow_token: str = "") -> List[str]:
    root = str(images_dir or "").strip()
    if not root or not os.path.isdir(root):
        return []
    prefixes = card_filename_prefixes(card_id, workflow_token)
    if not prefixes:
        return []
    found = []
    for name in os.listdir(root):
        if any(name.startswith(prefix) for prefix in prefixes):
            path = os.path.join(root, name)
            if os.path.isfile(path) and resource_kind(name):
                found.append(os.path.abspath(path))
    return sorted(found)


def list_script_resources(
    source: str,
    images_dir: str = "",
    card_id: Optional[int] = None,
    workflow_token: str = "",
    sounds_dir: str = "",
) -> List[Dict[str, Any]]:
    used: Dict[str, Dict[str, Any]] = {}
    for value, start, end in extract_string_literals(source):
        kind = resource_kind(value)
        if not kind:
            continue
        key = value.replace("\\", "/")
        item = used.get(key)
        if item is None:
            abs_path = resolve_resource_path(value, images_dir, sounds_dir)
            item = {
                "kind": kind,
                "path": key,
                "abs_path": abs_path,
                "name": os.path.basename(key) or key,
                "exists": bool(abs_path and os.path.exists(abs_path)),
                "used": 0,
                "unused": False,
                "spans": [],
            }
            used[key] = item
        item["used"] += 1
        item["spans"].append((start, end))
    listed = {os.path.normcase(str(item.get("abs_path") or "")) for item in used.values()}
    extras = []
    extra_roots = [images_dir]
    if sounds_dir:
        extra_roots.append(sounds_dir)
    for root in extra_roots:
        for abs_path in list_card_files(root, card_id, workflow_token):
            if os.path.normcase(abs_path) in listed:
                continue
            kind = resource_kind(abs_path)
            extras.append(
                {
                    "kind": kind,
                    "path": script_path_for_file(abs_path, kind, images_dir, sounds_dir),
                    "abs_path": abs_path,
                    "name": os.path.basename(abs_path),
                    "exists": True,
                    "used": 0,
                    "unused": True,
                    "spans": [],
                }
            )
            listed.add(os.path.normcase(abs_path))
    items = list(used.values()) + extras
    items.sort(key=lambda item: (0 if item["used"] else 1, item["kind"], item["name"].lower()))
    return items


def rewrite_resource_literal(source: str, old_path: str, new_path: str) -> str:
    text = str(source or "")
    olds = {str(old_path or "").strip(), str(old_path or "").replace("\\", "/"), str(old_path or "").replace("/", "\\")}
    new = str(new_path or "").replace("\\", "/")
    if not new:
        return text
    for old in olds:
        if not old:
            continue
        for quote in ('"', "'"):
            text = text.replace(f"{quote}{old}{quote}", f"{quote}{new}{quote}")
    return text


def _unique_dest(directory: str, filename: str) -> str:
    stem, ext = os.path.splitext(filename)
    dest = os.path.join(directory, filename)
    index = 1
    while os.path.exists(dest):
        dest = os.path.join(directory, f"{stem}_{index}{ext}")
        index += 1
    return dest


def import_resource_file(
    src_path: str,
    images_dir: str = "",
    card_id: Optional[int] = None,
    workflow_token: str = "",
    kind: str = "",
    sounds_dir: str = "",
) -> Dict[str, Any]:
    source = os.path.abspath(str(src_path or "").strip())
    if not os.path.isfile(source):
        raise FileNotFoundError(source)
    detected = kind or resource_kind(source) or "image"
    if detected == "model":
        directory = os.path.join(get_app_root(), "yolo")
    elif detected == "audio":
        directory = str(sounds_dir or "").strip() or get_sounds_dir("LCA")
    else:
        directory = str(images_dir or "").strip() or get_images_dir("LCA")
    os.makedirs(directory, exist_ok=True)
    name = os.path.basename(source)
    dest = os.path.join(directory, name)
    if os.path.normcase(os.path.abspath(dest)) != os.path.normcase(source):
        if os.path.exists(dest):
            prefixes = card_filename_prefixes(card_id, workflow_token)
            prefix = prefixes[0] if prefixes else ""
            dest = _unique_dest(directory, f"{prefix}{name}" if prefix else name)
        shutil.copy2(source, dest)
    path = script_path_for_file(dest, detected, images_dir, sounds_dir)
    return {
        "kind": detected,
        "path": path,
        "abs_path": os.path.abspath(dest),
        "name": os.path.basename(dest),
        "exists": True,
        "used": 0,
        "unused": True,
        "spans": [],
    }


def replace_resource_file(
    item: Dict[str, Any],
    src_path: str,
    images_dir: str = "",
    sounds_dir: str = "",
) -> Dict[str, Any]:
    source = os.path.abspath(str(src_path or "").strip())
    if not os.path.isfile(source):
        raise FileNotFoundError(source)
    current = str((item or {}).get("abs_path") or "")
    kind = str((item or {}).get("kind") or resource_kind(source) or "image")
    if current and os.path.isfile(current) and os.path.splitext(current)[1].lower() == os.path.splitext(source)[1].lower():
        shutil.copy2(source, current)
        updated = dict(item or {})
        updated["exists"] = True
        updated["abs_path"] = os.path.abspath(current)
        return updated
    imported = import_resource_file(source, images_dir, kind=kind, sounds_dir=sounds_dir)
    imported["used"] = int((item or {}).get("used") or 0)
    imported["unused"] = bool((item or {}).get("unused"))
    imported["old_path"] = str((item or {}).get("path") or "")
    return imported


def rename_resource_file(
    item: Dict[str, Any],
    new_name: str,
    source: str,
    images_dir: str = "",
    sounds_dir: str = "",
) -> Tuple[str, Dict[str, Any]]:
    name = os.path.basename(str(new_name or "").strip())
    if not name or name in {".", ".."} or any(char in name for char in '\\/:*?"<>|'):
        raise ValueError("文件名不合法")
    abs_path = str((item or {}).get("abs_path") or "")
    if not abs_path or not os.path.isfile(abs_path):
        raise FileNotFoundError(abs_path or name)
    directory = os.path.dirname(abs_path)
    dest = os.path.join(directory, name)
    if os.path.normcase(dest) != os.path.normcase(abs_path) and os.path.exists(dest):
        raise FileExistsError(name)
    if os.path.normcase(dest) != os.path.normcase(abs_path):
        os.rename(abs_path, dest)
    kind = str((item or {}).get("kind") or resource_kind(dest))
    new_path = script_path_for_file(dest, kind, images_dir, sounds_dir)
    old_path = str((item or {}).get("path") or "")
    updated_source = rewrite_resource_literal(source, old_path, new_path)
    updated = dict(item or {})
    updated["path"] = new_path
    updated["abs_path"] = os.path.abspath(dest)
    updated["name"] = os.path.basename(dest)
    updated["exists"] = True
    return updated_source, updated


def delete_resource_file(item: Dict[str, Any]) -> None:
    abs_path = str((item or {}).get("abs_path") or "")
    if abs_path and os.path.isfile(abs_path):
        os.remove(abs_path)


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
    updated = _rewrite_model_arg(lines[safe_index], literal)
    if updated is not None:
        return {"mode": "replace", "line": safe_index, "text": updated}
    name = command_name_from_snippet(lines[safe_index])
    snippet = f"检测({literal})" if name != "持续检测" else f"持续检测({literal}, 间隔=0.3)"
    return plan_snippet_insert(snippet, source, safe_index, column)
