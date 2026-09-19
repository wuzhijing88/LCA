# -*- coding: utf-8 -*-
"""自定义脚本资源路径：扫描、改写、运行时限制在项目目录内。"""

from __future__ import annotations

import os
import shutil
from typing import Any, Dict, List, Optional, Tuple

from utils.app_paths import (
    get_app_root,
    get_images_dir,
    get_plugin_dir,
    get_sounds_dir,
    get_user_data_dir,
    normalize_workflow_image_path,
)


def _current_dirs(
    images_dir: str = "",
    sounds_dir: str = "",
    dicts_dir: str = "",
    yolo_dir: str = "",
    replays_dir: str = "",
    plugins_dir: str = "",
) -> Dict[str, str]:
    from task_workflow.resource_context import current_resource_dirs

    current = current_resource_dirs()
    return {
        "images_dir": str(images_dir or "").strip() or current["images_dir"],
        "sounds_dir": str(sounds_dir or "").strip() or current["sounds_dir"],
        "dicts_dir": str(dicts_dir or "").strip() or current["dicts_dir"],
        "yolo_dir": str(yolo_dir or "").strip() or current["yolo_dir"],
        "replays_dir": str(replays_dir or "").strip() or current["replays_dir"],
        "plugins_dir": str(plugins_dir or "").strip() or current["plugins_dir"],
    }


def _kind_suffix(path: str, folder: str) -> str:
    text = str(path or "").replace("\\", "/").strip()
    lowered = text.lower()
    packaged = {
        "images": ("assets/images/",),
        "sounds": ("assets/sounds/",),
        "dicts": ("assets/dicts/", "assets/images/dicts/"),
        "yolo": ("assets/yolo/", "assets/models/"),
        "replays": ("assets/replays/",),
        "plugins": ("assets/components/",),
    }
    for prefix in packaged.get(folder, ()):
        if lowered.startswith(prefix):
            return text[len(prefix):]
    prefix = f"{folder}/"
    if lowered.startswith(prefix):
        return text[len(prefix):]
    return os.path.basename(text)

IMAGE_EXTS = {".bmp", ".png", ".jpg", ".jpeg", ".webp"}
MODEL_EXTS = {".onnx"}
AUDIO_EXTS = {".wav", ".mp3", ".wma", ".m4a", ".ogg", ".flac"}
COMPONENT_EXTS = {".dll", ".exe", ".py"}
DICT_EXTS = {".dict"}
DICT_TEXT_EXTS = {".txt", ".dict"}
_DICT_SCRIPT_CALLS = ("找字库", "点字库", "等字库", "等字库消失")
_MODULE_OFFSET_EXTS = {".exe", ".dll", ".sys"}
_PLUGIN_MODULE_PREFIXES = ("plugins/", "assets/components/")


def _is_module_offset_literal(path: str) -> bool:
    """大漠「模块名+偏移」地址不是磁盘上的组件文件。"""
    text = str(path or "").replace("\\", "/").strip()
    plus = text.find("+")
    if plus <= 0:
        return False
    module = text[:plus]
    while module.startswith("["):
        module = module[1:]
    base = module.rsplit("/", 1)[-1]
    return os.path.splitext(base)[1].lower() in _MODULE_OFFSET_EXTS


def strip_plugin_module_prefix(value: str) -> str:
    """去掉地址或汇编指令里模块名前面的 plugins/ 路径。"""
    text = str(value or "").replace("\\", "/").strip()
    lowered = text.lower()
    out = []
    index = 0
    length = len(text)
    while index < length:
        skipped = False
        for prefix in _PLUGIN_MODULE_PREFIXES:
            if lowered.startswith(prefix, index):
                after = text[index + len(prefix):]
                name = after.split("+", 1)[0].split("/", 1)[0].split("]", 1)[0]
                if os.path.splitext(name)[1].lower() in _MODULE_OFFSET_EXTS:
                    index += len(prefix)
                    skipped = True
                    break
        if skipped:
            continue
        out.append(text[index])
        index += 1
    return "".join(out)


