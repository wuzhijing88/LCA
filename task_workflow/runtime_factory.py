"""Canonical factory for subprocess and in-process workflow runtimes."""

from __future__ import annotations

from typing import Any, Dict, Optional


def _resolve_get_image_data(payload: Dict[str, Any]):
    from app_core.player.runtime_images import resolve_get_image_data

    return resolve_get_image_data(payload)


def _attach_window_resolution_context(runtime: Any, payload: Dict[str, Any]) -> None:
    windows = payload.get("bound_windows")
    runtime.bound_windows = list(windows) if isinstance(windows, list) else []
    try:
        runtime.custom_width = int(payload.get("custom_width") or 0)
    except (TypeError, ValueError):
        runtime.custom_width = 0
    try:
        runtime.custom_height = int(payload.get("custom_height") or 0)
    except (TypeError, ValueError):
        runtime.custom_height = 0


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
    execution_mode = str(payload.get("execution_mode") or "").strip()
    if not execution_mode:
        raise ValueError("工作流载荷缺少 execution_mode")
    session_mode = str(payload.get("session_mode") or "single").strip().lower()
    cards_data = payload.get("cards_data") or {}
    connections_data = payload.get("connections_data") or []
    common_kwargs = dict(
        task_modules=modules,
        target_window_title=payload.get("target_window_title"),
        execution_mode=execution_mode,
        images_dir=payload.get("images_dir"),
        target_hwnd=payload.get("target_hwnd"),
        workflow_id=payload.get("workflow_id"),
        workflow_filepath=payload.get("workflow_filepath"),
        get_image_data=_resolve_get_image_data(payload),
    )
    if session_mode == "multi_thread":
        runtime = WorkflowMultiThreadSession(
            cards_data=cards_data,
            connections_data=connections_data,
            start_card_ids=payload.get("start_card_ids") or [],
            thread_labels=payload.get("thread_labels") or {},
            thread_window_configs=payload.get("thread_window_configs") or {},
            **common_kwargs,
        )
        _attach_window_resolution_context(runtime, payload)
        return runtime
    runtime = WorkflowExecutor(
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
    _attach_window_resolution_context(runtime, payload)
    return runtime


__all__ = ["create_inprocess_runtime", "create_subprocess_runtime"]
