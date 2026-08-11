#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""运行时依赖预热工具。"""

from __future__ import annotations

import importlib
import logging
import threading

logger = logging.getLogger(__name__)

_PRELOADED_MODULES: set[str] = set()
_PRELOAD_LOCK = threading.Lock()


def preload_optional_module(module_name: str) -> bool:
    """幂等预热可选模块，固定依赖初始化顺序。"""
    normalized_name = str(module_name or "").strip()
    if not normalized_name:
        return False

    with _PRELOAD_LOCK:
        if normalized_name in _PRELOADED_MODULES:
            return True

    try:
        importlib.import_module(normalized_name)
    except Exception as exc:
        logger.debug("可选模块预热失败: %s -> %s", normalized_name, exc)
        return False

    with _PRELOAD_LOCK:
        _PRELOADED_MODULES.add(normalized_name)
    return True


def preload_onnxruntime() -> bool:
    """
    在截图链路初始化前预热 ONNX Runtime。

    部分截图底层在首次导入后会影响后续 DLL 初始化顺序，这里统一固定导入顺序。
    """

    return preload_optional_module("onnxruntime")
