from __future__ import annotations

import atexit
import json
import threading
from typing import Dict, Mapping, Optional


_LOCK = threading.RLock()
_FILES: Dict[str, bytes] = {}
_INSTALLED = False


def clear_player_memory_store() -> None:
    with _LOCK:
        _FILES.clear()


def put_player_memory_file(key: str, data: bytes) -> None:
    normalized = _normalize_key(key)
    if not normalized:
        return
    with _LOCK:
        _FILES[normalized] = data


def get_player_memory_file(key: str) -> Optional[bytes]:
    normalized = _normalize_key(key)
    if not normalized:
        return None
    with _LOCK:
        return _FILES.get(normalized)


def has_player_memory_files() -> bool:
    with _LOCK:
        return bool(_FILES)


def list_player_memory_files() -> Dict[str, bytes]:
    with _LOCK:
        return dict(_FILES)


def _normalize_key(key: str) -> str:
    text = str(key or "").strip().replace("\\", "/")
    if text.startswith("memory://"):
        text = text[len("memory://") :]
    return text.lstrip("/")


def memory_uri(key: str) -> str:
    return "memory://" + _normalize_key(key)


def get_player_memory_json(key: str) -> Optional[dict]:
    raw = get_player_memory_file(key)
    if raw is None:
        return None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _provider(uri: str) -> Optional[bytes]:
    if not uri:
        return None
    key = uri
    if key.startswith("memory://"):
        key = key[len("memory://") :]
    data = get_player_memory_file(key)
    if data is not None:
        return data
    # 兼容只存了文件名的情况
    base = key.rsplit("/", 1)[-1]
    if base and base != key:
        return get_player_memory_file(base)
    return None


def install_player_memory_provider() -> None:
    global _INSTALLED
    try:
        from utils.match.template_preloader import set_memory_image_provider
    except (ImportError, AttributeError):
        return

    set_memory_image_provider(_provider)
    if not _INSTALLED:
        atexit.register(_atexit_clear)
        _INSTALLED = True


def _atexit_clear() -> None:
    clear_player_memory_store()
    try:
        from utils.match.template_preloader import set_memory_image_provider

        set_memory_image_provider(None)
    except Exception:
        pass


def load_files_into_memory(files: Mapping[str, bytes]) -> None:
    clear_player_memory_store()
    for key, data in files.items():
        put_player_memory_file(key, data)
    # 额外用 basename 索引图片，兼容部分卡片只存文件名
    for key, data in list(files.items()):
        norm = _normalize_key(key)
        if norm.startswith("assets/images/"):
            put_player_memory_file("images/" + norm[len("assets/images/") :], data)
            put_player_memory_file(norm.rsplit("/", 1)[-1], data)
        elif norm.startswith("assets/sounds/"):
            put_player_memory_file("sounds/" + norm[len("assets/sounds/") :], data)
            put_player_memory_file(norm.rsplit("/", 1)[-1], data)
        elif norm.startswith("ui_assets/"):
            put_player_memory_file(norm, data)
            put_player_memory_file(norm.rsplit("/", 1)[-1], data)
        elif norm.startswith("workflows/"):
            put_player_memory_file(norm, data)
    install_player_memory_provider()
