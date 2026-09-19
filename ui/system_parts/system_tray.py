"""系统托盘：作为全局热键之外的备用启动 / 停止控制入口。"""

from __future__ import annotations

import logging
import os

from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtGui import QAction, QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from utils.app_paths import get_resource_path

_DEFAULT_APP_DISPLAY_NAME = "工作流自动化工具"


class SystemTrayManager(QObject):
    """系统托盘管理器，提供备用的启动/停止控制"""

    start_requested = Signal()
    stop_requested = Signal()
    show_window_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tray_icon = None
        self.main_window = None
        self._task_state_signal = None
        self._task_state_slot = None
        self._tray_start_action = None
        self._tray_stop_action = None

    def attach_task_state_binding(self, signal_obj, slot_obj):
        """记录任务状态信号绑定，供 cleanup 时精确断连。"""
        self._task_state_signal = signal_obj
        self._task_state_slot = slot_obj

    def setup_tray(self, main_window):
        """设置系统托盘"""
        self.main_window = main_window

        if not QSystemTrayIcon.isSystemTrayAvailable():
            logging.warning("系统托盘不可用")
            return False

        try:
            self.tray_icon = QSystemTrayIcon(self)
            self._apply_tray_icon(main_window)

            tray_menu = self._build_tray_menu()
            self.tray_icon.setContextMenu(tray_menu)
            self.tray_icon.setToolTip(self._tray_tooltip())
            self.tray_icon.activated.connect(self._on_tray_activated)
            self.tray_icon.show()

            logging.info(" 系统托盘已设置，可作为热键的备用控制方式")
            return True
        except Exception as e:
            logging.error(f"设置系统托盘失败: {e}")
            return False

    def _apply_tray_icon(self, main_window) -> None:
        try:
            icon_path = get_resource_path("icon.ico")
            if os.path.exists(icon_path):
                self.tray_icon.setIcon(QIcon(icon_path))
                logging.info(f" 系统托盘图标已设置: {icon_path}")
                return

            icon = main_window.windowIcon()
            if icon.isNull():
                app = QApplication.instance()
                if app:
                    icon = app.style().standardIcon(app.style().StandardPixmap.SP_ComputerIcon)
            self.tray_icon.setIcon(icon)
            logging.warning(f" 指定的图标文件不存在: {icon_path}，使用默认图标")
        except Exception as e:
            logging.warning(f"设置托盘图标时出错: {e}，使用默认图标")
            try:
                pixmap = QPixmap(16, 16)
                pixmap.fill(Qt.GlobalColor.blue)
                self.tray_icon.setIcon(QIcon(pixmap))
            except Exception as icon_error:
                logging.error(f"创建默认图标失败: {icon_error}")

    def _build_tray_menu(self) -> QMenu:
        from ui.system_parts.menu_style import apply_unified_menu_style

        tray_menu = apply_unified_menu_style(QMenu(), frameless=True)

        show_action = QAction("显示主窗口", self)
        show_action.triggered.connect(self.show_window_requested.emit)
        tray_menu.addAction(show_action)

        tray_menu.addSeparator()

        start_action = QAction(self._start_action_text(), self)
        start_action.triggered.connect(self._on_start_requested)
        tray_menu.addAction(start_action)
        self._tray_start_action = start_action

        stop_action = QAction(self._stop_action_text(), self)
        stop_action.triggered.connect(self._on_stop_requested)
        tray_menu.addAction(stop_action)
        self._tray_stop_action = stop_action

        tray_menu.addSeparator()

        reset_close_action = QAction("清除关闭记住选择", self)
        reset_close_action.triggered.connect(self._on_reset_close_choice)
        tray_menu.addAction(reset_close_action)

        tray_menu.addSeparator()

        quit_action = QAction("退出程序", self)
        app = QApplication.instance()
        if app:
            quit_action.triggered.connect(app.quit)
        tray_menu.addAction(quit_action)
        return tray_menu

    def _on_tray_activated(self, reason):
        """托盘图标激活处理"""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_window_requested.emit()

    def _on_start_requested(self):
        logging.info(" 系统托盘请求启动任务")
        self.start_requested.emit()

    def _on_stop_requested(self):
        logging.info(" 系统托盘请求停止任务")
        self.stop_requested.emit()

    def _on_reset_close_choice(self):
        """清除关闭记住选择"""
        try:
            if self.main_window is not None and hasattr(self.main_window, "config"):
                self.main_window.config["close_behavior"] = "ask"
                self.main_window.config["close_behavior_remember"] = False
                if hasattr(self.main_window, "save_config_func") and callable(self.main_window.save_config_func):
                    self.main_window.save_config_func(self.main_window.config)
            try:
                from utils.instance_runtime import create_app_settings

                settings = create_app_settings()
                settings.setValue("close_behavior", "ask")
                settings.setValue("close_behavior_remember", False)
            except Exception:
                pass
            if self.tray_icon:
                self.tray_icon.showMessage("设置已重置", "已清除关闭记住选择", QSystemTrayIcon.MessageIcon.Information, 2000)
        except Exception as exc:
            logging.error(f"清除关闭记住选择失败: {exc}")

    def _hotkey_display(self, hotkey_type: str) -> str:
        from app_core.config_sections import DEFAULT_HOTKEYS
        from app_core.hotkey_spec import display_hotkey

        field = "start_task_hotkey" if hotkey_type == "start" else "stop_task_hotkey"
        main_window = self.main_window
        getter = getattr(main_window, "_get_hotkey_value", None)
        if callable(getter):
            return display_hotkey(getter(hotkey_type))
        config = getattr(main_window, "config", None)
        raw = config.get(field) if isinstance(config, dict) else None
        return display_hotkey(raw or DEFAULT_HOTKEYS[field])

    def _start_action_text(self) -> str:
        return f"启动任务 ({self._hotkey_display('start')})"

    def _stop_action_text(self) -> str:
        return f"停止任务 ({self._hotkey_display('stop')})"

    def refresh_hotkey_labels(self):
        try:
            start_action = self._tray_start_action
            if start_action is not None:
                start_action.setText(self._start_action_text())
            stop_action = self._tray_stop_action
            if stop_action is not None:
                stop_action.setText(self._stop_action_text())
        except RuntimeError:
            self._tray_start_action = None
            self._tray_stop_action = None

    def _tray_app_name(self):
        try:
            from utils.instance_runtime import get_instance_display_name

            return get_instance_display_name(_DEFAULT_APP_DISPLAY_NAME)
        except Exception:
            return _DEFAULT_APP_DISPLAY_NAME

    def _tray_tooltip(self, status=None):
        if status:
            return f"{self._tray_app_name()}\n状态: {status}\n右键查看菜单"
        return f"{self._tray_app_name()}\n右键查看菜单"

    def update_tooltip(self, status):
        """更新托盘提示文本"""
        if self.tray_icon:
            self.tray_icon.setToolTip(self._tray_tooltip(status))

    def show_message(self, title, message, icon=QSystemTrayIcon.MessageIcon.Information):
        """显示托盘通知"""
        if self.tray_icon:
            self.tray_icon.showMessage(title, message, icon, 3000)

    def cleanup(self):
        """清理系统托盘资源和信号连接"""
        try:
            if self._task_state_signal is not None and self._task_state_slot is not None:
                try:
                    self._task_state_signal.disconnect(self._task_state_slot)
                except (TypeError, RuntimeError):
                    pass
                finally:
                    self._task_state_signal = None
                    self._task_state_slot = None
            self._tray_start_action = None
            self._tray_stop_action = None
            if self.tray_icon:
                self.tray_icon.hide()
                for signal in (self.start_requested, self.stop_requested, self.show_window_requested):
                    try:
                        signal.disconnect()
                    except (TypeError, RuntimeError):
                        pass
                self.tray_icon.deleteLater()
                self.tray_icon = None
                logging.info("系统托盘已清理")
        except Exception as e:
            logging.error(f"清理系统托盘时出错: {e}")
