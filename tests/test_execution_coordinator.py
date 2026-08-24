import pytest

from app_core.runtime.execution_coordinator import (
    ExecutionConflictError,
    ExecutionCoordinator,
    ExecutionSource,
)


class _Signal:
    def __init__(self):
        self._slots = []

    def connect(self, slot):
        self._slots.append(slot)

    def emit(self, *args):
        for slot in list(self._slots):
            slot(*args)


class _Executor:
    def __init__(self):
        self.execution_finished = _Signal()


class _ThreadHandle:
    def __init__(self):
        self.finished = _Signal()


def _factory(**_kwargs):
    return _Executor(), _ThreadHandle()


def test_coordinator_blocks_competing_execution_sources():
    coordinator = ExecutionCoordinator(runtime_factory=_factory)
    executor, _thread = coordinator.create_runtime(
        source=ExecutionSource.MAIN_WINDOW,
        workflow_id="one",
    )

    with pytest.raises(ExecutionConflictError):
        coordinator.create_runtime(
            source=ExecutionSource.CONTROL_CENTER,
            workflow_id="two",
        )

    executor.execution_finished.emit(True, "done")
    assert coordinator.active_sources() == set()


def test_coordinator_allows_multiple_sessions_from_same_source():
    coordinator = ExecutionCoordinator(runtime_factory=_factory)

    coordinator.create_runtime(source=ExecutionSource.CONTROL_CENTER, workflow_id="one")
    coordinator.create_runtime(source=ExecutionSource.CONTROL_CENTER, workflow_id="two")

    assert coordinator.active_sources() == {ExecutionSource.CONTROL_CENTER}
    assert len(coordinator.snapshots()) == 2
