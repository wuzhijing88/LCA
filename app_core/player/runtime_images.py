from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

_AUDIO_EXTS = {".wav", ".mp3", ".wma", ".m4a", ".ogg", ".flac"}


def _sound_relative_key(key: str) -> str:
    text = str(key or "").replace("\\", "/").lstrip("/")
    if text.startswith("memory://"):
        text = text[len("memory://") :]
    lowered = text.lower()
    if lowered.startswith("assets/sounds/"):
        return text[len("assets/sounds/") :]
    if lowered.startswith("sounds/"):
        return text[len("sounds/") :]
    return ""


def _map_relative_key(key: str) -> str:
    text = str(key or "").replace("\\", "/").lstrip("/")
    if text.startswith("memory://"):
        text = text[len("memory://") :]
    lowered = text.lower()
    if lowered.startswith("assets/maps/"):
        return text[len("assets/maps/") :]
    if lowered.startswith("maps/"):
        return text[len("maps/") :]
    return ""


def materialize_player_sounds(userdata_dir: str) -> int:
    """把密封包里的音效落到 userdata/sounds，供播放任务按文件名查找。"""
    from app_core.player.memory_store import list_player_memory_files

    root = Path(str(userdata_dir or "").strip())
    if not str(root):
        return 0
    sounds_dir = root / "sounds"
    sounds_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    seen: set[str] = set()
    for key, data in list_player_memory_files().items():
        rel = _sound_relative_key(key)
        if not rel or rel in seen or not data:
            continue
        if Path(rel).suffix.lower() not in _AUDIO_EXTS:
            continue
        if ".." in Path(rel).parts:
            continue
        seen.add(rel)
        destination = sounds_dir / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.is_file():
            continue
        destination.write_bytes(data)
        count += 1
    return count


def materialize_player_maps(userdata_dir: str) -> int:
    """把密封包里的地图落到 userdata/maps，保留每张地图的目录结构。"""
    from app_core.player.memory_store import list_player_memory_files

    root_text = str(userdata_dir or "").strip()
    if not root_text:
        return 0
    maps_dir = Path(root_text) / "maps"
    maps_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    seen: set[str] = set()
    for key, data in list_player_memory_files().items():
        rel = _map_relative_key(key)
        rel_path = Path(rel)
        if (
            not rel
            or rel in seen
            or not data
            or ".." in rel_path.parts
            or rel_path.is_absolute()
            or rel_path.drive
        ):
            continue
        seen.add(rel)
        destination = maps_dir / rel_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.is_file():
            continue
        destination.write_bytes(data)
        count += 1
    return count


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
