import unittest

from task_workflow.thread_window_binding import (
    THREAD_WINDOW_LIMIT_PARAM,
    THREAD_WINDOW_LIMIT_TASK_TYPE,
    resolve_thread_window_configs,
)
from utils.thread_start_utils import THREAD_START_TASK_TYPE


def _start(card_id):
    return {"id": card_id, "task_type": THREAD_START_TASK_TYPE, "parameters": {}}


def _limit(card_id, window_index):
    return {
        "id": card_id,
        "task_type": THREAD_WINDOW_LIMIT_TASK_TYPE,
        "parameters": {THREAD_WINDOW_LIMIT_PARAM: window_index},
    }


def _connection(start_id, end_id, line_type="sequential"):
    return {
        "start_card_id": start_id,
        "end_card_id": end_id,
        "type": line_type,
    }


class ThreadWindowBindingTests(unittest.TestCase):
    def _resolve(self, **overrides):
        values = {
            "cards_data": {1: _start(1), 10: _limit(10, 2)},
            "connections_data": [_connection(10, 1)],
            "start_card_ids": [1],
            "bound_windows": [
                {"hwnd": 101, "title": "A", "enabled": True},
                {"hwnd": 202, "title": "B", "enabled": True},
            ],
        }
        values.update(overrides)
        return resolve_thread_window_configs(**values)

    def test_resolves_selected_enabled_window(self):
        self.assertEqual(
            self._resolve(),
            {
                1: {
                    "window_index": 2,
                    "target_hwnd": 202,
                    "target_window_title": "B",
                    "source_card_id": 10,
                }
            },
        )

    def test_missing_limit_card_keeps_explicit_workflow_target(self):
        result = self._resolve(
            cards_data={1: _start(1)},
            connections_data=[],
            bound_windows=[],
        )
        self.assertEqual(result, {})

    def test_unset_limit_selector_keeps_explicit_workflow_target(self):
        result = self._resolve(cards_data={1: _start(1), 10: _limit(10, None)})
        self.assertEqual(result, {})

    def test_duplicate_limit_cards_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "多个窗口限制卡"):
            self._resolve(
                cards_data={1: _start(1), 10: _limit(10, 1), 11: _limit(11, 2)},
                connections_data=[_connection(10, 1), _connection(11, 1)],
            )

    def test_out_of_range_window_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "当前只有2个启用窗口"):
            self._resolve(cards_data={1: _start(1), 10: _limit(10, 3)})

    def test_invalid_window_handle_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "句柄必须大于0"):
            self._resolve(bound_windows=[{"hwnd": 0, "title": "A", "enabled": True}])

    def test_wrong_limit_connection_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "只能用顺序连线"):
            self._resolve(connections_data=[_connection(10, 1, "success")])

    def test_non_start_requested_as_thread_start_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "不是线程起点"):
            self._resolve(start_card_ids=[10])

    def test_duplicate_connection_is_rejected(self):
        connection = _connection(10, 1)
        with self.assertRaisesRegex(ValueError, "连接重复"):
            self._resolve(connections_data=[connection, dict(connection)])

    def test_conflicting_duplicate_card_data_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "内容冲突"):
            self._resolve(
                cards_data={
                    1: _start(1),
                    "1": {"id": 1, "task_type": "other", "parameters": {}},
                    10: _limit(10, 1),
                }
            )


if __name__ == "__main__":
    unittest.main()
