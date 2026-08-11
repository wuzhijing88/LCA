# -*- coding: utf-8 -*-
"""虚拟鼠标运行态/全局态读写工具。"""

from __future__ import annotations

import logging
from typing import Any, Optional, Tuple

logger = logging.getLogger(__name__)

_KEY_ENABLED = "虚拟鼠标启用"
_KEY_X = "虚拟鼠标坐标X"
_KEY_Y = "虚拟鼠标坐标Y"


def _read_runtime_var(name: str) -> Any:
    try:
        from task_workflow.workflow_context import get_workflow_context

        context = get_workflow_context()
        return context.get_global_var(name)
    except Exception:
        return None


def _write_runtime_var(name: str, value: Any) -> None:
    try:
        from task_workflow.workflow_context import get_workflow_context

        context = get_workflow_context()
        context.set_global_var(name, value)
    except Exception:
        pass


def _read_global_store_var(name: str) -> Any:
    try:
        from task_workflow.global_var_store import ensure_global_context_loaded

        store = ensure_global_context_loaded()
        return store.get_value(name)
    except Exception:
        return None


def is_virtual_mouse_enabled() -> bool:
    value = _read_runtime_var(_KEY_ENABLED)
    if value is None:
        value = _read_global_store_var(_KEY_ENABLED)
    return bool(value)


def get_virtual_mouse_coords() -> Optional[Tuple[int, int]]:
    vm_x = _read_runtime_var(_KEY_X)
    vm_y = _read_runtime_var(_KEY_Y)

    if vm_x is None:
        vm_x = _read_global_store_var(_KEY_X)
    if vm_y is None:
        vm_y = _read_global_store_var(_KEY_Y)

    if vm_x is None or vm_y is None:
        return None

    try:
        return int(vm_x), int(vm_y)
    except Exception:
        logger.debug("虚拟鼠标坐标类型无效: x=%r, y=%r", vm_x, vm_y)
        return None


def sync_virtual_mouse_position(
    x: int,
    y: int,
    *,
    persist_global: bool = False,
) -> None:
    safe_x = int(x)
    safe_y = int(y)
    _write_runtime_var(_KEY_ENABLED, True)
    _write_runtime_var(_KEY_X, safe_x)
    _write_runtime_var(_KEY_Y, safe_y)

    if not persist_global:
        return

    try:
        from task_workflow.global_var_store import ensure_global_context_loaded
        from task_workflow.workflow_context import get_workflow_context

        store = ensure_global_context_loaded()
        store.set_value(_KEY_ENABLED, True, var_type="bool")
        store.set_value(_KEY_X, safe_x, var_type="int")
        store.set_value(_KEY_Y, safe_y, var_type="int")
        store.save()
        store.apply_to_context(get_workflow_context("global"), force=True)
    except Exception:
        logger.debug("同步虚拟鼠标位置到全局变量池失败")
