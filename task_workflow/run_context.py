"""Explicit per-run state that replaces ad-hoc dynamic context attributes."""

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

    def request_stop(self, reason: str = "stop_requested") -> bool:
        self.should_stop_workflow = True
        return self.cancellation.cancel(reason)

    def is_stop_requested(self) -> bool:
        return self.should_stop_workflow or self.cancellation.is_cancelled()


__all__ = ["RunContext"]
