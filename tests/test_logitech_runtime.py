import unittest
from pathlib import Path
from unittest.mock import patch

from utils.logitech_runtime import (
    LogitechRuntimeResult,
    _InstalledProduct,
    _clean_executable_path,
    _version_at_least,
    _version_matches,
    _version_prefix_matches,
    detect_logitech_runtime,
    is_logitech_ibinputsimulator_configured,
)


def product(name: str, version: str) -> _InstalledProduct:
    return _InstalledProduct(
        name=name,
        version=version,
        install_location="",
        display_icon="",
        key_name=name,
        publisher="Logitech",
        source="registry:HKLM:64",
    )


class LogitechRuntimeTests(unittest.TestCase):
    def test_version_comparisons(self):
        self.assertTrue(_version_matches("2026.4.919028", "2026.4.919028"))
        self.assertTrue(_version_matches("9.2.65.0", "9.02.65"))
        self.assertFalse(_version_matches("2026.4.919029", "2026.4.919028"))
        self.assertFalse(_version_matches("9.02.65.1", "9.02.65"))

        self.assertTrue(_version_at_least("2026.0.0.0", "2026.0.0.0"))
        self.assertTrue(_version_at_least("2026.1.0.0", "2026.0.0.0"))
        self.assertTrue(_version_at_least("2027.0", "2026.0.0.0"))
        self.assertFalse(_version_at_least("2025.9.9.9", "2026.0.0.0"))
        self.assertFalse(_version_at_least("", "2026.0.0.0"))

        self.assertTrue(_version_prefix_matches("2026.4.919028", "2026.4"))
        self.assertTrue(_version_prefix_matches("2026.4", "2026.4"))
        self.assertFalse(_version_prefix_matches("2026.5.939708", "2026.4"))
        self.assertFalse(_version_prefix_matches("2025.4.1", "2026.4"))

    def test_supported_ghub_selects_new_report_type(self):
        ghub = product("Logitech G HUB", "2026.4.919028")
        versions = (
            ("logi_joy_bus_enum.x64.sys", "2026.0.0.0"),
            ("logi_joy_xlcore.x64.sys", "2026.0.0.0"),
            ("logi_joy_vir_hid.x64.sys", "2026.0.0.0"),
        )
        with (
            patch("utils.logitech_runtime._iter_uninstall_products", return_value=iter((ghub,))),
            patch("utils.logitech_runtime._ghub_driver_versions", return_value=versions),
            patch("utils.logitech_runtime._ghub_virtual_mouse_ready", return_value=True),
        ):
            result = detect_logitech_runtime()

        self.assertTrue(result.compatible)
        self.assertEqual(result.send_type, "LogitechGHubNew")
        self.assertEqual(result.reason, "ghub_ready")

    def test_unsupported_ghub_version_asks_to_install_2026_4(self):
        ghub = product("Logitech G HUB", "2026.5.939708")
        with patch(
            "utils.logitech_runtime._iter_uninstall_products",
            return_value=iter((ghub,)),
        ):
            result = detect_logitech_runtime()

        self.assertFalse(result.compatible)
        self.assertEqual(result.reason, "unsupported_ghub_version")
        self.assertIn("Logitech G HUB 2026.4", result.user_message())
        self.assertNotIn("Logitech Gaming Software", result.user_message())

    def test_ghub_ready_via_bus_interface_without_started_hid_node(self):
        # HID 鼠标节点可能是 phantom，只要指定版本的总线设备接口已激活即应放行。
        ghub = product("Logitech G HUB", "2026.4.919028")
        versions = tuple(
            (name, "2026.0.0.0")
            for name in (
                "logi_joy_bus_enum.x64.sys",
                "logi_joy_xlcore.x64.sys",
                "logi_joy_vir_hid.x64.sys",
            )
        )
        with (
            patch("utils.logitech_runtime._iter_uninstall_products", return_value=iter((ghub,))),
            patch("utils.logitech_runtime._ghub_driver_versions", return_value=versions),
            patch("utils.logitech_runtime._device_interface_linked", return_value=True),
            patch("utils.logitech_runtime._find_started_device", return_value=""),
        ):
            result = detect_logitech_runtime()

        self.assertTrue(result.compatible)
        self.assertEqual(result.reason, "ghub_ready")

    def test_newer_ghub_driver_version_is_allowed_on_specified_app(self):
        ghub = product("Logitech G HUB", "2026.4.919028")
        versions = tuple(
            (name, "2026.1.2.3")
            for name in (
                "logi_joy_bus_enum.x64.sys",
                "logi_joy_xlcore.x64.sys",
                "logi_joy_vir_hid.x64.sys",
            )
        )
        with (
            patch("utils.logitech_runtime._iter_uninstall_products", return_value=iter((ghub,))),
            patch("utils.logitech_runtime._ghub_driver_versions", return_value=versions),
            patch("utils.logitech_runtime._ghub_virtual_mouse_ready", return_value=True),
        ):
            result = detect_logitech_runtime()

        self.assertTrue(result.compatible)
        self.assertEqual(result.reason, "ghub_ready")

    def test_outdated_ghub_app_is_blocked_before_driver_check(self):
        ghub = product("Logitech G HUB", "2021.3.5")
        with patch(
            "utils.logitech_runtime._iter_uninstall_products",
            return_value=iter((ghub,)),
        ):
            result = detect_logitech_runtime()

        self.assertFalse(result.compatible)
        self.assertEqual(result.reason, "unsupported_ghub_version")
        self.assertIn("Logitech G HUB 2026.4", result.user_message())

    def test_outdated_ghub_driver_is_blocked(self):
        ghub = product("Logitech G HUB", "2026.4.919028")
        versions = tuple(
            (name, "2021.0.0.0")
            for name in (
                "logi_joy_bus_enum.x64.sys",
                "logi_joy_xlcore.x64.sys",
                "logi_joy_vir_hid.x64.sys",
            )
        )
        with (
            patch("utils.logitech_runtime._iter_uninstall_products", return_value=iter((ghub,))),
            patch("utils.logitech_runtime._ghub_driver_versions", return_value=versions),
        ):
            result = detect_logitech_runtime()

        self.assertFalse(result.compatible)
        self.assertEqual(result.reason, "unsupported_ghub_driver")
        self.assertIn("Logitech G HUB 2026.4", result.user_message())

    def test_missing_ghub_driver_is_blocked(self):
        ghub = product("Logitech G HUB", "2026.4.919028")
        versions = (
            ("logi_joy_bus_enum.x64.sys", "2026.0.0.0"),
            ("logi_joy_xlcore.x64.sys", ""),
            ("logi_joy_vir_hid.x64.sys", "2026.0.0.0"),
        )
        with (
            patch("utils.logitech_runtime._iter_uninstall_products", return_value=iter((ghub,))),
            patch("utils.logitech_runtime._ghub_driver_versions", return_value=versions),
        ):
            result = detect_logitech_runtime()

        self.assertFalse(result.compatible)
        self.assertEqual(result.reason, "ghub_driver_missing")

    def test_ghub_requires_started_virtual_mouse(self):
        # 总线接口未激活且 HID 节点未启动时，如实拦截（本机截图即此场景）。
        ghub = product("Logitech G HUB", "2026.4.919028")
        versions = tuple((name, "2026.0.0.0") for name in ("bus", "core", "hid"))
        with (
            patch("utils.logitech_runtime._iter_uninstall_products", return_value=iter((ghub,))),
            patch("utils.logitech_runtime._ghub_driver_versions", return_value=versions),
            patch("utils.logitech_runtime._device_interface_linked", return_value=False),
            patch("utils.logitech_runtime._find_started_device", return_value=""),
        ):
            result = detect_logitech_runtime()

        self.assertFalse(result.compatible)
        self.assertEqual(result.reason, "ghub_virtual_mouse_not_started")

    def test_supported_lgs_selects_legacy_report_type(self):
        lgs = product("Logitech Gaming Software", "9.02.65")
        candidate = Path(r"C:\Program Files\Logitech Gaming Software\LCore.exe")
        with (
            patch("utils.logitech_runtime._iter_uninstall_products", return_value=iter((lgs,))),
            patch("utils.logitech_runtime._iter_lcore_candidates", return_value=iter((candidate,))),
            patch("utils.logitech_runtime._read_file_version", return_value="9.02.65"),
            patch(
                "utils.logitech_runtime._find_started_device",
                return_value=r"LogiDevice\VID_046D&PID_C231\active",
            ),
        ):
            result = detect_logitech_runtime()

        self.assertTrue(result.compatible)
        self.assertEqual(result.send_type, "Logitech")
        self.assertEqual(result.reason, "lgs_ready")

    def test_unsupported_lgs_version_asks_to_install_9_02_65(self):
        lgs = product("Logitech Gaming Software", "9.04.49")
        candidate = Path(r"C:\Program Files\Logitech Gaming Software\LCore.exe")
        with (
            patch("utils.logitech_runtime._iter_uninstall_products", return_value=iter((lgs,))),
            patch("utils.logitech_runtime._iter_lcore_candidates", return_value=iter((candidate,))),
            patch("utils.logitech_runtime._read_file_version", return_value="9.04.49"),
        ):
            result = detect_logitech_runtime()

        self.assertFalse(result.compatible)
        self.assertEqual(result.reason, "unsupported_lgs_version")
        self.assertIn("Logitech Gaming Software 9.02.65", result.user_message())

    def test_not_installed_lists_specified_versions(self):
        with (
            patch(
                "utils.logitech_runtime._iter_uninstall_products",
                return_value=iter(()),
            ),
            patch(
                "utils.logitech_runtime._iter_lcore_candidates",
                return_value=iter(()),
            ),
        ):
            result = detect_logitech_runtime()

        self.assertFalse(result.compatible)
        self.assertEqual(result.reason, "not_installed")
        message = result.user_message()
        self.assertIn("Logitech G HUB 2026.4", message)
        self.assertIn("Logitech Gaming Software 9.02.65", message)

    def test_display_icon_path_is_cleaned(self):
        self.assertEqual(
            _clean_executable_path(
                r'"C:\Program Files\Logitech Gaming Software\LCore.exe",0'
            ),
            r"C:\Program Files\Logitech Gaming Software\LCore.exe",
        )

    def test_config_detection_does_not_depend_on_execution_mode(self):
        config = {
            "execution_mode": "background_sendmessage",
            "foreground_mouse_driver_backend": "ibinputsimulator",
            "foreground_keyboard_driver_backend": "interception",
            "ibinputsimulator_driver": "Logitech",
        }
        self.assertTrue(is_logitech_ibinputsimulator_configured(config))

    def test_legacy_unified_backend_key_is_ignored(self):
        config = {
            "foreground_driver_backend": "ibinputsimulator",
            "ibinputsimulator_driver": "Logitech",
        }
        self.assertFalse(is_logitech_ibinputsimulator_configured(config))

    def test_driver_error_is_stable(self):
        result = LogitechRuntimeResult(
            compatible=False,
            detected_name="Logitech G HUB",
            detected_version="2027.1.0",
            reason="unsupported_ghub_driver",
        )
        self.assertIn("LogitechRuntimeUnavailable", result.driver_error())


if __name__ == "__main__":
    unittest.main()
