from __future__ import annotations

import os
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterator, Mapping, Optional


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


class LcaPackageSession:
    """打开的 LCA 工程所包含文件的只读内存映射。"""

    def __init__(self, files: Mapping[str, bytes]):
        self._files = {
            _normalize_logical_path(path): bytes(data)
            for path, data in files.items()
            if _normalize_logical_path(path)
        }
        self._temp_dir = tempfile.TemporaryDirectory(prefix="lca-package-")
        self._resolved_assets: dict[str, str] = {}
        self._resolve_lock = threading.RLock()

    def get_bytes(self, logical_path: object) -> Optional[bytes]:
        path = _normalize_logical_path(logical_path)
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
        return dict(self._files)

    def resolve_asset(self, logical_path: object) -> Optional[str]:
        path = _normalize_logical_path(logical_path)
        data = self.get_bytes(path)
        if data is None:
            return None
        parts = [part for part in path.split("/") if part not in {"", "."}]
        if not parts or ".." in parts:
            return None
        with self._resolve_lock:
            existing = self._resolved_assets.get(path)
            if existing and Path(existing).is_file():
                return existing
            destination = Path(self._temp_dir.name).joinpath(*parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
            resolved = str(destination)
            self._resolved_assets[path] = resolved
            return resolved

    def resource_root(self) -> str:
        return self._temp_dir.name

    def resource_dirs(self) -> Dict[str, str]:
        root = self._temp_dir.name
        dirs = {
            "images_dir": os.path.join(root, "assets", "images"),
            "sounds_dir": os.path.join(root, "assets", "sounds"),
            "dicts_dir": os.path.join(root, "assets", "dicts"),
            "yolo_dir": os.path.join(root, "assets", "yolo"),
            "replays_dir": os.path.join(root, "assets", "replays"),
            "plugins_dir": os.path.join(root, "assets", "components"),
        }
        for path in dirs.values():
            os.makedirs(path, exist_ok=True)
        return dirs


def register(path: object, session: LcaPackageSession) -> LcaPackageSession:
    if not isinstance(session, LcaPackageSession):
        raise TypeError("session 必须是 LcaPackageSession")
    normalized = _normalize_project_path(path)
    with _registry_lock:
        _registry[normalized] = session
    return session


def register_temporary(session: LcaPackageSession) -> str:
    if not isinstance(session, LcaPackageSession):
        raise TypeError("session 必须是 LcaPackageSession")
    path = str(Path(session.resource_root()) / "package.lca")
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
    with _registry_lock:
        _registry.pop(normalized, None)
        if _active_path == normalized:
            _active_path = None
    _clear_resolver_cache()


def deactivate() -> None:
    global _active_path
    with _registry_lock:
        _active_path = None
    _clear_resolver_cache()


def _resolve_active_package_asset(logical_path: str) -> Optional[str]:
    session = get_active()
    if session is None:
        return None
    return session.resolve_asset(logical_path)


def _register_image_path_hook() -> None:
    """把当前工程会话接到通用图片路径解析器上，避免 utils 层反向依赖本模块。"""
    try:
        from utils.image_paths import set_package_asset_resolver

        set_package_asset_resolver(_resolve_active_package_asset)
    except Exception:
        pass


_register_image_path_hook()
