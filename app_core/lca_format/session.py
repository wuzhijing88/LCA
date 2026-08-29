from __future__ import annotations

import tempfile
import threading
from pathlib import Path
from typing import Mapping, Optional


_current_session: Optional["LcaPackageSession"] = None


def _normalize_logical_path(logical_path: object) -> str:
    path = str(logical_path or "").strip().replace("\\", "/")
    if path.startswith("memory://"):
        path = path[len("memory://") :]
    return path.lstrip("/")


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
        if data is None and path.startswith("images/"):
            data = self._files.get(f"assets/{path}")
        return data

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

    def activate(self) -> "LcaPackageSession":
        global _current_session
        _current_session = self
        try:
            from utils.image_paths import get_image_path_resolver

            get_image_path_resolver().clear_cache()
        except Exception:
            pass
        return self


def get_current_session() -> Optional[LcaPackageSession]:
    return _current_session
