import unittest
from unittest.mock import Mock, patch

from ui.workflow_parts.workflow_task import WorkflowTask


class WorkflowTaskContractTests(unittest.TestCase):
    def _task(self, *, workflow_data=None, config=None):
        return WorkflowTask(
            task_id=7,
            name="合同测试",
            filepath="F:/LCA/workflows/contract.json",
            workflow_data=workflow_data
            or {
                "cards": [
                    {"id": 1, "task_type": "线程起点", "parameters": {}},
                ],
                "connections": [],
            },
            task_modules={},
            images_dir="F:/LCA/images",
            config=config
            or {
                "execution_mode": "background",
                "screenshot_engine": "gdi",
                "bound_windows": [{"hwnd": 100, "title": "目标", "enabled": True}],
            },
        )

    def test_paused_task_requires_explicit_resume(self):
        task = self._task()
        task.status = "paused"
        task.executor = Mock()

        self.assertFalse(task.can_execute())
        self.assertIsNone(task.execute_async())
        task.executor.resume.assert_not_called()

    def test_new_start_is_rejected_while_previous_runtime_is_present(self):
        task = self._task()
        task.executor = Mock()
        task.executor_thread = Mock()

        self.assertIsNone(task.execute_async())
        task.executor.terminate.assert_not_called()

    def test_card_id_must_be_integer(self):
        task = self._task(
            workflow_data={
                "cards": [{"id": "1", "task_type": "线程起点", "parameters": {}}],
                "connections": [],
            }
        )

        with self.assertRaisesRegex(TypeError, "卡片ID必须是整数"):
            task._create_executor()

    def test_duplicate_card_id_is_rejected(self):
        task = self._task(
            workflow_data={
                "cards": [
                    {"id": 1, "task_type": "线程起点", "parameters": {}},
                    {"id": 1, "task_type": "延迟", "parameters": {}},
                ],
                "connections": [],
            }
        )

        with self.assertRaisesRegex(ValueError, "重复卡片ID"):
            task._create_executor()

    def test_connection_must_reference_existing_integer_cards(self):
        task = self._task(
            workflow_data={
                "cards": [{"id": 1, "task_type": "线程起点", "parameters": {}}],
                "connections": [
                    {"start_card_id": 1, "end_card_id": 2, "type": "sequential"}
                ],
            }
        )

        with self.assertRaisesRegex(ValueError, "引用了不存在的卡片"):
            task._create_executor()

    def test_stale_tab_window_does_not_fall_back_to_global_window(self):
        task = self._task()
        task.target_hwnd = 999
        task.target_window_title = "旧窗口"

        with self.assertRaisesRegex(ValueError, "不在当前全局窗口配置中"):
            task._create_executor()

    def test_unbound_task_uses_explicit_first_enabled_global_window(self):
        task = self._task()
        proxy = Mock()
        handle = Mock()

        with (
            patch("win32gui.IsWindow", return_value=True),
            patch(
                "ui.workflow_parts.workflow_task.create_process_workflow_runtime",
                return_value=(proxy, handle),
            ) as create_runtime,
        ):
            task._create_executor()

        self.assertIs(task.executor, proxy)
        self.assertIs(task.executor_thread, handle)
        kwargs = create_runtime.call_args.kwargs
        self.assertEqual(kwargs["cards_data"], {1: task.workflow_data["cards"][0]})
        self.assertEqual(kwargs["start_card_ids"], [1])
        self.assertEqual(kwargs["target_hwnd"], 100)
        self.assertEqual(kwargs["screenshot_engine"], "gdi")

    def test_cleanup_does_not_read_consumed_runtime_snapshot_again(self):
        task = self._task()
        executor = Mock()
        thread = Mock()
        task.executor = executor
        task.executor_thread = thread
        task.status = "completed"

        with patch.object(task, "sender", return_value=thread):
            task._cleanup_executor_thread()

        self.assertIsNone(task.executor)
        self.assertIsNone(task.executor_thread)
        thread.deleteLater.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
