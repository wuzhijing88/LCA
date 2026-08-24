import unittest

from ui.workflow_parts.workflow_lifecycle import _normalize_task_manager_before_start
from ui.workflow_parts.workflow_task_manager import WorkflowTaskManager


class _ThreadStub:
    def __init__(self, running: bool):
        self.running = running

    def isRunning(self):
        return self.running


class _TaskStub:
    def __init__(self, status: str, thread_running: bool, cleanup_success: bool = True):
        self.status = status
        self.enabled = True
        self.modified = False
        self.executor = None
        self.executor_thread = _ThreadStub(thread_running)
        self.cleanup_calls = 0
        self.cleanup_success = cleanup_success

    def can_execute(self):
        return self.enabled and self.status in ["idle", "completed", "failed", "stopped", "paused"]

    def _force_cleanup_executor(self):
        self.cleanup_calls += 1
        if self.cleanup_success:
            self.executor = None
            self.executor_thread = None
            return True
        return False


class _JumpTaskStub:
    def __init__(self, task_id: int, name: str):
        self.task_id = task_id
        self.name = name
        self.stop_reason = "success"
        self.jump_rules = {}


class WorkflowTaskManagerRuntimeCleanupTests(unittest.TestCase):
    def test_defers_all_tasks_completed_until_runtime_cleanup_finishes(self):
        manager = WorkflowTaskManager({}, "", {})
        task = _TaskStub(status="failed", thread_running=True)
        manager.tasks = {1: task}
        manager._is_executing = True
        manager._executing_task_ids = [1]

        completed_events = []
        manager.all_tasks_completed.connect(
            lambda success, result_type: completed_events.append((success, result_type))
        )

        manager._on_task_status_changed(1, "failed")

        self.assertTrue(manager._is_executing)
        self.assertEqual(completed_events, [])

        task.executor_thread.running = False
        manager._on_task_status_changed(1, "failed")

        self.assertFalse(manager._is_executing)
        self.assertEqual(completed_events, [(False, "failed")])

    def test_runtime_cleanup_callback_finishes_execution_without_second_status_change(self):
        manager = WorkflowTaskManager({}, "", {})
        task = _TaskStub(status="completed", thread_running=True)
        manager.tasks = {1: task}
        manager._is_executing = True
        manager._executing_task_ids = [1]

        completed_events = []
        manager.all_tasks_completed.connect(
            lambda success, result_type: completed_events.append((success, result_type))
        )

        manager._on_task_status_changed(1, "completed")

        self.assertTrue(manager._is_executing)
        self.assertEqual(completed_events, [])

        task.executor_thread.running = False
        manager._on_task_runtime_cleanup_finished(1)

        self.assertFalse(manager._is_executing)
        self.assertEqual(completed_events, [(True, "completed")])

    def test_normalize_keeps_executing_flag_while_cleanup_is_pending(self):
        manager = WorkflowTaskManager({}, "", {})
        task = _TaskStub(status="running", thread_running=True)
        manager.tasks = {1: task}
        manager._is_executing = True
        manager._executing_task_ids = [1]

        _normalize_task_manager_before_start(manager)

        self.assertTrue(manager._is_executing)
        self.assertEqual(manager._executing_task_ids, [1])
        self.assertEqual(task.cleanup_calls, 0)

        task.status = "failed"
        task.executor_thread.running = False
        _normalize_task_manager_before_start(manager)

        self.assertFalse(manager._is_executing)
        self.assertEqual(manager._executing_task_ids, [])
        self.assertEqual(task.cleanup_calls, 1)

    def test_normalize_attempts_cleanup_for_terminal_task_with_live_thread_before_restart(self):
        manager = WorkflowTaskManager({}, "", {})
        task = _TaskStub(status="stopped", thread_running=True, cleanup_success=True)
        manager.tasks = {1: task}
        manager._is_executing = False
        manager._executing_task_ids = []

        _normalize_task_manager_before_start(manager)

        self.assertEqual(task.cleanup_calls, 1)
        self.assertIsNone(task.executor_thread)

    def test_normalize_keeps_terminal_task_when_live_thread_cleanup_fails(self):
        manager = WorkflowTaskManager({}, "", {})
        task = _TaskStub(status="stopped", thread_running=True, cleanup_success=False)
        manager.tasks = {1: task}
        manager._is_executing = False
        manager._executing_task_ids = []

        _normalize_task_manager_before_start(manager)

        self.assertEqual(task.cleanup_calls, 1)
        self.assertIsNotNone(task.executor_thread)

    def test_find_jump_target_rejects_legacy_integer_rule(self):
        manager = WorkflowTaskManager({}, "", {})
        task = _JumpTaskStub(1, "main")
        task.jump_rules = {"success": 1}
        manager.tasks = {1: task}

        with self.assertRaisesRegex(TypeError, "对象格式"):
            manager.find_jump_target(task)

    def test_find_jump_target_does_not_fall_back_to_name(self):
        manager = WorkflowTaskManager({}, "", {})
        task = _JumpTaskStub(1, "main")
        task.jump_rules = {"success": {"id": 999, "name": "main"}}
        manager.tasks = {1: task}

        with self.assertRaisesRegex(ValueError, "不存在"):
            manager.find_jump_target(task)

    def test_find_jump_target_accepts_new_id_object(self):
        manager = WorkflowTaskManager({}, "", {})
        task = _JumpTaskStub(1, "main")
        task.jump_rules = {"success": {"id": 1}}
        manager.tasks = {1: task}

        self.assertEqual(manager.find_jump_target(task), 1)


if __name__ == "__main__":
    unittest.main()
