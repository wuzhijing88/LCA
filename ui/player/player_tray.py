from __future__ import annotations

import logging

from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from ui.system_parts.menu_style import apply_unified_menu_style

logger = logging.getLogger(__name__)


class PlayerTraySession:
    """独立程序自己的托盘：显示窗口 / 开始 / 暂停 / 停止 / 退出。"""

    def __init__(self, window) -> None:
        self._window = window
        self._icon: QSystemTrayIcon | None = None

    def install(self) -> bool:
        if self._icon is not None:
            return True
        if not QSystemTrayIcon.isSystemTrayAvailable():
            logger.warning("系统托盘不可用，独立程序改为普通窗口")
            return False
        icon = QSystemTrayIcon(self._window)
        window_icon = self._window.windowIcon()
        if window_icon is None or window_icon.isNull():
            app = QApplication.instance()
            if app is not None:
                window_icon = app.windowIcon()
        if window_icon is not None and not window_icon.isNull():
            icon.setIcon(window_icon)
        else:
            icon.setIcon(QIcon())
        menu = apply_unified_menu_style(QMenu(), frameless=True)
        show_action = QAction("显示窗口", menu)
        show_action.triggered.connect(self._window.restore_main_window)
        start_action = QAction("开始", menu)
        start_action.triggered.connect(self._window.safe_start_tasks)
        pause_action = QAction("暂停 / 恢复", menu)
        pause_action.triggered.connect(self._window._on_pause_clicked)
        stop_action = QAction("停止", menu)
        stop_action.triggered.connect(self._window.safe_stop_tasks)
        quit_action = QAction("退出程序", menu)
        quit_action.triggered.connect(self._window.request_quit)
        menu.addAction(show_action)
        menu.addSeparator()
        menu.addAction(start_action)
        menu.addAction(pause_action)
        menu.addAction(stop_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        icon.setContextMenu(menu)
        icon.setToolTip(str(self._window.windowTitle() or "独立程序"))
        icon.activated.connect(self._on_activated)
        icon.show()
        self._icon = icon
        return True

    def cleanup(self) -> None:
        icon = self._icon
        self._icon = None
        if icon is None:
            return
        try:
            icon.hide()
            icon.setContextMenu(None)
            icon.deleteLater()
        except RuntimeError:
            pass

    def _on_activated(self, reason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._window.restore_main_window()
