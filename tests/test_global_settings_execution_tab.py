import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import ui.main_window_parts.main_window  # Establish the application's normal import order.
from ui.global_settings_parts.global_settings_dialog import GlobalSettingsDialog


class GlobalSettingsExecutionTabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_native_execution_tab_and_modes_are_visible(self):
        dialog = GlobalSettingsDialog(
            {
                "bound_windows": [],
                "window_binding_mode": "single",
                "execution_mode": "foreground_driver",
            }
        )

        tab_titles = [
            dialog.tab_widget.tabText(index)
            for index in range(dialog.tab_widget.count())
        ]
        mode_values = [
            dialog.mode_combo.itemData(index)
            for index in range(dialog.mode_combo.count())
        ]

        self.assertIn("执行模式", tab_titles)
        self.assertEqual(
            mode_values,
            [
                "foreground_driver",
                "foreground_py",
                "background_sendmessage",
                "background_postmessage",
            ],
        )

        dialog.close()
        dialog.deleteLater()
        self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
