"""Typed task execution contract with legacy tuple compatibility."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional


class TransitionKind(str, Enum):
    NEXT = "next"
    JUMP = "jump"
    RETRY = "retry"
    CONTINUE = "continue"
    STOP = "stop"


_ACTION_TO_KIND = {
    "": TransitionKind.NEXT,
    "执行下一步": TransitionKind.NEXT,
    "下一步": TransitionKind.NEXT,
    "跳转到步骤": TransitionKind.JUMP,
    "跳转到指定步骤": TransitionKind.JUMP,
    "继续执行本步骤": TransitionKind.RETRY,
    "继续本步骤": TransitionKind.RETRY,
    "停止工作流": TransitionKind.STOP,
    "stop_workflow": TransitionKind.STOP,
}

_KIND_TO_ACTION = {
    TransitionKind.NEXT: "执行下一步",
    TransitionKind.JUMP: "跳转到步骤",
    TransitionKind.RETRY: "继续执行本步骤",
    TransitionKind.CONTINUE: "继续执行本步骤",
    TransitionKind.STOP: "停止工作流",
}


@dataclass(frozen=True)
class Transition:
    kind: TransitionKind = TransitionKind.NEXT
    target_card_id: Optional[int] = None

    @classmethod
    def from_legacy(cls, action: Any, target_card_id: Any = None) -> "Transition":
        if isinstance(action, Transition):
            return action
        if isinstance(action, TransitionKind):
            return cls(action, _normalize_card_id(target_card_id))
        normalized = str(action or "").strip()
        kind = _ACTION_TO_KIND.get(normalized, TransitionKind.NEXT)
        return cls(kind, _normalize_card_id(target_card_id))

    def legacy_action(self) -> str:
        return _KIND_TO_ACTION[self.kind]


@dataclass(frozen=True)
class TaskResult:
    success: bool
    transition: Transition = Transition()
    detail: str = ""

    def as_legacy_tuple(self) -> tuple[bool, str, Optional[int], str]:
        return (
            bool(self.success),
            self.transition.legacy_action(),
            self.transition.target_card_id,
            str(self.detail or ""),
        )

    @classmethod
    def from_legacy(cls, result: Any) -> "TaskResult":
        if isinstance(result, TaskResult):
            return result
        if not isinstance(result, (tuple, list)):
            raise TypeError(f"task result must be TaskResult or tuple, got {type(result).__name__}")
        if len(result) < 3:
            raise ValueError(f"task result must contain at least 3 values, got {len(result)}")
        success, action, target = result[:3]
        detail = result[3] if len(result) >= 4 else ""
        return cls(
            success=bool(success),
            transition=Transition.from_legacy(action, target),
            detail=str(detail or ""),
        )


def _normalize_card_id(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_task_result(result: Any) -> TaskResult:
    return TaskResult.from_legacy(result)


__all__ = [
    "TaskResult",
    "Transition",
    "TransitionKind",
    "normalize_task_result",
]
