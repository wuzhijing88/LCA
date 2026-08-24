import unittest

from ui.main_window_parts.main_window_execution_flow_runtime_mixin import (
    MainWindowExecutionFlowRuntimeMixin,
)
from ui.main_window_parts.main_window_execution_status_mixin import (
    MainWindowExecutionStatusMixin,
)


class _TaskStub:
    def __init__(self, status: str):
        self.status = status


class _TaskManagerStub:
    def __init__(self, tasks, active_runtime: bool):
        self._tasks = list(tasks)
        self._active_runtime = active_runtime

    def get_all_tasks(self):
        return list(self._tasks)

    def get_running_count(self):
        return sum(1 for task in self._tasks if task.status == "running")

    def has_active_runtime_tasks(self):
        return self._active_runtime


class _TaskStateManagerStub:
    def __init__(self):
        self.confirm_calls = 0

    def confirm_stopped(self):
        self.confirm_calls += 1


class _ExecutionStatusWindowStub(MainWindowExecutionStatusMixin):
    def __init__(self, task_manager, task_state_manager=None):
        self.task_manager = task_manager
        self.task_state_manager = task_state_manager
        self._floating_controller = None
        self._active_jump_timers = []
        self._is_jumping = False
        self.reset_calls = 0
        self.pause_updates = []

    def _update_status_bar(self):
        pass

    def _set_line_animation_paused(self, reason: str, paused: bool):
        self.pause_updates.append((reason, paused))

    def _reset_run_button(self):
        self.reset_calls += 1

    def _set_step_detail_style(self, text_color=None):
        pass


class _ExecutionFlowRuntimeWindowStub(MainWindowExecutionFlowRuntimeMixin):
    def __init__(self, task_manager, task_state_manager):
        self.task_manager = task_manager
        self.task_state_manager = task_state_manager
        self._active_jump_timers = []
        self._is_jumping = False
        self.reset_calls = 0

    def _reset_run_button(self):
        self.reset_calls += 1


class MainWindowRuntimeCleanupGateTests(unittest.TestCase):
    def test_status_change_does_not_reset_button_while_cleanup_pending(self):
        task_manager = _TaskManagerStub([_TaskStub("failed")], active_runtime=True)
        window = _ExecutionStatusWindowStub(task_manager)

        window._on_task_status_changed(1, "failed")

        self.assertEqual(window.reset_calls, 0)
        self.assertEqual(window.pause_updates[-1], ("task_runtime", True))

        task_manager._active_runtime = False
        window._on_task_status_changed(1, "failed")

        self.assertEqual(window.reset_calls, 1)
        self.assertEqual(window.pause_updates[-1], ("task_runtime", False))

    def test_flow_completion_does_not_confirm_stopped_before_cleanup_finishes(self):
        task_manager = _TaskManagerStub([_TaskStub("failed")], active_runtime=True)
        task_state_manager = _TaskStateManagerStub()
        window = _ExecutionFlowRuntimeWindowStub(task_manager, task_state_manager)

        window._check_and_reset_button_after_workflow()

        self.assertEqual(window.reset_calls, 0)
        self.assertEqual(task_state_manager.confirm_calls, 0)

    def test_all_tasks_completed_confirms_stopped(self):
        task_manager = _TaskManagerStub([_TaskStub("completed")], active_runtime=False)
        task_state_manager = _TaskStateManagerStub()
        window = _ExecutionStatusWindowStub(task_manager, task_state_manager)

        window._on_all_tasks_completed(True, "completed")

        self.assertEqual(window.reset_calls, 1)
        self.assertEqual(task_state_manager.confirm_calls, 1)
        self.assertEqual(window.pause_updates[-1], ("task_runtime", False))


if __name__ == "__main__":
    unittest.main()
