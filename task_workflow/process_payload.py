# -*- coding: utf-8 -*-
"""工作流子进程载荷构建工具。"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

from task_workflow.thread_window_binding import resolve_thread_window_configs


def _normalize_start_card_ids(
    start_card_id: Optional[int],
    start_card_ids: Optional[Iterable[Any]],
) -> list[int]:
    normalized: list[int] = []
    seen: set[int] = set()

    def append_one(value: Any) -> None:
        try:
            normalized_value = int(value)
        except (TypeError, ValueError):
            return
        if normalized_value in seen:
            return
        seen.add(normalized_value)
        normalized.append(normalized_value)

    if start_card_ids is not None:
        for item in start_card_ids:
            append_one(item)
    if start_card_id is not None:
        append_one(start_card_id)
    return normalized


def build_process_workflow_payload(
    *,
    cards_data: Dict[str, Any],
    connections_data: list[Dict[str, Any]],
    execution_mode: str,
    screenshot_engine: Optional[str] = None,
    images_dir: Optional[str],
    workflow_id: str,
    workflow_filepath: Optional[str] = None,
    start_card_id: Optional[int] = None,
    start_card_ids: Optional[Iterable[Any]] = None,
    target_window_title: Optional[str] = None,
    target_hwnd: Optional[int] = None,
    thread_labels: Optional[Dict[int, str]] = None,
    bound_windows: Optional[list[Dict[str, Any]]] = None,
    logger_obj=None,
    enable_thread_window_binding: bool = True,
    single_mode_overrides: Optional[Dict[str, Any]] = None,
    multi_thread_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    normalized_start_ids = _normalize_start_card_ids(start_card_id, start_card_ids)
    primary_start_id = normalized_start_ids[0] if normalized_start_ids else None

    single_thread_target_hwnd = target_hwnd
    single_thread_target_window_title = target_window_title
    safe_bound_windows = bound_windows or []

    if enable_thread_window_binding and primary_start_id is not None:
        single_thread_window_configs = resolve_thread_window_configs(
            cards_data=cards_data,
            connections_data=connections_data,
            start_card_ids=[primary_start_id],
            bound_windows=safe_bound_windows,
            logger_obj=logger_obj,
        )
        single_thread_window_config = next(iter(single_thread_window_configs.values()), {})
        if single_thread_window_config:
            single_thread_target_hwnd = single_thread_window_config.get("target_hwnd", single_thread_target_hwnd)
            single_thread_target_window_title = (
                single_thread_window_config.get("target_window_title")
                or single_thread_target_window_title
            )

    payload: Dict[str, Any] = {
        "cards_data": cards_data,
        "connections_data": connections_data,
        "execution_mode": execution_mode,
        "images_dir": images_dir,
        "workflow_id": workflow_id,
        "workflow_filepath": workflow_filepath,
    }
    normalized_screenshot_engine = str(screenshot_engine or "").strip().lower()
    if normalized_screenshot_engine:
        payload["screenshot_engine"] = normalized_screenshot_engine

    if enable_thread_window_binding and len(normalized_start_ids) > 1:
        thread_window_configs = resolve_thread_window_configs(
            cards_data=cards_data,
            connections_data=connections_data,
            start_card_ids=normalized_start_ids,
            bound_windows=safe_bound_windows,
            logger_obj=logger_obj,
        )
        payload.update(
            {
                "session_mode": "multi_thread",
                "target_window_title": target_window_title,
                "target_hwnd": target_hwnd,
                "start_card_ids": normalized_start_ids,
                "thread_labels": thread_labels or {},
                "thread_window_configs": thread_window_configs,
            }
        )
        if multi_thread_overrides:
            payload.update(dict(multi_thread_overrides))
        return payload

    payload.update(
        {
            "session_mode": "single",
            "target_window_title": single_thread_target_window_title,
            "target_hwnd": single_thread_target_hwnd,
            "start_card_id": primary_start_id,
        }
    )
    if single_mode_overrides:
        payload.update(dict(single_mode_overrides))
    return payload