def enclosing_call_name(source: str, pos: int) -> str:
    """字面量所在调用的命令名，例如 大漠内存.读取文本。"""
    text = str(source or "")
    depth = 0
    index = int(pos) - 1
    while index >= 0:
        char = text[index]
        if char == ")":
            depth += 1
        elif char == "(":
            if depth == 0:
                end = index
                start = index - 1
                while start >= 0:
                    current = text[start]
                    if current.isalnum() or current in "._" or "\u4e00" <= current <= "\u9fff":
                        start -= 1
                        continue
                    break
                return text[start + 1 : end]
            depth -= 1
        index -= 1
    return ""


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
    if _is_module_offset_literal(text):
        return ""
    lowered = text.lower()
    if lowered.endswith(".replay.json") or lowered.startswith(("replays/", "assets/replays/")):
        return "replay"
    ext = os.path.splitext(text)[1].lower()
    if (
        ext in DICT_EXTS
        or lowered.startswith(("dicts/", "assets/dicts/", "assets/images/dicts/", "images/dicts/"))
        or "/dicts/" in f"/{lowered}"
    ):
        return "dict"
    if ext in MODEL_EXTS or lowered.startswith(("yolo/", "assets/yolo/", "assets/models/")):
        return "model"
    if ext in AUDIO_EXTS or lowered.startswith(("sounds/", "assets/sounds/")):
        return "audio"
    if ext in COMPONENT_EXTS or lowered.startswith(("plugins/", "assets/components/")):
        return "component"
    if ext in IMAGE_EXTS or lowered.startswith(("images/", "assets/images/")):
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


def script_resource_roots(
    images_dir: str = "",
    sounds_dir: str = "",
    dicts_dir: str = "",
    yolo_dir: str = "",
    replays_dir: str = "",
    plugins_dir: str = "",
) -> List[str]:
    dirs = _current_dirs(images_dir, sounds_dir, dicts_dir, yolo_dir, replays_dir, plugins_dir)
    app_root = get_app_root()
    roots = []
    for raw in (
        dirs["images_dir"],
        dirs["sounds_dir"],
        dirs["dicts_dir"],
        dirs["yolo_dir"],
        dirs["replays_dir"],
        dirs["plugins_dir"],
        get_images_dir("LCA"),
        get_sounds_dir("LCA"),
        os.path.join(app_root, "yolo"),
        os.path.join(app_root, "replays"),
        os.path.join(app_root, "images"),
        os.path.join(app_root, "sounds"),
        get_plugin_dir(),
        os.path.join(get_user_data_dir("LCA"), "components"),
        os.path.join(app_root, "dicts"),
    ):
        text = str(raw or "").strip()
        if not text:
            continue
        absolute = os.path.abspath(text)
        if absolute not in roots:
            roots.append(absolute)
    return roots


def _workflow_local_roots(
    images_dir: str = "",
    sounds_dir: str = "",
    dicts_dir: str = "",
    yolo_dir: str = "",
    replays_dir: str = "",
) -> List[str]:
    from task_workflow.resource_context import (
        bound_dicts_dir,
        bound_images_dir,
        bound_replays_dir,
        bound_sounds_dir,
        bound_yolo_dir,
    )

    values = (
        str(images_dir or "").strip() or bound_images_dir(),
        str(sounds_dir or "").strip() or bound_sounds_dir(),
        str(dicts_dir or "").strip() or bound_dicts_dir(),
        str(yolo_dir or "").strip() or bound_yolo_dir(),
        str(replays_dir or "").strip() or bound_replays_dir(),
    )
    roots: List[str] = []
    seen = set()
    for raw in values:
        text = str(raw or "").strip()
        if not text:
            continue
        absolute = os.path.abspath(text)
        key = os.path.normcase(absolute)
        if key in seen:
            continue
        seen.add(key)
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


def is_allowed_script_path(
    path: str,
    images_dir: str = "",
    sounds_dir: str = "",
    dicts_dir: str = "",
    yolo_dir: str = "",
    replays_dir: str = "",
    plugins_dir: str = "",
) -> bool:
    text = str(path or "").strip()
    if not text:
        return False
    try:
        resolved = os.path.abspath(text)
    except Exception:
        return False
    return any(
        _is_under_root(resolved, root)
        for root in script_resource_roots(
            images_dir, sounds_dir, dicts_dir, yolo_dir, replays_dir, plugins_dir
        )
    )


