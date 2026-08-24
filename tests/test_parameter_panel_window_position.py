import unittest

from PySide6.QtCore import QRect

from ui.panels.window.parameter_panel_window_position_mixin import (
    _is_native_client_geometry_usable,
)


class ParameterPanelWindowPositionTests(unittest.TestCase):
    def test_rejects_scaled_physical_geometry(self):
        fallback = QRect(100, 100, 1000, 700)
        candidate = QRect(150, 150, 1500, 1050)

        self.assertFalse(_is_native_client_geometry_usable(candidate, fallback))

    def test_accepts_matching_qt_geometry(self):
        fallback = QRect(100, 100, 1000, 700)
        candidate = QRect(102, 103, 996, 694)

        self.assertTrue(_is_native_client_geometry_usable(candidate, fallback))


if __name__ == "__main__":
    unittest.main()
