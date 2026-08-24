import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from ui.workflow_parts.workflow_task_manager import WorkflowTaskManager


class _Task:
    def __init__(self, task_id, *, status="idle", enabled=True, start_result=True):
        self.task_id = task_id
        self.name = f"task-{task_id}"
        self.status = status
        self.enabled = enabled
        self.first_execute = False
        self.workflow_data = {"cards": []}
        self.execution_mode = "foreground"
        self.executor = None
        self.executor_thread = None
        self.start_result = start_result
        self.stop_calls = 0
        self.delete_calls = 0

    def can_execute(self):
        return self.enabled and self.status in {"idle", "completed", "failed", "stopped"}

    def execute_async(self):
        if not self.start_result:
            return None
        self.status = "running"
        return object()

    def stop(self):
        self.stop_calls += 1
        self.status = "stopped"
        return True

    def deleteLater(self):
        self.delete_calls += 1


class WorkflowTaskManagerContractTests(unittest.TestCase):
    def test_sequential_mode_requires_explicit_current_task(self):
        manager = WorkflowTaskManager({}, "", {"workflow_execution_mode": "sequential_jump"})
        manager.tasks = {1: _Task(1)}

        self.assertFalse(manager.execute_all(None))
        self.assertIn("明确指定", manager.get_last_execute_error_message())

    def test_multiple_first_execute_tasks_are_rejected(self):
        manager = WorkflowTaskManager({}, "", {"workflow_execution_mode": "sequential_jump"})
        first = _Task(1)
        second = _Task(2)
        first.first_execute = True
        second.first_execute = True
        manager.tasks = {1: first, 2: second}

        self.assertFalse(manager.execute_all(1))
        self.assertIn("只能配置一个", manager.get_last_execute_error_message())

    def test_execute_task_uses_manager_state_tracking(self):
        manager = WorkflowTaskManager({}, "", {})
        task = _Task(1)
        manager.tasks = {1: task}

        self.assertTrue(manager.execute_task(1))
        self.assertTrue(manager._is_executing)
        self.assertEqual(manager._executing_task_ids, [1])

    def test_remove_active_task_is_rejected_without_stop_or_retry(self):
        manager = WorkflowTaskManager({}, "", {"workflow_execution_mode": "parallel"})
        task = _Task(1, status="running")
        task.executor = SimpleNamespace(is_running=lambda: True)
        manager.tasks = {1: task}

        self.assertFalse(manager.remove_task(1))

        self.assertEqual(task.stop_calls, 0)
        self.assertIn(1, manager.tasks)

    def test_remove_idle_task_with_runtime_reference_is_rejected(self):
        manager = WorkflowTaskManager({}, "", {"workflow_execution_mode": "parallel"})
        task = _Task(1, status="completed")
        task.executor_thread = Mock()
        task.executor_thread.isRunning.return_value = False
        manager.tasks = {1: task}

        self.assertFalse(manager.remove_task(1))
        self.assertIn(1, manager.tasks)

    def test_remove_clean_idle_task_is_immediate(self):
        manager = WorkflowTaskManager({}, "", {"workflow_execution_mode": "parallel"})
        task = _Task(1)
        manager.tasks = {1: task}

        self.assertTrue(manager.remove_task(1))
        self.assertNotIn(1, manager.tasks)
        self.assertEqual(task.delete_calls, 1)

    def test_stop_all_without_active_task_reports_failure(self):
        manager = WorkflowTaskManager({}, "", {"workflow_execution_mode": "parallel"})
        manager.tasks = {1: _Task(1)}

        self.assertFalse(manager.stop_all())

    def test_clear_all_rejects_active_tasks_without_stopping_them(self):
        manager = WorkflowTaskManager({}, "", {})
        task = _Task(1, status="running")
        manager.tasks = {1: task}

        self.assertFalse(manager.clear_all())
        self.assertEqual(task.stop_calls, 0)
        self.assertIn(1, manager.tasks)


if __name__ == "__main__":
    unittest.main()