def _memory_resource_keys(path: str) -> List[str]:
    text = str(path or "").replace("\\", "/").strip()
    if text.startswith("memory://"):
        text = text[len("memory://") :]
    text = text.lstrip("/")
    if not text:
        return []
    base = os.path.basename(text)
    keys = [text, base]
    kind = resource_kind(text) or resource_kind(base)
    if kind == "image":
        keys.extend((f"images/{base}", f"assets/images/{base}"))
    elif kind == "audio":
        keys.extend((f"sounds/{base}", f"assets/sounds/{base}"))
    elif kind == "dict":
        keys.extend((f"dicts/{base}", f"assets/dicts/{base}"))
    elif kind == "model":
        keys.extend((f"yolo/{base}", f"models/{base}", f"assets/yolo/{base}", f"assets/models/{base}"))
    elif kind == "replay":
        keys.extend((f"replays/{base}", f"assets/replays/{base}"))
    elif kind == "component":
        keys.extend((f"plugins/{base}", f"components/{base}", f"assets/components/{base}"))
    unique: List[str] = []
    seen = set()
    for key in keys:
        item = str(key or "").strip().lstrip("/")
        if not item or item in seen:
            continue
        seen.add(item)
        unique.append(item)
    return unique


def _player_memory_bytes(path: str) -> Optional[bytes]:
    try:
        from app_core.player.memory_store import get_player_memory_file, has_player_memory_files
        from app_core.player.runtime_images import ensure_player_image_memory
    except Exception:
        return None
    if not has_player_memory_files():
        ensure_player_image_memory()
    if not has_player_memory_files():
        return None
    for key in _memory_resource_keys(path):
        data = get_player_memory_file(key)
        if data is not None:
            return bytes(data)
    return None


def read_resource_bytes(
    path: str,
    images_dir: str = "",
    sounds_dir: str = "",
    dicts_dir: str = "",
    yolo_dir: str = "",
    replays_dir: str = "",
    plugins_dir: str = "",
) -> Optional[bytes]:
    """主程序与自定义脚本共用的资源读取：磁盘工作区 / 工程包 / 独立程序内存。"""
    located = resolve_resource_path(
        path,
        images_dir=images_dir,
        sounds_dir=sounds_dir,
        dicts_dir=dicts_dir,
        yolo_dir=yolo_dir,
        replays_dir=replays_dir,
        plugins_dir=plugins_dir,
        enforce_jail=False,
    )
    if located and str(located).startswith("memory://"):
        return _player_memory_bytes(located)
    if located and os.path.isfile(located):
        with open(located, "rb") as handle:
            return handle.read()
    return _player_memory_bytes(path)


