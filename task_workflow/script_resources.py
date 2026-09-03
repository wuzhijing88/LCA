# -*- coding: utf-8 -*-
"""自定义脚本资源路径：扫描、改写、运行时限制在项目目录内。"""

from __future__ import annotations

import os
import shutil
from typing import Any, Dict, List, Optional, Tuple

from utils.app_paths import get_app_root, get_images_dir, get_sounds_dir, normalize_workflow_image_path

IMAGE_EXTS = {".bmp", ".png", ".jpg", ".jpeg", ".webp"}
MODEL_EXTS = {".onnx"}
AUDIO_EXTS = {".wav", ".mp3", ".wma", ".m4a", ".ogg", ".flac"}


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
    lowered = text.lower()
    if lowered.endswith(".replay.json") or lowered.startswith("replays/"):
        return "replay"
    ext = os.path.splitext(text)[1].lower()
    if ext in MODEL_EXTS or lowered.startswith("yolo/"):
        return "model"
    if ext in AUDIO_EXTS or lowered.startswith("sounds/"):
        return "audio"
    if ext in IMAGE_EXTS or lowered.startswith("images/"):
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


def script_resource_roots(images_dir: str = "", sounds_dir: str = "") -> List[str]:
    roots = []
    for raw in (
        images_dir,
        sounds_dir,
        get_images_dir("LCA"),
        get_sounds_dir("LCA"),
        os.path.join(get_app_root(), "yolo"),
        os.path.join(get_app_root(), "replays"),
        os.path.join(get_app_root(), "images"),
        os.path.join(get_app_root(), "sounds"),
    ):
        text = str(raw or "").strip()
        if not text:
            continue
        absolute = os.path.abspath(text)
        if absolute not in roots:
            roots.append(absolute)
    return roots


def _is_under_root(path: str, root: str) -> bool:
    try:
        path_abs = os.path.abspath(path)
        root_abs = os.path.abspath(root)
    except Exception:
        return False
    path_key = os.path.normcase(path_abs)
    root_key = os.path.normcase(root_abs)
    return path_key == root_key or path_key.startswith(root_key + os.sep)


def is_allowed_script_path(path: str, images_dir: str = "", sounds_dir: str = "") -> bool:
    text = str(path or "").strip()
    if not text:
        return False
    try:
        resolved = os.path.abspath(text)
    except Exception:
        return False
    return any(_is_under_root(resolved, root) for root in script_resource_roots(images_dir, sounds_dir))


def resolve_resource_path(
    path: str,
    images_dir: str = "",
    sounds_dir: str = "",
    enforce_jail: bool = False,
) -> str:
    text = str(path or "").replace("\\", "/").strip()
    if not text:
        return ""
    root = str(images_dir or "").strip() or get_images_dir("LCA")
    sounds = str(sounds_dir or "").strip()
    candidates = []
    lowered = text.lower()
    if os.path.isabs(text):
        candidates.append(os.path.abspath(text))
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
    if lowered.endswith(".replay.json") or lowered.startswith("replays/"):
        suffix = text[8:] if lowered.startswith("replays/") else os.path.basename(text)
        candidates.extend(
            (
                os.path.join(app_root, text),
                os.path.join(app_root, "replays", os.path.basename(text)),
                os.path.join(root, "replays", os.path.basename(text)),
                os.path.join(root, suffix),
            )
        )
    try:
        from utils.image_paths import get_image_path_resolver

        resolved = get_image_path_resolver().resolve(text)
        if resolved:
            candidates.insert(0, str(resolved))
    except Exception:
        pass
    allowed = []
    existing = []
    for candidate in candidates:
        if not candidate:
            continue
        absolute = os.path.abspath(candidate)
        if enforce_jail and not is_allowed_script_path(absolute, images_dir, sounds_dir):
            continue
        allowed.append(absolute)
        if os.path.exists(absolute):
            existing.append(absolute)
    if existing:
        return existing[0]
    if allowed:
        return allowed[0]
    if enforce_jail:
        return ""
    return os.path.abspath(candidates[0]) if candidates else text


def constrain_script_path(path: str, images_dir: str = "", sounds_dir: str = "") -> str:
    text = str(path or "").strip()
    if not text:
        raise ValueError("缺少资源路径")
    if os.path.isabs(text):
        projected = os.path.abspath(text)
        if not is_allowed_script_path(projected, images_dir, sounds_dir):
            raise ValueError("脚本不能访问该路径")
        return projected
    located = resolve_resource_path(text, images_dir, sounds_dir, enforce_jail=False)
    if located and os.path.exists(located):
        projected = os.path.abspath(located)
    else:
        root = str(images_dir or "").strip() or get_images_dir("LCA")
        lowered = text.replace("\\", "/").lower()
        if lowered.startswith("images/"):
            projected = os.path.abspath(os.path.join(root, text.replace("\\", "/")[7:]))
        elif lowered.startswith("sounds/"):
            sounds = str(sounds_dir or "").strip() or get_sounds_dir("LCA")
            projected = os.path.abspath(os.path.join(sounds, text.replace("\\", "/")[7:]))
        elif lowered.startswith("yolo/") or lowered.endswith(".onnx"):
            projected = os.path.abspath(os.path.join(get_app_root(), text.replace("\\", "/")))
        elif lowered.startswith("replays/") or lowered.endswith(".replay.json"):
            projected = os.path.abspath(os.path.join(get_app_root(), text.replace("\\", "/")))
        else:
            projected = os.path.abspath(os.path.join(root, text))
    if not is_allowed_script_path(projected, images_dir, sounds_dir):
        raise ValueError("脚本不能访问该路径")
    if os.path.isabs(text):
        return projected
    return text.replace("\\", "/")


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
    if detected == "replay":
        app_root = os.path.abspath(get_app_root())
        try:
            relative = os.path.relpath(absolute, app_root).replace(os.sep, "/")
        except ValueError:
            relative = os.path.basename(absolute)
        if relative.startswith("replays/") or relative.endswith(".replay.json"):
            return relative
        return f"replays/{os.path.basename(absolute)}"
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
            abs_path = resolve_resource_path(value, images_dir, sounds_dir, enforce_jail=False)
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
    old = str(old_path or "").strip()
    new = str(new_path or "").replace("\\", "/")
    if not old or not new:
        return text
    old_keys = {old, old.replace("\\", "/"), old.replace("/", "\\")}
    pieces = []
    cursor = 0
    for value, start, end in extract_string_literals(text):
        if value not in old_keys:
            continue
        quote = text[start]
        pieces.append(text[cursor:start])
        pieces.append(f"{quote}{new}{quote}")
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces)


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
    elif detected == "replay":
        directory = os.path.join(get_app_root(), "replays")
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
