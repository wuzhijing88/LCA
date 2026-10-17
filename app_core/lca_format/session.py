from __future__ import annotations

import os
import tempfile
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator, Mapping, Optional


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
        self._source_path: Optional[str] = None
        self._closed = False

    @property
    def source_path(self) -> Optional[str]:
        """磁盘入口确认的现行工程路径；纯内存包没有磁盘路径。"""
        return self._source_path

    def bind_source(self, path: object) -> None:
        text = str(path or "").strip()
        if not text:
            raise ValueError("LCA 工程路径不能为空")
        self._source_path = str(Path(text).resolve())
        self._source_stat = _file_source_stat(path)

    def matches_source(self, path: object) -> bool:
        current = _file_source_stat(path)
        return current is not None and current == self._source_stat

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._source_path = None
        self._source_stat = None
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


def _selected_asset_paths(logical_paths: Optional[Iterable[object]]) -> Optional[set[str]]:
    """规范化本次工程实际引用的资源路径。None 表示保留全量落盘行为。"""
    if logical_paths is None:
        return None
    selected: set[str] = set()
    for value in logical_paths:
        path = _normalize_logical_path(value)
        if not path or path == "manifest.json" or path.endswith(".lca"):
            continue
        selected.add(path)
        selected.update(_package_alias_paths(path))
    return selected


def materialize_package_assets(
    session: LcaPackageSession,
    workspace_root: str,
    *,
    logical_paths: Optional[Iterable[object]] = None,
) -> int:
    """把包内资源落到工作区。已有文件不覆盖。

    ``logical_paths`` 传入时只落盘当前工程引用的资源；省略时保留完整导出能力。
    """
    root = str(workspace_root or "").strip()
    if not root:
        return 0
    base = Path(root)
    selected = _selected_asset_paths(logical_paths)
    selected_names = (
        {item for item in selected if "/" not in item}
        if selected is not None
        else set()
    )
    materialized = 0
    with session._files_lock:
        files = tuple(session._files.items())
    for logical, data in files:
        path = str(logical or "").replace("\\", "/").strip().lstrip("/")
        if not path or path == "manifest.json" or path.endswith(".lca"):
            continue
        if path.startswith("workflows/") and path.endswith(".json"):
            continue
        if selected is not None and path not in selected:
            # 未带资源目录的引用只靠文件名定位（如脚本中的“提示.wav”）。
            # 这类引用无法在包内形成唯一逻辑键，按文件名匹配现有解析规则。
            if path.rsplit("/", 1)[-1] not in selected_names:
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
        materialized += 1
    return materialized


def register(path: object, session: LcaPackageSession) -> LcaPackageSession:
    if not isinstance(session, LcaPackageSession):
        raise TypeError("session 必须是 LcaPackageSession")
    if session._closed:
        raise ValueError("工程会话已释放，不能重新注册")
    normalized = _normalize_project_path(path)
    old: Optional[LcaPackageSession] = None
    with _registry_lock:
        old = _registry.get(normalized)
        _registry[normalized] = session
    if old is not None and old is not session:
        old.close()
    return session


def move_path(old_path: object, new_path: object) -> LcaPackageSession:
    """将已注册的工程会话迁移到新路径，并保持会话有效。"""
    global _active_path
    old_normalized = _normalize_project_path(old_path)
    new_normalized = _normalize_project_path(new_path)

    replaced: Optional[LcaPackageSession] = None
    with _registry_lock:
        session = _registry.get(old_normalized)
        if session is None:
            raise KeyError(f"LCA 工程会话未注册: {old_path}")
        if session._closed:
            raise ValueError("工程会话已释放，不能迁移")
        session.bind_source(new_normalized)

        if old_normalized != new_normalized:
            replaced = _registry.get(new_normalized)
            _registry.pop(old_normalized, None)
            _registry[new_normalized] = session
            if _active_path == old_normalized:
                _active_path = new_normalized

    if replaced is not None and replaced is not session:
        replaced.close()
    _clear_resolver_cache()
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
