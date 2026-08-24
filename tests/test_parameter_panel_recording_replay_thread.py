import os
import sys
import unittest
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication

from ui.panels.recording.parameter_panel_recording_replay_thread import (
    ParameterPanelReplayThread,
)


class _FakeReplayEngine:
    def __init__(self, should_succeed=True):
        self.should_succeed = should_succeed
        self.stop_called = False
        self.replay_kwargs = None

    def stop(self):
        self.stop_called = True

    def replay(self, **kwargs):
        self.replay_kwargs = kwargs
        step_callback = kwargs.get('step_callback')
        if step_callback:
            step_callback(0)
            step_callback(1)
        return self.should_succeed


class ParameterPanelReplayThreadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_run_emits_step_and_success_result_without_touching_global_hook(self):
        fake_engine = _FakeReplayEngine(should_succeed=True)

        with mock.patch(
            'ui.panels.recording.parameter_panel_recording_replay_thread.ReplayEngine',
            return_value=fake_engine,
        ):
            thread = ParameterPanelReplayThread(
                [{'type': 'mouse_move'}, {'type': 'mouse_click'}],
                1.0,
                1,
                '全屏录制',
                0,
                0,
            )

        steps = []
        results = []
        finished = []
        original_hook = sys.excepthook

        thread.step_changed.connect(steps.append)
        thread.result_signal.connect(lambda success, message: results.append((success, message)))
        thread.finished_signal.connect(lambda: finished.append(True))

        thread.run()

        self.assertIs(sys.excepthook, original_hook)
        self.assertEqual(steps, [0, 1])
        self.assertEqual(results, [(True, '回放完成')])
        self.assertEqual(finished, [True])
        self.assertIn('step_callback', fake_engine.replay_kwargs)

    def test_stop_delegates_to_replay_engine(self):
        fake_engine = _FakeReplayEngine(should_succeed=False)

        with mock.patch(
            'ui.panels.recording.parameter_panel_recording_replay_thread.ReplayEngine',
            return_value=fake_engine,
        ):
            thread = ParameterPanelReplayThread(
                [{'type': 'mouse_move'}],
                1.0,
                1,
                '全屏录制',
                0,
                0,
            )

        thread.stop()
        self.assertTrue(fake_engine.stop_called)


if __name__ == '__main__':
    unittest.main()
