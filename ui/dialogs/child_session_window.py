# -*- coding: utf-8 -*-
"""LCA 桌面分身窗口：嵌入本机 Child Session 的 RDP 画面。"""

from __future__ import annotations

import ctypes
import logging
from typing import Any, Callable, Mapping

from PySide6.QtCore import QEvent, QSize, Qt, QTimer
from PySide6.QtGui import QActionGroup
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from themes.rounded_popup import apply_native_window_corners
from ui.system_parts.menu_style import apply_unified_menu_style
from utils.child_session.rdp_host import RdpActiveXHost
from utils.child_session.service import ChildSessionService
from utils.child_session.settings import DESKTOP_RESOLUTIONS
from utils.window.window_coordinate_common import (
    center_window_on_widget_screen,
    clamp_preferred_window_size,
    get_available_geometry_for_widget,
)

logger = logging.getLogger(__name__)


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _MINMAXINFO(ctypes.Structure):
    _fields_ = [
        ("ptReserved", _POINT),
        ("ptMaxSize", _POINT),
        ("ptMaxPosition", _POINT),
        ("ptMinTrackSize", _POINT),
        ("ptMaxTrackSize", _POINT),
    ]


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("rcMonitor", _RECT),
        ("rcWork", _RECT),
        ("dwFlags", ctypes.c_ulong),
    ]


_USER32 = None


def _user32():
    global _USER32
    if _USER32 is None:
        dll = ctypes.WinDLL("user32", use_last_error=True)
        dll.MonitorFromWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        dll.MonitorFromWindow.restype = ctypes.c_void_p
        dll.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_MONITORINFO)]
        dll.GetMonitorInfoW.restype = ctypes.c_int
        _USER32 = dll
    return _USER32


def _constrain_maximized_to_work_area(message) -> bool:
    """最大化时把窗口限制在工作区，避免盖住原桌面任务栏。"""
    from ui.main_window_parts.main_window_support import _safe_get_win_msg

    msg = _safe_get_win_msg(message)
    if msg is None or int(msg.message) != _WM_GETMINMAXINFO:
        return False
    info = _MINMAXINFO.from_address(int(msg.lParam))
    monitor = _user32().MonitorFromWindow(int(msg.hWnd), _MONITOR_DEFAULTTONEAREST)
    if not monitor:
        return False
    monitor_info = _MONITORINFO()
    monitor_info.cbSize = ctypes.sizeof(_MONITORINFO)
    if not _user32().GetMonitorInfoW(monitor, ctypes.byref(monitor_info)):
        return False
    work = monitor_info.rcWork
    screen = monitor_info.rcMonitor
    info.ptMaxPosition.x = work.left - screen.left
    info.ptMaxPosition.y = work.top - screen.top
    info.ptMaxSize.x = work.right - work.left
    info.ptMaxSize.y = work.bottom - work.top
    info.ptMaxTrackSize.x = info.ptMaxSize.x
    info.ptMaxTrackSize.y = info.ptMaxSize.y
    return True

DEFAULT_WINDOW_WIDTH = 1280
SMALL_WINDOW_WIDTH = 500
ASPECT_RATIO = 16 / 9
NORMAL_MIN_SIZE = QSize(640, 400)
SMALL_MIN_SIZE = QSize(400, 250)
_WM_GETMINMAXINFO = 0x0024
_MONITOR_DEFAULTTONEAREST = 2
CLOSE_WARNING = (
    "关闭会断开 RDP 并注销桌面分身，其中所有正在运行的软件都会被关闭，未保存的数据会丢失。是否继续？"
)


