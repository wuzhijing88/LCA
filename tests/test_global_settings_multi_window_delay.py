import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock


_MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "ui/global_settings_parts/global_settings_dialog_save_mixin.py"
)
_SPEC = importlib.util.spec_from_file_location(
    "tests._global_settings_dialog_save_mixin",
    _MODULE_PATH,
)
_SAVE_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _SAVE_MODULE
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_SAVE_MODULE)

GlobalSettingsDialogSaveMixin = _SAVE_MODULE.GlobalSettingsDialogSaveMixin


class _ValueWidget:
    def __init__(self, value):
        self._value = value

    def value(self):
        return self._value


class _ComboWidget:
    def __init__(self, data=None, text=""):
        self._data = data
        self._text = text

    def currentData(self):
        return self._data

    def currentText(self):
        return self._text

    def currentIndex(self):
        return -1


class _SettingsDialogStub(GlobalSettingsDialogSaveMixin):
    MODE_INTERNAL_MAP = {"前台一模式": "foreground_driver"}

    def __init__(self, config):
        self.current_config = config
        self.bound_windows = []
        self.mode_combo = _ComboWidget("foreground_driver", "前台一模式")
        self.width_spinbox = _ValueWidget(0)
        self.height_spinbox = _ValueWidget(0)
        self.screenshot_engine_combo = _ComboWidget(text="WGC")
        self.screenshot_engine_map = {"WGC": "wgc"}
        self.start_task_hotkey = _ComboWidget(text="XButton1")
        self.stop_task_hotkey = _ComboWidget(text="XButton2")
        self.pause_workflow_hotkey = _ComboWidget(text="F11")
        self.record_hotkey = _ComboWidget(text="F12")
        self.replay_hotkey = _ComboWidget(text="F10")


class GlobalSettingsMultiWindowDelayTests(unittest.TestCase):
    def test_get_settings_preserves_configured_delay_without_dialog_attribute(self):
        dialog = _SettingsDialogStub({"multi_window_delay": 750})

        with mock.patch.object(_SAVE_MODULE, "sync_runtime_window_binding_state"):
            settings = dialog.get_settings()

        self.assertEqual(settings["multi_window_delay"], 750)
        self.assertFalse(hasattr(dialog, "multi_window_delay"))

    def test_invalid_delay_falls_back_to_default(self):
        for value in (None, True, "invalid", -1):
            with self.subTest(value=value):
                dialog = _SettingsDialogStub({"multi_window_delay": value})
                self.assertEqual(dialog.get_multi_window_delay(), 500)


if __name__ == "__main__":
    unittest.main()
