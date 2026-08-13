#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""运行时依赖预热工具。"""

from __future__ import annotations

import importlib
import logging
import threading

logger = logging.getLogger(__name__)

_PRELOADED_MODULES: set[str] = set()
_PRELOAD_LOCK = threading.RLock()


def _normalize_module_name(module_name: str) -> str:
    if not isinstance(module_name, str):
        raise TypeError("module_name must be a string")

    normalized_name = module_name.strip()
    if not normalized_name:
        raise ValueError("module_name cannot be empty")

    parts = normalized_name.split(".")
    if any(not part.isidentifier() for part in parts):
        raise ValueError(f"invalid module name: {module_name!r}")
    return normalized_name


def preload_optional_module(module_name: str) -> bool:
    """幂等预热可选模块。模块不存在时返回 False，非法名称直接抛错。"""
    normalized_name = _normalize_module_name(module_name)

    with _PRELOAD_LOCK:
        if normalized_name in _PRELOADED_MODULES:
            return True
        try:
            importlib.import_module(normalized_name)
        except ImportError as exc:
            logger.debug("可选模块预热失败: %s -> %s", normalized_name, exc)
            return False

        _PRELOADED_MODULES.add(normalized_name)
        return True


def preload_onnxruntime() -> bool:
    """在截图链路初始化前预热 ONNX Runtime，固定 DLL 导入顺序。"""
    return preload_optional_module("onnxruntime")
