# -*- coding: utf-8 -*-
"""自定义脚本资源路径解析。脚本路径不受工程目录边界限制。"""

from __future__ import annotations

import os
import shutil
from typing import Any, Dict, Iterator, List, Optional, Tuple

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
COMPONENT_EXTS = {".dll", ".exe", ".com", ".py"}
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


def _call_name_before(text: str, end: int) -> str:
    start = end - 1
    while start >= 0:
        current = text[start]
        if current.isalnum() or current in "._" or "\u4e00" <= current <= "\u9fff":
            start -= 1
            continue
        break
    return text[start + 1 : end]


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
                return _call_name_before(text, index)
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


def _string_literals_with_calls(source: str) -> Iterator[Tuple[str, int, int, str]]:
    text = str(source or "")
    calls: List[str] = []
    index = 0
    for value, start, end in extract_string_literals(text):
        while index < start:
            char = text[index]
            if char == "(":
                calls.append(_call_name_before(text, index))
            elif char == ")" and calls:
                calls.pop()
            index += 1
        yield value, start, end, calls[-1] if calls else ""


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


def is_direct_component_path(path: str, kind: str = "component") -> bool:
    """绝对组件路径表示外部引用，不属于工程内的 plugins 资源。"""
    text = os.path.expanduser(os.path.expandvars(str(path or "").strip()))
    suffix = os.path.splitext(text.replace("\\", "/").rsplit("/", 1)[-1])[1].lower()
    return (
        str(kind or "").strip() == "component"
        and suffix in {".exe", ".com"}
        and os.path.isabs(text)
    )


def is_managed_resource_file(
    item: Dict[str, Any],
    images_dir: str = "",
    sounds_dir: str = "",
    dicts_dir: str = "",
    yolo_dir: str = "",
    replays_dir: str = "",
    plugins_dir: str = "",
) -> bool:
    """只有绑定资源目录内的文件允许由资源面板重命名或删除。"""
    payload = item if isinstance(item, dict) else {}
    if payload.get("external_path"):
        return False
    raw_path = str(payload.get("path") or "").strip()
    kind = str(payload.get("kind") or resource_kind(raw_path) or "")
    if kind == "component":
        suffix = os.path.splitext(raw_path.replace("\\", "/").rsplit("/", 1)[-1])[1].lower()
        if suffix in {".exe", ".com"}:
            return False
    dirs = _current_dirs(images_dir, sounds_dir, dicts_dir, yolo_dir, replays_dir, plugins_dir)
    roots = {
        "image": dirs["images_dir"],
        "audio": dirs["sounds_dir"],
        "dict": dirs["dicts_dir"],
        "model": dirs["yolo_dir"],
        "replay": dirs["replays_dir"],
        "component": dirs["plugins_dir"],
    }
    root = str(roots.get(kind) or "").strip()
    if not root:
        return False
    absolute = str(payload.get("abs_path") or "").strip()
    if not absolute or not os.path.isfile(absolute):
        absolute = resolve_resource_path(raw_path, enforce_jail=False, **dirs)
    return bool(absolute and os.path.isfile(absolute) and _is_under_root(absolute, root))


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
    if text.lower().startswith(("dicts/", "assets/dicts/")):
        suffix = _kind_suffix(text, "dicts")
        return [f"dicts/{suffix}", f"assets/dicts/{suffix}"]
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
    from app_core.player.memory_store import get_player_memory_file, has_player_memory_files
    from app_core.player.runtime_images import ensure_player_image_memory
    if not has_player_memory_files():
        ensure_player_image_memory()
    if not has_player_memory_files():
        return None
    for key in _memory_resource_keys(path):
        data = get_player_memory_file(key)
        if data is not None:
            return bytes(data)
    return None


def _package_resource_candidates(path: str) -> List[str]:
    """按现行资源目录生成工程包内查找键。"""
    text = str(path or "").replace("\\", "/").strip()
    if text.startswith("memory://"):
        text = text[len("memory://") :]
    text = text.lstrip("/")
    if not text:
        return []
    candidates: List[str] = [text]
    aliases = {
        "image": "images",
        "audio": "sounds",
        "dict": "dicts",
        "model": "yolo",
        "replay": "replays",
        "component": "plugins",
    }
    kind = resource_kind(text) or resource_kind(os.path.basename(text))
    folder = aliases.get(kind)
    if folder:
        suffix = _kind_suffix(text, folder)
        if suffix:
            candidates.extend((f"{folder}/{suffix}", f"assets/{folder}/{suffix}"))
    base = os.path.basename(text)
    if base and folder:
        candidates.extend((f"{folder}/{base}", f"assets/{folder}/{base}"))
        if folder == "yolo":
            candidates.extend((f"models/{base}", f"assets/models/{base}"))
    result: List[str] = []
    seen = set()
    for candidate in candidates:
        normalized = str(candidate or "").replace("\\", "/").lstrip("/")
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _package_resource_bytes(path: str) -> Optional[bytes]:
    from task_workflow.resource_context import current_package_session

    session = current_package_session()
    if session is None:
        return None
    for candidate in _package_resource_candidates(path):
        data = session.get_bytes(candidate)
        if data is not None:
            return bytes(data)
    return None


