import unittest

from utils.unified_dpi_handler import serialize_window_dpi_info


class _StubDpiHandler:
    def __init__(self, dpi_info=None, exc=None):
        self._dpi_info = dpi_info or {}
        self._exc = exc

    def get_window_dpi_info(self, hwnd, check_changes=False):
        if self._exc is not None:
            raise self._exc
        return dict(self._dpi_info)


class UnifiedDpiHandlerTests(unittest.TestCase):
    def test_serialize_window_dpi_info_uses_single_payload_shape(self):
        payload = serialize_window_dpi_info(
            123,
            dpi_handler=_StubDpiHandler(
                {"dpi": 144, "scale_factor": 1.5, "method": "GetDpiForWindow"}
            ),
            recorded_at=42.0,
        )

        self.assertEqual(
            payload,
            {
                "dpi": 144,
                "scale_factor": 1.5,
                "method": "GetDpiForWindow",
                "recorded_at": 42.0,
            },
        )

    def test_serialize_window_dpi_info_falls_back_to_default_payload(self):
        payload = serialize_window_dpi_info(
            456,
            dpi_handler=_StubDpiHandler(exc=RuntimeError("boom")),
            recorded_at=7.0,
        )

        self.assertEqual(payload["dpi"], 96)
        self.assertEqual(payload["scale_factor"], 1.0)
        self.assertEqual(payload["method"], "Default")
        self.assertEqual(payload["recorded_at"], 7.0)


if __name__ == "__main__":
    unittest.main()
