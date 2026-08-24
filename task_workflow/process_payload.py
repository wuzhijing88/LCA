# -*- coding: utf-8 -*-
"""工作流子进程载荷构建工具。"""

from __future__ import annotations

import hashlib
import os
from typing import Any, Dict, Iterable, Optional

from task_workflow.thread_window_binding import resolve_thread_window_configs


def _normalize_start_card_ids(
    start_card_ids: Iterable[int],
) -> list[int]:
    if isinstance(start_card_ids, (str, bytes)) or not isinstance(start_card_ids, Iterable):
        raise TypeError("start_card_ids 必须是整数序列")

    normalized: list[int] = []
    seen: set[int] = set()
    for value in start_card_ids:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"线程起点ID必须是整数: {value!r}")
        if value in seen:
            raise ValueError(f"线程起点ID重复: {value}")
        seen.add(value)
        normalized.append(value)
    if not normalized:
        raise ValueError("工作流至少需要一个线程起点")
    return normalized


def _validate_payload_inputs(
    *,
    cards_data: Dict[Any, Any],
    connections_data: list[Dict[str, Any]],
    execution_mode: str,
    screenshot_engine: str,
    workflow_id: str,
    start_card_ids: list[int],
    bound_windows: Optional[list[Dict[str, Any]]],
) -> None:
    if not isinstance(cards_data, dict) or not cards_data:
        raise ValueError("cards_data 必须是非空字典")
    if not isinstance(connections_data, list):
        raise TypeError("connections_data 必须是列表")
    for index, connection in enumerate(connections_data):
        if not isinstance(connection, dict):
            raise TypeError(f"连接数据必须是字典: index={index}")
        if connection.get("start_card_id") is None or connection.get("end_card_id") is None:
            raise ValueError(f"连接数据缺少起点或终点: index={index}")

    if not str(execution_mode or "").strip():
        raise ValueError("execution_mode 不能为空")
    if str(screenshot_engine or "").strip().lower() not in {"wgc", "printwindow", "gdi", "dxgi"}:
        raise ValueError(f"不支持的 screenshot_engine: {screenshot_engine!r}")
    if not str(workflow_id or "").strip():
        raise ValueError("workflow_id 不能为空")
    if bound_windows is not None:
        if not isinstance(bound_windows, list):
            raise TypeError("bound_windows 必须是列表")
        if any(not isinstance(window, dict) for window in bound_windows):
            raise TypeError("bound_windows 中的窗口配置必须是字典")

    for start_card_id in start_card_ids:
        if start_card_id not in cards_data and str(start_card_id) not in cards_data:
            raise ValueError(f"线程起点卡片不存在: {start_card_id}")


def build_process_workflow_payload(
    *,
    cards_data: Dict[Any, Any],
    connections_data: list[Dict[str, Any]],
    execution_mode: str,
    screenshot_engine: str,
    images_dir: Optional[str],
    workflow_id: str,
    workflow_filepath: Optional[str] = None,
    start_card_ids: Iterable[int],
    target_window_title: Optional[str] = None,
    target_hwnd: Optional[int] = None,
    thread_labels: Optional[Dict[int, str]] = None,
    bound_windows: Optional[list[Dict[str, Any]]] = None,
    test_mode: Any = None,
    prefer_file_reference: bool = False,
) -> Dict[str, Any]:
    normalized_start_ids = _normalize_start_card_ids(start_card_ids)
    _validate_payload_inputs(
        cards_data=cards_data,
        connections_data=connections_data,
        execution_mode=execution_mode,
        screenshot_engine=screenshot_engine,
        workflow_id=workflow_id,
        start_card_ids=normalized_start_ids,
        bound_windows=bound_windows,
    )
    primary_start_id = normalized_start_ids[0]

    single_thread_target_hwnd = target_hwnd
    single_thread_target_window_title = target_window_title
    safe_bound_windows = list(bound_windows or [])

    if len(normalized_start_ids) == 1:
        single_thread_window_configs = resolve_thread_window_configs(
            cards_data=cards_data,
            connections_data=connections_data,
            start_card_ids=[primary_start_id],
            bound_windows=safe_bound_windows,
        )
        single_thread_window_config = next(iter(single_thread_window_configs.values()), {})
        if single_thread_window_config:
            single_thread_target_hwnd = single_thread_window_config["target_hwnd"]
            single_thread_target_window_title = single_thread_window_config["target_window_title"]

    payload: Dict[str, Any] = {
        "payload_version": 2,
        "cards_data": cards_data,
        "connections_data": connections_data,
        "execution_mode": str(execution_mode).strip(),
        "screenshot_engine": str(screenshot_engine).strip().lower(),
        "images_dir": images_dir,
        "workflow_id": str(workflow_id).strip(),
        "workflow_filepath": workflow_filepath,
    }
    if prefer_file_reference and workflow_filepath:
        workflow_path = os.path.abspath(str(workflow_filepath))
        if os.path.isfile(workflow_path):
            payload["workflow_reference"] = {
                "path": workflow_path,
                "sha256": _sha256_file(workflow_path),
            }
            payload.pop("cards_data", None)
            payload.pop("connections_data", None)

    if len(normalized_start_ids) > 1:
        thread_window_configs = resolve_thread_window_configs(
            cards_data=cards_data,
            connections_data=connections_data,
            start_card_ids=normalized_start_ids,
            bound_windows=safe_bound_windows,
        )
        payload.update(
            {
                "session_mode": "multi_thread",
                "target_window_title": target_window_title,
                "target_hwnd": target_hwnd,
                "start_card_ids": normalized_start_ids,
                "thread_labels": dict(thread_labels or {}),
                "thread_window_configs": thread_window_configs,
            }
        )
        return payload

    payload.update(
        {
            "session_mode": "single",
            "target_window_title": single_thread_target_window_title,
            "target_hwnd": single_thread_target_hwnd,
            "start_card_id": primary_start_id,
            "test_mode": test_mode,
        }
    )
    return payload


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
