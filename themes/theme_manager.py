# -*- coding: utf-8 -*-
"""
主题管理器 - 负责加载和切换应用主题
支持亮色和深色模式切换，支持跟随系统主题自动切换
"""

from pathlib import Path
from utils.app_paths import get_app_root
from typing import Optional, Dict, Callable
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QColor
from PySide6.QtCore import QObject, Signal, QTimer, Qt
import json
import logging
import sys
import platform

logger = logging.getLogger(__name__)


def detect_system_theme() -> str:
    """
    检测系统主题模式
    返回 'dark' 或 'light'
    """
    system = platform.system()

    if system == "Windows":
        try:
            import winreg
            registry = winreg.ConnectRegistry(None, winreg.HKEY_CURRENT_USER)
            key = winreg.OpenKey(
                registry,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            )
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            winreg.CloseKey(key)
            return 'light' if value == 1 else 'dark'
        except FileNotFoundError:
            logger.debug("未找到Windows主题注册表项，回退到亮色主题")
            return 'light'
        except OSError as e:
            if getattr(e, 'winerror', None) == 2:
                logger.debug("无法访问Windows主题注册表项，回退到亮色主题")
                return 'light'
            logger.warning(f"无法检测Windows系统主题: {e}")
            return 'light'
        except Exception as e:
            logger.warning(f"无法检测Windows系统主题: {e}")
            return 'light'

    elif system == "Darwin":  # macOS
        try:
            import subprocess
            result = subprocess.run(
                ['defaults', 'read', '-g', 'AppleInterfaceStyle'],
                capture_output=True,
                text=True
            )
            return 'dark' if 'Dark' in result.stdout else 'light'
        except Exception as e:
            logger.warning(f"无法检测macOS系统主题: {e}")
            return 'light'

    elif system == "Linux":
        try:
            import subprocess
            # 尝试检测GNOME主题
            result = subprocess.run(
                ['gsettings', 'get', 'org.gnome.desktop.interface', 'gtk-theme'],
                capture_output=True,
                text=True
            )
            theme = result.stdout.strip().lower()
            return 'dark' if 'dark' in theme else 'light'
        except Exception as e:
            logger.warning(f"无法检测Linux系统主题: {e}")
            return 'light'

    return 'light'


class ThemeWatcher(QObject):
    """系统主题监视器 - 监听系统主题变化"""

    theme_changed = Signal(str)  # 主题变化信号
    ACTIVE_CHECK_INTERVAL_MS = 5000
    INACTIVE_CHECK_INTERVAL_MS = 30000

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_system_theme = detect_system_theme()
        self._app = QApplication.instance()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setTimerType(Qt.TimerType.VeryCoarseTimer)
        self.timer.timeout.connect(self._check_theme)
        if self._app is not None:
            self._app.applicationStateChanged.connect(self._on_application_state_changed)
        self._schedule_next_check(force=True)

    def _get_check_interval(self) -> int:
        if self._app is None:
            return self.ACTIVE_CHECK_INTERVAL_MS

        app_state = self._app.applicationState()
        if app_state == Qt.ApplicationState.ApplicationActive:
            return self.ACTIVE_CHECK_INTERVAL_MS
        return self.INACTIVE_CHECK_INTERVAL_MS

    def _schedule_next_check(self, force: bool = False):
        interval = self._get_check_interval()
        if force or not self.timer.isActive() or self.timer.interval() != interval:
            self.timer.start(interval)

    def _check_theme(self):
        """检查系统主题是否变化"""
        new_theme = detect_system_theme()
        if new_theme != self.current_system_theme:
            logger.info(f"检测到系统主题变化: {self.current_system_theme} -> {new_theme}")
            self.current_system_theme = new_theme
            self.theme_changed.emit(new_theme)
        self._schedule_next_check(force=True)

    def _on_application_state_changed(self, state):
        if state == Qt.ApplicationState.ApplicationActive:
            self._check_theme()
            return
        self._schedule_next_check(force=True)

    def stop(self):
        """停止监视"""
        self.timer.stop()
        if self._app is not None:
            try:
                self._app.applicationStateChanged.disconnect(self._on_application_state_changed)
            except (RuntimeError, TypeError):
                pass


