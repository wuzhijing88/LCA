import unittest
from unittest import mock

import ui.selectors.color_coordinate_picker as color_coordinate_picker_module
import ui.selectors.coordinate_selector as coordinate_selector_module
import ui.selectors.ocr_region_selector as ocr_region_selector_module
from ui.selectors.color_coordinate_picker import ColorCoordinatePickerOverlay
from ui.selectors.coordinate_selector import (
    CoordinateSelectorOverlay,
    MultiPointCoordinateSelectorOverlay,
)
from ui.selectors.ocr_region_selector import OCRRegionSelectorOverlay
from ui.selectors.window_picker import WindowPickerOverlay


class _DummyReadyOverlay:
    def __init__(self):
        self._closing = False
        self._activation_attempts = 0
        self._is_ready_for_input = False


class _DummyMouseEvent:
    def __init__(self, button):
        self._button = button
        self._pos = object()
        self.accepted = False

    def button(self):
        return self._button

    def pos(self):
        return self._pos

    def accept(self):
        self.accepted = True


class OverlayWindowActivationTests(unittest.TestCase):
    def test_coordinate_overlay_reuses_shared_overlay_activator(self):
        dummy = _DummyReadyOverlay()
        with mock.patch(
            'ui.selectors.coordinate_selector.ensure_overlay_ready_for_input',
        ) as ensure_ready:
            CoordinateSelectorOverlay._ensure_ready_for_input(dummy)

        self.assertEqual(ensure_ready.call_args.kwargs['log_prefix'], '坐标选择覆盖层')

    def test_ocr_overlay_reuses_shared_overlay_activator(self):
        dummy = _DummyReadyOverlay()
        with mock.patch(
            'ui.selectors.ocr_region_selector.ensure_overlay_ready_for_input',
        ) as ensure_ready:
            OCRRegionSelectorOverlay._ensure_ready_for_input(dummy)

        self.assertEqual(ensure_ready.call_args.kwargs['log_prefix'], 'OCR覆盖层')
        self.assertTrue(ensure_ready.call_args.kwargs['allow_closed_skip'])

    def test_color_overlay_reuses_shared_overlay_activator(self):
        dummy = _DummyReadyOverlay()
        with mock.patch(
            'ui.selectors.color_coordinate_picker.ensure_overlay_ready_for_input',
        ) as ensure_ready:
            ColorCoordinatePickerOverlay._ensure_ready_for_input(dummy)

        self.assertEqual(ensure_ready.call_args.kwargs['log_prefix'], '颜色取点覆盖层')
        self.assertTrue(ensure_ready.call_args.kwargs['auto_show'])

    def test_window_picker_overlay_reuses_shared_overlay_activator(self):
        dummy = _DummyReadyOverlay()
        with mock.patch(
            'ui.selectors.window_picker.ensure_overlay_ready_for_input',
        ) as ensure_ready:
            WindowPickerOverlay._ensure_ready_for_input(dummy)

        self.assertEqual(ensure_ready.call_args.kwargs['log_prefix'], '窗口选择覆盖层')

    def test_coordinate_overlay_mouse_press_reuses_shared_widget_activator(self):
        class _DummyCoordinateOverlay:
            def __init__(self):
                self._is_ready_for_input = False

            def isActiveWindow(self):
                return False

            def _is_point_in_target_window(self, pos):
                _ = pos
                return False

        dummy = _DummyCoordinateOverlay()
        event = _DummyMouseEvent(coordinate_selector_module.Qt.MouseButton.LeftButton)

        with mock.patch.object(
            coordinate_selector_module,
            'activate_overlay_widget',
        ) as activate_overlay_widget:
            CoordinateSelectorOverlay.mousePressEvent(dummy, event)

        activate_overlay_widget.assert_called_once_with(
            dummy,
            log_prefix='坐标选择覆盖层',
            focus=True,
        )
        self.assertTrue(dummy._is_ready_for_input)

    def test_multi_point_overlay_mouse_press_reuses_shared_widget_activator(self):
        class _DummyMultiPointOverlay:
            def __init__(self):
                self._is_ready_for_input = False
                self.appended_pos = None

            def isActiveWindow(self):
                return False

            def _append_route_point(self, pos):
                self.appended_pos = pos

        dummy = _DummyMultiPointOverlay()
        event = _DummyMouseEvent(coordinate_selector_module.Qt.MouseButton.LeftButton)

        with mock.patch.object(
            coordinate_selector_module,
            'activate_overlay_widget',
        ) as activate_overlay_widget:
            MultiPointCoordinateSelectorOverlay.mousePressEvent(dummy, event)

        activate_overlay_widget.assert_called_once_with(
            dummy,
            log_prefix='多点坐标覆盖层',
            focus=True,
        )
        self.assertTrue(dummy._is_ready_for_input)
        self.assertIs(dummy.appended_pos, event.pos())

    def test_ocr_overlay_mouse_press_reuses_shared_widget_activator_when_inactive(self):
        class _DummyOcrOverlay:
            def isActiveWindow(self):
                return False

        dummy = _DummyOcrOverlay()
        event = _DummyMouseEvent(ocr_region_selector_module.Qt.MouseButton.LeftButton)

        with mock.patch.object(
            ocr_region_selector_module,
            'activate_overlay_widget',
        ) as activate_overlay_widget:
            OCRRegionSelectorOverlay.mousePressEvent(dummy, event)

        activate_overlay_widget.assert_called_once_with(
            dummy,
            log_prefix='OCR覆盖层',
            focus=True,
        )
        self.assertTrue(event.accepted)

    def test_ocr_overlay_mouse_press_reuses_shared_widget_activator_when_not_ready(self):
        class _DummyOcrOverlay:
            _is_ready_for_input = False

            def isActiveWindow(self):
                return True

        dummy = _DummyOcrOverlay()
        event = _DummyMouseEvent(ocr_region_selector_module.Qt.MouseButton.LeftButton)

        with mock.patch.object(
            ocr_region_selector_module,
            'activate_overlay_widget',
        ) as activate_overlay_widget:
            OCRRegionSelectorOverlay.mousePressEvent(dummy, event)

        activate_overlay_widget.assert_called_once_with(
            dummy,
            log_prefix='OCR覆盖层',
            focus=True,
        )
        self.assertTrue(event.accepted)

    def test_color_overlay_mouse_press_reuses_shared_widget_activator(self):
        class _DummyColorOverlay:
            def __init__(self):
                self._is_ready_for_input = False

            def isActiveWindow(self):
                return False

            def _is_point_in_target_window(self, pos):
                _ = pos
                return False

        dummy = _DummyColorOverlay()
        event = _DummyMouseEvent(color_coordinate_picker_module.Qt.MouseButton.LeftButton)

        with mock.patch.object(
            color_coordinate_picker_module,
            'activate_overlay_widget',
        ) as activate_overlay_widget:
            ColorCoordinatePickerOverlay.mousePressEvent(dummy, event)

        activate_overlay_widget.assert_called_once_with(
            dummy,
            log_prefix='颜色取点覆盖层',
            focus=True,
        )
        self.assertTrue(dummy._is_ready_for_input)
        self.assertTrue(event.accepted)


if __name__ == '__main__':
    unittest.main()