class ChildSessionWindow(QMainWindow):
    def __init__(
        self,
        config: dict[str, Any],
        save_config: Callable[[Mapping[str, Any]], None],
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("ChildSessionWindow")
        self.setWindowTitle("LCA 桌面分身")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._config = config
        self._save_config = save_config
        self._closing = False
        self._allow_close = False
        self._small_window_mode = False
        self._keep_aspect_applying = False
        self._session_closing = False
        self._restoring_position = False
        self._surface_visible = False
        self._pending_position = None
        self._last_saved_position = None
        self._minimized_with_main = False
        self._state_before_main_minimize = Qt.WindowState.WindowNoState
        self._applying_main_minimize = False
        self._position_timer = QTimer(self)
        self._position_timer.setSingleShot(True)
        self._position_timer.setInterval(400)
        self._position_timer.timeout.connect(self._persist_pending_position)

        self.rdp_host = RdpActiveXHost(self)
        self.service = ChildSessionService(self.rdp_host, config, save_config, self)
        self.service.state_changed.connect(self._on_state_changed)
        self.rdp_host.transport_connected.connect(self._on_transport_connected)

        self.service.connection_failed.connect(self._on_connection_failed)
        self.service.start_failed.connect(self._on_start_failed)
        self.service.system_shortcuts_reconnect_completed.connect(self._on_shortcuts_reconnect_done)
        self.service.audio_reconnect_completed.connect(self._on_audio_reconnect_done)
        self.service.logoff_finished.connect(self._on_logoff_finished)
        self.service.logoff_failed.connect(self._on_logoff_failed)
        self._build_ui()
        self._apply_initial_geometry()
        self._register_theme_callback()
        self._apply_window_chrome()
        self._sync_option_checks()
        self._on_state_changed()

    def shutdown(self) -> None:
        self._flush_window_position()
        if self.request_close_after_logoff():
            return
        self._force_close()

    def _force_close(self) -> None:
        self._flush_window_position()
        self._allow_close = True
        try:
            self.service.dispose()
        except Exception as exc:
            logger.warning("关闭桌面分身服务失败: %s", exc)
        self.close()

    def present(self, reference=None) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        self._apply_topmost()

    def request_close_after_logoff(self) -> bool:
        if self._allow_close:
            return False
        if self._closing:
            return True
        if self.service.child_session_id is None:
            return False
        self._closing = True
        self._set_session_closing(True)
        try:
            self.service.logoff_and_disconnect()
        except Exception:
            self._closing = False
            self._set_session_closing(False)
            raise
        return True

    def closeEvent(self, event) -> None:
        if self._allow_close:
            self._forget_theme_callback()
            super().closeEvent(event)
            return
        if self._closing:
            event.ignore()
            return
        if self.service.child_session_id is None:
            self.shutdown()
            event.accept()
            return
        event.ignore()
        result = QMessageBox.warning(
            self,
            "关闭 LCA 桌面分身",
            CLOSE_WARNING,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        try:
            if not self.request_close_after_logoff():
                self.shutdown()
        except Exception as exc:
            QMessageBox.warning(self, "注销桌面分身失败", str(exc))
            self._closing = False
            self._set_session_closing(False)

    def _on_logoff_finished(self, _session_id) -> None:
        if not self._closing:
            return
        self._closing = False
        self._set_session_closing(False)
        self._force_close()

    def _on_logoff_failed(self, message: str) -> None:
        QMessageBox.warning(self, "注销桌面分身失败", message)
        self._closing = False
        self._set_session_closing(False)

    def _follow_main_window_minimized(self, minimized: bool) -> None:
        if minimized:
            if self._minimized_with_main or not self.isVisible() or self.isMinimized():
                return
            self._state_before_main_minimize = self.windowState()
            self._minimized_with_main = True
            self._applying_main_minimize = True
            try:
                self.showMinimized()
            finally:
                self._applying_main_minimize = False
            return
        if not self._minimized_with_main:
            return
        previous = self._state_before_main_minimize
        self._minimized_with_main = False
        self._state_before_main_minimize = Qt.WindowState.WindowNoState
        restored = (
            Qt.WindowState.WindowMaximized
            if previous & Qt.WindowState.WindowMaximized
            else Qt.WindowState.WindowNoState
        )
        self._applying_main_minimize = True
        try:
            self.setWindowState(restored)
        finally:
            self._applying_main_minimize = False

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() != QEvent.Type.WindowStateChange or self._applying_main_minimize:
            return
        if not self.isMinimized():
            self._minimized_with_main = False

    def nativeEvent(self, eventType, message):
        if eventType == b"windows_generic_MSG" or eventType == "windows_generic_MSG":
            if _constrain_maximized_to_work_area(message):
                return True, 0
        return super().nativeEvent(eventType, message)

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        if self.isMinimized() or self._applying_main_minimize:
            return
        self._remember_window_position()
        self.rdp_host._sync_place()

    def hideEvent(self, event) -> None:
        self._flush_window_position()
        if not self._applying_main_minimize:
            self._minimized_with_main = False
        super().hideEvent(event)

    def _remember_window_position(self) -> None:
        if self._session_closing or self._restoring_position or not self.isVisible():
            return
        key = "small_window_position" if self._small_window_mode else "normal_window_position"
        position = (key, int(self.x()), int(self.y()))
        if position == self._last_saved_position:
            return
        self._pending_position = position
        self._position_timer.start()

    def _flush_window_position(self) -> None:
        self._position_timer.stop()
        self._persist_pending_position()

    def _persist_pending_position(self) -> None:
        pending = self._pending_position
        self._pending_position = None
        if pending is None or pending == self._last_saved_position:
            return
        try:
            self.service.store_window_position(pending[0], pending[1], pending[2])
        except Exception:
            logger.exception("保存桌面分身窗口位置失败")
            return
        self._last_saved_position = pending

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.start_button = QPushButton("启动并连接")
        self.start_button.setProperty("primary", True)
        self.start_button.clicked.connect(self._on_start_clicked)
        self.more_button = QPushButton("更多")
        self.more_button.clicked.connect(self._on_more_clicked)
        self.status_label = QLabel("桌面分身尚未启动")
        self.status_label.setObjectName("childSessionStatusLabel")
        self.status_label.setWordWrap(True)
        toolbar.addWidget(self.start_button)
        toolbar.addWidget(self.more_button)
        toolbar.addWidget(self.status_label, 1)
        layout.addLayout(toolbar)

        self.host_container = QWidget(self)
        self.host_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        host_layout = QVBoxLayout(self.host_container)
        host_layout.setContentsMargins(0, 0, 0, 0)
        self.rdp_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        host_layout.addWidget(self.rdp_host)
        self.prompt_label = QLabel(
            "点击“启动并连接”，LCA 将创建独立桌面并建立 RDP 连接。"
        )
        self.prompt_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.prompt_label.setWordWrap(True)
        self.prompt_label.setParent(self.host_container)
        layout.addWidget(self.host_container, 1)

        self._build_more_menu()

    def _build_more_menu(self) -> None:
        self.more_menu = apply_unified_menu_style(QMenu(self), frameless=True)
        self.more_menu.addAction("以管理员启动…", self._on_launch_executable)
        self.more_menu.addAction("显示桌面", self._on_show_desktop)
        self.more_menu.addAction("任务视图", self._on_show_task_view)
        self.more_menu.addSeparator()
        self._build_resolution_menu()
        self.more_menu.addSeparator()
        self.topmost_action = self.more_menu.addAction("窗口置顶")
        self.topmost_action.setCheckable(True)
        self.topmost_action.toggled.connect(self._on_topmost_toggled)
        self.block_mouse_action = self.more_menu.addAction("屏蔽物理鼠标")
        self.block_mouse_action.setCheckable(True)
        self.block_mouse_action.toggled.connect(self._on_block_physical_mouse_toggled)
        self.adaptive_action = self.more_menu.addAction("自适应显示")
        self.adaptive_action.setCheckable(True)
        self.one_to_one_action = self.more_menu.addAction("1:1 显示")
        self.one_to_one_action.setCheckable(True)
        self.display_mode_group = QActionGroup(self.more_menu)
        self.display_mode_group.setExclusive(True)
        self.display_mode_group.addAction(self.adaptive_action)
        self.display_mode_group.addAction(self.one_to_one_action)
        self.adaptive_action.toggled.connect(self._on_adaptive_toggled)
        self.one_to_one_action.toggled.connect(self._on_one_to_one_toggled)
        self.aspect_action = self.more_menu.addAction("保持宽高比")
        self.aspect_action.setCheckable(True)
        self.aspect_action.toggled.connect(self._on_aspect_toggled)
        self.shortcuts_action = self.more_menu.addAction("系统组合键发到桌面分身")
        self.shortcuts_action.setCheckable(True)
        self.shortcuts_action.toggled.connect(self._on_shortcuts_toggled)
        self.mute_action = self.more_menu.addAction("静音")
        self.mute_action.setCheckable(True)
        self.mute_action.toggled.connect(self._on_mute_toggled)
        self.small_action = self.more_menu.addAction("小窗模式")
        self.small_action.setCheckable(True)
        self.small_action.toggled.connect(self._on_small_toggled)
        self.more_menu.addSeparator()
        self.more_menu.addAction("隐藏窗口", self.hide)
        self.more_menu.addAction("关闭并注销", self.close)
        self.more_menu.aboutToShow.connect(self._sync_option_checks)

    def _build_resolution_menu(self) -> None:
        self.resolution_menu = apply_unified_menu_style(
            QMenu("桌面分辨率", self.more_menu),
            frameless=True,
        )
        self.more_menu.addMenu(self.resolution_menu)
        self.resolution_group = QActionGroup(self.resolution_menu)
        self.resolution_group.setExclusive(True)
        self.resolution_menu.aboutToShow.connect(self._sync_option_checks)
        current = (self.service.desktop_width, self.service.desktop_height)
        choices = list(DESKTOP_RESOLUTIONS)
        if current not in choices:
            choices.append(current)
        for width, height in choices:
            action = self.resolution_menu.addAction("{0} × {1}".format(width, height))
            action.setCheckable(True)
            action.setData((width, height))
            self.resolution_group.addAction(action)
            action.triggered.connect(self._on_resolution_triggered)

    def _apply_initial_geometry(self) -> None:
        available = get_available_geometry_for_widget(self.parentWidget() or self)
        width, height = clamp_preferred_window_size(
            DEFAULT_WINDOW_WIDTH,
            int(DEFAULT_WINDOW_WIDTH / ASPECT_RATIO) + 72,
            available,
        )
        self.resize(width, height)
        self.setMinimumSize(NORMAL_MIN_SIZE)
        center_window_on_widget_screen(self, self.parentWidget())

    def _apply_window_chrome(self) -> None:
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self.service.topmost_enabled)
        apply_native_window_corners(self)

    def _register_theme_callback(self) -> None:
        from themes import get_theme_manager

        get_theme_manager().register_theme_change_callback(self._on_theme_changed)

    def _forget_theme_callback(self) -> None:
        try:
            from themes import get_theme_manager

            get_theme_manager().unregister_theme_change_callback(self._on_theme_changed)
        except Exception:
            pass

    def _on_theme_changed(self, _theme=None) -> None:
        style = self.style()
        for widget in [self, *self.findChildren(QWidget)]:
            style.unpolish(widget)
            style.polish(widget)
            widget.update()
        apply_native_window_corners(self)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        apply_native_window_corners(self)
        self._layout_prompt()

    def _layout_prompt(self) -> None:
        self.prompt_label.setGeometry(self.host_container.rect())
        self.prompt_label.raise_()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._layout_prompt()
        if (
            self._keep_aspect_applying
            or self._applying_main_minimize
            or self.isMinimized()
            or not self.service.keep_aspect_ratio
            or self._session_closing
        ):
            return
        self._apply_aspect_ratio()

    def _apply_aspect_ratio(self) -> None:
        # 最大化时窗口必须停在工作区里。再按 16:9 拉高会盖住原桌面任务栏。
        if self.isMaximized() or self.isFullScreen() or self.isMinimized():
            return
        self._keep_aspect_applying = True
        try:
            toolbar = 72
            content_height = max(1, self.height() - toolbar)
            width = self.width()
            expected_height = int(width / ASPECT_RATIO) + toolbar
            available = get_available_geometry_for_widget(self)
            if available is not None and not available.isEmpty():
                frame = self.frameGeometry()
                chrome_h = max(0, int(frame.height()) - int(self.height()))
                if expected_height + chrome_h > int(available.height()):
                    return
            if abs(self.height() - expected_height) > 8:
                self.resize(width, expected_height)
        finally:
            self._keep_aspect_applying = False

    def _sync_option_checks(self) -> None:
        self.topmost_action.blockSignals(True)
        self.block_mouse_action.blockSignals(True)
        self.adaptive_action.blockSignals(True)
        self.one_to_one_action.blockSignals(True)
        self.aspect_action.blockSignals(True)
        self.shortcuts_action.blockSignals(True)
        self.mute_action.blockSignals(True)
        self.small_action.blockSignals(True)
        self.topmost_action.setChecked(self.service.topmost_enabled)
        self.block_mouse_action.setChecked(self.service.block_physical_mouse)
        self._check_single_action(
            self.display_mode_group,
            self.adaptive_action if self.service.smart_sizing_enabled else self.one_to_one_action,
        )
        self.aspect_action.setChecked(self.service.keep_aspect_ratio)
        self.shortcuts_action.setChecked(self.service.send_system_shortcuts_to_remote)
        self.mute_action.setChecked(self.service.audio_muted)
        self.small_action.setChecked(self._small_window_mode)
        current = (self.service.desktop_width, self.service.desktop_height)
        selected = None
        for action in self.resolution_group.actions():
            size = action.data()
            if (int(size[0]), int(size[1])) == current:
                selected = action
                break
        self._check_single_action(self.resolution_group, selected)
        for action in (
            self.topmost_action,
            self.block_mouse_action,
            self.adaptive_action,
            self.one_to_one_action,
            self.aspect_action,
            self.shortcuts_action,
            self.mute_action,
            self.small_action,
        ):
            action.blockSignals(False)

    def _set_session_closing(self, closing: bool) -> None:
        self._session_closing = closing
        enabled = not closing
        self.start_button.setEnabled(enabled)
        self.more_button.setEnabled(enabled)

    def _on_state_changed(self) -> None:
        self.status_label.setText(self.service.status_text)
        if self.service.connected_state == 0:
            self._surface_visible = False
        connected = self.service.connected_state == 1
        self._apply_topmost()
        show_prompt = not connected and not self._surface_visible
        self.prompt_label.setVisible(show_prompt)
        if show_prompt:
            self.prompt_label.show()
            self._layout_prompt()
        else:
            self.prompt_label.hide()

    def _on_transport_connected(self) -> None:
        self._surface_visible = True
        self._on_state_changed()

    def _on_connection_failed(self, event) -> None:
        self._surface_visible = False
        self._on_state_changed()
        message = getattr(event, "message", str(event))
        QMessageBox.warning(self, "桌面分身连接失败", message)

    def _on_start_failed(self, message: str) -> None:
        QMessageBox.warning(self, "无法启动桌面分身", message)

    def _on_shortcuts_reconnect_done(self) -> None:
        self._sync_option_checks()

    def _on_audio_reconnect_done(self) -> None:
        self._sync_option_checks()

    def _on_start_clicked(self) -> None:
        try:
            self.service.start()
        except Exception as exc:
            QMessageBox.warning(self, "无法启动桌面分身", str(exc))

    def _on_more_clicked(self) -> None:
        self.more_menu.exec(self.more_button.mapToGlobal(self.more_button.rect().bottomLeft()))

    def _on_launch_executable(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(self, "选择要以管理员启动的程序", "", "程序 (*.exe)")
        if not path:
            return
        try:
            self.service.launch_executable(path)
        except Exception as exc:
            QMessageBox.warning(self, "无法启动程序", str(exc))

    def _on_show_desktop(self) -> None:
        try:
            self.rdp_host.send_show_desktop_shortcut()
        except Exception as exc:
            QMessageBox.warning(self, "无法发送 Win+D", str(exc))

    def _on_show_task_view(self) -> None:
        try:
            self.rdp_host.send_task_view_shortcut()
        except Exception as exc:
            QMessageBox.warning(self, "无法发送 Win+Tab", str(exc))

    def _check_single_action(self, group: QActionGroup, selected) -> None:
        for action in group.actions():
            action.blockSignals(True)
            action.setChecked(action is selected)
            action.blockSignals(False)

    def _on_resolution_triggered(self, _checked: bool = False) -> None:
        action = self.sender()
        size = action.data()
        self._check_single_action(self.resolution_group, action)
        try:
            self.service.set_desktop_resolution(int(size[0]), int(size[1]))
        except Exception as exc:
            QMessageBox.warning(self, "无法调整分辨率", str(exc))
        self._sync_option_checks()

    def _apply_topmost(self) -> None:
        enabled = self.service.topmost_enabled
        current = bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        if current == enabled:
            return
        visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        if visible:
            self.show()

    def _on_topmost_toggled(self, checked: bool) -> None:
        self.service.set_topmost(checked)
        self._apply_topmost()

    def _on_block_physical_mouse_toggled(self, checked: bool) -> None:
        try:
            self.service.set_block_physical_mouse(checked)
        except Exception as exc:
            QMessageBox.warning(self, "无法切换物理鼠标屏蔽", str(exc))
            self._sync_option_checks()

    def _on_adaptive_toggled(self, checked: bool) -> None:
        if not checked:
            return
        self._check_single_action(self.display_mode_group, self.adaptive_action)
        self.service.set_smart_sizing(True)

    def _on_one_to_one_toggled(self, checked: bool) -> None:
        if not checked:
            return
        self._check_single_action(self.display_mode_group, self.one_to_one_action)
        self.service.set_smart_sizing(False)

    def _on_aspect_toggled(self, checked: bool) -> None:
        self.service.set_keep_aspect_ratio(checked)
        if checked:
            self._apply_aspect_ratio()

    def _on_shortcuts_toggled(self, checked: bool) -> None:
        try:
            self.service.set_send_system_shortcuts_to_remote(checked)
        except Exception as exc:
            QMessageBox.warning(self, "无法切换系统组合键", str(exc))
            self._sync_option_checks()

    def _on_mute_toggled(self, checked: bool) -> None:
        try:
            self.service.set_audio_muted(checked)
        except Exception as exc:
            QMessageBox.warning(self, "无法切换静音", str(exc))
            self._sync_option_checks()

    def _on_small_toggled(self, checked: bool) -> None:
        self._small_window_mode = bool(checked)
        self.setMinimumSize(SMALL_MIN_SIZE if checked else NORMAL_MIN_SIZE)
        target_width = SMALL_WINDOW_WIDTH if checked else DEFAULT_WINDOW_WIDTH
        target_height = int(target_width / ASPECT_RATIO) + 72
        self._keep_aspect_applying = True
        try:
            self.resize(target_width, target_height)
        finally:
            self._keep_aspect_applying = False
        center_window_on_widget_screen(self, self.parentWidget())
