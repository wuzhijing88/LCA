import unittest
from unittest import mock

from ui.selectors.color_coordinate_picker import ColorCoordinatePickerOverlay
from ui.selectors.coordinate_selector import (
    CoordinateSelectorOverlay,
    MultiPointCoordinateSelectorOverlay,
)
from ui.selectors.ocr_region_selector import OCRRegionSelectorOverlay


class _DummyOverlay:
    def __init__(self, target_hwnd=None):
        self.target_window_title = 'dummy'


class SelectorWindowActivationTests(unittest.TestCase):
    def test_coordinate_selector_reuses_shared_window_activator(self):
        dummy = _DummyOverlay()
        with mock.patch(
            'ui.selectors.coordinate_selector.activate_window',
            return_value=456,
        ) as activate_window:
            CoordinateSelectorOverlay._activate_target_window(dummy, 123)

        activate_window.assert_called_once_with(123, log_prefix='坐标选择')

    def test_multi_point_coordinate_selector_reuses_shared_window_activator(self):
        dummy = _DummyOverlay()
        with mock.patch(
            'ui.selectors.coordinate_selector.activate_window',
            return_value=789,
        ) as activate_window:
            MultiPointCoordinateSelectorOverlay._activate_target_window(dummy, 123)

        activate_window.assert_called_once_with(123, log_prefix='多点坐标选择')

    def test_ocr_selector_reuses_shared_window_activator(self):
        dummy = _DummyOverlay()
        with mock.patch(
            'ui.selectors.ocr_region_selector.activate_window',
            return_value=654,
        ) as activate_window:
            OCRRegionSelectorOverlay._activate_target_window(dummy, 123)

        activate_window.assert_called_once_with(123, log_prefix='OCR区域选择')

    def test_color_picker_reuses_shared_window_activator(self):
        dummy = _DummyOverlay()
        with mock.patch(
            'ui.selectors.color_coordinate_picker.activate_window',
            return_value=321,
        ) as activate_window:
            ColorCoordinatePickerOverlay._activate_target_window(dummy, 123)

        activate_window.assert_called_once_with(123, log_prefix='颜色取点')


if __name__ == '__main__':
    unittest.main()