def resolve_resource_path(
    path: str,
    images_dir: str = "",
    sounds_dir: str = "",
    enforce_jail: bool = False,
    dicts_dir: str = "",
    yolo_dir: str = "",
    replays_dir: str = "",
    plugins_dir: str = "",
) -> str:
    text = str(path or "").replace("\\", "/").strip()
    if not text:
        return ""
    dirs = _current_dirs(images_dir, sounds_dir, dicts_dir, yolo_dir, replays_dir, plugins_dir)
    root = dirs["images_dir"]
    sounds = dirs["sounds_dir"]
    app_root = get_app_root()
    candidates = []
    lowered = text.lower()
    if os.path.isabs(text):
        candidates.append(os.path.abspath(text))
    if lowered.startswith(("images/", "assets/images/")) and not lowered.startswith(
        ("assets/images/dicts/", "images/dicts/")
    ) and "/dicts/" not in f"/{lowered}":
        suffix = _kind_suffix(text, "images")
        candidates.append(os.path.join(root, suffix))
        parent = os.path.dirname(root)
        if parent:
            candidates.append(os.path.join(parent, f"images/{suffix}"))
    if lowered.startswith(("sounds/", "assets/sounds/")) or lowered.endswith(tuple(AUDIO_EXTS)):
        if lowered.startswith(("sounds/", "assets/sounds/")):
            suffix = _kind_suffix(text, "sounds")
            candidates.append(os.path.join(sounds, suffix))
            candidates.append(os.path.join(app_root, f"sounds/{suffix}"))
        candidates.extend(
            (
                os.path.join(sounds, os.path.basename(text)),
                os.path.join(sounds, text),
                os.path.join(app_root, "sounds", os.path.basename(text)),
            )
        )
    if (
        lowered.startswith(("dicts/", "assets/dicts/", "images/dicts/", "assets/images/dicts/"))
        or os.path.splitext(lowered)[1] in DICT_TEXT_EXTS
    ):
        suffix = _kind_suffix(text, "dicts")
        candidates.extend(
            (
                os.path.join(dirs["dicts_dir"], suffix),
                os.path.join(dirs["dicts_dir"], os.path.basename(text)),
                os.path.join(app_root, f"dicts/{suffix}"),
            )
        )
    if not _is_module_offset_literal(text) and (
        os.path.splitext(lowered)[1] in COMPONENT_EXTS or lowered.startswith("plugins/")
    ):
        suffix = _kind_suffix(text, "plugins")
        candidates.extend(
            (
                os.path.join(dirs["plugins_dir"], suffix),
                os.path.join(dirs["plugins_dir"], os.path.basename(text)),
                os.path.join(get_plugin_dir(), suffix),
                os.path.join(get_plugin_dir(), os.path.basename(text)),
                os.path.join(get_user_data_dir("LCA"), "components", suffix),
                os.path.join(get_user_data_dir("LCA"), "components", os.path.basename(text)),
            )
        )
    candidates.append(os.path.join(root, os.path.basename(text)))
    candidates.append(os.path.join(root, text))
    if lowered.endswith(".onnx") or lowered.startswith("yolo/"):
        suffix = _kind_suffix(text, "yolo")
        candidates.extend(
            (
                os.path.join(dirs["yolo_dir"], suffix),
                os.path.join(dirs["yolo_dir"], os.path.basename(text)),
                os.path.join(root, "yolo", os.path.basename(text)),
                os.path.join(app_root, text),
                os.path.join(app_root, "yolo", os.path.basename(text)),
            )
        )
    if lowered.endswith(".replay.json") or lowered.startswith("replays/"):
        suffix = _kind_suffix(text, "replays")
        candidates.extend(
            (
                os.path.join(dirs["replays_dir"], suffix),
                os.path.join(dirs["replays_dir"], os.path.basename(text)),
                os.path.join(app_root, text),
                os.path.join(app_root, "replays", os.path.basename(text)),
                os.path.join(root, "replays", os.path.basename(text)),
                os.path.join(root, suffix),
            )
        )
    allowed = []
    existing = []
    for candidate in candidates:
        if not candidate:
            continue
        absolute = os.path.abspath(candidate)
        if enforce_jail and not is_allowed_script_path(
            absolute,
            images_dir=dirs["images_dir"],
            sounds_dir=dirs["sounds_dir"],
            dicts_dir=dirs["dicts_dir"],
            yolo_dir=dirs["yolo_dir"],
            replays_dir=dirs["replays_dir"],
            plugins_dir=dirs["plugins_dir"],
        ):
            continue
        allowed.append(absolute)
        if os.path.exists(absolute):
            existing.append(absolute)
    local_roots = _workflow_local_roots(
        images_dir,
        sounds_dir,
        dicts_dir,
        yolo_dir,
        replays_dir,
    )
    if local_roots:
        for absolute in existing:
            if any(_is_under_root(absolute, root) for root in local_roots):
                return absolute
    memory_hit = _player_memory_bytes(text)
    if memory_hit is not None:
        keys = _memory_resource_keys(text)
        logical = keys[0] if keys else text.replace("\\", "/").lstrip("/")
        return f"memory://{logical}"
    if existing:
        return existing[0]
    if allowed:
        return allowed[0]
    if enforce_jail:
        return ""
    return os.path.abspath(candidates[0]) if candidates else text


