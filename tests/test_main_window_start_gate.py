import unittest
from types import SimpleNamespace
from unittest.mock import patch

from ui.main_window_parts.main_window_start_orchestrator import (
    _has_runtime_that_blocks_start,
    main_window_safe_start_tasks,
)


class _TaskManager:
    def __init__(self, tasks):
        self._tasks = tasks

    def get_all_tasks(self):
        return list(self._tasks)


class _Runtime:
    def __init__(self, state):
        self._state = state

    def get_pause_state(self):
        return self._state

    def is_running(self):
        return self._state in {"running", "paused"}


class MainWindowStartGateTests(unittest.TestCase):
    def test_stopping_flag_blocks_start(self):
        ctx = SimpleNamespace(_is_stopping_tasks=True)
        self.assertTrue(_has_runtime_that_blocks_start(ctx))

    def test_live_task_runtime_blocks_start(self):
        task = SimpleNamespace(status="stopped", executor=_Runtime("running"), executor_thread=None)
        ctx = SimpleNamespace(task_manager=_TaskManager([task]))
        self.assertTrue(_has_runtime_that_blocks_start(ctx))

    def test_paused_task_runtime_blocks_start(self):
        task = SimpleNamespace(status="paused", executor=_Runtime("paused"), executor_thread=None)
        ctx = SimpleNamespace(task_manager=_TaskManager([task]))
        self.assertTrue(_has_runtime_that_blocks_start(ctx))

    def test_paused_main_executor_blocks_start(self):
        runtime = SimpleNamespace(_paused=True, is_running=lambda: True)
        ctx = SimpleNamespace(executor=runtime)
        self.assertTrue(_has_runtime_that_blocks_start(ctx))

    def test_running_task_state_blocks_start_before_task_scan(self):
        state_manager = SimpleNamespace(get_current_state=lambda: "running")
        ctx = SimpleNamespace(task_state_manager=state_manager)
        self.assertTrue(_has_runtime_that_blocks_start(ctx))

    def test_terminal_task_with_pending_cleanup_blocks_start(self):
        task = SimpleNamespace(
            status="stopped",
            executor=_Runtime("idle"),
            executor_thread=None,
        )
        ctx = SimpleNamespace(task_manager=_TaskManager([task]))
        self.assertTrue(_has_runtime_that_blocks_start(ctx))

    def test_start_during_pause_is_rejected_without_popup(self):
        task = SimpleNamespace(
            status="paused",
            executor=_Runtime("paused"),
            executor_thread=None,
        )
        ctx = SimpleNamespace(task_manager=_TaskManager([task]))

        with patch(
            "ui.main_window_parts.main_window_start_orchestrator.QMessageBox.warning"
        ) as warning:
            main_window_safe_start_tasks(ctx)

        warning.assert_not_called()


if __name__ == "__main__":
    unittest.main()
