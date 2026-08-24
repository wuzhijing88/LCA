import unittest
from unittest import mock

from utils.window_hider import WindowHider


class _DummyWidget:
    def __init__(self, *, visible=True, is_window=True):
        self._visible = visible
        self._is_window = is_window
        self.calls = []

    def isVisible(self):
        return self._visible

    def isWindow(self):
        return self._is_window

    def show(self):
        self.calls.append('show')
        self._visible = True

    def raise_(self):
        self.calls.append('raise')


class WindowHiderTests(unittest.TestCase):
    def test_restore_all_reuses_shared_launcher_for_top_level_windows(self):
        widget = _DummyWidget(visible=True, is_window=True)
        hider = WindowHider()
        hider.add_window(widget, '主窗口', was_visible=True)

        with mock.patch(
            'utils.window_hider.show_and_activate_overlay',
        ) as show_and_activate_overlay:
            restored = hider.restore_all()

        self.assertEqual(restored, 1)
        show_and_activate_overlay.assert_called_once_with(
            widget,
            log_prefix='主窗口恢复',
            focus=False,
        )
        self.assertEqual(widget.calls, [])

    def test_restore_all_keeps_child_widget_restore_sequence(self):
        widget = _DummyWidget(visible=True, is_window=False)
        hider = WindowHider()
        hider.add_window(widget, '参数面板', was_visible=True)

        with mock.patch(
            'utils.window_hider.show_and_raise_widget',
        ) as show_and_raise_widget:
            restored = hider.restore_all()

        self.assertEqual(restored, 1)
        show_and_raise_widget.assert_called_once_with(
            widget,
            log_prefix='参数面板恢复',
        )


if __name__ == '__main__':
    unittest.main()
