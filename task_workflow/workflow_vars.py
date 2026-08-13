# -*- coding: utf-8 -*-
"""Utilities for workflow variable contexts and runtime snapshots."""

from typing import Any, Dict, Optional, Union

from task_workflow.workflow_context import (
    clear_workflow_context,
    get_workflow_context,
    import_global_vars,
)


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



