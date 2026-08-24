import ctypes
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.ibinputsimulator_driver import IbInputSimulatorDriver
from utils.logitech_runtime import LogitechRuntimeResult

ROOT_DIR = Path(__file__).resolve().parents[1]
BINDING_PATH = ROOT_DIR / "tools" / "ibinputsimulator" / "Binding.AHK2" / "IbInputSimulator.ahk"
WORKER_PATH = ROOT_DIR / "tools" / "ibinputsimulator" / "ib_worker_core.ahk"
DLL_PATH = ROOT_DIR / "tools" / "ibinputsimulator" / "Binding.AHK2" / "IbInputSimulator.dll"


class LogitechClickRoutingTests(unittest.TestCase):
    def test_binding_exposes_native_mouse_button_event(self):
        source = BINDING_PATH.read_text(encoding="utf-8")

        self.assertIn('send_type == "Logitech"', source)
        self.assertIn('"Int", 2, "Int", 0, "Ptr", 0, "Int"', source)
        self.assertIn('send_type == "LogitechGHubNew"', source)
        self.assertIn('"Int", 6, "Int", 0, "Ptr", 0, "Int"', source)
        self.assertIn("IbMouseButtonEvent(button, down_or_up)", source)
        self.assertIn('"IbInputSimulator\\IbSendMouseClick"', source)
        self.assertIn('"left:d", 0x0002', source)
        self.assertIn('"left:u", 0x0004', source)

    def test_worker_routes_logitech_family_button_events_to_native_api(self):
        source = WORKER_PATH.read_text(encoding="utf-8")

        self.assertIn('global _ib_driver_name := ""', source)
        self.assertIn(
            'if _ib_driver_name = "logitech" || _ib_driver_name = "logitechghubnew"',
            source,
        )
        self.assertIn("IbMouseButtonEvent(btn, downOrUp)", source)
        self.assertIn("IbMouseClick(btn, tx, ty, 1, 0, downOrUp)", source)

    @unittest.skipUnless(sys.platform == "win32", "Windows DLL export check")
    def test_runtime_dll_exports_native_mouse_click_api(self):
        library = ctypes.WinDLL(str(DLL_PATH))
        self.assertTrue(callable(getattr(library, "IbSendMouseClick")))

    def test_incompatible_logitech_runtime_blocks_worker_startup(self):
        result = LogitechRuntimeResult(
            compatible=False,
            detected_name="Logitech G HUB",
            detected_version="2027.1.0",
            reason="unsupported_ghub_version",
        )
        driver = IbInputSimulatorDriver(driver="Logitech")
        try:
            with (
                patch("utils.ibinputsimulator_driver.detect_logitech_runtime", return_value=result),
                patch.object(driver, "_find_ahk_exe") as find_ahk,
            ):
                self.assertFalse(driver.initialize())
            find_ahk.assert_not_called()
            self.assertIn("LogitechRuntimeUnavailable", driver.get_last_error())
        finally:
            driver.close()


if __name__ == "__main__":
    unittest.main()
