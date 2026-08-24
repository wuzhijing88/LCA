import unittest

from ui.workflow_parts.workflow_task_manager import WorkflowTaskManager


class _TaskStub:
    def __init__(self, name: str, execution_mode: str, task_types):
        self.name = name
        self.execution_mode = execution_mode
        self.workflow_data = {
            "cards": [{"task_type": task_type} for task_type in task_types]
        }


class WorkflowTaskManagerYoloPrecheckTests(unittest.TestCase):
    def test_rejects_yolo_task_with_background_mode(self):
        manager = WorkflowTaskManager({}, "", {"execution_mode": "background_sendmessage", "screenshot_engine": "dxgi"})
        task = _TaskStub("测试YOLO", "background_sendmessage", ["YOLO目标检测"])

        ok, message = manager._validate_yolo_runtime_for_tasks([task])

        self.assertFalse(ok)
        self.assertIn("前台模式", message)
        self.assertIn("YOLO", message)

    def test_rejects_yolo_task_with_wgc_engine(self):
        manager = WorkflowTaskManager({}, "", {"execution_mode": "foreground", "screenshot_engine": "wgc"})
        task = _TaskStub("测试YOLO", "foreground", ["YOLO目标检测"])

        ok, message = manager._validate_yolo_runtime_for_tasks([task])

        self.assertFalse(ok)
        self.assertIn("WGC", message)
        self.assertIn("DXGI/GDI", message)

    def test_allows_yolo_task_with_foreground_dxgi(self):
        manager = WorkflowTaskManager({}, "", {"execution_mode": "foreground", "screenshot_engine": "dxgi"})
        task = _TaskStub("测试YOLO", "foreground", ["YOLO目标检测"])

        ok, message = manager._validate_yolo_runtime_for_tasks([task])

        self.assertTrue(ok)
        self.assertEqual(message, "")

if __name__ == "__main__":
    unittest.main()
