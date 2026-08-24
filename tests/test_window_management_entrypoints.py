import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

from utils.universal_window_manager import UniversalWindowManager


def _load_module(module_name: str, relative_path: str):
    module_path = Path(__file__).resolve().parents[1] / relative_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


_close_module = _load_module(
    'tests._main_window_close_mixin',
    'ui/main_window_parts/main_window_close_mixin.py',
)
_global_settings_module = _load_module(
    'tests._main_window_global_settings_mixin',
    'ui/main_window_parts/main_window_global_settings_mixin.py',
)

MainWindowCloseMixin = _close_module.MainWindowCloseMixin
MainWindowGlobalSettingsMixin = _global_settings_module.MainWindowGlobalSettingsMixin


class _DummyCloseWindow(MainWindowCloseMixin):
    def __init__(self, window_state):
        self._window_state = window_state
        self.state_updates = []

    def windowState(self):
        return self._window_state

    def setWindowState(self, state):
        self.state_updates.append(state)
        self._window_state = state


class _DummySettingsWindow(MainWindowGlobalSettingsMixin):
    pass


class WindowManagementEntrypointsTests(unittest.TestCase):
    def test_universal_window_manager_reuses_shared_window_finder(self):
        manager = UniversalWindowManager.__new__(UniversalWindowManager)

        with mock.patch(
            'utils.universal_window_manager.resolve_unique_window_hwnd',
            return_value=456,
        ) as resolve_unique_window_hwnd:
            self.assertEqual(manager._find_window_by_title('测试窗口'), 456)

        resolve_unique_window_hwnd.assert_called_once_with('测试窗口')

    def test_present_global_settings_dialog_uses_shared_window_launcher(self):
        host = _DummySettingsWindow()
        dialog = mock.Mock()

        with mock.patch.object(
            _global_settings_module,
            'center_window_on_widget_screen',
        ) as center_window_on_widget_screen:
            with mock.patch.object(
                _global_settings_module,
                'show_and_activate_overlay',
            ) as show_and_activate_overlay:
                host._present_global_settings_dialog(dialog)

        center_window_on_widget_screen.assert_called_once_with(dialog, host)
        show_and_activate_overlay.assert_called_once_with(
            dialog,
            log_prefix='全局设置对话框',
            focus=True,
        )

    def test_restore_main_window_uses_shared_window_launcher(self):
        window = _DummyCloseWindow(_close_module.Qt.WindowState.WindowMinimized)

        with mock.patch.object(
            _close_module,
            'show_and_activate_overlay',
        ) as show_and_activate_overlay:
            window.restore_main_window()

        self.assertEqual(
            window.state_updates,
            [_close_module.Qt.WindowState(0)],
        )
        show_and_activate_overlay.assert_called_once_with(
            window,
            log_prefix='主窗口恢复',
            focus=True,
        )


if __name__ == '__main__':
    unittest.main()
