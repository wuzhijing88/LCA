import unittest
from unittest.mock import patch

from tasks import yolo_detection


class _WidgetStub:
    def __init__(self, hwnd):
        self._hwnd = hwnd

    def winId(self):
        return self._hwnd


class _AppStub:
    def __init__(self, widgets):
        self._widgets = widgets

    def topLevelWidgets(self):
        return list(self._widgets)


class _SignalStub:
    def __init__(self):
        self.payloads = []

    def emit(self, payload):
        self.payloads.append(payload)


class _ExecutorStub:
    def __init__(self):
        self.overlay_update_requested = _SignalStub()


class _DetectionStub:
    def __init__(self, x1=1, y1=2, x2=11, y2=12, class_name="target", confidence=0.8):
        self.x1 = x1
        self.y1 = y1
        self.x2 = x2
        self.y2 = y2
        self.class_name = class_name
        self.confidence = confidence


class _OverlayThreadStub:
    def __init__(self, alive=True):
        self._alive = alive
        self.join_calls = []

    def is_alive(self):
        return self._alive

    def join(self, timeout=None):
        self.join_calls.append(timeout)


class _OverlayInstanceStub:
    def __init__(self):
        self.hide_calls = 0

    def hide(self):
        self.hide_calls += 1


class YoloOverlayRoutingTests(unittest.TestCase):
    def test_qt_overlay_only_used_for_internal_window(self):
        app = _AppStub([_WidgetStub(123), _WidgetStub(456)])

        with patch("PySide6.QtWidgets.QApplication.instance", return_value=app):
            self.assertTrue(yolo_detection._should_use_qt_overlay(123))
            self.assertFalse(yolo_detection._should_use_qt_overlay(999))

    def test_draw_requests_are_raised_to_executor_when_available(self):
        executor = _ExecutorStub()
        detections = [
            {"x1": 10, "y1": 20, "x2": 30, "y2": 40, "class_name": "target", "confidence": 0.95}
        ]

        with patch.object(yolo_detection, "_schedule_native_overlay") as native_overlay:
            yolo_detection.draw_detections_on_window(
                123,
                detections,
                (720, 1280, 3),
                executor=executor,
            )

        native_overlay.assert_not_called()
        self.assertEqual(len(executor.overlay_update_requested.payloads), 1)
        payload = executor.overlay_update_requested.payloads[0]
        self.assertEqual(payload["action"], "update")
        self.assertEqual(payload["hwnd"], 123)
        self.assertEqual(payload["frame_shape"], [720, 1280, 3])
        self.assertEqual(payload["detections"][0]["class_name"], "target")

    def test_hide_overlay_keeps_live_render_thread_for_next_start(self):
        original_thread = yolo_detection._overlay_thread
        original_instance = yolo_detection._overlay_instance
        original_active = yolo_detection._overlay_active
        original_shutdown_requested = yolo_detection._overlay_shutdown_requested
        original_tracking_thread = yolo_detection._tracking_thread
        original_tracking_active = yolo_detection._tracking_active
        original_tracking_state = yolo_detection._tracking_state

        try:
            thread_stub = _OverlayThreadStub(alive=True)
            instance_stub = _OverlayInstanceStub()
            yolo_detection._overlay_thread = thread_stub
            yolo_detection._overlay_instance = instance_stub
            yolo_detection._overlay_active = True
            yolo_detection._overlay_shutdown_requested = False
            yolo_detection._tracking_thread = None
            yolo_detection._tracking_active = False
            yolo_detection._tracking_state = None

            yolo_detection.hide_detections_overlay()

            self.assertIs(yolo_detection._overlay_thread, thread_stub)
            self.assertFalse(yolo_detection._overlay_active)
            self.assertEqual(thread_stub.join_calls, [])
            self.assertGreaterEqual(instance_stub.hide_calls, 1)
        finally:
            yolo_detection._overlay_thread = original_thread
            yolo_detection._overlay_instance = original_instance
            yolo_detection._overlay_active = original_active
            yolo_detection._overlay_shutdown_requested = original_shutdown_requested
            yolo_detection._tracking_thread = original_tracking_thread
            yolo_detection._tracking_active = original_tracking_active
            yolo_detection._tracking_state = original_tracking_state

    def test_schedule_overlay_reuses_existing_live_thread_after_hide(self):
        original_thread = yolo_detection._overlay_thread
        original_active = yolo_detection._overlay_active
        original_shutdown_requested = yolo_detection._overlay_shutdown_requested
        original_hwnd = yolo_detection._overlay_hwnd
        original_detections = yolo_detection._overlay_detections
        original_frame_shape = yolo_detection._overlay_frame_shape
        original_dirty = yolo_detection._overlay_dirty

        try:
            thread_stub = _OverlayThreadStub(alive=True)
            yolo_detection._overlay_thread = thread_stub
            yolo_detection._overlay_active = False
            yolo_detection._overlay_shutdown_requested = False

            with patch.object(yolo_detection.threading, "Thread") as thread_ctor:
                yolo_detection._schedule_native_overlay(
                    456,
                    [{"x1": 1, "y1": 2, "x2": 11, "y2": 12, "class_name": "target", "confidence": 0.8}],
                    (720, 1280, 3),
                )

            thread_ctor.assert_not_called()
            self.assertIs(yolo_detection._overlay_thread, thread_stub)
            self.assertTrue(yolo_detection._overlay_active)
            self.assertEqual(yolo_detection._overlay_hwnd, 456)
        finally:
            yolo_detection._overlay_thread = original_thread
            yolo_detection._overlay_active = original_active
            yolo_detection._overlay_shutdown_requested = original_shutdown_requested
            yolo_detection._overlay_hwnd = original_hwnd
            yolo_detection._overlay_detections = original_detections
            yolo_detection._overlay_frame_shape = original_frame_shape
            yolo_detection._overlay_dirty = original_dirty

    def test_tracking_state_keeps_executor_for_realtime_overlay_updates(self):
        original_thread = yolo_detection._tracking_thread
        original_active = yolo_detection._tracking_active
        original_state = yolo_detection._tracking_state

        try:
            executor = _ExecutorStub()
            screenshot = yolo_detection.np.zeros((20, 20, 3), dtype=yolo_detection.np.uint8)
            yolo_detection._tracking_thread = None
            yolo_detection._tracking_active = False
            yolo_detection._tracking_state = None

            with patch.object(yolo_detection.threading, "Thread") as thread_ctor:
                thread_ref = thread_ctor.return_value
                yolo_detection._update_tracking_state(
                    789,
                    [_DetectionStub()],
                    (20, 20, 3),
                    screenshot,
                    tracking_engine="gdi",
                    executor=executor,
                )

            self.assertIs(yolo_detection._tracking_state["executor"], executor)
            self.assertEqual(yolo_detection._tracking_state["tracking_engine"], "gdi")
            thread_ref.start.assert_called_once()
        finally:
            yolo_detection._tracking_thread = original_thread
            yolo_detection._tracking_active = original_active
            yolo_detection._tracking_state = original_state

    def test_tracking_loop_routes_overlay_updates_through_executor(self):
        original_active = yolo_detection._tracking_active
        original_state = yolo_detection._tracking_state

        try:
            executor = _ExecutorStub()
            old_ts = yolo_detection.time.perf_counter() - yolo_detection._tracking_missing_timeout - 1.0
            yolo_detection._tracking_active = True
            yolo_detection._tracking_state = {
                "hwnd": 321,
                "frame_shape": (20, 20, 3),
                "boxes": [{"x1": 1, "y1": 2, "x2": 11, "y2": 12, "class_name": "target", "confidence": 0.8}],
                "last_update": old_ts,
                "last_model_update": old_ts,
                "last_model_seen": old_ts,
                "executor": executor,
            }

            with patch.object(yolo_detection, "_dispatch_overlay_update") as dispatch_overlay:
                with patch.object(yolo_detection, "precise_sleep", side_effect=lambda _interval: setattr(yolo_detection, "_tracking_active", False)):
                    yolo_detection._tracking_loop()

            dispatch_overlay.assert_called_once_with(321, [], (20, 20, 3), executor=executor)
        finally:
            yolo_detection._tracking_active = original_active
            yolo_detection._tracking_state = original_state


if __name__ == "__main__":
    unittest.main()
