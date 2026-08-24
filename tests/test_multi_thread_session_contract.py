import os
import unittest
from unittest.mock import patch

from task_workflow.multi_thread_session import WorkflowMultiThreadSession
from utils.thread_start_utils import THREAD_START_TASK_TYPE


def _start(card_id):
    return {
        "id": card_id,
        "task_type": THREAD_START_TASK_TYPE,
        "parameters": {},
    }


class MultiThreadSessionContractTests(unittest.TestCase):
    def _create(self, **overrides):
        values = {
            "cards_data": {1: _start(1), 2: _start(2)},
            "connections_data": [],
            "task_modules": {},
            "start_card_ids": [1, 2],
            "target_window_title": "workflow-window",
            "target_hwnd": 100,
            "workflow_id": "workflow",
        }
        values.update(overrides)
        return WorkflowMultiThreadSession(**values)

    def test_preserves_explicit_start_order(self):
        session = self._create(start_card_ids=[2, 1])

        self.assertEqual(list(session._entries), [2, 1])

    def test_requires_at_least_two_starts(self):
        with self.assertRaisesRegex(ValueError, "至少需要两个线程起点"):
            self._create(start_card_ids=[1])

    def test_rejects_duplicate_start(self):
        with self.assertRaisesRegex(ValueError, "线程起点ID重复"):
            self._create(start_card_ids=[1, 1])

    def test_rejects_non_integer_start(self):
        with self.assertRaisesRegex(TypeError, "线程起点ID必须是整数"):
            self._create(start_card_ids=[1, "2"])

    def test_rejects_start_count_above_cpu_limit(self):
        with patch.object(WorkflowMultiThreadSession, "_detect_cpu_logical_threads", return_value=1):
            with self.assertRaisesRegex(ValueError, "超过CPU逻辑线程上限"):
                self._create()

    def test_rejects_unknown_thread_label(self):
        with self.assertRaisesRegex(ValueError, "线程标签引用了未知起点"):
            self._create(thread_labels={3: "unknown"})

    def test_rejects_unknown_window_config(self):
        with self.assertRaisesRegex(ValueError, "线程窗口配置引用了未知起点"):
            self._create(
                thread_window_configs={
                    3: {"target_hwnd": 300, "target_window_title": "unknown"}
                }
            )

    def test_rejects_invalid_window_handle_in_thread_config(self):
        with self.assertRaisesRegex(ValueError, "线程窗口配置句柄无效"):
            self._create(thread_window_configs={1: {"target_hwnd": "100"}})

    def test_thread_window_config_does_not_mix_workflow_title(self):
        session = self._create(
            thread_window_configs={
                1: {"target_hwnd": 200, "target_window_title": ""}
            }
        )

        self.assertEqual(session._entries[1]["target_hwnd"], 200)
        self.assertEqual(session._entries[1]["target_window_title"], "")
        self.assertEqual(session._entries[2]["target_hwnd"], 100)
        self.assertEqual(
            session._entries[2]["target_window_title"],
            "workflow-window",
        )

    def test_invalid_boolean_environment_value_is_rejected(self):
        with patch.dict(os.environ, {"LCA_MT_MEM_DIAG": "maybe"}):
            with self.assertRaisesRegex(ValueError, "必须是布尔值"):
                self._create()

    def test_invalid_screenshot_limit_environment_is_rejected(self):
        session = self._create()
        with patch.dict(os.environ, {"LCA_MT_SCREENSHOT_LIMIT": "invalid"}):
            with self.assertRaisesRegex(ValueError, "必须是整数"):
                session._resolve_runtime_screenshot_limit()

    def test_duplicate_run_is_rejected(self):
        session = self._create()
        session._is_running = True

        with self.assertRaisesRegex(RuntimeError, "已在运行中"):
            session.run()


if __name__ == "__main__":
    unittest.main()
