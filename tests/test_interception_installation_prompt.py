import unittest
from enum import IntEnum, IntFlag
from unittest.mock import Mock, patch

from utils.interception_installation_prompt import (
    INTERCEPTION_DEVICE_RISK_TEXT,
    is_interception_required_by_config,
    request_interception_installation,
)


class _FakeMessageBox:
    class Icon(IntEnum):
        Warning = 1
        Information = 2

    class StandardButton(IntFlag):
        Yes = 1
        No = 2
        Ok = 4

    results = []
    instances = []

    def __init__(self, parent=None):
        self.parent = parent
        self.__class__.instances.append(self)

    def __getattr__(self, _name):
        return lambda *args, **kwargs: None

    def exec(self):
        return self.__class__.results.pop(0)

    @staticmethod
    def warning(*args, **kwargs):
        return _FakeMessageBox.StandardButton.Ok

    @staticmethod
    def information(*args, **kwargs):
        return _FakeMessageBox.StandardButton.Ok

    @staticmethod
    def critical(*args, **kwargs):
        return _FakeMessageBox.StandardButton.Ok


class InterceptionInstallationPromptTests(unittest.TestCase):
    def setUp(self):
        _FakeMessageBox.results = []
        _FakeMessageBox.instances = []
        self.config = {
            "execution_mode": "foreground_driver",
            "foreground_mouse_driver_backend": "interception",
            "foreground_keyboard_driver_backend": "ibinputsimulator",
        }

    def test_config_must_actually_use_interception(self):
        self.assertTrue(is_interception_required_by_config(self.config))
        self.assertFalse(
            is_interception_required_by_config(
                {
                    "execution_mode": "background_sendmessage",
                    "foreground_mouse_driver_backend": "interception",
                    "foreground_keyboard_driver_backend": "interception",
                }
            )
        )

    def test_warning_explains_bluetooth_and_device_number_limit(self):
        self.assertIn("KbdClass0–9", INTERCEPTION_DEVICE_RISK_TEXT)
        self.assertIn("MouClass0–9", INTERCEPTION_DEVICE_RISK_TEXT)
        self.assertIn("蓝牙", INTERCEPTION_DEVICE_RISK_TEXT)
        self.assertIn("重启", INTERCEPTION_DEVICE_RISK_TEXT)

    def test_declining_never_calls_installer(self):
        driver = Mock()
        driver.is_driver_registered.return_value = False
        _FakeMessageBox.results = [_FakeMessageBox.StandardButton.No]

        with (
            patch("PySide6.QtWidgets.QMessageBox", _FakeMessageBox),
            patch("os.path.isfile", return_value=True),
            patch("utils.interception_driver.get_driver", return_value=driver),
        ):
            result = request_interception_installation(None, self.config)

        self.assertEqual(result, "declined")
        driver.install_driver.assert_not_called()

    def test_accepting_calls_installer_once_and_shows_restart_notice(self):
        driver = Mock()
        driver.is_driver_registered.return_value = False
        driver.install_driver.return_value = "installed"
        _FakeMessageBox.results = [
            _FakeMessageBox.StandardButton.Yes,
            _FakeMessageBox.StandardButton.Ok,
        ]

        with (
            patch("PySide6.QtWidgets.QMessageBox", _FakeMessageBox),
            patch("os.path.isfile", return_value=True),
            patch("utils.interception_driver.get_driver", return_value=driver),
        ):
            result = request_interception_installation(None, self.config)

        self.assertEqual(result, "installed")
        driver.install_driver.assert_called_once_with()
        self.assertEqual(len(_FakeMessageBox.instances), 2)


if __name__ == "__main__":
    unittest.main()
