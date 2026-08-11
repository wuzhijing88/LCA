# -*- coding: utf-8 -*-
"""Utilities for workflow variable contexts and runtime snapshots."""

from typing import Any, Dict, Optional, Union

from task_workflow.workflow_context import (
    clear_workflow_context,
    export_global_vars,
    get_workflow_context,
    import_global_vars,
)
from task_workflow.runtime_var_store import is_storage_manifest


WorkflowSelector = Union[int, str]


# 兼容历史被错误编码后写入的数据值（UTF-8 按 latin-1 误解码）
def _legacy_mojibake(text: str) -> str:
    return text.encode("utf-8", errors="ignore").decode("latin-1", errors="ignore")


_LEGACY_CURRENT_VALUES = {_legacy_mojibake("当前工作流"), _legacy_mojibake("当前")}
_LEGACY_GLOBAL_VALUES = {_legacy_mojibake("全局变量")}


def normalize_workflow_task_id(value: Any) -> Optional[WorkflowSelector]:
    if value in (None, ""):
        return None

    text = str(value).strip()
    if text in ("当前工作流", "当前", "current", "default"):
        return None
    if text in _LEGACY_CURRENT_VALUES:
        return None

    if text in ("全局变量", "global"):
        return "global"
    if text in _LEGACY_GLOBAL_VALUES:
        return "global"

    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def workflow_context_key(task_id: Any) -> Optional[str]:
    task_id = normalize_workflow_task_id(task_id)
    if task_id is None:
        return None
    if task_id == "global":
        return "global"
    return f"workflow_{task_id}"


def get_context_for_task(task_id: Any):
    key = workflow_context_key(task_id)
    if key is None:
        return None
    if key == "global":
        try:
            from task_workflow.global_var_store import ensure_global_context_loaded

            ensure_global_context_loaded()
        except Exception:
            pass
    return get_workflow_context(key)


def update_context_from_variables(task_id: Any, variables_data: Optional[Dict[str, Any]]) -> None:
    key = workflow_context_key(task_id)
    if key is None:
        return
    if key == "global":
        return
    import_global_vars(variables_data, workflow_id=key)


def clear_context_for_task(task_id: Any) -> None:
    key = workflow_context_key(task_id)
    if key is None:
        return
    if key == "global":
        return
    clear_workflow_context(key)


def has_runtime_variables(variables_data: Optional[Dict[str, Any]]) -> bool:
    """判断变量快照里是否包含有效变量。"""
    if not isinstance(variables_data, dict):
        return False

    if is_storage_manifest(variables_data):
        count = variables_data.get("count")
        try:
            return int(count) > 0
        except Exception:
            return True

    global_vars = variables_data.get("global_vars")
    if isinstance(global_vars, dict):
        return bool(global_vars)

    # 兼容旧格式（平铺变量字典）
    return bool(variables_data)


def pick_variables_override(
    target_task_id: Any,
    current_task_id: Any,
    task_workflow_data: Optional[Dict[str, Any]],
    runtime_variables_data: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    为序列化选择变量覆盖来源。
    规则：
    1. 非当前标签页任务：优先使用任务自身持久化变量。
    2. 当前标签页任务：优先使用运行时变量快照。
    3. 当前标签页任务若运行时变量为空：回退到任务持久化变量。
    4. 其余情况：不覆盖，使用当前上下文变量。
    """
    persisted_vars = None
    if isinstance(task_workflow_data, dict):
        candidate = task_workflow_data.get("variables")
        if isinstance(candidate, dict):
            persisted_vars = candidate

    normalized_target = normalize_workflow_task_id(target_task_id)
    normalized_current = normalize_workflow_task_id(current_task_id)
    if normalized_target != normalized_current:
        return persisted_vars

    runtime_snapshot = runtime_variables_data
    if runtime_snapshot is None:
        try:
            runtime_workflow_id = workflow_context_key(current_task_id) or "default"
            runtime_snapshot = export_global_vars(runtime_workflow_id)
        except Exception:
            runtime_snapshot = None

    if has_runtime_variables(runtime_snapshot):
        return runtime_snapshot

    if persisted_vars is not None:
        return persisted_vars

    return None

