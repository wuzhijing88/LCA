import queue
import threading
import time
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from task_workflow.process_proxy import ProcessWorkflowExecutorProxy
from services.socket_message_utils import SocketMessageError


class _FakeProcess:
    def __init__(self, poll_values):
        self._poll_values = list(poll_values)

    def poll(self):
        if len(self._poll_values) > 1:
            return self._poll_values.pop(0)
        if self._poll_values:
            return self._poll_values[0]
        return 0

    def wait(self, timeout=None):
        return self.poll()


class _LaunchProcess:
    pid = 43210

    def __init__(self):
        self.killed = False

    def poll(self):
        return -9 if self.killed else None

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        return self.poll()


class _BlockingLaunchSocket:
    def __init__(self):
        self.closed = threading.Event()

    def setsockopt(self, *args):
        return None

    def bind(self, address):
        return None

    def listen(self, backlog):
        return None

    def getsockname(self):
        return ("127.0.0.1", 32123)

    def settimeout(self, timeout):
        return None

    def accept(self):
        self.closed.wait(2.0)
        raise OSError("listener closed")

    def close(self):
        self.closed.set()


class ProcessWorkflowExecutorProxyCompletionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def _drain_messages(self, proxy):
        messages = []
        while True:
            try:
                messages.append(proxy._event_queue.get_nowait())
            except queue.Empty:
                break
        return messages

    def test_buffered_execution_finished_wont_be_overwritten_by_fallback(self):
        proxy = ProcessWorkflowExecutorProxy(payload={}, parent=None)
        proxy._process = _FakeProcess([0])
        proxy._running = True

        proxy._enqueue_message(
            {
                "type": "signal",
                "name": "execution_finished",
                "args": [True, "工作流执行完成"],
            }
        )
        proxy._on_process_stopped()

        messages = self._drain_messages(proxy)
        execution_finished_messages = [
            message
            for message in messages
            if message.get("type") == "signal" and message.get("name") == "execution_finished"
        ]

        self.assertEqual(len(execution_finished_messages), 1)
        self.assertEqual(execution_finished_messages[0].get("args"), [True, "工作流执行完成"])

    def test_reader_loop_stops_when_socket_channel_is_closed(self):
        proxy = ProcessWorkflowExecutorProxy(payload={}, parent=None)
        proxy._process = _FakeProcess([None])
        proxy._socket = object()
        proxy._running = True

        with patch("task_workflow.process_proxy.recv_message", return_value=None):
            with patch.object(ProcessWorkflowExecutorProxy, "_is_socket_peer_closed", return_value=True):
                proxy._reader_loop()

        messages = self._drain_messages(proxy)
        execution_finished_messages = [
            message
            for message in messages
            if message.get("type") == "signal" and message.get("name") == "execution_finished"
        ]

        self.assertEqual(len(execution_finished_messages), 1)
        self.assertEqual(execution_finished_messages[0].get("args"), [False, "工作流子进程已退出"])

    def test_reader_loop_keeps_draining_tail_messages_after_process_exit(self):
        proxy = ProcessWorkflowExecutorProxy(payload={}, parent=None)
        proxy._process = _FakeProcess([0, 0, 0])
        proxy._socket = object()
        proxy._running = True

        recv_side_effect = [
            None,
            {
                "type": "signal",
                "name": "execution_finished",
                "args": [True, "工作流执行完成"],
            },
            None,
        ]

        with patch("task_workflow.process_proxy.recv_message", side_effect=recv_side_effect):
            with patch.object(
                ProcessWorkflowExecutorProxy,
                "_is_socket_peer_closed",
                side_effect=[False, True],
            ):
                proxy._reader_loop()

        messages = self._drain_messages(proxy)
        execution_finished_messages = [
            message
            for message in messages
            if message.get("type") == "signal" and message.get("name") == "execution_finished"
        ]

        self.assertEqual(len(execution_finished_messages), 1)
        self.assertEqual(execution_finished_messages[0].get("args"), [True, "工作流执行完成"])

    def test_protocol_error_is_reported_instead_of_generic_process_exit(self):
        proxy = ProcessWorkflowExecutorProxy(payload={}, parent=None)
        proxy._process = _FakeProcess([None, 0])
        proxy._socket = object()
        proxy._running = True

        with patch(
            "task_workflow.process_proxy.recv_message",
            side_effect=SocketMessageError("partial_timeout"),
        ):
            proxy._reader_loop()

        messages = self._drain_messages(proxy)
        execution_finished_messages = [
            message
            for message in messages
            if message.get("type") == "signal" and message.get("name") == "execution_finished"
        ]

        self.assertEqual(len(execution_finished_messages), 1)
        self.assertEqual(
            execution_finished_messages[0].get("args"),
            [False, "工作流子进程通信中断，状态=partial_timeout"],
        )

    def test_overlay_update_signal_is_dispatched(self):
        proxy = ProcessWorkflowExecutorProxy(payload={}, parent=None)
        payload = {
            "action": "update",
            "hwnd": 123,
            "detections": [{"x1": 1, "y1": 2, "x2": 3, "y2": 4, "class_name": "test", "confidence": 0.9}],
            "frame_shape": [720, 1280, 3],
        }
        received = []
        proxy.overlay_update_requested.connect(lambda data: received.append(data))

        proxy._dispatch_message(
            {
                "type": "signal",
                "name": "overlay_update_requested",
                "args": [payload],
            }
        )

        self.assertEqual(received, [payload])

    def test_terminate_during_launch_kills_process_and_finishes_launch_thread(self):
        proxy = ProcessWorkflowExecutorProxy(payload={}, parent=None)
        fake_process = _LaunchProcess()
        fake_server = _BlockingLaunchSocket()

        with patch("task_workflow.process_proxy.socket.socket", return_value=fake_server):
            with patch("task_workflow.process_proxy.subprocess.Popen", return_value=fake_process):
                with patch(
                    "task_workflow.process_proxy._kill_process_tree",
                    side_effect=lambda process: process.kill(),
                ):
                    proxy.run()
                    deadline = time.monotonic() + 2.0
                    while proxy._process is None and time.monotonic() < deadline:
                        time.sleep(0.01)

                    self.assertIs(proxy._process, fake_process)
                    proxy.terminate()

        self.assertTrue(fake_process.killed)
        self.assertFalse(proxy._launch_thread.is_alive())
        self.assertFalse(proxy.is_running())

        messages = self._drain_messages(proxy)
        execution_finished_messages = [
            message
            for message in messages
            if message.get("type") == "signal" and message.get("name") == "execution_finished"
        ]
        self.assertEqual(len(execution_finished_messages), 1)

    def test_terminate_while_popen_is_returning_does_not_lose_child_process(self):
        proxy = ProcessWorkflowExecutorProxy(payload={}, parent=None)
        fake_process = _LaunchProcess()
        fake_server = _BlockingLaunchSocket()
        popen_entered = threading.Event()
        release_popen = threading.Event()

        def _delayed_popen(*args, **kwargs):
            popen_entered.set()
            release_popen.wait(2.0)
            return fake_process

        with patch("task_workflow.process_proxy.socket.socket", return_value=fake_server):
            with patch("task_workflow.process_proxy.subprocess.Popen", side_effect=_delayed_popen):
                with patch(
                    "task_workflow.process_proxy._kill_process_tree",
                    side_effect=lambda process: process.kill(),
                ):
                    proxy.run()
                    self.assertTrue(popen_entered.wait(2.0))

                    terminate_thread = threading.Thread(target=proxy.terminate)
                    terminate_thread.start()
                    release_popen.set()
                    terminate_thread.join(2.0)

        self.assertFalse(terminate_thread.is_alive())
        self.assertTrue(fake_process.killed)
        self.assertIsNone(proxy._process)
        self.assertFalse(proxy._launch_thread.is_alive())
        self.assertFalse(proxy.is_running())


if __name__ == "__main__":
    unittest.main()
