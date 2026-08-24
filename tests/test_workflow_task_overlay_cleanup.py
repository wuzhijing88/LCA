import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt

from ui.workflow_parts.workflow_task import WorkflowTask


class _SignalRecorder:
    def __init__(self):
        self.calls = []

    def connect(self, callback, connection_type=None):
        self.calls.append((callback, connection_type))


class _ExecutorStub:
    def __init__(self):
        self.overlay_update_requested = _SignalRecorder()


class WorkflowTaskOverlayCleanupTests(unittest.TestCase):
    def _create_task(self) -> WorkflowTask:
        return WorkflowTask(
            task_id=1,
            name="测试任务",
            filepath="",
            workflow_data={},
            task_modules={},
            images_dir="",
            config={"execution_mode": "foreground"},
        )

    def test_overlay_signal_uses_auto_connection(self):
        task = self._create_task()
        task.executor = _ExecutorStub()

        task._connect_overlay_update_signal()

        self.assertEqual(len(task.executor.overlay_update_requested.calls), 1)
        callback, connection_type = task.executor.overlay_update_requested.calls[0]
        self.assertEqual(callback, task._on_overlay_update_requested)
        self.assertEqual(connection_type, Qt.ConnectionType.AutoConnection)

    def test_overlay_hide_is_deferred_to_avoid_racing_update(self):
        task = self._create_task()
        scheduled = []

        with patch("ui.workflow_parts.workflow_task.QTimer.singleShot", side_effect=lambda ms, cb: scheduled.append((ms, cb))):
            with patch("tasks.yolo_detection.hide_detections_overlay") as hide_overlay:
                task._hide_detection_overlay_in_main_process()

                self.assertEqual(hide_overlay.call_count, 0)
                self.assertEqual(len(scheduled), 1)
                self.assertEqual(scheduled[0][0], 180)

                scheduled[0][1]()
                self.assertEqual(hide_overlay.call_count, 1)

    def test_overlay_update_cancels_pending_hide(self):
        task = self._create_task()
        scheduled = []

        with patch("ui.workflow_parts.workflow_task.QTimer.singleShot", side_effect=lambda ms, cb: scheduled.append((ms, cb))):
            task._hide_detection_overlay_in_main_process()

            with patch("tasks.yolo_detection.draw_detections_on_window") as draw_overlay:
                with patch("tasks.yolo_detection.hide_detections_overlay") as hide_overlay:
                    task._on_overlay_update_requested(
                        {
                            "action": "update",
                            "hwnd": 123,
                            "detections": [{"x1": 1, "y1": 2, "x2": 3, "y2": 4, "class_name": "target", "confidence": 0.9}],
                            "frame_shape": [720, 1280, 3],
                        }
                    )

                    draw_overlay.assert_called_once()
                    scheduled[0][1]()
                    self.assertEqual(hide_overlay.call_count, 0)


if __name__ == "__main__":
    unittest.main()
