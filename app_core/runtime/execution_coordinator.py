"""Single application-level entry point for workflow runtime creation."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Optional


class ExecutionSource(str, Enum):
    MAIN_WINDOW = "main_window"
    CONTROL_CENTER = "control_center"
    WORKFLOW_TEST = "workflow_test"
    SCHEDULE = "schedule"
    PLAYER = "player"


@dataclass(frozen=True)
class ExecutionSessionSnapshot:
    session_id: str
    source: ExecutionSource
    workflow_id: str
    active: bool


class ExecutionConflictError(RuntimeError):
    pass


class ExecutionCoordinator:
    def __init__(self, runtime_factory: Optional[Callable[..., tuple[Any, Any]]] = None):
        self._lock = threading.RLock()
        self._runtime_factory = runtime_factory
        self._sessions: dict[str, ExecutionSessionSnapshot] = {}

    def _factory(self) -> Callable[..., tuple[Any, Any]]:
        if self._runtime_factory is not None:
            return self._runtime_factory
        from task_workflow.runtime_factory import create_subprocess_runtime

        return create_subprocess_runtime

    def snapshots(self) -> list[ExecutionSessionSnapshot]:
        with self._lock:
            return list(self._sessions.values())

    def active_sources(self) -> set[ExecutionSource]:
        with self._lock:
            return {snapshot.source for snapshot in self._sessions.values() if snapshot.active}

    def can_start(self, source: ExecutionSource | str) -> tuple[bool, str]:
        normalized = ExecutionSource(source)
        active_sources = self.active_sources()
        if not active_sources or active_sources == {normalized}:
            return True, ""
        running = ", ".join(sorted(item.value for item in active_sources))
        return False, f"已有其他执行来源正在运行: {running}"

    def create_runtime(
        self,
        *,
        source: ExecutionSource | str,
        session_id: Optional[str] = None,
        **runtime_kwargs: Any,
    ) -> tuple[Any, Any]:
        normalized_source = ExecutionSource(source)
        allowed, reason = self.can_start(normalized_source)
        if not allowed:
            raise ExecutionConflictError(reason)

        normalized_session_id = str(session_id or uuid.uuid4().hex)
        workflow_id = str(runtime_kwargs.get("workflow_id") or "")
        with self._lock:
            if normalized_session_id in self._sessions:
                raise ValueError(f"execution session already exists: {normalized_session_id}")
            self._sessions[normalized_session_id] = ExecutionSessionSnapshot(
                session_id=normalized_session_id,
                source=normalized_source,
                workflow_id=workflow_id,
                active=True,
            )

        try:
            executor, thread_handle = self._factory()(**runtime_kwargs)
        except Exception:
            self.release(normalized_session_id)
            raise

        released = False

        def release_once(*_args: Any) -> None:
            nonlocal released
            if released:
                return
            released = True
            self.release(normalized_session_id)

        execution_finished = getattr(executor, "execution_finished", None)
        if execution_finished is not None and callable(getattr(execution_finished, "connect", None)):
            execution_finished.connect(release_once)
        thread_finished = getattr(thread_handle, "finished", None)
        if thread_finished is not None and callable(getattr(thread_finished, "connect", None)):
            thread_finished.connect(release_once)

        setattr(executor, "execution_session_id", normalized_session_id)
        setattr(executor, "execution_source", normalized_source.value)
        return executor, thread_handle

    def release(self, session_id: str) -> bool:
        with self._lock:
            return self._sessions.pop(str(session_id or ""), None) is not None

    def reset(self) -> None:
        with self._lock:
            self._sessions.clear()


_COORDINATOR: Optional[ExecutionCoordinator] = None
_COORDINATOR_LOCK = threading.Lock()


def get_execution_coordinator() -> ExecutionCoordinator:
    global _COORDINATOR
    with _COORDINATOR_LOCK:
        if _COORDINATOR is None:
            _COORDINATOR = ExecutionCoordinator()
        return _COORDINATOR


def create_coordinated_workflow_runtime(
    *,
    source: ExecutionSource | str,
    session_id: Optional[str] = None,
    **runtime_kwargs: Any,
) -> tuple[Any, Any]:
    return get_execution_coordinator().create_runtime(
        source=source,
        session_id=session_id,
        **runtime_kwargs,
    )


__all__ = [
    "ExecutionConflictError",
    "ExecutionCoordinator",
    "ExecutionSessionSnapshot",
    "ExecutionSource",
    "create_coordinated_workflow_runtime",
    "get_execution_coordinator",
]
