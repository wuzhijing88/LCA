import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest import mock


def _load_module(module_name: str, relative_path: str):
    module_path = Path(__file__).resolve().parents[1] / relative_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


_dialog_module = _load_module(
    'tests._main_window_dialog_mixin',
    'ui/main_window_parts/main_window_dialog_mixin.py',
)
MainWindowDialogMixin = _dialog_module.MainWindowDialogMixin


class _DummyControlCenter:
    def __init__(self, *args, **kwargs):
        _ = (args, kwargs)
        self.destroyed = mock.Mock()


class _DummyWindow(MainWindowDialogMixin):
    def __init__(self):
        self.bound_windows = []
        self.task_modules = []
        self.control_center = None
        self.hotkeys_disabled = False

    def _disable_main_window_hotkeys(self):
        self.hotkeys_disabled = True

    def _on_control_center_closed(self, *args, **kwargs):
        _ = (args, kwargs)


class MainWindowDialogEntrypointsTests(unittest.TestCase):
    def test_open_control_center_reuses_shared_window_launcher(self):
        host = _DummyWindow()
        fake_control_center_module = types.SimpleNamespace(ControlCenterWindow=_DummyControlCenter)
        fake_win32gui = types.SimpleNamespace(
            IsWindow=lambda hwnd: True,
            GetClassName=lambda hwnd: 'DummyClass',
        )

        with mock.patch.dict(
            sys.modules,
            {
                'ui.control_center_parts.control_center': fake_control_center_module,
                'win32gui': fake_win32gui,
            },
        ):
            with mock.patch.object(
                _dialog_module,
                'center_window_on_widget_screen',
            ) as center_window_on_widget_screen:
                with mock.patch.object(
                    _dialog_module,
                    'show_and_activate_overlay',
                ) as show_and_activate_overlay:
                    host.open_control_center()

        self.assertIsNotNone(host.control_center)
        self.assertTrue(host.hotkeys_disabled)
        center_window_on_widget_screen.assert_called_once_with(host.control_center, host)
        show_and_activate_overlay.assert_called_once_with(
            host.control_center,
            log_prefix='中控窗口',
            focus=True,
        )


if __name__ == '__main__':
    unittest.main()
