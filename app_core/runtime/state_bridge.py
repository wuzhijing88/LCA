"""Read-only bridge between global UI state and per-job control state."""

from __future__ import annotations

from typing import Any, Optional

from app_core.control_plane.job_state import ACTIVE_JOB_STATES, JobState, parse_job_state


_GLOBAL_TO_JOB = {
    "starting": JobState.STARTING,
    "running": JobState.RUNNING,
    "paused": JobState.PAUSED,
    "stopping": JobState.STOPPING,
    "stopped": JobState.STOPPED,
}


def global_state_to_job(value: Any) -> Optional[JobState]:
    text = str(value or "").strip().lower()
    if text in _GLOBAL_TO_JOB:
        return _GLOBAL_TO_JOB[text]
    return parse_job_state(value)


def state_blocks_new_source(value: Any) -> bool:
    state = global_state_to_job(value)
    return state in ACTIVE_JOB_STATES if state is not None else False


__all__ = ["global_state_to_job", "state_blocks_new_source"]