class ThemeManager:
    """主题管理器 - 负责加载和切换应用主题"""

    THEMES = {
        'light': '亮色主题',
        'dark': '深色主题',
        'auto': '跟随系统',
    }

    # 尺寸配置
    SIZES = {
        'preview_max_width': 350,
        'preview_max_height': 200,
        'dict_list_max_height': 100,
        'slider_width': 100,
        'color_input_width': 90,
        'tolerance_label_width': 35,
    }

    # 主题颜色映射
    THEME_COLORS = {
        'light': {
            'background': '#ffffff',
            'surface': '#f5f5f5',
            'canvas': '#fafafa',
            'card': '#ffffff',
            'card_title': '#f0f0f0',
            'text': '#333333',
            'text_secondary': '#666666',
            'text_disabled': '#999999',
            'border': '#e0e0e0',
            'border_light': '#eeeeee',
            'accent': '#0078d4',
            'accent_hover': '#1084d8',
            'accent_pressed': '#006cbe',
            'success': '#107c10',
            'warning': '#ff8c00',
            'error': '#e81123',
            'info': '#0078d4',
            'hover': '#e8e8e8',
            'pressed': '#d8d8d8',
            'selected': '#0078d4',
            'focus': '#0078d4',
            'combo_popup_border': '#707070',
            # UI颜色（颜色选择器等）
            'picker_target_border': '#00ff00',  # 目标窗口边框：绿色
            'picker_search_border': '#ffff00',  # 搜索区域边框：黄色
            'picker_search_bg': '#ffff00',      # 搜索区域背景：黄色
            'picker_crosshair_outer': '#ffffff',  # 十字光标外边框：白色
            'picker_crosshair_inner': '#ff0000',  # 十字光标内部：红色
            'picker_text': '#ffffff',           # UI文本：白色
            'picker_text_bg': '#000000',        # 文本背景：黑色
        },
        'dark': {
            'background': '#1e1e1e',
            'surface': '#2d2d2d',
            'canvas': '#252525',
            'card': '#2d2d2d',
            'card_title': '#3a3a3a',
            'text': '#e0e0e0',
            'text_secondary': '#b0b0b0',
            'text_disabled': '#666666',
            'border': '#3e3e3e',
            'border_light': '#4e4e4e',
            'accent': '#0078d4',
            'accent_hover': '#1084d8',
            'accent_pressed': '#006cbe',
            'success': '#107c10',
            'warning': '#ffa500',
            'error': '#f1707b',
            'info': '#60cdff',
            'hover': '#3a3a3a',
            'pressed': '#252525',
            'selected': '#0078d4',
            'focus': '#0078d4',
            'combo_popup_border': '#707070',
            # UI颜色（颜色选择器等）
            'picker_target_border': '#00ff00',  # 目标窗口边框：绿色
            'picker_search_border': '#ffff00',  # 搜索区域边框：黄色
            'picker_search_bg': '#ffff00',      # 搜索区域背景：黄色
            'picker_crosshair_outer': '#ffffff',  # 十字光标外边框：白色
            'picker_crosshair_inner': '#ff0000',  # 十字光标内部：红色
            'picker_text': '#ffffff',           # UI文本：白色
            'picker_text_bg': '#000000',        # 文本背景：黑色
        }
    }

    def __init__(self, config_path: Optional[str] = None):
        self.themes_dir = Path(__file__).parent
        self.config_path = config_path
        self.theme_mode = self._load_preference()  # 'light', 'dark', 或 'auto'
        self.current_theme = self._resolve_theme()  # 实际应用的主题
        self.theme_watcher: Optional[ThemeWatcher] = None
        self.app: Optional[QApplication] = None
        self.theme_change_callbacks: list[Callable] = []  # 主题切换回调列表

    def _load_preference(self) -> str:
        """从配置文件加载主题偏好"""
        if self.config_path and Path(self.config_path).exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    theme = config.get('theme', 'auto')
                    # 兼容旧配置
                    if theme not in self.THEMES:
                        theme = 'auto'
                    return theme
            except Exception as e:
                logger.warning(f"加载主题偏好失败: {e}")
        return 'auto'

    def _resolve_theme(self) -> str:
        """解析实际应用的主题（处理auto模式）"""
        if self.theme_mode == 'auto':
            return detect_system_theme()
        return self.theme_mode

    def _save_preference(self, theme: str):
        """保存主题偏好到配置文件"""
        if not self.config_path:
            return
        try:
            config = {}
            if Path(self.config_path).exists():
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)

            config['theme'] = theme

            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4, ensure_ascii=False)

            logger.info(f"已保存主题偏好: {theme}")
        except Exception as e:
            logger.error(f"保存主题偏好失败: {e}")

    def load_stylesheet(self, theme_name: str) -> str:
        """加载主题样式表"""
        qss_file = self.themes_dir / f"{theme_name}.qss"
        if not qss_file.exists():
            # 打包后常见：主题文件位于程序根目录/themes 或当前工作目录/themes
            candidate_dirs = [
                Path(get_app_root()) / "themes",
                Path.cwd() / "themes",
            ]
            for base in candidate_dirs:
                candidate = base / f"{theme_name}.qss"
                if candidate.exists():
                    qss_file = candidate
                    break
            else:
                logger.warning(f"主题文件不存在: {qss_file}")
                logger.warning(f"已尝试路径: {[str(p / f'{theme_name}.qss') for p in candidate_dirs]}")
                return ""

        try:
            with open(qss_file, 'r', encoding='utf-8') as f:
                stylesheet = f.read()
            logger.info(f"成功加载主题样式表: {theme_name}")
            return stylesheet
        except Exception as e:
            logger.error(f"加载主题样式表失败: {e}")
            return ""

    def apply_theme(self, app: QApplication, theme_mode: str):
        """
        应用主题到应用程序

        Args:
            app: QApplication实例
            theme_mode: 主题模式 ('light', 'dark', 或 'auto')
        """
        if theme_mode not in self.THEMES:
            logger.warning(f"未知主题模式: {theme_mode}，使用自动模式")
            theme_mode = 'auto'

        self.app = app
        self.theme_mode = theme_mode

        # 解析实际主题
        actual_theme = self._resolve_theme()

        # 先强制使用 Fusion，避免原生样式导致QSS显示异常
        try:
            app.setStyle('Fusion')
        except Exception:
            pass

        # 加载QSS样式表
        stylesheet = self.load_stylesheet(actual_theme)
        if stylesheet:
            app.setStyleSheet(stylesheet)

        self.current_theme = actual_theme

        # 保存偏好
        self._save_preference(theme_mode)

        # 启动或停止主题监视器
        if theme_mode == 'auto':
            self._start_theme_watcher()
        else:
            self._stop_theme_watcher()

        logger.info(f"已应用主题模式: {self.THEMES[theme_mode]} (实际主题: {actual_theme})")

        # 通知所有回调函数
        self._notify_theme_change_callbacks()

    def _start_theme_watcher(self):
        """启动系统主题监视器"""
        if self.theme_watcher is None and self.app is not None:
            self.theme_watcher = ThemeWatcher()
            self.theme_watcher.theme_changed.connect(self._on_system_theme_changed)
            logger.info("已启动系统主题监视器")

    def _stop_theme_watcher(self):
        """停止系统主题监视器"""
        if self.theme_watcher is not None:
            self.theme_watcher.stop()
            self.theme_watcher.deleteLater()
            self.theme_watcher = None
            logger.info("已停止系统主题监视器")

    def _on_system_theme_changed(self, new_theme: str):
        """系统主题变化回调"""
        if self.theme_mode == 'auto' and self.app is not None:
            logger.info(f"系统主题已变化，自动切换到: {new_theme}")
            self.current_theme = new_theme
            stylesheet = self.load_stylesheet(new_theme)
            if stylesheet:
                try:
                    self.app.setStyle('Fusion')
                except Exception:
                    pass
                self.app.setStyleSheet(stylesheet)

            # 通知所有回调函数
            self._notify_theme_change_callbacks()

    def toggle_theme(self, app: QApplication):
        """切换主题（亮色/深色/自动）"""
        # 循环切换: light -> dark -> auto -> light
        if self.theme_mode == 'light':
            new_mode = 'dark'
        elif self.theme_mode == 'dark':
            new_mode = 'auto'
        else:  # auto
            new_mode = 'light'

        self.apply_theme(app, new_mode)
        return new_mode

    def set_theme_mode(self, app: QApplication, mode: str):
        """
        设置主题模式

        Args:
            app: QApplication实例
            mode: 主题模式 ('light', 'dark', 或 'auto')
        """
        self.apply_theme(app, mode)

    def get_current_theme(self) -> str:
        """获取当前实际应用的主题名称"""
        return self.current_theme

    def get_theme_mode(self) -> str:
        """获取当前主题模式（可能是'auto'）"""
        return self.theme_mode

    def is_dark_mode(self) -> bool:
        """判断当前是否为深色模式"""
        return self.current_theme == 'dark'

    def get_color(self, color_key: str) -> str:
        """获取当前主题的指定颜色"""
        theme_colors = self.THEME_COLORS.get(self.current_theme, self.THEME_COLORS['light'])
        return theme_colors.get(color_key, '#000000')

    def get_qcolor(self, color_key: str) -> QColor:
        """获取当前主题的指定颜色（QColor对象）"""
        color_str = self.get_color(color_key)
        return QColor(color_str)

    def get_size(self, size_key: str) -> int:
        """获取指定尺寸配置"""
        return self.SIZES.get(size_key, 0)

    def register_theme_change_callback(self, callback: Callable):
        """注册主题切换回调函数"""
        if callback not in self.theme_change_callbacks:
            self.theme_change_callbacks.append(callback)
            logger.info(f"已注册主题切换回调: {callback.__name__}")

    def unregister_theme_change_callback(self, callback: Callable):
        """取消注册主题切换回调函数"""
        if callback in self.theme_change_callbacks:
            self.theme_change_callbacks.remove(callback)
            logger.info(f"已取消注册主题切换回调: {callback.__name__}")

    def _notify_theme_change_callbacks(self):
        """通知所有注册的回调函数主题已切换"""
        for callback in self.theme_change_callbacks:
            try:
                callback(self.current_theme)
            except Exception as e:
                logger.error(f"主题切换回调执行失败: {callback.__name__}, 错误: {e}")


# 全局主题管理器实例
_theme_manager: Optional[ThemeManager] = None


def get_theme_manager(config_path: Optional[str] = None) -> ThemeManager:
    """获取主题管理器单例"""
    global _theme_manager
    if _theme_manager is None:
        _theme_manager = ThemeManager(config_path)
    return _theme_manager


def reset_theme_manager():
    """重置主题管理器（用于测试）"""
    global _theme_manager
    _theme_manager = None


# --- 统一的 ComboBox 项目高度 Delegate ---
from PySide6.QtWidgets import QStyledItemDelegate

