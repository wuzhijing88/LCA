import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt

from task_workflow.multi_thread_session import WorkflowMultiThreadSession
from utils.thread_start_utils import THREAD_START_TASK_TYPE


class _FinishedExecutor:
    workflow_id = "thread-workflow"
    thread_session = object()
    thread_id = 1
    thread_label = "线程起点1"

    def deleteLater(self):
        return None


class MultiThreadSessionStatusTests(unittest.TestCase):
    def test_child_failure_detail_is_not_sent_to_bottom_step_details(self):
        session = WorkflowMultiThreadSession(
            cards_data={
                1: {
                    "id": 1,
                    "task_type": THREAD_START_TASK_TYPE,
                    "parameters": {},
                },
                2: {
                    "id": 2,
                    "task_type": THREAD_START_TASK_TYPE,
                    "parameters": {},
                },
            },
            connections_data=[],
            task_modules={},
            start_card_ids=[1, 2],
            workflow_id="workflow",
        )
        entry = session._entries[1]
        entry["executor"] = _FinishedExecutor()
        entry["launch_token"] = 3
        received_details = []
        session.step_details.connect(
            received_details.append,
            Qt.ConnectionType.DirectConnection,
        )

        with patch.object(session, "_clear_executor_workflow_context"):
            with self.assertLogs("task_workflow.multi_thread_session", level="ERROR"):
                session._on_child_execution_finished(
                    thread_id=1,
                    launch_token=3,
                    success=False,
                    message="完整失败详情",
                )

        self.assertEqual(received_details, [])
        self.assertEqual(entry["status"], "failed")
        self.assertEqual(entry["last_message"], "完整失败详情")


if __name__ == "__main__":
    unittest.main()
