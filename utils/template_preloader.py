#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模板图片预加载器
在工作流执行前预加载模板图片到内存，减少 I/O 延迟。
"""

import logging
import os
import threading
import hashlib
from collections import OrderedDict
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# 延迟导入 cv2，减少启动开销
cv2 = None

_memory_image_provider: Optional[Callable[[str], Optional[bytes]]] = None


def _read_int_env(name: str, default: int, min_value: int, max_value: int) -> int:
    """读取整型环境变量并限制范围。"""
    try:
        value = int(os.getenv(name, str(default)))
    except Exception:
        value = default
    return max(min_value, min(max_value, value))


def _ensure_cv2():
    """延迟导入 cv2。"""
    global cv2
    if cv2 is None:
        import cv2 as _cv2
        cv2 = _cv2




def get_memory_image_provider() -> Optional[Callable[[str], Optional[bytes]]]:
    return _memory_image_provider


class TemplatePreloader:
    """
    模板图片预加载器。

    注意：
    - 仅缓存模板图像数据。
    - 不缓存识别结果（窗口内容是实时变化的）。
    """

    def __init__(self):
        self.template_cache: Dict[str, np.ndarray] = {}
        self._template_signatures: Dict[str, Optional[Tuple[int, int]]] = {}
        self._template_sizes: Dict[str, int] = {}
        self._cache_order: OrderedDict[str, None] = OrderedDict()
        self._cache_lock = threading.RLock()
        self._workflow_preload_lock = threading.RLock()
        self._workflow_preload_inflight: Dict[str, threading.Event] = {}
        self._workflow_preload_done: OrderedDict[str, None] = OrderedDict()
        self._max_workflow_preload_keys = 256
        self._max_cache_bytes = (
            _read_int_env("TEMPLATE_CACHE_MAX_MB", 128, 16, 2048) * 1024 * 1024
        )
        self._stats = {
            "total_loaded": 0,
            "total_failed": 0,
            "total_size_bytes": 0,
        }

    def _touch_workflow_preload_key(self, key: str) -> None:
        self._workflow_preload_done.pop(key, None)
        self._workflow_preload_done[key] = None
        while len(self._workflow_preload_done) > self._max_workflow_preload_keys:
            try:
                self._workflow_preload_done.popitem(last=False)
            except Exception:
                break

    def _build_workflow_preload_key(self, workflow_data: dict) -> str:
        cards = workflow_data.get("cards", []) if isinstance(workflow_data, dict) else []
        if not isinstance(cards, list):
            cards = []

        unique_paths: List[str] = []
        seen_paths = set()
        for card in cards:
            if not isinstance(card, dict):
                continue
            params = card.get("parameters", {})
            for image_path in self._extract_paths_from_params(params):
                normalized = self._normalize_cache_key(image_path)
                if not normalized:
                    continue
                if normalized in seen_paths:
                    continue
                seen_paths.add(normalized)
                unique_paths.append(normalized)

        if not unique_paths:
            return "workflow_templates:empty"

        unique_paths.sort()
        digest_input = "\n".join(unique_paths)
        digest = hashlib.sha1(digest_input.encode("utf-8", errors="ignore")).hexdigest()
        return f"workflow_templates:{len(unique_paths)}:{digest}"

    def _normalize_cache_key(self, image_path: str) -> str:
        """规范化缓存键，确保同一文件只有一条缓存链路。"""
        raw = str(image_path or "").strip()
        if not raw:
            return ""
        if raw.startswith("memory://"):
            return raw
        try:
            return os.path.normcase(os.path.normpath(os.path.abspath(raw)))
        except Exception:
            try:
                return os.path.normpath(raw)
            except Exception:
                return raw

    def _resolve_file_path(self, image_path: str) -> Optional[str]:
        """解析图片路径，优先复用统一路径解析器。"""
        raw = str(image_path or "").strip()
        if not raw:
            return None
        if raw.startswith("memory://"):
            return raw

        if os.path.isfile(raw):
            return raw

        from tasks.task_utils import correct_single_image_path

        resolved = correct_single_image_path(raw)
        if resolved:
            return str(resolved)
        return None

    def _build_cache_keys(self, image_path: str) -> List[str]:
        """构建缓存键，只使用解析后的现行路径。"""
        raw = str(image_path or "").strip()
        if not raw:
            return []

        resolved = self._resolve_file_path(raw)
        if not resolved:
            return []
        resolved_key = self._normalize_cache_key(resolved)
        return [resolved_key] if resolved_key else []

    @staticmethod
    def _parse_multiline_paths(raw_text: str) -> List[str]:
        """解析多行图片路径文本，兼容注释与共同目录格式。"""
        text = str(raw_text or "").strip()
        if not text:
            return []

        results: List[str] = []
        common_dir: Optional[str] = None

        for raw_line in text.splitlines():
            line = (
                str(raw_line)
                .replace("\u200b", "")
                .replace("\u200c", "")
                .replace("\u200d", "")
                .replace("\ufeff", "")
                .strip()
            )
            if not line:
                continue

            if line.startswith("# 共同目录:") or line.startswith("#共同目录:"):
                parts = line.split(":", 1)
                common_dir = parts[1].strip() if len(parts) > 1 else None
                continue

            if line.startswith("#"):
                continue

            if "  # " in line:
                filename, directory = line.split("  # ", 1)
                filename = filename.strip()
                directory = directory.strip()
                if filename and directory:
                    line = os.path.join(directory, filename)
                else:
                    line = filename or directory

            if common_dir and line and (not os.path.isabs(line)) and (not line.startswith("memory://")):
                line = os.path.join(common_dir, line)

            line = line.strip()
            if line:
                results.append(line)

        return results

    @classmethod
    def _split_image_path_value(cls, raw_text: str) -> List[str]:
        text = str(raw_text or "").strip()
        if not text:
            return []
        if "\n" in text or "\r" in text:
            return cls._parse_multiline_paths(text)
        if ";" in text:
            return [part.strip() for part in text.split(";") if part.strip()]
        return [text]

    def _extract_paths_from_params(self, params: dict) -> List[str]:
        """从卡片参数中提取所有模板路径字段。"""
        if not isinstance(params, dict):
            return []

        candidates: List[str] = []

        single_fields = (
            "target_image",
            "image_path",
            "target_image_path",
            "drag_start_image_path",
            "drag_end_image_path",
        )
        for field in single_fields:
            value = params.get(field)
            if isinstance(value, str):
                value = value.strip()
                if value:
                    candidates.append(value)

        list_fields = ("target_images",)
        for field in list_fields:
            value = params.get(field)
            if isinstance(value, (list, tuple, set)):
                for item in value:
                    if isinstance(item, str):
                        item = item.strip()
                        if item:
                            candidates.append(item)
            elif isinstance(value, str):
                text_value = value.strip()
                if not text_value:
                    continue
                candidates.extend(self._split_image_path_value(text_value))

        image_paths_value = params.get("image_paths")
        if isinstance(image_paths_value, str) and image_paths_value.strip():
            candidates.extend(self._split_image_path_value(image_paths_value))

        results: List[str] = []
        seen: set = set()
        for path in candidates:
            normalized = str(path).strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            results.append(normalized)
        return results

    def _touch_template(self, image_path: str) -> None:
        """更新模板最近使用顺序。"""
        self._cache_order.pop(image_path, None)
        self._cache_order[image_path] = None

    def _enforce_cache_limit(self) -> None:
        """按LRU策略回收模板缓存，防止主进程内存持续膨胀。"""
        if self._max_cache_bytes <= 0:
            return
        while (
            int(self._stats.get("total_size_bytes", 0)) > self._max_cache_bytes
            and self._cache_order
        ):
            oldest_key, _ = self._cache_order.popitem(last=False)
            self._evict_template(oldest_key)

    def _get_file_signature(self, image_path: str) -> Optional[Tuple[int, int]]:
        """
        返回文件签名：`(mtime_ns, size)`。
        对 `memory://` 或不可访问文件返回 `None`。
        """
        if not image_path or image_path.startswith("memory://"):
            return None

        try:
            file_stat = os.stat(image_path)
            return int(file_stat.st_mtime_ns), int(file_stat.st_size)
        except OSError:
            return None

    def _is_cache_fresh(self, image_path: str) -> bool:
        """判断缓存是否仍然有效。"""
        if image_path not in self.template_cache:
            return False

        if image_path.startswith("memory://"):
            return True

        current_signature = self._get_file_signature(image_path)
        cached_signature = self._template_signatures.get(image_path)
        if current_signature is None:
            return False

        return cached_signature == current_signature

    def _evict_template(self, image_path: str) -> None:
        """移除指定模板缓存并更新统计。"""
        cached_template = self.template_cache.pop(image_path, None)
        self._template_signatures.pop(image_path, None)
        cached_size = self._template_sizes.pop(image_path, None)
        self._cache_order.pop(image_path, None)

        if cached_size is None and cached_template is not None:
            cached_size = int(getattr(cached_template, "nbytes", 0) or 0)

        if cached_size:
            self._stats["total_size_bytes"] = max(
                0, int(self._stats["total_size_bytes"]) - int(cached_size)
            )

    def preload_workflow_templates(self, workflow_data: dict) -> int:
        """预加载工作流中的模板图。"""
        _ensure_cv2()
        preload_key = self._build_workflow_preload_key(workflow_data)
        owner_event: Optional[threading.Event] = None

        with self._workflow_preload_lock:
            if preload_key in self._workflow_preload_done:
                self._touch_workflow_preload_key(preload_key)
                logger.debug("模板预加载已完成，跳过重复请求: key=%s", preload_key)
                return 0
            inflight_event = self._workflow_preload_inflight.get(preload_key)
            if inflight_event is not None:
                owner_event = inflight_event
            else:
                owner_event = threading.Event()
                self._workflow_preload_inflight[preload_key] = owner_event
                inflight_event = None

        if inflight_event is not None:
            owner_event.wait(timeout=30.0)
            with self._workflow_preload_lock:
                if preload_key in self._workflow_preload_done:
                    self._touch_workflow_preload_key(preload_key)
                    logger.debug("模板预加载等待完成，跳过重复执行: key=%s", preload_key)
                    return 0
            logger.warning("模板预加载等待超时，跳过重复执行: key=%s", preload_key)
            return 0

        logger.info("开始预加载工作流模板图片...")
        loaded_count = 0

        try:
            cards = workflow_data.get("cards", [])
            if not isinstance(cards, list):
                cards = []

            seen_keys: set = set()
            for card in cards:
                if not isinstance(card, dict):
                    continue
                params = card.get("parameters", {})
                for image_path in self._extract_paths_from_params(params):
                    cache_keys = self._build_cache_keys(image_path)
                    dedupe_key = cache_keys[0] if cache_keys else image_path
                    if dedupe_key in seen_keys:
                        continue
                    seen_keys.add(dedupe_key)
                    if self._load_template(image_path):
                        loaded_count += 1

            logger.info(
                "模板预加载完成: 成功=%s, 失败=%s, 内存占用=%.2fMB",
                loaded_count,
                self._stats["total_failed"],
                self._stats["total_size_bytes"] / 1024 / 1024,
            )
            return loaded_count
        finally:
            with self._workflow_preload_lock:
                self._workflow_preload_inflight.pop(preload_key, None)
                self._touch_workflow_preload_key(preload_key)
                if owner_event is not None:
                    owner_event.set()

    def _load_template(self, image_path: str) -> bool:
        """加载并缓存单个模板图。"""
        raw_path = str(image_path or "").strip()
        if not raw_path:
            return False

        cache_keys = self._build_cache_keys(raw_path)
        cache_key = cache_keys[0] if cache_keys else ""
        if not cache_key:
            return False

        resolved_path = self._resolve_file_path(raw_path)
        if raw_path.startswith("memory://"):
            resolved_path = raw_path

        with self._cache_lock:
            for key in cache_keys:
                if key not in self.template_cache:
                    continue
                if self._is_cache_fresh(key):
                    self._touch_template(key)
                    logger.debug(f"模板已缓存，跳过: {key}")
                    return True
                self._evict_template(key)

        if not resolved_path:
            logger.warning(f"模板文件不存在: {raw_path}")
            self._stats["total_failed"] += 1
            return False

        if (not resolved_path.startswith("memory://")) and (not os.path.exists(resolved_path)):
            logger.warning(f"模板文件不存在: {resolved_path}")
            self._stats["total_failed"] += 1
            return False

        try:
            _ensure_cv2()

            image_bytes: Optional[bytes] = None
            if resolved_path.startswith("memory://"):
                provider = get_memory_image_provider()
                if callable(provider):
                    try:
                        image_bytes = provider(resolved_path)
                    except Exception:
                        image_bytes = None

                if not image_bytes:
                    logger.warning(f"无法从内存提供器读取模板图片: {resolved_path}")
                    self._stats["total_failed"] += 1
                    return False

                file_array = np.frombuffer(image_bytes, dtype=np.uint8)
            else:
                file_array = np.fromfile(resolved_path, dtype=np.uint8)

            if file_array is None or len(file_array) == 0:
                logger.warning(f"无法读取模板图片文件: {resolved_path}")
                self._stats["total_failed"] += 1
                return False

            template = cv2.imdecode(file_array, cv2.IMREAD_UNCHANGED)
            if template is None:
                logger.warning(f"无法解码模板图片: {resolved_path}")
                self._stats["total_failed"] += 1
                return False

            template_size = int(template.nbytes)

            with self._cache_lock:
                # 并发场景下再次确认，避免重复累计
                for key in cache_keys:
                    if key in self.template_cache:
                        self._evict_template(key)

                self.template_cache[cache_key] = template
                self._template_signatures[cache_key] = self._get_file_signature(cache_key)
                self._template_sizes[cache_key] = template_size
                self._touch_template(cache_key)

                self._stats["total_loaded"] += 1
                self._stats["total_size_bytes"] += template_size
                self._enforce_cache_limit()

                cached_ok = cache_key in self.template_cache

            logger.debug(f"预加载模板成功: {cache_key} ({template_size / 1024:.2f}KB)")
            return cached_ok
        except Exception as error:
            logger.error(f"预加载模板失败 {raw_path}: {error}")
            self._stats["total_failed"] += 1
            return False

    def get_template(self, image_path: str) -> Optional[np.ndarray]:
        """获取模板图；缓存失效时自动重载。"""
        cache_keys = self._build_cache_keys(image_path)
        with self._cache_lock:
            for key in cache_keys:
                cached = self.template_cache.get(key)
                if cached is None:
                    continue
                if self._is_cache_fresh(key):
                    self._touch_template(key)
                    return cached
                self._evict_template(key)

        if self._load_template(image_path):
            cache_keys = self._build_cache_keys(image_path)
            with self._cache_lock:
                for key in cache_keys:
                    cached = self.template_cache.get(key)
                    if cached is None:
                        continue
                    self._touch_template(key)
                    return cached
        return None

    def has_template(self, image_path: str) -> bool:
        """检查模板是否已缓存且有效。"""
        cache_keys = self._build_cache_keys(image_path)
        with self._cache_lock:
            for key in cache_keys:
                if key not in self.template_cache:
                    continue
                if self._is_cache_fresh(key):
                    self._touch_template(key)
                    return True
                self._evict_template(key)
            return False

    def invalidate_template(self, image_path: str) -> None:
        """主动使某个模板失效。"""
        invalidated = False
        cache_keys = self._build_cache_keys(image_path)
        with self._cache_lock:
            for key in cache_keys:
                if key in self.template_cache:
                    self._evict_template(key)
                    invalidated = True
        if invalidated:
            logger.debug(f"模板缓存已失效: {image_path}")

    def clear_cache(self):
        """清理所有缓存。"""
        with self._cache_lock:
            count = len(self.template_cache)
            size = self._stats["total_size_bytes"]

            self.template_cache.clear()
            self._template_signatures.clear()
            self._template_sizes.clear()
            self._cache_order.clear()
            self._stats = {
                "total_loaded": 0,
                "total_failed": 0,
                "total_size_bytes": 0,
            }
        with self._workflow_preload_lock:
            self._workflow_preload_inflight.clear()
            self._workflow_preload_done.clear()

        logger.info(f"模板缓存已清理: {count}个模板, {size / 1024 / 1024:.2f}MB")

    def get_stats(self) -> dict:
        """获取统计信息。"""
        with self._cache_lock:
            return {
                **self._stats,
                "cached_count": len(self.template_cache),
                "max_cache_bytes": self._max_cache_bytes,
            }


# 全局单例
_global_preloader: Optional[TemplatePreloader] = None


def get_global_preloader() -> TemplatePreloader:
    """获取全局预加载器单例。"""
    global _global_preloader
    if _global_preloader is None:
        _global_preloader = TemplatePreloader()
    return _global_preloader


def clear_global_cache():
    """清理全局缓存。"""
    global _global_preloader
    if _global_preloader is not None:
        _global_preloader.clear_cache()
        _global_preloader = None
