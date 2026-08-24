import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt

from task_workflow.process_worker import _SocketSignalBridge


class _FakeSignal:
    def __init__(self):
        self.connections = []

    def connect(self, handler, connection_type=None):
        self.connections.append((handler, connection_type))


class _FakeExecutor:
    def __init__(self):
        for signal_name in _SocketSignalBridge._FORWARDED_SIGNALS:
            setattr(self, signal_name, _FakeSignal())
        self.execution_finished = _FakeSignal()


class ProcessWorkerSignalBridgeTests(unittest.TestCase):
    def test_executor_signals_use_direct_connections(self):
        bridge = _SocketSignalBridge(object())
        executor = _FakeExecutor()

        bridge.bind_executor(executor)

        signal_names = (*bridge._FORWARDED_SIGNALS, "execution_finished")
        for signal_name in signal_names:
            connections = getattr(executor, signal_name).connections
            self.assertEqual(len(connections), 1, signal_name)
            self.assertEqual(
                connections[0][1],
                Qt.ConnectionType.DirectConnection,
                signal_name,
            )

    def test_completion_is_marked_after_finished_message_is_sent(self):
        bridge = _SocketSignalBridge(object())

        with patch("task_workflow.process_worker.send_message", return_value=True) as send_mock:
            sent = bridge.send_execution_finished(True, "完成")

        self.assertTrue(sent)
        self.assertTrue(bridge.finished_sent)
        self.assertFalse(bridge.send_failed)
        self.assertEqual(send_mock.call_count, 1)
        payload = send_mock.call_args.args[1]
        self.assertEqual(payload["name"], "execution_finished")
        self.assertEqual(payload["args"], [True, "完成"])

    def test_finished_send_failure_does_not_mark_completion(self):
        bridge = _SocketSignalBridge(object())

        with patch("task_workflow.process_worker.send_message", return_value=False) as send_mock:
            sent = bridge.send_execution_finished(True, "完成")

        self.assertFalse(sent)
        self.assertFalse(bridge.finished_sent)
        self.assertTrue(bridge.send_failed)
        self.assertEqual(send_mock.call_count, 1)

    def test_duplicate_completion_is_rejected(self):
        bridge = _SocketSignalBridge(object())

        with patch("task_workflow.process_worker.send_message", return_value=True):
            bridge.send_execution_finished(True, "完成")
            with self.assertRaisesRegex(RuntimeError, "拒绝重复发送"):
                bridge.send_execution_finished(True, "再次完成")


if __name__ == "__main__":
    unittest.main()