def _package_resource_path(path: str) -> str:
    from task_workflow.resource_context import current_package_session

    session = current_package_session()
    if session is None:
        return ""
    for candidate in _package_resource_candidates(path):
        if session.get_bytes(candidate) is not None:
            return f"memory://{candidate}"
    return ""


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
        package_data = _package_resource_bytes(located)
        if package_data is not None:
            return package_data
        return _player_memory_bytes(located)
    if located and os.path.isfile(located):
        with open(located, "rb") as handle:
            return handle.read()
    return None


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
    if lowered.startswith("memory://"):
        if _package_resource_bytes(text) is not None:
            return text
        return text if _player_memory_bytes(text) is not None else ""
    if os.path.isabs(text):
        absolute = os.path.abspath(os.path.expanduser(os.path.expandvars(text)))
        if enforce_jail and not is_allowed_script_path(absolute, **dirs):
            return ""
        return absolute
    package_path = _package_resource_path(text)
    if package_path:
        return package_path
    if not _is_module_offset_literal(text) and (
        os.path.splitext(lowered)[1] in COMPONENT_EXTS
        or lowered.startswith(("plugins/", "assets/components/"))
    ):
        suffix = _kind_suffix(text, "plugins")
        absolute = os.path.abspath(os.path.join(dirs["plugins_dir"], suffix))
        if enforce_jail and not is_allowed_script_path(absolute, **dirs):
            return ""
        return absolute
    if os.path.splitext(lowered)[1] in DICT_TEXT_EXTS or lowered.startswith(("dicts/", "assets/dicts/")):
        suffix = text
        for prefix in ("assets/dicts/", "dicts/"):
            if lowered.startswith(prefix):
                suffix = text[len(prefix):]
                break
        absolute = os.path.abspath(os.path.join(dirs["dicts_dir"], suffix))
        if enforce_jail and not is_allowed_script_path(absolute, **dirs):
            return ""
        if os.path.isfile(absolute):
            return absolute
        logical = f"dicts/{suffix}"
        if _player_memory_bytes(logical) is not None:
            return f"memory://{logical}"
        return absolute
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


