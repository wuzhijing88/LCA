from __future__ import annotations

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

    def get_bytes(self, logical_path: object) -> Optional[bytes]:
        path = _normalize_logical_path(logical_path)
        data = self._files.get(path)
        if data is None and path.startswith("images/"):
            data = self._files.get(f"assets/{path}")
        return data

    def activate(self) -> "LcaPackageSession":
        global _current_session
        _current_session = self
        return self


def get_current_session() -> Optional[LcaPackageSession]:
    return _current_session
