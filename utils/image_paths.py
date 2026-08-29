# -*- coding: utf-8 -*-
"""Workflow/image path resolver used by tasks and the workspace."""

from __future__ import annotations

import logging
import os
import sys
import threading
from collections import OrderedDict
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


class ImagePathResolver:
    """Resolve workflow image paths across the app images directory."""

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
        self._search_paths: List[Path] = []
        self._path_cache: "OrderedDict[str, Optional[str]]" = OrderedDict()
        self._cache_lock = threading.RLock()
        self._cache_enabled = True
        self._max_cache_entries = self._read_cache_limit()
        self._setup_default_search_paths()
        logger.debug(f"[路径解析器] 初始化完成，搜索路径: {[str(p) for p in self._search_paths]}")

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

    def _setup_default_search_paths(self):
        from utils.app_paths import get_images_dir

        images_dir = Path(get_images_dir("LCA")).resolve()
        self._search_paths = [images_dir]

    def add_search_path(self, path: str, priority: int = -1):
        try:
            p = Path(path).resolve()
        except Exception:
            p = Path(path).absolute()
        if p.exists() and p not in self._search_paths:
            if priority < 0:
                self._search_paths.append(p)
            else:
                self._search_paths.insert(priority, p)
            self.clear_cache()
            logger.info(f"[路径解析器] 添加搜索路径: {p}")

    def resolve(self, raw_path: str) -> Optional[str]:
        if not raw_path or not raw_path.strip():
            return None
        raw_path = raw_path.strip()
        try:
            from app_core.lca_format.session import get_active

            session = get_active()
            if session is not None:
                package_path = session.resolve_asset(raw_path)
                if package_path:
                    return package_path
        except Exception as exc:
            logger.debug("[路径解析器] LCA 包资源解析失败: %s", exc)
        if raw_path.startswith("memory://"):
            return raw_path
        if self._cache_enabled:
            with self._cache_lock:
                if raw_path in self._path_cache:
                    cached = self._path_cache[raw_path]
                    self._path_cache.move_to_end(raw_path)
                    return cached
        resolved = self._do_resolve(raw_path)
        # 未命中不缓存：截图刚落盘时预览常会先解析一次失败，缓存 None 会让刚保存的图一直显示“文件不存在”。
        if self._cache_enabled and resolved:
            with self._cache_lock:
                self._path_cache[raw_path] = resolved
                self._path_cache.move_to_end(raw_path)
                self._prune_cache_locked()
        return resolved

    def _do_resolve(self, raw_path: str) -> Optional[str]:
        if raw_path.startswith("memory://"):
            return raw_path
        normalized = Path(raw_path)
        if normalized.is_absolute():
            if normalized.exists() and normalized.is_file():
                return str(normalized)
            filename = normalized.name
            relative_parts = self._extract_relative_path(raw_path)
        else:
            if (not getattr(sys, "frozen", False)) and normalized.exists() and normalized.is_file():
                return raw_path
            filename = normalized.name
            relative_parts = normalized.parts
        for search_dir in self._search_paths:
            if relative_parts and len(relative_parts) > 1:
                start_idx = 1 if relative_parts[0].lower() == "images" else 0
                if start_idx < len(relative_parts):
                    candidate = search_dir / Path(*relative_parts[start_idx:])
                    if candidate.exists() and candidate.is_file():
                        logger.debug(f"[路径解析器] 找到(子目录): {raw_path} -> {candidate}")
                        return str(candidate)
            candidate = search_dir / filename
            if candidate.exists() and candidate.is_file():
                logger.debug(f"[路径解析器] 找到: {raw_path} -> {candidate}")
                return str(candidate)
        logger.warning(f"[路径解析器] 未找到: {raw_path}")
        return None

    def _extract_relative_path(self, abs_path: str) -> Optional[tuple]:
        try:
            parts = Path(abs_path).parts
            for i, part in enumerate(parts):
                if part.lower() == "images":
                    return parts[i:]
            if len(parts) >= 2:
                return parts[-2:]
            return parts
        except Exception:
            return None

    def resolve_many(self, paths: List[str], filter_invalid: bool = True) -> List[str]:
        results = []
        for item in paths:
            resolved = self.resolve(item)
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
            basename = Path(raw_path).name.lower()
            for key in [item for item in self._path_cache if item == raw_path or Path(item).name.lower() == basename]:
                self._path_cache.pop(key, None)

    def clear_cache(self):
        self.invalidate()
        logger.debug("[路径解析器] 缓存已清除")

    def get_search_paths(self) -> List[str]:
        return [str(p) for p in self._search_paths]

    def set_cache_enabled(self, enabled: bool):
        self._cache_enabled = enabled
        if not enabled:
            self.clear_cache()

    @classmethod
    def reset_instance(cls):
        cls._instance = None


def get_image_path_resolver() -> ImagePathResolver:
    return ImagePathResolver()
