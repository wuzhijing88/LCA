import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock


_MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "ui/main_window_parts/main_window_global_settings_mixin.py"
)
_SPEC = importlib.util.spec_from_file_location(
    "tests._main_window_global_settings_mixin",
    _MODULE_PATH,
)
_SETTINGS_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _SETTINGS_MODULE
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_SETTINGS_MODULE)


class GlobalSettingsInputRuntimeTests(unittest.TestCase):
    def test_runtime_sync_does_not_close_foreground_driver(self):
        foreground_manager = mock.Mock()
        simulator_manager = mock.Mock()
        config = {
            "foreground_driver_backend": "interception",
            "foreground_mouse_driver_backend": "interception",
            "foreground_keyboard_driver_backend": "interception",
        }

        with mock.patch(
            "utils.foreground_input_manager.get_foreground_input_manager",
            return_value=foreground_manager,
        ), mock.patch(
            "utils.input_simulation.global_input_simulator_manager",
            simulator_manager,
        ):
            _SETTINGS_MODULE._sync_foreground_input_runtime(config)

        foreground_manager.set_forced_modes.assert_called_once_with(
            "interception",
            "interception",
        )
        foreground_manager.close.assert_not_called()
        simulator_manager.clear_cache.assert_called_once_with()

    def test_ib_driver_configuration_is_forwarded(self):
        foreground_manager = mock.Mock()
        simulator_manager = mock.Mock()
        config = {
            "foreground_mouse_driver_backend": "ibinputsimulator",
            "foreground_keyboard_driver_backend": "ibinputsimulator",
            "ibinputsimulator_driver": "Razer",
            "ibinputsimulator_driver_arg": "device-1",
            "ibinputsimulator_ahk_path": "F:/drivers/ib.ahk",
            "ibinputsimulator_ahk_dir": "F:/drivers",
        }

        with mock.patch(
            "utils.foreground_input_manager.get_foreground_input_manager",
            return_value=foreground_manager,
        ), mock.patch(
            "utils.input_simulation.global_input_simulator_manager",
            simulator_manager,
        ):
            _SETTINGS_MODULE._sync_foreground_input_runtime(config)

        foreground_manager.set_ibinputsimulator_driver.assert_called_once_with(
            "Razer",
            "device-1",
            "F:/drivers/ib.ahk",
            "F:/drivers",
        )
        foreground_manager.set_forced_modes.assert_called_once_with(
            "ibinputsimulator",
            "ibinputsimulator",
        )
        foreground_manager.close.assert_not_called()


if __name__ == "__main__":
    unittest.main()
