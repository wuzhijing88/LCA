import os
import sys
import types
import unittest
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from themes.theme_manager import ThemeWatcher, detect_system_theme


class ThemeManagerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_detect_system_theme_uses_light_fallback_without_warning_when_registry_missing(self):
        fake_winreg = types.SimpleNamespace(
            HKEY_CURRENT_USER=object(),
            ConnectRegistry=lambda *args, **kwargs: object(),
            OpenKey=mock.Mock(side_effect=FileNotFoundError()),
            QueryValueEx=mock.Mock(),
            CloseKey=mock.Mock(),
        )

        with mock.patch('themes.theme_manager.platform.system', return_value='Windows'):
            with mock.patch.dict(sys.modules, {'winreg': fake_winreg}):
                with mock.patch('themes.theme_manager.logger.warning') as warning_logger:
                    theme = detect_system_theme()

        self.assertEqual(theme, 'light')
        warning_logger.assert_not_called()

    def test_theme_watcher_uses_longer_interval_when_app_inactive(self):
        watcher = ThemeWatcher()
        try:
            watcher._app = mock.Mock(
                applicationState=mock.Mock(return_value=Qt.ApplicationState.ApplicationInactive)
            )
            self.assertEqual(
                watcher._get_check_interval(),
                ThemeWatcher.INACTIVE_CHECK_INTERVAL_MS,
            )
        finally:
            watcher.stop()

    def test_theme_watcher_checks_immediately_when_app_becomes_active(self):
        watcher = ThemeWatcher()
        events = []
        watcher.theme_changed.connect(events.append)
        watcher.current_system_theme = 'light'
        try:
            with mock.patch('themes.theme_manager.detect_system_theme', return_value='dark'):
                watcher._app = mock.Mock(
                    applicationState=mock.Mock(return_value=Qt.ApplicationState.ApplicationActive)
                )
                watcher._on_application_state_changed(Qt.ApplicationState.ApplicationActive)
        finally:
            watcher.stop()

        self.assertEqual(events, ['dark'])


if __name__ == '__main__':
    unittest.main()
