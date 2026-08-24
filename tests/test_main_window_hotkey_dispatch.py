import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock


_MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "ui/main_window_parts/main_window_hotkey_core_mixin.py"
)
_SPEC = importlib.util.spec_from_file_location(
    "tests._main_window_hotkey_core_mixin",
    _MODULE_PATH,
)
_HOTKEY_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _HOTKEY_MODULE
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_HOTKEY_MODULE)

MainWindowHotkeyCoreMixin = _HOTKEY_MODULE.MainWindowHotkeyCoreMixin


class _HotkeyHost(MainWindowHotkeyCoreMixin):
    def __init__(self, owner_thread):
        self._owner_thread = owner_thread

    def thread(self):
        return self._owner_thread


class MainWindowHotkeyDispatchTests(unittest.TestCase):
    def test_callback_runs_immediately_on_window_thread(self):
        owner_thread = object()
        host = _HotkeyHost(owner_thread)
        callback = mock.Mock()

        with mock.patch.object(
            _HOTKEY_MODULE.QThread,
            "currentThread",
            return_value=owner_thread,
        ):
            host._queue_hotkey_callback(callback)

        callback.assert_called_once_with()

    def test_background_hook_callback_is_queued_to_window_thread(self):
        host = _HotkeyHost(object())
        callback = mock.Mock()

        with mock.patch.object(
            _HOTKEY_MODULE.QThread,
            "currentThread",
            return_value=object(),
        ), mock.patch.object(_HOTKEY_MODULE.QTimer, "singleShot") as single_shot:
            host._queue_hotkey_callback(callback)

        callback.assert_not_called()
        single_shot.assert_called_once_with(0, host, callback)


if __name__ == "__main__":
    unittest.main()
