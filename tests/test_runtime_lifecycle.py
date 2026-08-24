from app_core.control_plane.job_state import JobState
from app_core.runtime.lifecycle import RuntimeLifecycle
from app_core.runtime.state_bridge import global_state_to_job, state_blocks_new_source


def test_lifecycle_orders_callbacks_and_runs_once():
    calls = []
    lifecycle = RuntimeLifecycle()
    lifecycle.register("late", lambda: calls.append("late"), priority=20)
    lifecycle.register("early", lambda: calls.append("early"), priority=10)

    first = lifecycle.teardown()
    second = lifecycle.teardown()

    assert calls == ["early", "late"]
    assert [result.name for result in first] == ["early", "late"]
    assert second == []


def test_state_bridge_maps_global_state_without_owning_state():
    assert global_state_to_job("starting") is JobState.STARTING
    assert global_state_to_job("已暂停") is JobState.PAUSED
    assert state_blocks_new_source("running")
    assert not state_blocks_new_source("stopped")
