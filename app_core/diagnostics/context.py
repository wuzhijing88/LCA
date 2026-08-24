"""Context-local identifiers shared by main and worker logs."""

from __future__ import annotations

import contextlib
import contextvars
import os
import uuid
from dataclasses import asdict, dataclass, replace
from typing import Iterator, Optional


@dataclass(frozen=True)
class DiagnosticContext:
    session_id: str = ""
    job_id: str = ""
    workflow_id: str = ""
    request_id: str = ""
    worker_pid: int = 0

    def as_log_fields(self) -> dict[str, object]:
        return {key: value for key, value in asdict(self).items() if value not in ("", 0, None)}


_DEFAULT_CONTEXT = DiagnosticContext(
    session_id=uuid.uuid4().hex,
    worker_pid=os.getpid(),
)
_CURRENT_CONTEXT: contextvars.ContextVar[DiagnosticContext] = contextvars.ContextVar(
    "lca_diagnostic_context",
    default=_DEFAULT_CONTEXT,
)


def current_diagnostic_context() -> DiagnosticContext:
    return _CURRENT_CONTEXT.get()


@contextlib.contextmanager
def bind_diagnostic_context(
    *,
    session_id: Optional[str] = None,
    job_id: Optional[str] = None,
    workflow_id: Optional[str] = None,
    request_id: Optional[str] = None,
    worker_pid: Optional[int] = None,
) -> Iterator[DiagnosticContext]:
    current = current_diagnostic_context()
    updated = replace(
        current,
        session_id=current.session_id if session_id is None else str(session_id),
        job_id=current.job_id if job_id is None else str(job_id),
        workflow_id=current.workflow_id if workflow_id is None else str(workflow_id),
        request_id=current.request_id if request_id is None else str(request_id),
        worker_pid=current.worker_pid if worker_pid is None else int(worker_pid),
    )
    token = _CURRENT_CONTEXT.set(updated)
    try:
        yield updated
    finally:
        _CURRENT_CONTEXT.reset(token)
