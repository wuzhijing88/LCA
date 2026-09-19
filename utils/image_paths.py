# -*- coding: utf-8 -*-
"""Resource path cache. Lookup goes through resolve_resource_path."""

from __future__ import annotations

import logging
import os
import threading
from collections import OrderedDict
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


class ImagePathResolver:
    """Cache over the unified resource reader."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._path_cache: "OrderedDict[str, Optional[str]]" = OrderedDict()
        self._cache_lock = threading.RLock()
        self._cache_enabled = True
        self._max_cache_entries = self._read_cache_limit()

    @staticmethod
    def _read_cache_limit() -> int:
        raw = os.getenv("IMAGE_PATH_CACHE_MAX_ENTRIES", "4096")
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = 4096
        return max(256, min(65536, value))

    def _prune_cache_locked(self):
        while len(self._path_cache) > self._max_cache_entries:
            try:
                self._path_cache.popitem(last=False)
            except Exception:
                break

    def add_search_path(self, path: str, priority: int = -1):
        _ = path
        _ = priority
        self.clear_cache()

    def resolve(self, raw_path: str, search_dirs: Optional[List[str]] = None) -> Optional[str]:
        if not raw_path or not raw_path.strip():
            return None
        raw_path = raw_path.strip()
        if raw_path.startswith("memory://"):
            return raw_path
        cache_key = self._resolve_cache_key(raw_path, search_dirs)
        if self._cache_enabled:
            with self._cache_lock:
                if cache_key in self._path_cache:
                    cached = self._path_cache[cache_key]
                    self._path_cache.move_to_end(cache_key)
                    return cached
        from task_workflow.script_resources import resolve_resource_path

        kwargs = {}
        extra = ""
        if search_dirs:
            extra = str(search_dirs[0] or "").strip()
        if extra:
            kwargs["images_dir"] = extra
        located = resolve_resource_path(raw_path, enforce_jail=False, **kwargs)
        resolved = None
        if located and (str(located).startswith("memory://") or os.path.isfile(located)):
            resolved = located
        if self._cache_enabled and resolved:
            with self._cache_lock:
                self._path_cache[cache_key] = resolved
                self._path_cache.move_to_end(cache_key)
                self._prune_cache_locked()
        return resolved

    def _resolve_cache_key(self, raw_path: str, search_dirs: Optional[List[str]]) -> str:
        extra = ""
        if search_dirs:
            extra = "|" + "|".join(str(item or "") for item in search_dirs)
        bound = ""
        try:
            from task_workflow.resource_context import bound_search_dirs

            bound = "|".join(str(item or "") for item in bound_search_dirs())
        except Exception:
            bound = ""
        return f"{raw_path}||{bound}{extra}"

    def resolve_many(
        self,
        paths: List[str],
        filter_invalid: bool = True,
        search_dirs: Optional[List[str]] = None,
    ) -> List[str]:
        results = []
        for item in paths:
            resolved = self.resolve(item, search_dirs=search_dirs)
            if resolved is not None:
                results.append(resolved)
            elif not filter_invalid:
                results.append(item)
        return results

    def invalidate(self, raw_path: Optional[str] = None) -> None:
        with self._cache_lock:
            if not raw_path:
                self._path_cache.clear()
                return
            raw_path = str(raw_path).strip()
            basename = Path(raw_path.replace("\\", "/")).name.lower()
            drop_keys = []
            for key in self._path_cache:
                raw_part = str(key).split("||", 1)[0]
                if key == raw_path or raw_part == raw_path:
                    drop_keys.append(key)
                    continue
                key_name = Path(str(raw_part).replace("\\", "/")).name.lower()
                if basename and key_name == basename:
                    drop_keys.append(key)
            for key in drop_keys:
                self._path_cache.pop(key, None)

    def clear_cache(self):
        self.invalidate()
        logger.debug("[路径解析器] 缓存已清除")

    def set_cache_enabled(self, enabled: bool):
        self._cache_enabled = enabled
        if not enabled:
            self.clear_cache()

    @classmethod
    def reset_instance(cls):
        cls._instance = None


def get_image_path_resolver() -> ImagePathResolver:
    return ImagePathResolver()
