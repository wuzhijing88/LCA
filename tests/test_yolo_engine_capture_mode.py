import unittest
from unittest import mock

from utils.yolo_engine import YOLOONNXEngine


class YoloEngineCaptureModeTests(unittest.TestCase):
    def test_non_foreground_mode_is_rejected(self):
        engine = YOLOONNXEngine.__new__(YOLOONNXEngine)

        with mock.patch("utils.yolo_engine.is_foreground_mode", return_value=False):
            result = engine._capture_window(123, "background")

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
