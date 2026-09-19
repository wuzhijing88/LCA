from __future__ import annotations

import os
import tempfile
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Mapping, Optional


_registry: dict[str, "LcaPackageSession"] = {}
_active_path: Optional[str] = None
_registry_lock = threading.RLock()


def _normalize_project_path(path: object) -> str:
    text = str(path or "").strip()
    if not text:
        raise ValueError("LCA 工程路径不能为空")
    return os.path.normcase(os.path.abspath(os.path.normpath(text)))


def _clear_resolver_cache() -> None:
    try:
        from utils.image_paths import get_image_path_resolver

        get_image_path_resolver().clear_cache()
    except Exception:
        pass


_PACKAGE_LOGICAL_ALIASES = (
    ("images/", "assets/images/"),
    ("sounds/", "assets/sounds/"),
    ("yolo/", "assets/yolo/"),
    ("models/", "assets/yolo/"),
    ("replays/", "assets/replays/"),
    ("dicts/", "assets/dicts/"),
    ("plugins/", "assets/components/"),
)


def _normalize_logical_path(logical_path: object) -> str:
    path = str(logical_path or "").strip().replace("\\", "/")
    if path.startswith("memory://"):
        path = path[len("memory://") :]
    return path.lstrip("/")


def _package_alias_paths(path: str) -> list[str]:
    aliases = []
    for logical, packaged in _PACKAGE_LOGICAL_ALIASES:
        if path.startswith(logical):
            aliases.append(packaged + path[len(logical) :])
        elif path.startswith(packaged):
            aliases.append(logical + path[len(packaged) :])
    return aliases


def _file_source_stat(path: object) -> Optional[tuple[int, int]]:
    text = str(path or "").strip()
    if not text or not os.path.isfile(text):
        return None
    try:
        stat = os.stat(text)
        return int(stat.st_mtime_ns), int(stat.st_size)
    except OSError:
        return None


_ASSET_FOLDER_PREFIXES = (
    ("assets/images/", "images"),
    ("images/", "images"),
    ("assets/sounds/", "sounds"),
    ("sounds/", "sounds"),
    ("assets/dicts/", "dicts"),
    ("dicts/", "dicts"),
    ("assets/yolo/", "yolo"),
    ("assets/models/", "yolo"),
    ("yolo/", "yolo"),
    ("models/", "yolo"),
    ("assets/replays/", "replays"),
    ("replays/", "replays"),
    ("assets/components/", "plugins"),
    ("plugins/", "plugins"),
)


class LcaPackageSession:
    """打开的 LCA 工程所包含文件的只读内存映射，供保存/嵌套工作流使用。运行时资源不走这里。"""

    def __init__(self, files: Mapping[str, bytes]):
        self._files = {
            _normalize_logical_path(path): bytes(data)
            for path, data in files.items()
            if _normalize_logical_path(path)
        }
        self._files_lock = threading.RLock()
        self._source_stat: Optional[tuple[int, int]] = None
        self._closed = False

    def bind_source(self, path: object) -> None:
        self._source_stat = _file_source_stat(path)

    def matches_source(self, path: object) -> bool:
        current = _file_source_stat(path)
        return current is not None and current == self._source_stat

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        with self._files_lock:
            self._files.clear()

    def get_bytes(self, logical_path: object) -> Optional[bytes]:
        path = _normalize_logical_path(logical_path)
        with self._files_lock:
            data = self._files.get(path)
            if data is not None:
                return data
            for alias in _package_alias_paths(path):
                data = self._files.get(alias)
                if data is not None:
                    return data
        return None

    def snapshot_files(self) -> dict[str, bytes]:
        """返回包内文件快照，供导出等只读收集流程使用。"""
        with self._files_lock:
            return dict(self._files)


def materialize_package_assets(session: LcaPackageSession, workspace_root: str) -> None:
    """把包内资源落到工作区。已有文件不覆盖。"""
    root = str(workspace_root or "").strip()
    if not root:
        return
    base = Path(root)
    for logical, data in session.snapshot_files().items():
        path = str(logical or "").replace("\\", "/").strip().lstrip("/")
        if not path or path == "manifest.json" or path.endswith(".lca"):
            continue
        if path.startswith("workflows/") and path.endswith(".json"):
            continue
        dest_rel = None
        for prefix, folder in _ASSET_FOLDER_PREFIXES:
            if path.startswith(prefix):
                rest = path[len(prefix) :]
                dest_rel = Path(folder) / rest if rest else None
                break
        if dest_rel is None:
            continue
        destination = base / dest_rel
        if destination.exists():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)


def register(path: object, session: LcaPackageSession) -> LcaPackageSession:
    if not isinstance(session, LcaPackageSession):
        raise TypeError("session 必须是 LcaPackageSession")
    normalized = _normalize_project_path(path)
    old: Optional[LcaPackageSession] = None
    with _registry_lock:
        old = _registry.get(normalized)
        _registry[normalized] = session
    if old is not None and old is not session:
        old.close()
    return session


def register_temporary(session: LcaPackageSession) -> str:
    if not isinstance(session, LcaPackageSession):
        raise TypeError("session 必须是 LcaPackageSession")
    path = os.path.join(tempfile.gettempdir(), f"lca-nested-{uuid.uuid4().hex}.lca")
    register(path, session)
    return _normalize_project_path(path)


@contextmanager
def active_session_scope(
    path: object,
    session: Optional[LcaPackageSession] = None,
) -> Iterator[None]:
    previous = get_active_path()
    target = str(path or "").strip()
    if not target:
        raise ValueError("LCA 工程路径不能为空")
    if session is not None:
        register(target, session)
    activate(target)
    try:
        yield
    finally:
        if previous:
            with _registry_lock:
                previous_session = _registry.get(previous)
            if previous_session is not None:
                activate(previous)
            else:
                deactivate()
        else:
            deactivate()


def activate(path: object) -> LcaPackageSession:
    global _active_path
    normalized = _normalize_project_path(path)
    with _registry_lock:
        session = _registry.get(normalized)
        if session is None:
            raise KeyError(f"LCA 工程会话未注册: {path}")
        _active_path = normalized
    _clear_resolver_cache()
    return session


def get_active() -> Optional[LcaPackageSession]:
    with _registry_lock:
        if _active_path is None:
            return None
        return _registry.get(_active_path)


def get_active_path() -> str:
    with _registry_lock:
        return _active_path or ""


def get_for_path(path: object) -> Optional[LcaPackageSession]:
    try:
        normalized = _normalize_project_path(path)
    except ValueError:
        return None
    with _registry_lock:
        return _registry.get(normalized)


def clear_path(path: object) -> None:
    global _active_path
    try:
        normalized = _normalize_project_path(path)
    except ValueError:
        return
    old: Optional[LcaPackageSession] = None
    with _registry_lock:
        old = _registry.pop(normalized, None)
        if _active_path == normalized:
            _active_path = None
    if old is not None:
        old.close()
    _clear_resolver_cache()


def deactivate() -> None:
    global _active_path
    with _registry_lock:
        _active_path = None
    _clear_resolver_cache()

