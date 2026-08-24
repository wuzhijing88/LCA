import unittest
from unittest import mock

from ui.selectors.screenshot_tool import ScreenshotOverlay


class ScreenshotToolTests(unittest.TestCase):
    def test_activate_target_window_reuses_shared_window_activator(self):
        with mock.patch('ui.selectors.screenshot_tool.PYWIN32_AVAILABLE', True):
            with mock.patch('ui.selectors.screenshot_tool.win32gui') as win32gui:
                win32gui.IsWindow.return_value = True
                with mock.patch(
                    'ui.selectors.screenshot_tool.activate_window',
                    return_value=456,
                ) as activate_window:
                    ScreenshotOverlay._activate_target_window(object(), 123)

        activate_window.assert_called_once_with(123, log_prefix='截图')


if __name__ == '__main__':
    unittest.main()
