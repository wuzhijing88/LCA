import os
import unittest
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication

from ui.dialogs.action_editor_dialog import ActionEditorDialog


class _DummySignal:
    def __init__(self):
        self.connected = []

    def connect(self, callback):
        self.connected.append(callback)


class _FakeReplayThread:
    def __init__(
        self,
        actions,
        speed,
        loop_count,
        recording_area,
        window_offset_x,
        window_offset_y,
        recording_mode,
    ):
        self.args = (
            actions,
            speed,
            loop_count,
            recording_area,
            window_offset_x,
            window_offset_y,
            recording_mode,
        )
        self.step_changed = _DummySignal()
        self.result_signal = _DummySignal()
        self.finished = _DummySignal()
        self.started = False

    def start(self):
        self.started = True

    def isRunning(self):
        return self.started

    def stop(self):
        self.started = False

    def wait(self, timeout):
        return True


class _FakeRunningReplayThread:
    def __init__(self):
        self.stop_called = False
        self.wait_timeout = None

    def isRunning(self):
        return True

    def stop(self):
        self.stop_called = True

    def wait(self, timeout):
        self.wait_timeout = timeout
        return True


class ActionEditorDialogReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_run_test_replay_uses_shared_thread_and_window_resolver(self):
        dialog = ActionEditorDialog(
            actions=[{'type': 'mouse_move', 'time': 0, 'x': 10, 'y': 20}],
            recording_area='窗口录制',
        )

        try:
            with mock.patch(
                'ui.dialogs.action_editor_dialog.resolve_replay_window_offsets_from_config',
                return_value=(100, 200),
            ):
                with mock.patch(
                    'ui.dialogs.action_editor_dialog.ParameterPanelReplayThread',
                    _FakeReplayThread,
                ):
                    dialog._run_test_replay(
                        {
                            'actions': [{'type': 'mouse_move', 'time': 0, 'x': 10, 'y': 20}],
                            'recording_area': '窗口录制',
                            'recording_mode': '绝对坐标',
                        }
                    )

            self.assertIsInstance(dialog._replay_thread, _FakeReplayThread)
            self.assertTrue(dialog._replay_thread.started)
            self.assertEqual(
                dialog._replay_thread.args,
                (
                    [{'type': 'mouse_move', 'time': 0, 'x': 10, 'y': 20}],
                    1.0,
                    1,
                    '窗口录制',
                    100,
                    200,
                    '绝对坐标',
                ),
            )
            self.assertEqual(dialog._replay_thread.step_changed.connected, [dialog.highlight_step])
            self.assertEqual(dialog._replay_thread.result_signal.connected, [dialog._on_test_replay_result])
            self.assertEqual(dialog._replay_thread.finished.connected, [dialog._on_replay_thread_finished])
        finally:
            dialog.close()

    def test_stop_active_replay_thread_stops_running_thread(self):
        dialog = ActionEditorDialog(actions=[])
        fake_thread = _FakeRunningReplayThread()
        dialog._replay_thread = fake_thread

        try:
            dialog._stop_active_replay_thread()
            self.assertTrue(fake_thread.stop_called)
            self.assertEqual(fake_thread.wait_timeout, 1500)
        finally:
            dialog.close()


if __name__ == '__main__':
    unittest.main()
