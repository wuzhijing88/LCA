from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Mapping, Optional


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
