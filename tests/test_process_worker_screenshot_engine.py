import unittest

from task_workflow.process_payload import build_process_workflow_payload
from task_workflow.process_proxy import _resolve_payload_screenshot_engine
from task_workflow.process_worker import _resolve_worker_screenshot_engine


class ProcessWorkerScreenshotEngineTests(unittest.TestCase):
    def test_payload_carries_screenshot_engine(self):
        payload = build_process_workflow_payload(
            cards_data={1: {"id": 1, "task_type": "线程起点"}},
            connections_data=[],
            execution_mode="foreground_driver",
            screenshot_engine="dxgi",
            images_dir=None,
            workflow_id="demo",
            start_card_ids=[1],
        )

        self.assertEqual(payload.get("screenshot_engine"), "dxgi")

    def test_worker_prefers_payload_screenshot_engine(self):
        resolved = _resolve_worker_screenshot_engine({"screenshot_engine": "gdi"})

        self.assertEqual(resolved, "gdi")

    def test_worker_rejects_missing_screenshot_engine(self):
        with self.assertRaisesRegex(ValueError, "缺少 screenshot_engine"):
            _resolve_worker_screenshot_engine({})

    def test_worker_rejects_invalid_screenshot_engine(self):
        with self.assertRaisesRegex(ValueError, "无效 screenshot_engine"):
            _resolve_worker_screenshot_engine({"screenshot_engine": "automatic"})

    def test_parent_rejects_missing_screenshot_engine(self):
        with self.assertRaisesRegex(ValueError, "必须显式指定"):
            _resolve_payload_screenshot_engine(screenshot_engine=None)

    def test_parent_rejects_invalid_screenshot_engine(self):
        with self.assertRaisesRegex(ValueError, "不支持"):
            _resolve_payload_screenshot_engine(screenshot_engine="automatic")


if __name__ == "__main__":
    unittest.main()
