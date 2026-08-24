import unittest
from unittest import mock

from task_workflow.executor import WorkflowExecutor


class ExecutorInfiniteLoopGuardTests(unittest.TestCase):
    def _executor(self, cards, connections, start_card_id=1, guard_enabled=True):
        return WorkflowExecutor(
            cards_data=cards,
            connections_data=connections,
            task_modules={},
            start_card_id=start_card_id,
            target_hwnd=None,
            infinite_loop_guard_enabled=guard_enabled,
        )

    def test_detects_closed_reachable_cycle(self):
        executor = self._executor(
            {
                1: {"id": 1, "task_type": "线程起点", "parameters": {}},
                2: {"id": 2, "task_type": "模拟鼠标操作", "parameters": {}},
            },
            [
                {"start_card_id": 1, "end_card_id": 2, "type": "sequential"},
                {"start_card_id": 2, "end_card_id": 1, "type": "sequential"},
            ],
        )

        loop_info = executor._detect_infinite_loop_logic(1)

        self.assertIsNotNone(loop_info)
        self.assertEqual(loop_info["cards"], [1, 2])

    def test_allows_cycle_with_possible_exit(self):
        executor = self._executor(
            {
                1: {"id": 1, "task_type": "线程起点", "parameters": {}},
                2: {
                    "id": 2,
                    "task_type": "模拟鼠标操作",
                    "parameters": {
                        "on_success": "跳转到步骤",
                        "success_jump_target_id": 3,
                        "on_failure": "执行下一步",
                    },
                },
                3: {"id": 3, "task_type": "延迟", "parameters": {}},
            },
            [
                {"start_card_id": 1, "end_card_id": 2, "type": "sequential"},
                {"start_card_id": 2, "end_card_id": 1, "type": "sequential"},
            ],
        )

        self.assertIsNone(executor._detect_infinite_loop_logic(1))

    def test_execute_workflow_warns_and_stops_before_closed_cycle_runs(self):
        executor = self._executor(
            {
                1: {"id": 1, "task_type": "线程起点", "parameters": {}},
                2: {"id": 2, "task_type": "模拟鼠标操作", "parameters": {}},
            },
            [
                {"start_card_id": 1, "end_card_id": 2, "type": "sequential"},
                {"start_card_id": 2, "end_card_id": 1, "type": "sequential"},
            ],
        )
        warnings = []
        executor.show_warning.connect(lambda title, message: warnings.append((title, message)))

        success, message = executor._execute_workflow()

        self.assertFalse(success)
        self.assertIn("无限循环", message)
        self.assertEqual(warnings[0][0], "检测到无限循环")

    def test_main_workflow_guard_is_off_by_default(self):
        executor = WorkflowExecutor(
            cards_data={
                1: {"id": 1, "task_type": "线程起点", "parameters": {}},
                2: {"id": 2, "task_type": "模拟鼠标操作", "parameters": {}},
            },
            connections_data=[
                {"start_card_id": 1, "end_card_id": 2, "type": "sequential"},
                {"start_card_id": 2, "end_card_id": 1, "type": "sequential"},
            ],
            task_modules={},
            start_card_id=1,
            target_hwnd=None,
        )

        self.assertFalse(executor._infinite_loop_guard_enabled)

    def test_main_workflow_execution_skips_guard_by_default(self):
        executor = WorkflowExecutor(
            cards_data={1: {"id": 1, "task_type": "dummy", "parameters": {}}},
            connections_data=[],
            task_modules={},
            start_card_id=1,
            target_hwnd=None,
        )

        with (
            mock.patch.object(
                executor,
                "_detect_infinite_loop_logic",
                side_effect=AssertionError("main workflow must not run loop guard"),
            ),
            mock.patch.object(executor, "_execute_card", return_value=(True, "STOP_WORKFLOW", "")),
        ):
            success, message = executor._execute_workflow()

        self.assertTrue(success)
        self.assertEqual(message, "工作流执行完成")


if __name__ == "__main__":
    unittest.main()
