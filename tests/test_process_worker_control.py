import threading
import unittest
from unittest.mock import patch

from task_workflow.process_worker import _control_loop


class _FakeExecutor:
    def __init__(self):
        self.stop_calls = []

    def request_stop(self, force=False):
        self.stop_calls.append(bool(force))


class ProcessWorkerControlTests(unittest.TestCase):
    def test_parent_socket_close_force_stops_executor(self):
        executor = _FakeExecutor()
        stop_event = threading.Event()

        with patch("task_workflow.process_worker.recv_message", return_value=None):
            with patch("task_workflow.process_worker._is_socket_peer_closed", return_value=True):
                _control_loop(object(), executor, stop_event)

        self.assertTrue(stop_event.is_set())
        self.assertEqual(executor.stop_calls, [True])

    def test_normal_control_loop_shutdown_does_not_stop_completed_executor(self):
        executor = _FakeExecutor()
        stop_event = threading.Event()
        stop_event.set()

        _control_loop(object(), executor, stop_event)

        self.assertEqual(executor.stop_calls, [])

    def test_shutdown_command_force_stops_executor_once(self):
        executor = _FakeExecutor()
        stop_event = threading.Event()

        with patch(
            "task_workflow.process_worker.recv_message",
            return_value={"command": "shutdown"},
        ):
            _control_loop(object(), executor, stop_event)

        self.assertTrue(stop_event.is_set())
        self.assertEqual(executor.stop_calls, [True])

    def test_unknown_command_force_stops_executor_once(self):
        executor = _FakeExecutor()
        stop_event = threading.Event()

        with patch(
            "task_workflow.process_worker.recv_message",
            return_value={"command": "legacy_restart"},
        ):
            _control_loop(object(), executor, stop_event)

        self.assertTrue(stop_event.is_set())
        self.assertEqual(executor.stop_calls, [True])


if __name__ == "__main__":
    unittest.main()
