import unittest
from unittest import mock

from utils.raw_input_recorder import OptimizedMouseReplayer


class RawInputRecorderTests(unittest.TestCase):
    def test_replay_relative_movements_reuses_unified_replay_engine(self):
        fake_engine = mock.Mock()
        fake_engine.replay.return_value = True
        actions = [
            {'type': 'mouse_move_relative', 'time': 0.1, 'dx': 3, 'dy': -2},
            {'type': 'mouse_click', 'time': 0.2, 'x': 1, 'y': 2},
        ]

        with mock.patch('utils.raw_input_recorder.ReplayEngine', return_value=fake_engine):
            result = OptimizedMouseReplayer.replay_relative_movements(actions, speed=1.5)

        self.assertTrue(result)
        fake_engine.replay.assert_called_once_with(
            actions=[{'type': 'mouse_move_relative', 'time': 0.1, 'dx': 3, 'dy': -2}],
            speed=1.5,
            loop_count=1,
            recording_area='全屏录制',
            window_offset_x=0,
            window_offset_y=0,
            precise_timer=None,
            recording_mode='相对位移',
        )


if __name__ == '__main__':
    unittest.main()
