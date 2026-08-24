import unittest

from tasks import start_task
from utils.thread_start_utils import is_thread_start_task_type


class ThreadStartTaskTests(unittest.TestCase):
    def test_thread_start_has_no_runtime_parameters(self):
        self.assertEqual(start_task.get_params_definition(), {})

    def test_execute_follows_the_workflow_connection(self):
        result = start_task.execute_task(
            params={},
            counters={},
            execution_mode="foreground",
            target_hwnd=None,
        )

        self.assertEqual(result, (True, "执行下一步", None))

    def test_only_current_thread_start_type_is_recognized(self):
        self.assertTrue(is_thread_start_task_type("线程起点"))
        self.assertFalse(is_thread_start_task_type("起点"))
        self.assertFalse(is_thread_start_task_type(None))

    def test_legacy_run_interface_is_removed(self):
        self.assertFalse(hasattr(start_task, "run"))


if __name__ == "__main__":
    unittest.main()