def resolve_script_program_path(
    path: str,
    *,
    require_file: bool = True,
    images_dir: str = "",
    sounds_dir: str = "",
    dicts_dir: str = "",
    yolo_dir: str = "",
    replays_dir: str = "",
    plugins_dir: str = "",
) -> str:
    """按绝对路径、plugins 资源路径、当前目录相对路径、PATH 命令名的顺序解析程序。"""
    raw = os.path.expandvars(os.path.expanduser(str(path or "").strip()))
    if not raw:
        raise ValueError("程序不能为空")
    if _is_module_offset_literal(raw):
        raise ValueError("模块地址不能作为程序路径，请使用大漠内存或大漠汇编命令")
    lowered = raw.replace("\\", "/").lower()
    if os.path.isabs(raw):
        resolved = os.path.abspath(raw)
    elif lowered.startswith(("plugins/", "assets/components/")):
        dirs = _current_dirs(images_dir, sounds_dir, dicts_dir, yolo_dir, replays_dir, plugins_dir)
        located = resolve_resource_path(raw, enforce_jail=False, **dirs)
        resolved = os.path.abspath(located) if located and os.path.isfile(located) else ""
    elif "/" in lowered or "\\" in raw:
        resolved = os.path.abspath(raw)
    elif os.path.isfile(raw):
        resolved = os.path.abspath(raw)
    else:
        import shutil

        located = shutil.which(raw)
        resolved = os.path.abspath(located) if located else raw
    if require_file and (not resolved or not os.path.isfile(resolved)):
        raise FileNotFoundError(f"程序文件不存在: {raw}")
    return resolved


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
    resource_kwargs = dict(
        images_dir=dirs["images_dir"],
        sounds_dir=dirs["sounds_dir"],
        dicts_dir=dirs["dicts_dir"],
        yolo_dir=dirs["yolo_dir"],
        replays_dir=dirs["replays_dir"],
        plugins_dir=dirs["plugins_dir"],
    )
    if os.path.isabs(text):
        return os.path.abspath(os.path.expanduser(text))
    located = resolve_resource_path(text, enforce_jail=False, **resource_kwargs)
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
            projected = os.path.abspath(os.path.expanduser(text))
    return projected


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
    if is_direct_component_path(absolute, detected):
        return absolute.replace("\\", "/")
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
    # 可执行程序是直接引用的外部路径，不属于工程资源包，也不复制到插件目录。
    if is_direct_component_path(source, detected):
        return source.replace("\\", "/")
    folder_key = {
        "image": ("images_dir", "images"),
        "model": ("yolo_dir", "yolo"),
        "replay": ("replays_dir", "replays"),
        "audio": ("sounds_dir", "sounds"),
        "component": ("plugins_dir", "plugins"),
        "dict": ("dicts_dir", "dicts"),
    }.get(detected)
    if folder_key is None:
        raise ValueError(f"不支持的资源类型，不能导入图库：{source_path}")
    root = str(dirs.get(folder_key[0]) or "").strip()
    if not root:
        raise ValueError("未绑定资源目录")
    dest_dir = os.path.abspath(root)
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
    for value, start, end, call in _string_literals_with_calls(source):
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
    # 进程启动使用原文件的绝对路径。选择程序只是登记路径，不能把程序复制到 plugins。
    if is_direct_component_path(source, detected):
        return {
            "kind": "component",
            "path": source.replace("\\", "/"),
            "abs_path": source,
            "name": os.path.basename(source),
            "exists": True,
            "used": 0,
            "unused": True,
            "spans": [],
            "external_path": True,
        }
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
    dicts_dir: str = "",
    yolo_dir: str = "",
    replays_dir: str = "",
    plugins_dir: str = "",
) -> Dict[str, Any]:
    source = os.path.abspath(str(src_path or "").strip())
    if not os.path.isfile(source):
        raise FileNotFoundError(source)
    current = str((item or {}).get("abs_path") or "")
    kind = str((item or {}).get("kind") or resource_kind(source) or "image")
    managed = is_managed_resource_file(
        item,
        images_dir=images_dir,
        sounds_dir=sounds_dir,
        dicts_dir=dicts_dir,
        yolo_dir=yolo_dir,
        replays_dir=replays_dir,
        plugins_dir=plugins_dir,
    )
    if (
        managed
        and current
        and os.path.isfile(current)
        and os.path.normcase(os.path.abspath(current)) != os.path.normcase(source)
        and os.path.splitext(current)[1].lower() == os.path.splitext(source)[1].lower()
    ):
        shutil.copy2(source, current)
        updated = dict(item or {})
        updated["exists"] = True
        updated["abs_path"] = os.path.abspath(current)
        return updated
    if current and os.path.normcase(os.path.abspath(current)) == os.path.normcase(source):
        return dict(item or {})
    imported = import_resource_file(
        source,
        images_dir,
        kind=kind,
        sounds_dir=sounds_dir,
        dicts_dir=dicts_dir,
        yolo_dir=yolo_dir,
        replays_dir=replays_dir,
        plugins_dir=plugins_dir,
    )
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
    dicts_dir: str = "",
    yolo_dir: str = "",
    replays_dir: str = "",
    plugins_dir: str = "",
) -> Tuple[str, Dict[str, Any]]:
    name = os.path.basename(str(new_name or "").strip())
    if not name or name in {".", ".."} or any(char in name for char in '\\/:*?"<>|'):
        raise ValueError("文件名不合法")
    abs_path = str((item or {}).get("abs_path") or "")
    if not abs_path or not os.path.isfile(abs_path):
        raise FileNotFoundError(abs_path or name)
    if not is_managed_resource_file(
        item,
        images_dir=images_dir,
        sounds_dir=sounds_dir,
        dicts_dir=dicts_dir,
        yolo_dir=yolo_dir,
        replays_dir=replays_dir,
        plugins_dir=plugins_dir,
    ):
        raise ValueError("只能重命名绑定资源目录内的文件")
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


def delete_resource_file(
    item: Dict[str, Any],
    images_dir: str = "",
    sounds_dir: str = "",
    dicts_dir: str = "",
    yolo_dir: str = "",
    replays_dir: str = "",
    plugins_dir: str = "",
) -> None:
    abs_path = str((item or {}).get("abs_path") or "")
    if not is_managed_resource_file(
        item,
        images_dir=images_dir,
        sounds_dir=sounds_dir,
        dicts_dir=dicts_dir,
        yolo_dir=yolo_dir,
        replays_dir=replays_dir,
        plugins_dir=plugins_dir,
    ):
        raise ValueError("只能删除绑定资源目录内的文件")
    if abs_path and os.path.isfile(abs_path):
        os.remove(abs_path)
