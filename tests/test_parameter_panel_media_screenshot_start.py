import unittest

from ui.panels.media.parameter_panel_media_screenshot_start_mixin import (
    ParameterPanelMediaScreenshotStartMixin,
)


class _DummyMainWindow:
    def __init__(self, is_bound=False, validated_hwnd=None):
        self._is_bound = is_bound
        self._validated_hwnd = validated_hwnd
        self.hide_called = False

    def is_hwnd_bound(self, hwnd):
        return self._is_bound

    def validate_hwnd_or_get_first(self, hwnd):
        return self._validated_hwnd, None

    def hide(self):
        self.hide_called = True


class _DummyPanel(ParameterPanelMediaScreenshotStartMixin):
    def __init__(self, target_window_hwnd=None, main_window=None):
        self.target_window_hwnd = target_window_hwnd
        self.main_window = main_window
        self.hide_called = False
        self.warn_called = False
        self.scheduled = []

    def hide(self):
        self.hide_called = True

    def _warn_no_available_screenshot_window(self):
        self.warn_called = True

    def _schedule_screenshot_overlay_start(self, line_edit, hwnd):
        self.scheduled.append((line_edit, hwnd))


class ParameterPanelMediaScreenshotStartTests(unittest.TestCase):
    def test_blocks_screenshot_when_no_bound_window(self):
        main_window = _DummyMainWindow()
        panel = _DummyPanel(target_window_hwnd=None, main_window=main_window)

        panel._start_screenshot_for_param(object())

        self.assertTrue(panel.warn_called)
        self.assertFalse(panel.hide_called)
        self.assertFalse(main_window.hide_called)
        self.assertEqual(panel.scheduled, [])

    def test_blocks_screenshot_when_bound_window_becomes_invalid(self):
        main_window = _DummyMainWindow(is_bound=False, validated_hwnd=None)
        panel = _DummyPanel(target_window_hwnd=123, main_window=main_window)

        panel._start_screenshot_for_param(object())

        self.assertTrue(panel.warn_called)
        self.assertFalse(panel.hide_called)
        self.assertFalse(main_window.hide_called)
        self.assertEqual(panel.scheduled, [])

    def test_starts_screenshot_with_validated_window(self):
        main_window = _DummyMainWindow(is_bound=False, validated_hwnd=456)
        panel = _DummyPanel(target_window_hwnd=123, main_window=main_window)
        line_edit = object()

        panel._start_screenshot_for_param(line_edit)

        self.assertFalse(panel.warn_called)
        self.assertTrue(panel.hide_called)
        self.assertTrue(main_window.hide_called)
        self.assertEqual(panel.scheduled, [(line_edit, 456)])


if __name__ == "__main__":
    unittest.main()
