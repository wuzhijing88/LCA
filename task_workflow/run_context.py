"""Explicit per-run state that replaces ad-hoc dynamic context attributes.

停止 / 强制停止 / 暂停 只在这里保存一份：WorkflowExecutor、WorkflowContext 与任务模块
拿到的都是同一个 RunContext，避免多处标志各自为政导致“停不下来”或“恢复不了”。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from app_core.runtime.cancellation import CancelToken


@dataclass
class RunContext:
    workflow_id: str
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    resource_lane_key: Optional[str] = None
    start_card_id: Optional[int] = None
    window_hwnd: Optional[int] = None
    cancellation: CancelToken = field(default_factory=CancelToken)
    monitor_configs: dict[int, dict[str, Any]] = field(default_factory=dict)
    should_stop_workflow: bool = False
    force_stop: bool = False
    paused: bool = False

    # --- 停止 ---
    def request_stop(self, reason: str = "stop_requested", *, force: bool = False) -> bool:
        """登记停止请求；force=True 表示不等待当前任务完成。"""
        self.should_stop_workflow = True
        if force:
            self.force_stop = True
        return self.cancellation.cancel(reason)

    def is_stop_requested(self) -> bool:
        return self.should_stop_workflow or self.cancellation.is_cancelled()

    def is_force_stop_requested(self) -> bool:
        return self.force_stop

    def clear_stop(self) -> None:
        """撤销停止标志。已取消的令牌不可复用，换一个新的。"""
        self.should_stop_workflow = False
        self.force_stop = False
        if self.cancellation.is_cancelled():
            self.cancellation = CancelToken()

    # --- 暂停 ---
    def pause(self) -> None:
        self.paused = True

    def resume(self) -> None:
        self.paused = False

    def is_paused(self) -> bool:
        return self.paused


__all__ = ["RunContext"]
