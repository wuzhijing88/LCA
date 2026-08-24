import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import ui.main_window_parts.main_window  # Establish the application's normal import order.
from app_core.app_config import APP_EDITION, APP_NAME, APP_SOURCE_REPOSITORY, app_source_url
from ui.global_settings_parts.global_settings_dialog import GlobalSettingsDialog


class GlobalSettingsAboutTabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _create_dialog(self):
        return GlobalSettingsDialog(
            {
                "bound_windows": [],
                "window_binding_mode": "single",
            }
        )

    def test_about_tab_shows_formal_identity_and_source_address(self):
        dialog = self._create_dialog()
        tab_titles = [
            dialog.tab_widget.tabText(index)
            for index in range(dialog.tab_widget.count())
        ]

        self.assertEqual(tab_titles[-1], "关于")
        self.assertEqual(dialog.about_name_label.text(), APP_NAME)
        self.assertEqual(dialog.about_edition_label.text(), APP_EDITION)
        self.assertEqual(dialog.about_source_label.text(), app_source_url())
        self.assertEqual(APP_SOURCE_REPOSITORY, "github.com/wuzhijing88/LCA")
        self.assertIn("GNU Affero General Public License v3.0", dialog.about_license_label.text())

        dialog.close()
        dialog.deleteLater()
        self.app.processEvents()

    def test_copy_source_address_writes_full_repository_url(self):
        dialog = self._create_dialog()
        dialog._copy_source_repository()

        self.assertEqual(self.app.clipboard().text(), app_source_url())
        self.assertEqual(dialog.about_copy_source_button.text(), "已复制")

        dialog.close()
        dialog.deleteLater()
        self.app.processEvents()

    def test_open_source_repository_uses_system_browser(self):
        dialog = self._create_dialog()
        with mock.patch(
            "ui.global_settings_parts.global_settings_dialog_about_tab_mixin.QDesktopServices.openUrl"
        ) as open_url:
            dialog._open_source_repository()

        opened_url = open_url.call_args.args[0]
        self.assertEqual(opened_url.toString(), app_source_url())

        dialog.close()
        dialog.deleteLater()
        self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
