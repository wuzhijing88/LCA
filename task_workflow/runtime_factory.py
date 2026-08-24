"""Canonical factory for subprocess and in-process workflow runtimes."""

from __future__ import annotations

from typing import Any, Dict, Optional


def create_subprocess_runtime(**kwargs: Any):
    from task_workflow.process_proxy import create_process_workflow_runtime

    return create_process_workflow_runtime(**kwargs)


def create_inprocess_runtime(
    payload: Dict[str, Any],
    *,
    task_modules: Optional[Dict[str, Any]] = None,
):
    from task_workflow.executor import WorkflowExecutor
    from task_workflow.multi_thread_session import WorkflowMultiThreadSession
    from tasks import get_task_modules

    modules = task_modules if task_modules is not None else get_task_modules()
    session_mode = str(payload.get("session_mode") or "single").strip().lower()
    cards_data = payload.get("cards_data") or {}
    connections_data = payload.get("connections_data") or []
    common_kwargs = dict(
        task_modules=modules,
        target_window_title=payload.get("target_window_title"),
        execution_mode=payload.get("execution_mode") or "foreground",
        images_dir=payload.get("images_dir"),
        target_hwnd=payload.get("target_hwnd"),
        workflow_id=payload.get("workflow_id"),
        workflow_filepath=payload.get("workflow_filepath"),
        get_image_data=payload.get("get_image_data"),
    )
    if session_mode == "multi_thread":
        return WorkflowMultiThreadSession(
            cards_data=cards_data,
            connections_data=connections_data,
            start_card_ids=payload.get("start_card_ids") or [],
            thread_labels=payload.get("thread_labels") or {},
            thread_window_configs=payload.get("thread_window_configs") or {},
            **common_kwargs,
        )
    return WorkflowExecutor(
        cards_data=cards_data,
        connections_data=connections_data,
        start_card_id=payload.get("start_card_id"),
        test_mode=payload.get("test_mode"),
        workflow_context=payload.get("workflow_context"),
        allowed_card_ids=payload.get("allowed_card_ids"),
        disallowed_task_types=payload.get("disallowed_task_types"),
        max_execution_steps=payload.get("max_execution_steps"),
        default_step_log_scope=payload.get("default_step_log_scope", "main"),
        default_step_log_name=payload.get("default_step_log_name"),
        external_stop_checker=payload.get("external_stop_checker"),
        external_pause_checker=payload.get("external_pause_checker"),
        cleanup_runtime_image_on_finish=payload.get("cleanup_runtime_image_on_finish", True),
        clear_runtime_state_on_start=payload.get("clear_runtime_state_on_start", True),
        infinite_loop_guard_enabled=payload.get("infinite_loop_guard_enabled", False),
        **common_kwargs,
    )


__all__ = ["create_inprocess_runtime", "create_subprocess_runtime"]
