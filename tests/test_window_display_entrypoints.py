import importlib.util
import sys
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


_positioning_module = _load_module(
    'tests._main_window_parameter_panel_positioning_mixin',
    'ui/main_window_parts/main_window_parameter_panel_positioning_mixin.py',
)
_floating_module = _load_module(
    'tests._floating_status_window',
    'ui/widgets/floating_status_window.py',
)
_recording_module = _load_module(
    'tests._recording_control_panel',
    'ui/recording_parts/recording_control_panel.py',
)

MainWindowParameterPanelPositioningMixin = _positioning_module.MainWindowParameterPanelPositioningMixin
FloatingWindowController = _floating_module.FloatingWindowController
RecordingControlPanel = _recording_module.RecordingControlPanel


class _DummyParameterPanel:
    def __init__(self):
        self._is_dragging = False

    def isVisible(self):
        return True

    def isActiveWindow(self):
        return False

    def _position_panel(self):
        pass


class _DummyMainWindow(MainWindowParameterPanelPositioningMixin):
    def __init__(self):
        self.config = {'enable_parameter_panel_snap': True}
        self.parameter_panel = _DummyParameterPanel()

    def isActiveWindow(self):
        return True


class _DummyFloatingMain:
    def __init__(self):
        self._state = _floating_module.Qt.WindowState.WindowMinimized

    def windowState(self):
        return self._state

    def setWindowState(self, state):
        self._state = state


class _DummyFloating:
    def hide(self):
        pass


class _DummyFloatingController:
    def __init__(self):
        self._main = _DummyFloatingMain()
        self._floating = _DummyFloating()


class _DummyRecordingPanel:
    def __init__(self):
        self.is_recording = False
        self.start_time = None
        self.step_count = 0
        self.timer = mock.Mock()

    def width(self):
        return 220

    def move(self, x, y):
        self.position = (x, y)


class WindowDisplayEntrypointsTests(unittest.TestCase):
    def test_parameter_panel_sync_reuses_shared_raise_helper(self):
        host = _DummyMainWindow()

        with mock.patch.object(
            _positioning_module.QApplication,
            'focusWidget',
            return_value=None,
        ):
            with mock.patch.object(
                _positioning_module,
                'show_and_raise_widget',
            ) as show_and_raise_widget:
                host._smart_sync_parameter_panel_activation()

        show_and_raise_widget.assert_called_once_with(
            host.parameter_panel,
            log_prefix='参数面板同步',
        )

    def test_floating_controller_restore_reuses_shared_window_launcher(self):
        controller = _DummyFloatingController()

        with mock.patch.object(
            _floating_module,
            'show_and_activate_overlay',
        ) as show_and_activate_overlay:
            FloatingWindowController._restore_main_window(controller)

        show_and_activate_overlay.assert_called_once_with(
            controller._main,
            log_prefix='主窗口恢复',
            focus=True,
        )

    def test_recording_control_panel_reuses_shared_window_launcher(self):
        panel = _DummyRecordingPanel()
        geometry = mock.Mock()
        geometry.isEmpty.return_value = False
        geometry.right.return_value = 500
        geometry.top.return_value = 100

        with mock.patch.object(
            _recording_module,
            'get_available_geometry_for_widget',
            return_value=geometry,
        ):
            with mock.patch.object(
                _recording_module.QCursor,
                'pos',
                return_value=object(),
            ):
                with mock.patch.object(
                    _recording_module,
                    'show_and_activate_overlay',
                ) as show_and_activate_overlay:
                    RecordingControlPanel.start_recording(panel)

        self.assertTrue(panel.is_recording)
        self.assertEqual(panel.step_count, 0)
        panel.timer.start.assert_called_once()
        show_and_activate_overlay.assert_called_once_with(
            panel,
            log_prefix='录制控制浮窗',
            focus=True,
        )


if __name__ == '__main__':
    unittest.main()
