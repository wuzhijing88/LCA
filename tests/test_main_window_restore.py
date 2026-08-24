import unittest
from unittest import mock

from PySide6.QtCore import Qt

from ui.main_window_parts.main_window_close_mixin import MainWindowCloseMixin


class _RestoreWindowStub(MainWindowCloseMixin):
    def __init__(self, state, visible=True):
        self._state = state
        self._visible = visible
        self.calls = []

    def windowState(self):
        return self._state

    def setWindowState(self, state):
        self._state = state
        self.calls.append(("setWindowState", state))

    def isVisible(self):
        return self._visible

    def show(self):
        self._visible = True
        self.calls.append("show")

    def raise_(self):
        self.calls.append("raise")

    def activateWindow(self):
        self.calls.append("activate")


class MainWindowRestoreTests(unittest.TestCase):
    def test_restore_main_window_clears_minimized_flag_and_uses_shared_launcher(self):
        window = _RestoreWindowStub(
            Qt.WindowState.WindowMinimized | Qt.WindowState.WindowMaximized,
            visible=False,
        )

        with mock.patch(
            'ui.main_window_parts.main_window_close_mixin.show_and_activate_overlay',
        ) as show_and_activate_overlay:
            window.restore_main_window()

        self.assertEqual(window.windowState(), Qt.WindowState.WindowMaximized)
        self.assertEqual(
            window.calls,
            [
                ("setWindowState", Qt.WindowState.WindowMaximized),
            ],
        )
        show_and_activate_overlay.assert_called_once_with(
            window,
            log_prefix='主窗口恢复',
            focus=True,
        )

    def test_restore_main_window_keeps_non_minimized_state_single_path(self):
        window = _RestoreWindowStub(Qt.WindowState.WindowMaximized)

        with mock.patch(
            'ui.main_window_parts.main_window_close_mixin.show_and_activate_overlay',
        ) as show_and_activate_overlay:
            window.restore_main_window()

        self.assertEqual(window.windowState(), Qt.WindowState.WindowMaximized)
        self.assertEqual(window.calls, [])
        show_and_activate_overlay.assert_called_once_with(
            window,
            log_prefix='主窗口恢复',
            focus=True,
        )



if __name__ == "__main__":
    unittest.main()