def constrain_script_path(
    path: str,
    images_dir: str = "",
    sounds_dir: str = "",
    dicts_dir: str = "",
    yolo_dir: str = "",
    replays_dir: str = "",
    plugins_dir: str = "",
) -> str:
    text = str(path or "").strip()
    if not text:
        raise ValueError("缺少资源路径")
    dirs = _current_dirs(images_dir, sounds_dir, dicts_dir, yolo_dir, replays_dir, plugins_dir)
    jail_kwargs = dict(
        images_dir=dirs["images_dir"],
        sounds_dir=dirs["sounds_dir"],
        dicts_dir=dirs["dicts_dir"],
        yolo_dir=dirs["yolo_dir"],
        replays_dir=dirs["replays_dir"],
        plugins_dir=dirs["plugins_dir"],
    )
    if os.path.isabs(text):
        projected = os.path.abspath(text)
        if not is_allowed_script_path(projected, **jail_kwargs):
            raise ValueError("脚本不能访问该路径")
        return projected
    located = resolve_resource_path(text, enforce_jail=False, **jail_kwargs)
    if located and os.path.exists(located):
        projected = os.path.abspath(located)
    else:
        root = dirs["images_dir"]
        lowered = text.replace("\\", "/").lower()
        normalized = text.replace("\\", "/")
        if lowered.startswith("images/"):
            projected = os.path.abspath(os.path.join(root, normalized[7:]))
        elif lowered.startswith("sounds/"):
            projected = os.path.abspath(os.path.join(dirs["sounds_dir"], normalized[7:]))
        elif lowered.startswith("dicts/"):
            projected = os.path.abspath(os.path.join(dirs["dicts_dir"], normalized[6:]))
        elif lowered.startswith("assets/dicts/"):
            projected = os.path.abspath(os.path.join(dirs["dicts_dir"], normalized[len("assets/dicts/") :]))
        elif lowered.startswith("yolo/") or lowered.endswith(".onnx"):
            projected = os.path.abspath(os.path.join(dirs["yolo_dir"], _kind_suffix(normalized, "yolo")))
        elif lowered.startswith("replays/") or lowered.endswith(".replay.json"):
            projected = os.path.abspath(os.path.join(dirs["replays_dir"], _kind_suffix(normalized, "replays")))
        elif lowered.startswith("plugins/") and not _is_module_offset_literal(normalized):
            projected = os.path.abspath(os.path.join(dirs["plugins_dir"], _kind_suffix(normalized, "plugins")))
        else:
            projected = os.path.abspath(os.path.join(root, text))
    if not is_allowed_script_path(projected, **jail_kwargs):
        raise ValueError("脚本不能访问该路径")
    if os.path.isabs(text):
        return projected
    return text.replace("\\", "/")


def _relative_kind_path(absolute: str, kind_dir: str, folder: str) -> str:
    root = os.path.abspath(str(kind_dir or "").strip())
    if not root:
        return f"{folder}/{os.path.basename(absolute)}"
    root_prefix = os.path.normcase(root) + os.sep
    abs_key = os.path.normcase(absolute)
    if abs_key == os.path.normcase(root):
        return folder
    if abs_key.startswith(root_prefix):
        relative = os.path.relpath(absolute, root).replace(os.sep, "/")
        return f"{folder}/{relative}"
    return f"{folder}/{os.path.basename(absolute)}"


def script_path_for_file(
    abs_path: str,
    kind: str = "",
    images_dir: str = "",
    sounds_dir: str = "",
    dicts_dir: str = "",
    yolo_dir: str = "",
    replays_dir: str = "",
    plugins_dir: str = "",
) -> str:
    text = str(abs_path or "").strip()
    if not text:
        return ""
    absolute = os.path.abspath(text)
    dirs = _current_dirs(images_dir, sounds_dir, dicts_dir, yolo_dir, replays_dir, plugins_dir)
    detected = kind or resource_kind(text)
    if detected == "model":
        return _relative_kind_path(absolute, dirs["yolo_dir"], "yolo")
    if detected == "replay":
        return _relative_kind_path(absolute, dirs["replays_dir"], "replays")
    if detected == "audio":
        return _relative_kind_path(absolute, dirs["sounds_dir"], "sounds")
    if detected == "component":
        return _relative_kind_path(absolute, dirs["plugins_dir"], "plugins")
    if detected == "dict":
        return _relative_kind_path(absolute, dirs["dicts_dir"], "dicts")
    root = os.path.abspath(dirs["images_dir"] or get_images_dir("LCA"))
    root_prefix = os.path.normcase(root) + os.sep
    if os.path.normcase(absolute) == os.path.normcase(root):
        return "images"
    if os.path.normcase(absolute).startswith(root_prefix):
        relative = os.path.relpath(absolute, root).replace(os.sep, "/")
        return f"images/{relative}"
    return normalize_workflow_image_path(text)


