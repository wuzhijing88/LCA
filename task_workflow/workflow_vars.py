# -*- coding: utf-8 -*-
"""按任务 ID 定位工作流执行上下文。"""

from typing import Any, Optional, Union

from task_workflow.workflow_context import (
    clear_workflow_context,
)


WorkflowSelector = Union[int, str]


def normalize_workflow_task_id(value: Any) -> Optional[WorkflowSelector]:
    if value in (None, ""):
        return None

    if isinstance(value, bool):
        raise ValueError(f"无效的来源工作流标识: {value!r}")

    if not isinstance(value, int):
        raise ValueError(f"无效的来源工作流标识: {value!r}")
    return value


def workflow_context_key(task_id: Any) -> Optional[str]:
    task_id = normalize_workflow_task_id(task_id)
    if task_id is None:
        return None
    return f"workflow_{task_id}"


def clear_context_for_task(task_id: Any) -> None:
    key = workflow_context_key(task_id)
    if key is None:
        return
    clear_workflow_context(key)
