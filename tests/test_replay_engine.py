import unittest
from unittest import mock

from utils.replay_engine import ReplayEngine


class ReplayEngineTests(unittest.TestCase):
    def test_replay_returns_false_when_stop_requested_midway(self):
        engine = ReplayEngine()
        actions = [
            {'type': 'mouse_move', 'time': 0},
            {'type': 'mouse_click', 'time': 0},
        ]

        with mock.patch('utils.replay_engine.WIN32_AVAILABLE', True):
            with mock.patch.object(engine, 'disable_mouse_acceleration'):
                with mock.patch.object(engine, 'restore_mouse_acceleration'):
                    def stop_after_first_action(*args, **kwargs):
                        engine.stop()
                        return True

                    with mock.patch.object(engine, 'execute_action', side_effect=stop_after_first_action) as execute_action:
                        result = engine.replay(actions=actions)

        self.assertFalse(result)
        self.assertEqual(execute_action.call_count, 1)

    def test_replay_emits_step_callback_for_each_action(self):
        engine = ReplayEngine()
        actions = [
            {'type': 'mouse_move', 'time': 0},
            {'type': 'mouse_click', 'time': 0},
        ]
        steps = []

        with mock.patch('utils.replay_engine.WIN32_AVAILABLE', True):
            with mock.patch.object(engine, 'disable_mouse_acceleration'):
                with mock.patch.object(engine, 'restore_mouse_acceleration'):
                    with mock.patch.object(engine, 'execute_action', return_value=True):
                        result = engine.replay(actions=actions, step_callback=steps.append)

        self.assertTrue(result)
        self.assertEqual(steps, [0, 1])


if __name__ == '__main__':
    unittest.main()