def place_resource_file(
    source_path: str,
    kind: str = "",
    images_dir: str = "",
    sounds_dir: str = "",
    dicts_dir: str = "",
    yolo_dir: str = "",
    replays_dir: str = "",
    plugins_dir: str = "",
) -> str:
    """把资源放到绑定目录，返回 images/foo.bmp 这类逻辑路径。"""
    source = os.path.abspath(str(source_path or "").strip())
    if not source or not os.path.isfile(source):
        raise FileNotFoundError(f"资源文件不存在: {source_path}")
    dirs = _current_dirs(images_dir, sounds_dir, dicts_dir, yolo_dir, replays_dir, plugins_dir)
    detected = str(kind or "").strip() or resource_kind(source)
    folder_key = {
        "model": ("yolo_dir", "yolo"),
        "replay": ("replays_dir", "replays"),
        "audio": ("sounds_dir", "sounds"),
        "component": ("plugins_dir", "plugins"),
        "dict": ("dicts_dir", "dicts"),
    }.get(detected, ("images_dir", "images"))
    dest_dir = os.path.abspath(str(dirs.get(folder_key[0]) or dirs["images_dir"] or ""))
    if not dest_dir:
        raise ValueError("未绑定资源目录")
    os.makedirs(dest_dir, exist_ok=True)
    dest_prefix = os.path.normcase(dest_dir) + os.sep
    if os.path.normcase(source).startswith(dest_prefix) or os.path.normcase(source) == os.path.normcase(dest_dir):
        return _relative_kind_path(source, dest_dir, folder_key[1])
    destination = os.path.join(dest_dir, os.path.basename(source))
    if os.path.normcase(os.path.abspath(destination)) != os.path.normcase(source):
        shutil.copy2(source, destination)
    return f"{folder_key[1]}/{os.path.basename(destination)}"


def list_card_files(images_dir: str, card_id: Optional[int] = None, workflow_token: str = "") -> List[str]:
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
    dicts_dir: str = "",
    yolo_dir: str = "",
    replays_dir: str = "",
    plugins_dir: str = "",
) -> List[Dict[str, Any]]:
    dirs = _current_dirs(images_dir, sounds_dir, dicts_dir, yolo_dir, replays_dir, plugins_dir)
    used: Dict[str, Dict[str, Any]] = {}
    for value, start, end in extract_string_literals(source):
        call = enclosing_call_name(source, start)
        if call.startswith("大漠内存.") or call.startswith("大漠汇编."):
            continue
        kind = resource_kind(value)
        if call in _DICT_SCRIPT_CALLS:
            lowered_value = value.replace("\\", "/").lower()
            ext = os.path.splitext(lowered_value)[1]
            if (
                ext in DICT_TEXT_EXTS
                or lowered_value.startswith(("dicts/", "assets/dicts/", "images/dicts/", "assets/images/dicts/"))
                or "/dicts/" in f"/{lowered_value}"
            ):
                kind = "dict"
        if not kind:
            continue
        key = value.replace("\\", "/")
        item = used.get(key)
        if item is None:
            abs_path = resolve_resource_path(value, enforce_jail=False, **dirs)
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
    extra_roots = [
        dirs["images_dir"],
        dirs["sounds_dir"],
        dirs["dicts_dir"],
        dirs["yolo_dir"],
        dirs["replays_dir"],
        dirs["plugins_dir"],
    ]
    for root in extra_roots:
        for abs_path in list_card_files(root, card_id, workflow_token):
            if os.path.normcase(abs_path) in listed:
                continue
            kind = resource_kind(abs_path)
            extras.append(
                {
                    "kind": kind,
                    "path": script_path_for_file(abs_path, kind, **dirs),
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
    dicts_dir: str = "",
    yolo_dir: str = "",
    replays_dir: str = "",
    plugins_dir: str = "",
) -> Dict[str, Any]:
    source = os.path.abspath(str(src_path or "").strip())
    if not os.path.isfile(source):
        raise FileNotFoundError(source)
    dirs = _current_dirs(images_dir, sounds_dir, dicts_dir, yolo_dir, replays_dir, plugins_dir)
    detected = kind or resource_kind(source) or "image"
    if detected == "model":
        directory = dirs["yolo_dir"]
    elif detected == "replay":
        directory = dirs["replays_dir"]
    elif detected == "audio":
        directory = dirs["sounds_dir"]
    elif detected == "component":
        directory = dirs["plugins_dir"]
    elif detected == "dict":
        directory = dirs["dicts_dir"]
    else:
        directory = dirs["images_dir"]
    os.makedirs(directory, exist_ok=True)
    name = os.path.basename(source)
    dest = os.path.join(directory, name)
    if os.path.normcase(os.path.abspath(dest)) != os.path.normcase(source):
        prefixes = card_filename_prefixes(card_id, workflow_token)
        prefix = prefixes[0] if prefixes else ""
        preferred = f"{prefix}{name}" if prefix else name
        dest = os.path.join(directory, preferred)
        if os.path.exists(dest):
            dest = _unique_dest(directory, preferred)
        shutil.copy2(source, dest)
    path = script_path_for_file(dest, detected, **dirs)
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
