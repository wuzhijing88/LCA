import unittest
from unittest import mock

from ui.panels.recording.parameter_panel_recording_replay_start_execution_mixin import (
    ParameterPanelRecordingReplayStartExecutionMixin,
)


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
        self.finished_signal = _DummySignal()
        self.finished = _DummySignal()
        self.started = False

    def start(self):
        self.started = True


class _DummyPanel(ParameterPanelRecordingReplayStartExecutionMixin):
    def __init__(self):
        self._replay_thread = None
        self._replay_active = False

    def _on_replay_finished(self):
        pass

    def _on_replay_thread_finished(self):
        pass


class _DummyStartPanel(ParameterPanelRecordingReplayStartExecutionMixin):
    def __init__(self):
        self._replay_thread = None
        self._replay_active = False
        self.current_parameters = {}
        self.messages = []
        self.started = False

    def _can_start_replay(self):
        return True

    def _get_recorded_actions_payload_or_warn(self):
        return {
            'actions': [{'type': 'click'}],
            'recording_area': '窗口录制',
            'recording_mode': '绝对坐标',
        }

    def _resolve_replay_window_offsets(self, recording_area):
        return None, None

    def _resolve_replay_runtime_options(self):
        return 1.0, 1

    def _set_replay_button_running_state(self):
        pass

    def _start_replay_thread(self, *args, **kwargs):
        self.started = True

    def _show_replay_message(self, icon, title, text):
        self.messages.append((title, text))

    def _restore_replay_button_default_state(self):
        pass


class ParameterPanelRecordingReplayStartTests(unittest.TestCase):
    def test_start_replay_thread_uses_explicit_thread_dependency(self):
        panel = _DummyPanel()

        with mock.patch(
            "ui.panels.recording.parameter_panel_recording_replay_start_execution_mixin.ParameterPanelReplayThread",
            _FakeReplayThread,
        ):
            panel._start_replay_thread(
                actions=[{"type": "click"}],
                speed=1.5,
                loop_count=2,
                recording_area="窗口录制",
                window_offset_x=10,
                window_offset_y=20,
                recording_mode="相对坐标",
            )

        self.assertIsNotNone(panel._replay_thread)
        self.assertTrue(panel._replay_thread.started)
        self.assertTrue(panel._replay_active)
        self.assertEqual(
            panel._replay_thread.args,
            ([{"type": "click"}], 1.5, 2, "窗口录制", 10, 20, "相对坐标"),
        )
        self.assertEqual(panel._replay_thread.finished_signal.connected, [panel._on_replay_finished])
        self.assertEqual(panel._replay_thread.finished.connected, [panel._on_replay_thread_finished])

    def test_start_replay_warns_when_window_offsets_unavailable(self):
        panel = _DummyStartPanel()

        panel._start_replay()

        self.assertFalse(panel.started)
        self.assertEqual(
            panel.messages,
            [('提示', '无法进行窗口回放，请检查绑定窗口配置或目标窗口状态')],
        )


if __name__ == "__main__":
    unittest.main()
