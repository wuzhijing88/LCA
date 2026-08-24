import unittest
from unittest.mock import patch

from utils.input_simulation.mode_utils import (
    get_foreground_driver_backends,
    normalize_ib_driver_name,
    parse_foreground_backends,
    requires_interception_driver,
)


class InputModeUtilsTests(unittest.TestCase):
    def test_parse_split_keys(self):
        mouse, keyboard = parse_foreground_backends(
            {
                "foreground_mouse_driver_backend": "ibinputsimulator",
                "foreground_keyboard_driver_backend": "interception",
            }
        )
        self.assertEqual(mouse, "ibinputsimulator")
        self.assertEqual(keyboard, "interception")

    def test_parse_ignores_legacy_unified_key(self):
        mouse, keyboard = parse_foreground_backends(
            {
                "foreground_driver_backend": "ibinputsimulator",
            }
        )
        self.assertEqual((mouse, keyboard), ("interception", "interception"))

    def test_invalid_backend_raises(self):
        with self.assertRaises(ValueError):
            parse_foreground_backends({"foreground_mouse_driver_backend": "pyautogui"})

    def test_foreground_py_uses_pyautogui(self):
        self.assertEqual(
            get_foreground_driver_backends("foreground_py"),
            ("pyautogui", "pyautogui"),
        )

    def test_requires_interception_false_for_background(self):
        self.assertFalse(
            requires_interception_driver(
                "background_sendmessage",
                "interception",
                "interception",
            )
        )

    def test_requires_interception_true_for_foreground_driver(self):
        self.assertTrue(
            requires_interception_driver(
                "foreground_driver",
                "interception",
                "ibinputsimulator",
            )
        )

    def test_unknown_ib_driver_raises(self):
        with self.assertRaises(ValueError):
            normalize_ib_driver_name("UnknownBrand")

    def test_get_foreground_driver_backends_reads_split_keys(self):
        config = {
            "foreground_mouse_driver_backend": "ibinputsimulator",
            "foreground_keyboard_driver_backend": "interception",
        }
        with patch(
            "utils.input_simulation.mode_utils._read_main_config",
            return_value=config,
        ):
            self.assertEqual(
                get_foreground_driver_backends("foreground_driver"),
                ("ibinputsimulator", "interception"),
            )


if __name__ == "__main__":
    unittest.main()
