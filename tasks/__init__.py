#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Task package initializer with lazy imports.
"""

from __future__ import annotations

import importlib
import logging
from typing import Dict

from utils.thread_start_utils import THREAD_START_TASK_TYPE

logger = logging.getLogger(__name__)

# 打包阶段由构建脚本负责收录 tasks 包，运行时保持纯懒加载，避免模块导入副作用。

_MODULE_CACHE: Dict[str, object] = {}


def _import_module_path(module_path: str):
    cached = _MODULE_CACHE.get(module_path)
    if cached is not None:
        return cached
    module = importlib.import_module(module_path)
    _MODULE_CACHE[module_path] = module
    return module


class LazyTaskModuleDict(dict):
    """Lazily import module values when first accessed."""

    def __getitem__(self, key):
        value = super().__getitem__(key)
        if isinstance(value, str):
            module = _import_module_path(value)
            super().__setitem__(key, module)
            return module
        return value

    def get(self, key, default=None):
        if key in self:
            return self[key]
        return default

    def items(self):
        for key in super().keys():
            yield key, self[key]

    def values(self):
        for key in super().keys():
            yield self[key]


_PRIMARY_TASK_MODULE_PATHS = {
    THREAD_START_TASK_TYPE: "tasks.start_task",
    "模拟鼠标操作": "tasks.mouse_action_task",
    "模拟键盘操作": "tasks.keyboard_input",
    "延迟": "tasks.delay_task",
    "条件控制": "tasks.conditional_control",
    "随机跳转": "tasks.random_jump",
    "线程控制": "tasks.thread_control_task",
    "线程窗口限制": "tasks.thread_window_limit_task",
    "OCR文字识别": "tasks.ocr_region_recognition",
    "YOLO目标检测": "tasks.yolo_detection",
    "变量提取": "tasks.variable_task",
    "变量比较": "tasks.variable_compare",
    "录制回放": "tasks.record_replay_task",
    "附加条件": "tasks.watchdog_monitor",
    "子工作流": "tasks.sub_workflow_task",
}

PRIMARY_TASK_MODULES = LazyTaskModuleDict(_PRIMARY_TASK_MODULE_PATHS)

TASK_MODULES_DICT = LazyTaskModuleDict(
    {
        **_PRIMARY_TASK_MODULE_PATHS,
        "图片点击": "tasks.image_match_click",
    }
)

TASK_MODULES = TASK_MODULES_DICT

_EXPORT_MODULES = {
    "delay_task": "tasks.delay_task",
    "keyboard_input": "tasks.keyboard_input",
    "conditional_control": "tasks.conditional_control",
    "start_task": "tasks.start_task",
    "ocr_region_recognition": "tasks.ocr_region_recognition",
    "mouse_action_task": "tasks.mouse_action_task",
    "image_match_click": "tasks.image_match_click",
    "yolo_detection": "tasks.yolo_detection",
    "record_replay_task": "tasks.record_replay_task",
    "watchdog_monitor": "tasks.watchdog_monitor",
    "sub_workflow_task": "tasks.sub_workflow_task",
    "random_jump": "tasks.random_jump",
    "variable_task": "tasks.variable_task",
    "variable_compare": "tasks.variable_compare",
    "thread_control_task": "tasks.thread_control_task",
    "thread_window_limit_task": "tasks.thread_window_limit_task",
    "click_coordinate": "tasks.click_coordinate",
    "task_utils": "tasks.task_utils",
}


def __getattr__(name: str):
    module_path = _EXPORT_MODULES.get(name)
    if module_path is None:
        module_path = f"{__name__}.{name}"
    try:
        return _import_module_path(module_path)
    except ModuleNotFoundError as exc:
        if exc.name == module_path:
            raise AttributeError(f"module '{__name__}' has no attribute '{name}'") from None
        raise


def __dir__():
    return sorted(set(globals().keys()) | set(_EXPORT_MODULES.keys()))


def get_available_tasks():
    """Return task names for UI display."""
    return list(PRIMARY_TASK_MODULES.keys())


def get_all_tasks():
    """Return all task names (including compatibility entries)."""
    return list(TASK_MODULES_DICT.keys())


def get_task_module(task_name: str, default=None):
    """Return one task module through the explicit package access point."""
    normalized_name = str(task_name or "").strip()
    if not normalized_name:
        return default
    return TASK_MODULES_DICT.get(normalized_name, default)


def get_task_modules():
    """Return the shared task module registry through the explicit package access point."""
    return TASK_MODULES_DICT


__all__ = [
    "TASK_MODULES",
    "TASK_MODULES_DICT",
    "PRIMARY_TASK_MODULES",
    "get_available_tasks",
    "get_all_tasks",
    "get_task_module",
    "get_task_modules",
] + sorted(_EXPORT_MODULES.keys())

