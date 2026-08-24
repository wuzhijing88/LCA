from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .job_state import (
    ACTIVE_JOB_STATES,
    JobState,
    default_step_for,
)


@dataclass
class JobSnapshot:
    job_id: str
    title: str
    hwnd: Optional[int]
    state: JobState
    step: str
    assignments: List[Dict[str, Any]]
    last_error: str = ""

    @property
    def is_active(self) -> bool:
        return self.state in ACTIVE_JOB_STATES

    @property
    def has_assignments(self) -> bool:
        return bool(self.assignments)


@dataclass
class CommandResult:
    ok: bool
    job_id: str = ""
    reason: str = ""
    state: Optional[JobState] = None
    snapshot: Optional[JobSnapshot] = None


@dataclass
class Job:
    job_id: str
    title: str = ""
    hwnd: Optional[int] = None
    assignments: List[Dict[str, Any]] = field(default_factory=list)
    state: JobState = JobState.UNASSIGNED
    step: str = ""
    last_error: str = ""

    def __post_init__(self):
        if not self.step:
            self.step = default_step_for(self.state)

    @property
    def is_active(self) -> bool:
        return self.state in ACTIVE_JOB_STATES

    def snapshot(self) -> JobSnapshot:
        return JobSnapshot(
            job_id=self.job_id,
            title=self.title,
            hwnd=self.hwnd,
            state=self.state,
            step=self.step,
            assignments=self.assignments,
            last_error=self.last_error,
        )
