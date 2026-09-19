from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

_AUDIO_EXTS = {".wav", ".mp3", ".wma", ".m4a", ".ogg", ".flac"}


def _relative_under_prefixes(key: str, prefixes: tuple[str, ...]) -> str:
    text = str(key or "").replace("\\", "/").lstrip("/")
    if text.startswith("memory://"):
        text = text[len("memory://") :]
    lowered = text.lower()
    for prefix in prefixes:
        if lowered.startswith(prefix):
            return text[len(prefix) :]
    return ""


def _materialize_memory_tree(
    userdata_dir: str,
    folder: str,
    prefixes: tuple[str, ...],
    suffix_allowed: Callable[[str], bool],
) -> int:
    from app_core.player.memory_store import list_player_memory_files

    root = Path(str(userdata_dir or "").strip())
    if not str(root):
        return 0
    dest_root = root / folder
    dest_root.mkdir(parents=True, exist_ok=True)
    count = 0
    seen: set[str] = set()
    for key, data in list_player_memory_files().items():
        rel = _relative_under_prefixes(key, prefixes)
        if not rel or rel in seen or not data:
            continue
        if ".." in Path(rel).parts:
            continue
        if not suffix_allowed(rel):
            continue
        seen.add(rel)
        destination = dest_root / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.is_file():
            continue
        destination.write_bytes(data)
        count += 1
    return count


def materialize_player_sounds(userdata_dir: str) -> int:
    """把密封包里的音效落到 userdata/sounds，供播放任务按文件名查找。"""
    return _materialize_memory_tree(
        userdata_dir,
        "sounds",
        ("assets/sounds/", "sounds/"),
        lambda rel: Path(rel).suffix.lower() in _AUDIO_EXTS,
    )


def materialize_player_replays(userdata_dir: str) -> int:
    """把密封包里的回放落到 userdata/replays。"""
    return _materialize_memory_tree(
        userdata_dir,
        "replays",
        ("assets/replays/", "replays/"),
        lambda rel: rel.lower().endswith(".replay.json"),
    )


def materialize_player_dicts(userdata_dir: str) -> int:
    """把密封包里的字库落到 userdata/dicts。"""
    return _materialize_memory_tree(
        userdata_dir,
        "dicts",
        ("assets/dicts/", "dicts/"),
        lambda _rel: True,
    )


def materialize_player_yolo(userdata_dir: str) -> int:
    """把密封包里的 YOLO 模型落到 userdata/yolo。"""
    return _materialize_memory_tree(
        userdata_dir,
        "yolo",
        ("assets/yolo/", "assets/models/", "yolo/", "models/"),
        lambda rel: Path(rel).suffix.lower() in {".onnx", ".txt"},
    )


def materialize_player_components(userdata_dir: str) -> int:
    """把密封包里的脚本外部组件落到 userdata/components。"""
    return _materialize_memory_tree(
        userdata_dir,
        "components",
        ("assets/components/", "components/", "plugins/"),
        lambda rel: Path(rel).suffix.lower() in {".dll", ".exe", ".py"},
    )


def resolve_get_image_data(payload: Optional[Mapping[str, Any]] = None) -> Optional[Callable[[str], Optional[bytes]]]:
    data = payload if isinstance(payload, Mapping) else {}
    explicit = data.get("get_image_data")
    if callable(explicit):
        return explicit
    from app_core.player.memory_store import get_player_memory_file, has_player_memory_files

    if has_player_memory_files():
        return get_player_memory_file
    return None


def ensure_player_image_memory() -> bool:
    """让当前进程能读独立程序包里的 memory:// 图片（含子进程）。"""
    from app_core.player.memory_store import has_player_memory_files, install_player_memory_provider

    if has_player_memory_files():
        install_player_memory_provider()
        return True

    export_root = str(os.environ.get("LCA_EXPORT_ROOT") or "").strip()
    if not export_root:
        return False
    root = Path(os.path.expandvars(export_root)).expanduser()
    try:
        from app_core.player.secure_package import find_sealed_package, load_sealed_package_memory
    except Exception:
        return False
    if find_sealed_package(root) is None:
        return False
    try:
        load_sealed_package_memory(root)
    except Exception:
        return False
    if not has_player_memory_files():
        return False
    install_player_memory_provider()
    return True
