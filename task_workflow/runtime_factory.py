"""Canonical factory for subprocess and in-process workflow runtimes."""

from __future__ import annotations

from typing import Any, Dict, Optional


def _resolve_get_image_data(payload: Dict[str, Any]):
    from app_core.player.runtime_images import resolve_get_image_data

    return resolve_get_image_data(payload)


def _window_resolution_context(payload: Dict[str, Any]) -> Dict[str, Any]:
    from task_workflow.thread_window_binding import (
        enabled_bound_windows,
        require_window_dimension,
    )
    from utils.window.hwnd_utils import as_hwnd

    windows = payload.get("bound_windows", [])
    enabled_windows = enabled_bound_windows(windows)
    bind_id = payload.get("target_bind_id")
    if bind_id is not None and (not isinstance(bind_id, str) or not bind_id.strip()):
        raise ValueError("目标窗口绑定标识必须是非空字符串")
    raw_hwnd = payload.get("target_hwnd")
    if raw_hwnd is not None and (isinstance(raw_hwnd, bool) or not isinstance(raw_hwnd, int)):
        raise TypeError("目标窗口句柄必须是整数")
    if bind_id is not None and not any(
        window["bind_id"] == bind_id and window["hwnd"] == as_hwnd(raw_hwnd)
        for window in enabled_windows
    ):
        raise ValueError("目标窗口绑定标识与句柄不一致")
    if bind_id is None and payload.get("target_hwnd") is not None:
        matches = [
            window["bind_id"] for window in enabled_windows
            if window["hwnd"] == as_hwnd(payload["target_hwnd"])
        ]
        if len(matches) > 1:
            raise ValueError("默认目标窗口对应多个绑定标识")
        if matches:
            bind_id = matches[0]
    return {
        "bound_windows": [dict(window) for window in windows],
        "custom_width": require_window_dimension(payload.get("custom_width", 0), "窗口宽度"),
        "custom_height": require_window_dimension(payload.get("custom_height", 0), "窗口高度"),
        "target_bind_id": bind_id,
        "target_hwnd": as_hwnd(raw_hwnd) if raw_hwnd is not None else None,
    }


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

    if not isinstance(payload, dict):
        raise TypeError("工作流载荷必须是字典")
    session_mode = payload.get("session_mode")
    if session_mode not in ("single", "multi_thread"):
        raise ValueError(f"无效的工作流会话模式: {session_mode!r}")
    window_context = _window_resolution_context(payload)
    modules = task_modules if task_modules is not None else get_task_modules()
    execution_mode = payload.get("execution_mode")
    if not isinstance(execution_mode, str) or not execution_mode.strip():
        raise ValueError("工作流载荷缺少 execution_mode")
    cards_data = payload.get("cards_data")
    connections_data = payload.get("connections_data")
    if not isinstance(cards_data, dict) or not cards_data:
        raise ValueError("工作流卡片数据必须是非空字典")
    if not isinstance(connections_data, list):
        raise TypeError("工作流连接数据必须是列表")
    images_dir = payload.get("images_dir")
    sounds_dir = payload.get("sounds_dir")
    dicts_dir = payload.get("dicts_dir")
    yolo_dir = payload.get("yolo_dir")
    replays_dir = payload.get("replays_dir")
    plugins_dir = payload.get("plugins_dir")
    from task_workflow.resource_context import bind_resource_dirs

    bind_resource_dirs(payload)
    common_kwargs = dict(
        task_modules=modules,
        target_window_title=payload.get("target_window_title"),
        execution_mode=execution_mode,
        images_dir=images_dir,
        sounds_dir=sounds_dir,
        dicts_dir=dicts_dir,
        yolo_dir=yolo_dir,
        replays_dir=replays_dir,
        plugins_dir=plugins_dir,
        target_hwnd=window_context["target_hwnd"],
        workflow_id=payload.get("workflow_id"),
        workflow_filepath=payload.get("workflow_filepath"),
        get_image_data=_resolve_get_image_data(payload),
    )
    if session_mode == "multi_thread":
        runtime = WorkflowMultiThreadSession(
            cards_data=cards_data,
            connections_data=connections_data,
            start_card_ids=payload.get("start_card_ids"),
            thread_labels=payload.get("thread_labels"),
            thread_window_configs=payload.get("thread_window_configs"),
            external_stop_checker=payload.get("external_stop_checker"),
            external_pause_checker=payload.get("external_pause_checker"),
            **common_kwargs,
        )
        for key, value in window_context.items():
            setattr(runtime, key, value)
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
    for key, value in window_context.items():
        setattr(runtime, key, value)
    return runtime


__all__ = ["create_inprocess_runtime", "create_subprocess_runtime"]
