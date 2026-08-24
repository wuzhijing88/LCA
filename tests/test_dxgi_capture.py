import threading
import time
import unittest

import numpy as np

from utils.dxgi_capture import CaptureStats, DXGICapture


class _FakeCamera:
    def __init__(self, frames):
        self._frames = list(frames)
        self.width = 1920
        self.height = 1080
        self.release_called = False

    def grab(self, region=None):
        _ = region
        if not self._frames:
            return None
        return self._frames.pop(0)

    def release(self):
        self.release_called = True


class DXGICaptureTests(unittest.TestCase):
    def _build_capture(self, camera):
        capture = DXGICapture.__new__(DXGICapture)
        capture.stats = CaptureStats()
        capture.lock = threading.Lock()
        capture._monitors = []
        capture._camera = camera
        capture._camera_output_idx = 0
        capture._camera_lock = threading.RLock()
        capture._initialized = True
        capture._last_hwnd = None
        capture._last_frame = None
        capture._last_frame_key = None
        capture._last_frame_ts = 0.0
        capture._last_none_log_ts = 0.0
        capture._reuse_frame_timeout = 0.25
        capture._none_frame_retry_count = 2
        capture._none_frame_retry_interval_sec = 0.0
        capture._last_reinit_attempt_ts = 0.0
        capture._reinit_cooldown_sec = 0.1
        return capture

    def test_capture_dxcam_reuses_recent_frame_when_grab_returns_none(self):
        cached_frame = np.zeros((20, 20, 3), dtype=np.uint8)
        capture = self._build_capture(_FakeCamera([None]))
        capture._last_frame = cached_frame
        capture._last_frame_key = ("hwnd", 1, 0, 0, 0, 100, 100)
        capture._last_frame_ts = time.time() - 0.1

        result = capture._capture_dxcam(
            monitor_index=0,
            region=(0, 0, 100, 100),
            start_time=time.time(),
            frame_key=("hwnd", 1, 0, 0, 0, 100, 100),
        )

        self.assertIs(result, cached_frame)
        self.assertEqual(1, capture.stats.success_captures)
        self.assertEqual(0, capture.stats.failed_captures)

    def test_capture_dxcam_retries_none_before_reporting_failure(self):
        fresh_frame = np.ones((10, 10, 3), dtype=np.uint8)
        capture = self._build_capture(_FakeCamera([None, fresh_frame]))

        result = capture._capture_dxcam(
            monitor_index=0,
            region=(0, 0, 50, 50),
            start_time=time.time(),
            frame_key=("hwnd", 2, 0, 0, 0, 50, 50),
        )

        self.assertIs(result, fresh_frame)
        self.assertEqual(1, capture.stats.success_captures)
        self.assertEqual(0, capture.stats.failed_captures)


if __name__ == "__main__":
    unittest.main()
