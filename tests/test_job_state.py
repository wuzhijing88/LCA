from app_core.control_plane.job_state import (
    JobState,
    aggregate_runner_states,
    can_transition,
    parse_job_state,
)


def test_job_state_transition_contract():
    assert can_transition(JobState.READY, JobState.STARTING)
    assert can_transition(JobState.RUNNING, JobState.PAUSED)
    assert can_transition(JobState.PAUSED, JobState.STOPPING)
    assert not can_transition(JobState.COMPLETED, JobState.RUNNING)


def test_job_state_aliases_and_aggregation():
    assert parse_job_state("暂停中") is JobState.PAUSED
    assert parse_job_state("FAILED") is JobState.FAILED
    assert aggregate_runner_states([JobState.COMPLETED, JobState.RUNNING]) is JobState.RUNNING
    assert aggregate_runner_states([JobState.COMPLETED, JobState.COMPLETED]) is JobState.COMPLETED
