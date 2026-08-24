import unittest
from unittest import mock

from ui.dialogs.parameter_dialog import ParameterDialog


class _DummyParentWindow:
    def __init__(self):
        self.current_target_window_title = '测试窗口'


class _DummyParameterDialog:
    def __init__(self, parent_window):
        self._parent_window = parent_window
        self.calls = []

    def parent(self):
        return self._parent_window

    def showNormal(self):
        self.calls.append('showNormal')


class ParameterDialogWindowHelpersTests(unittest.TestCase):
    def test_get_target_hwnd_reuses_shared_window_resolver(self):
        dialog = _DummyParameterDialog(_DummyParentWindow())

        with mock.patch(
            'ui.dialogs.parameter_dialog.resolve_unique_window_hwnd',
            return_value=456,
        ) as resolve_unique_window_hwnd:
            self.assertEqual(ParameterDialog._get_target_hwnd(dialog), 456)

        resolve_unique_window_hwnd.assert_called_once_with('测试窗口')

    def test_restore_dialog_visibility_reuses_shared_window_launcher(self):
        dialog = _DummyParameterDialog(_DummyParentWindow())

        with mock.patch(
            'ui.dialogs.parameter_dialog.show_and_activate_overlay',
        ) as show_and_activate_overlay:
            ParameterDialog._restore_dialog_visibility(dialog)

        self.assertEqual(dialog.calls, ['showNormal'])
        show_and_activate_overlay.assert_called_once_with(
            dialog,
            log_prefix='参数对话框恢复',
            focus=True,
        )


if __name__ == '__main__':
    unittest.main()
