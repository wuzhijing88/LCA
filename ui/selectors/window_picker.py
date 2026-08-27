#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
窗口选择器 - 通过鼠标点击选择窗口进行绑定
"""

import logging
from typing import Optional, Tuple
from PySide6.QtWidgets import QWidget, QMessageBox
from PySide6.QtCore import Signal, QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QPainter, QPen, QColor
from ui.system_parts.message_box_translator import place_dialog_on_screen

logger = logging.getLogger(__name__)

# 导入窗口隐藏管理器
from utils.window.hwnd_utils import as_hwnd
from utils.window.window_identity import is_desktop_window
from utils.window.window_hider import WindowHider
from utils.window.window_overlay_utils import (
    apply_overlay_text_style,
    capture_virtual_desktop_pixmap,
    configure_opaque_picker_overlay,
    draw_picker_backdrop,
    get_overlay_debug_snapshot,
    get_window_client_overlay_metrics,
    map_native_rect_to_local,
    prime_picker_backdrop,
    sync_overlay_geometry,
)
from utils.window.window_activation_utils import (
    ensure_overlay_ready_for_input,
    grab_overlay_input,
    release_overlay_input,
)

try:
    import win32gui
    import win32api
    import win32con
    PYWIN32_AVAILABLE = True
except ImportError:
    PYWIN32_AVAILABLE = False
    logger.warning("pywin32 not available, window picker may not work properly")

class WindowPickerOverlay(QWidget):
    """窗口选择器覆盖层 - 跟踪鼠标位置并高亮显示窗口"""

    window_selected = Signal(object, str)  # hwnd, title；object 避免 Qt int32 把 HWND 收成负数

    def __init__(
        self,
        parent=None,
        main_window=None,
        parent_was_visible=True,
        main_window_was_visible=True,
    ):
        super().__init__(None)  # 独立窗口，不设置父窗口避免事件冲突

        # 使用窗口隐藏管理器统一管理窗口隐藏/恢复
        self.window_hider = WindowHider()
        if parent:
            # 明确指定父窗口的原始可见状态（调用方在隐藏前已记录）
            self.window_hider.add_window(parent, "父窗口（参数面板）", was_visible=parent_was_visible)
        if main_window and main_window != parent:
            # 明确指定主窗口的原始可见状态（调用方在隐藏前已记录）
            self.window_hider.add_window(main_window, "主窗口", was_visible=main_window_was_visible)
        logger.info(f"窗口隐藏管理器已初始化，管理 {self.window_hider.get_window_count()} 个窗口")

        # 当前鼠标下的窗口信息
        self.current_window_hwnd = None
        self.current_window_rect = None
        self.current_window_title = ""

        # 锁定的窗口信息（第一次点击后锁定）
        self.locked_window_hwnd = None
        self.locked_window_rect = None
        self.locked_window_title = ""
        self.is_locked = False

        # 窗口激活状态标志
        self._is_ready_for_input = False
        self._activation_attempts = 0

        self.desktop_pixmap = None
        self._highlight_overlay_rect = QRect()
        configure_opaque_picker_overlay(self)

        logger.info("创建窗口选择器覆盖层")

        # 设置全屏覆盖
        self._setup_fullscreen_overlay()
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        self.desktop_pixmap = capture_virtual_desktop_pixmap()
        prime_picker_backdrop(
            self,
            desktop_pixmap=self.desktop_pixmap,
            dim_color=QColor(0, 0, 0, 80) if self.desktop_pixmap is not None else None,
            fill_color=QColor(18, 18, 18),
        )

        # 启动鼠标跟踪定时器
        self.mouse_timer = QTimer(self)
        self.mouse_timer.timeout.connect(self._update_window_under_mouse)
        self.mouse_timer.start(100)  # 每100ms更新一次（降低频率减少闪烁）

    @staticmethod
    def _get_window_text_safe(hwnd: int) -> str:
        try:
            return (win32gui.GetWindowText(hwnd) or "").strip()
        except Exception:
            return ""

    @staticmethod
    def _get_window_class_safe(hwnd: int) -> str:
        try:
            return (win32gui.GetClassName(hwnd) or "").strip()
        except Exception:
            return ""

    def _resolve_display_title(self, hwnd: int, fallback_title: str = "", parent_hwnd: Optional[int] = None) -> str:
        if is_desktop_window(hwnd):
            return self._desktop_display_title(hwnd)
        title = self._get_window_text_safe(hwnd)
        if title:
            return title

        fallback_title = (fallback_title or "").strip()
        class_name = self._get_window_class_safe(hwnd)
        parent_title = self._get_window_text_safe(parent_hwnd) if parent_hwnd else ""

        if fallback_title and class_name:
            return f"{fallback_title} [{class_name}]"
        if fallback_title:
            return fallback_title
        if parent_title and class_name:
            return f"{parent_title} [{class_name}]"
        if parent_title:
            return parent_title
        if class_name:
            return f"窗口 [{class_name}]"
        return ""

    def _resolve_native_target_hwnd(self, hwnd: int, cursor_pos: Tuple[int, int]) -> int:
        original_hwnd = as_hwnd(hwnd)
        hwnd = original_hwnd
        while True:
            parent = as_hwnd(win32gui.GetParent(hwnd))
            if parent == 0:
                break
            hwnd = parent

        if hwnd != original_hwnd:
            try:
                parent_rect = win32gui.GetWindowRect(hwnd)
                if not (
                    parent_rect[0] <= cursor_pos[0] <= parent_rect[2]
                    and parent_rect[1] <= cursor_pos[1] <= parent_rect[3]
                ):
                    hwnd = original_hwnd
            except Exception:
                hwnd = original_hwnd

        return as_hwnd(hwnd)

    def _get_desktop_bind_hwnd(self) -> int:
        """取可绑定的桌面句柄：优先外壳窗口，其次桌面窗口。"""
        if not PYWIN32_AVAILABLE:
            return 0
        try:
            if hasattr(win32gui, "GetShellWindow"):
                shell_hwnd = as_hwnd(win32gui.GetShellWindow())
                if shell_hwnd and win32gui.IsWindow(shell_hwnd):
                    return shell_hwnd
        except Exception:
            pass
        try:
            desktop_hwnd = as_hwnd(win32gui.GetDesktopWindow())
            if desktop_hwnd and win32gui.IsWindow(desktop_hwnd):
                return desktop_hwnd
        except Exception:
            pass
        return 0

    def _desktop_display_title(self, hwnd: int) -> str:
        title = self._get_window_text_safe(hwnd)
        if title:
            return title
        return "桌面"

    def _set_current_desktop_target(self, hwnd: int) -> None:
        hwnd = as_hwnd(hwnd)
        title = self._desktop_display_title(hwnd)
        if hwnd == self.current_window_hwnd and self.current_window_title == title:
            return
        self.current_window_hwnd = hwnd
        self.current_window_title = title
        self.current_window_rect = self._resolve_window_client_native_rect(hwnd)
        self.update()

    def _quick_validate_window(self, hwnd: int, title: str) -> bool:
        """
        快速验证窗口是否适合锁定（不包括耗时的遮挡检测）

        Args:
            hwnd: 窗口句柄
            title: 窗口标题

        Returns:
            True表示可以锁定，False表示不能锁定
        """
        if not PYWIN32_AVAILABLE:
            return True  # 如果没有win32，无法检查，默认允许

        try:
            if is_desktop_window(hwnd):
                return True

            # 快速检查1：窗口是否仍然存在
            if not win32gui.IsWindow(hwnd):
                self._show_binding_error("窗口已关闭", f"窗口 '{title}' 已经不存在，无法选择。")
                logger.warning(f"窗口快速验证失败: 窗口 {hwnd} 已不存在")
                return False

            # 快速检查2：窗口是否可见
            if not win32gui.IsWindowVisible(hwnd):
                self._show_binding_error("窗口不可见", f"窗口 '{title}' 当前不可见（可能被隐藏），无法选择。\n\n请确保窗口可见后再次尝试。")
                logger.warning(f"窗口快速验证失败: 窗口 {hwnd} 不可见")
                return False

            # 快速检查3：窗口是否被最小化
            if win32gui.IsIconic(hwnd):
                self._show_binding_error("窗口已最小化", f"窗口 '{title}' 当前已最小化，无法选择。\n\n请先恢复窗口后再次尝试。")
                logger.warning(f"窗口快速验证失败: 窗口 {hwnd} 已最小化")
                return False

            # 快速检查4：窗口尺寸和屏幕位置
            try:
                rect = win32gui.GetWindowRect(hwnd)
                window_width = rect[2] - rect[0]
                window_height = rect[3] - rect[1]

                if window_width <= 0 or window_height <= 0:
                    self._show_binding_error("窗口尺寸无效", f"窗口 '{title}' 的尺寸无效（{window_width}x{window_height}），无法选择。")
                    logger.warning(f"窗口快速验证失败: 窗口 {hwnd} 尺寸无效")
                    return False

                if window_width < 50 or window_height < 50:
                    self._show_binding_error("窗口太小", f"窗口 '{title}' 太小（{window_width}x{window_height}），可能不是有效的应用窗口。")
                    logger.warning(f"窗口快速验证失败: 窗口 {hwnd} 太小")
                    return False

                # 检查是否在屏幕范围内
                try:
                    monitors = win32api.EnumDisplayMonitors()
                    on_screen = False

                    for monitor in monitors:
                        monitor_info = win32api.GetMonitorInfo(monitor[0])
                        monitor_rect = monitor_info['Monitor']

                        if not (rect[2] < monitor_rect[0] or rect[0] > monitor_rect[2] or
                                rect[3] < monitor_rect[1] or rect[1] > monitor_rect[3]):
                            on_screen = True
                            break

                    if not on_screen:
                        self._show_binding_error("窗口在屏幕外", f"窗口 '{title}' 当前不在任何屏幕的可见范围内，无法选择。")
                        logger.warning(f"窗口快速验证失败: 窗口 {hwnd} 在屏幕外")
                        return False
                except Exception as e:
                    logger.debug(f"快速检查屏幕边界失败: {e}")

            except Exception as e:
                logger.warning(f"快速检查窗口尺寸失败: {e}")

            # 所有快速检查通过
            logger.info(f"窗口快速验证通过: HWND={hwnd}, 标题='{title}'")
            return True

        except Exception as e:
            logger.error(f"窗口快速验证过程出错: {e}", exc_info=True)
            # 出错时默认允许，避免误拦截
            return True

    def _validate_window_for_binding(self, hwnd: int, title: str) -> bool:
        """
        验证窗口是否适合绑定

        Args:
            hwnd: 窗口句柄
            title: 窗口标题

        Returns:
            True表示可以绑定，False表示不能绑定
        """
        if not PYWIN32_AVAILABLE:
            return True  # 如果没有win32，无法检查，默认允许

        try:
            if is_desktop_window(hwnd):
                return True

            # 检查1：窗口是否仍然存在
            if not win32gui.IsWindow(hwnd):
                self._show_binding_error("窗口已关闭", f"窗口 '{title}' 已经不存在，无法绑定。")
                logger.warning(f"窗口验证失败: 窗口 {hwnd} 已不存在")
                return False

            # 检查2：窗口是否可见
            if not win32gui.IsWindowVisible(hwnd):
                self._show_binding_error("窗口不可见", f"窗口 '{title}' 当前不可见（可能被隐藏），无法绑定。\n\n请确保窗口可见后再次尝试。")
                logger.warning(f"窗口验证失败: 窗口 {hwnd} 不可见")
                return False

            # 检查3：窗口是否被最小化
            if win32gui.IsIconic(hwnd):
                self._show_binding_error("窗口已最小化", f"窗口 '{title}' 当前已最小化，无法绑定。\n\n请先恢复窗口后再次尝试。")
                logger.warning(f"窗口验证失败: 窗口 {hwnd} 已最小化")
                return False

            # 检查4：窗口尺寸是否有效
            try:
                rect = win32gui.GetWindowRect(hwnd)
                window_width = rect[2] - rect[0]
                window_height = rect[3] - rect[1]

                if window_width <= 0 or window_height <= 0:
                    self._show_binding_error("窗口尺寸无效", f"窗口 '{title}' 的尺寸无效（{window_width}x{window_height}），无法绑定。")
                    logger.warning(f"窗口验证失败: 窗口 {hwnd} 尺寸无效 {window_width}x{window_height}")
                    return False

                # 检查窗口是否太小（至少50x50像素）
                if window_width < 50 or window_height < 50:
                    self._show_binding_error("窗口太小", f"窗口 '{title}' 太小（{window_width}x{window_height}），可能不是有效的应用窗口。\n\n请选择一个更大的窗口。")
                    logger.warning(f"窗口验证失败: 窗口 {hwnd} 太小 {window_width}x{window_height}")
                    return False

                # 检查窗口是否在屏幕范围内
                try:
                    monitors = win32api.EnumDisplayMonitors()
                    on_screen = False

                    for monitor in monitors:
                        monitor_info = win32api.GetMonitorInfo(monitor[0])
                        monitor_rect = monitor_info['Monitor']

                        # 检查窗口是否与显示器有交集
                        if not (rect[2] < monitor_rect[0] or rect[0] > monitor_rect[2] or
                                rect[3] < monitor_rect[1] or rect[1] > monitor_rect[3]):
                            on_screen = True
                            break

                    if not on_screen:
                        self._show_binding_error("窗口在屏幕外", f"窗口 '{title}' 当前不在任何屏幕的可见范围内，无法绑定。\n\n窗口位置: ({rect[0]}, {rect[1]}, {rect[2]}, {rect[3]})\n\n请将窗口移动到屏幕内后再次尝试。")
                        logger.warning(f"窗口验证失败: 窗口 {hwnd} 在屏幕外 {rect}")
                        return False
                except Exception as e:
                    logger.debug(f"检查屏幕边界失败: {e}")

            except Exception as e:
                logger.warning(f"获取窗口尺寸失败: {e}")

            # 所有检查通过
            logger.info(f"窗口验证通过: HWND={hwnd}, 标题='{title}'")
            return True

        except Exception as e:
            logger.error(f"窗口验证过程出错: {e}", exc_info=True)
            # 出错时默认允许绑定，避免误拦截
            return True

    def _show_binding_error(self, title: str, message: str):
        """
        显示绑定错误消息框

        Args:
            title: 错误标题
            message: 错误消息
        """
        try:
            # 创建独立的消息框（不继承父窗口样式）
            msg_box = QMessageBox(self.parentWidget())
            msg_box.setIcon(QMessageBox.Icon.Warning)
            msg_box.setWindowTitle(f"窗口绑定失败 - {title}")
            msg_box.setText(message)
            msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)

            # 设置窗口标志（保留正常边框和样式）
            msg_box.setWindowFlags(
                Qt.WindowType.Dialog |
                Qt.WindowType.WindowStaysOnTopHint
            )

            from themes import theme_color

            text = theme_color("text", "#333333")
            accent = theme_color("accent", "#0078d4")
            accent_hover = theme_color("accent_hover", "#1084d8")
            accent_pressed = theme_color("accent_pressed", "#006cbe")
            msg_box.setStyleSheet(f"""
                QMessageBox QLabel {{
                    color: {text};
                    font-size: 10pt;
                    padding: 10px;
                }}
                QPushButton {{
                    background-color: {accent};
                    color: white;
                    border: none;
                    padding: 8px 20px;
                    font-size: 10pt;
                    min-width: 80px;
                }}
                QPushButton:hover {{
                    background-color: {accent_hover};
                }}
                QPushButton:pressed {{
                    background-color: {accent_pressed};
                }}
            """)

            # 显示消息框
            place_dialog_on_screen(msg_box, reference_widget=self.parentWidget())
            msg_box.exec()

        except Exception as e:
            logger.error(f"显示错误消息框失败: {e}")

    def _setup_fullscreen_overlay(self):
        """设置全屏覆盖层"""
        screen_geometry = sync_overlay_geometry(self)

        logger.info(f"全屏覆盖层设置: {screen_geometry}")

    def _native_rect_to_overlay_rect(self, rect: Tuple[int, int, int, int]) -> Optional[QRect]:
        """物理屏幕矩形 -> 覆盖层本地 Qt 矩形"""
        if not rect or len(rect) != 4:
            return None
        return map_native_rect_to_local(self, rect)

    def _resolve_window_client_native_rect(self, hwnd: int) -> Optional[Tuple[int, int, int, int]]:
        """统一返回窗口客户区的物理屏幕矩形。"""
        try:
            metrics = get_window_client_overlay_metrics(hwnd)
            native_rect = metrics.get("native_rect") if metrics else None
            if native_rect and len(native_rect) == 4:
                left, top, right, bottom = [int(value) for value in native_rect]
                if right > left and bottom > top:
                    return left, top, right, bottom
        except Exception as e:
            logger.warning(f"获取窗口标准化客户区失败: {e}")
        try:
            left, top, right, bottom = [int(value) for value in win32gui.GetWindowRect(hwnd)]
            if right > left and bottom > top:
                return left, top, right, bottom
        except Exception:
            pass
        return None

    def _update_window_under_mouse(self):
        """更新鼠标下的窗口"""
        if getattr(self, "_closing", False):
            return
        if not PYWIN32_AVAILABLE:
            return

        # 如果已经锁定窗口，停止跟踪鼠标
        if self.is_locked:
            return

        try:
            # 获取鼠标位置
            cursor_pos = win32api.GetCursorPos()

            # 获取覆盖层自己的窗口句柄
            overlay_hwnd = int(self.winId())

            # 枚举所有顶层窗口，找到鼠标位置下的窗口（排除覆盖层）
            # 这个方法比临时隐藏覆盖层更可靠
            candidate_windows = []

            def enum_windows_callback(enum_hwnd, param):
                try:
                    # 跳过覆盖层自己
                    if enum_hwnd == overlay_hwnd:
                        return True

                    # 只处理可见窗口
                    if not win32gui.IsWindowVisible(enum_hwnd):
                        return True

                    # 排除最小化的窗口
                    if win32gui.IsIconic(enum_hwnd):
                        return True

                    # 获取窗口位置
                    try:
                        rect = win32gui.GetWindowRect(enum_hwnd)
                    except Exception:
                        return True

                    # 检查窗口尺寸是否有效（排除0尺寸窗口）
                    window_width = rect[2] - rect[0]
                    window_height = rect[3] - rect[1]
                    if window_width <= 0 or window_height <= 0:
                        return True

                    # 检查窗口是否在屏幕范围内（排除屏幕外的窗口）
                    try:
                        monitors = win32api.EnumDisplayMonitors()
                        on_screen = False

                        for monitor in monitors:
                            monitor_info = win32api.GetMonitorInfo(monitor[0])
                            monitor_rect = monitor_info['Monitor']

                            # 检查窗口是否与显示器有交集
                            if not (rect[2] < monitor_rect[0] or rect[0] > monitor_rect[2] or
                                    rect[3] < monitor_rect[1] or rect[1] > monitor_rect[3]):
                                on_screen = True
                                break

                        if not on_screen:
                            return True
                    except Exception:
                        # 如果检查失败，假设窗口在屏幕上
                        pass

                    # 检查窗口样式，排除不应该绑定的窗口类型
                    try:
                        window_style = win32gui.GetWindowLong(enum_hwnd, win32con.GWL_STYLE)
                        ex_style = win32gui.GetWindowLong(enum_hwnd, win32con.GWL_EXSTYLE)

                        # 排除工具窗口（如任务栏、托盘等）
                        if ex_style & win32con.WS_EX_TOOLWINDOW:
                            return True

                        # 排除透明/分层窗口（可能是特效窗口）
                        if ex_style & win32con.WS_EX_LAYERED and ex_style & win32con.WS_EX_TRANSPARENT:
                            return True
                    except Exception:
                        # 如果检查失败，继续处理
                        pass

                    # 排除特殊系统窗口类
                    try:
                        class_name = win32gui.GetClassName(enum_hwnd)

                        # 排除的窗口类列表
                        excluded_classes = [
                            'Shell_TrayWnd',     # 任务栏
                            'DV2ControlHost',    # Windows Defender 控制
                            'Windows.UI.Core.CoreWindow',  # Windows 10/11 系统UI
                            'ApplicationFrameWindow',      # UWP应用框架（通常需要子窗口）
                            'ImmersiveLauncher', # 开始菜单
                        ]

                        if class_name in excluded_classes:
                            return True

                        # 排除 Windows 输入体验（IME相关）
                        if 'TextInput' in class_name or 'InputMethod' in class_name:
                            return True

                    except Exception:
                        # 如果检查失败，继续处理
                        pass

                    # 检查鼠标是否在窗口内
                    if (rect[0] <= cursor_pos[0] <= rect[2] and
                        rect[1] <= cursor_pos[1] <= rect[3]):
                        # 获取窗口标题
                        try:
                            title = win32gui.GetWindowText(enum_hwnd)
                        except Exception:
                            title = ""

                        # 计算窗口面积
                        area = window_width * window_height

                        # 添加到候选列表
                        param.append({
                            'hwnd': as_hwnd(enum_hwnd),
                            'rect': rect,
                            'title': title,
                            'area': area
                        })
                except Exception:
                    pass
                return True

            win32gui.EnumWindows(enum_windows_callback, candidate_windows)

            if not candidate_windows:
                desktop_hwnd = self._get_desktop_bind_hwnd()
                if desktop_hwnd:
                    self._set_current_desktop_target(desktop_hwnd)
                elif self.current_window_hwnd:
                    self.current_window_hwnd = None
                    self.current_window_rect = None
                    self.current_window_title = ""
                    self.update()
                return

            # 选择最合适的窗口
            # 策略：优先选择面积较小的（更具体的），但要排除明显的子控件
            # 同时要考虑窗口层级关系

            # 首先过滤掉太小的窗口
            valid_candidates = [w for w in candidate_windows if w['area'] >= 40000]  # 至少 200x200

            if not valid_candidates:
                # 如果没有足够大的窗口，降低标准
                valid_candidates = [w for w in candidate_windows if w['area'] >= 10000]  # 至少 100x100

            if not valid_candidates:
                # 还是没有，使用所有候选
                valid_candidates = candidate_windows

            if not valid_candidates:
                return

            # 按面积排序，优先选择较小的（通常在上层）
            valid_candidates.sort(key=lambda w: w['area'])

            # 从最小面积开始，找第一个有标题或者足够大的窗口
            selected = None
            for candidate in valid_candidates:
                # 如果有标题，优先选择
                if candidate['title'] and len(candidate['title'].strip()) > 0:
                    selected = candidate
                    break
                # 或者面积足够大
                elif candidate['area'] >= 100000:  # 约 316x316
                    selected = candidate
                    break

            # 如果没找到合适的，用第一个
            if not selected:
                selected = valid_candidates[0]

            hwnd = as_hwnd(selected['hwnd'])

            # 增加窗口切换的稳定性：如果当前窗口仍然有效且在候选列表中，优先保持不变
            # 这可以避免在重叠窗口之间频繁切换导致的闪烁
            if self.current_window_hwnd:
                current_still_valid = any(w['hwnd'] == self.current_window_hwnd for w in valid_candidates)
                if current_still_valid:
                    # 当前窗口仍然有效，检查新选择的窗口是否明显更好
                    current_candidate = next((w for w in valid_candidates if w['hwnd'] == self.current_window_hwnd), None)
                    if current_candidate:
                        # 只有当新窗口面积明显更小（至少小20%）或者有标题而当前窗口没有标题时才切换
                        should_switch = False
                        if selected['title'] and not current_candidate['title']:
                            should_switch = True  # 新窗口有标题，旧窗口没有，切换
                        elif selected['area'] < current_candidate['area'] * 0.8:
                            should_switch = True  # 新窗口明显更小，切换

                        if not should_switch:
                            hwnd = self.current_window_hwnd
                            logger.debug(f"保持当前窗口: HWND={hwnd}")
                        else:
                            logger.debug(f"切换到新窗口: HWND={hwnd}, 标题='{selected['title']}', 面积={selected['area']}")
                    else:
                        logger.debug(f"选择窗口: HWND={hwnd}, 标题='{selected['title']}', 面积={selected['area']}")
                else:
                    logger.debug(f"选择窗口: HWND={hwnd}, 标题='{selected['title']}', 面积={selected['area']}")
            else:
                logger.debug(f"选择窗口: HWND={hwnd}, 标题='{selected['title']}', 面积={selected['area']}")

            title = selected['title']
            title_parent_hwnd = None
            hwnd = self._resolve_native_target_hwnd(hwnd, cursor_pos)

            # 如果窗口变化了，更新显示
            if hwnd != self.current_window_hwnd:
                self.current_window_hwnd = hwnd
                self.current_window_title = self._resolve_display_title(
                    hwnd,
                    fallback_title=title,
                    parent_hwnd=title_parent_hwnd,
                )

                self.current_window_rect = self._resolve_window_client_native_rect(hwnd)
                overlay_rect = QRect()
                try:
                    overlay_rect = self._native_rect_to_overlay_rect(self.current_window_rect) if self.current_window_rect else QRect()
                    snapshot = get_overlay_debug_snapshot(self, self.current_window_rect)
                    logger.info(
                        "窗口选择器映射诊断: "
                        f"hwnd={self.current_window_hwnd}, title='{self.current_window_title}', "
                        f"native_rect={self.current_window_rect}, "
                        f"overlay_rect=({overlay_rect.x()}, {overlay_rect.y()}, {overlay_rect.width()}, {overlay_rect.height()}), "
                        f"coord_mode={snapshot.get('coord_mode')}, "
                        f"widget_qt_geometry={snapshot.get('widget_qt_geometry')}, "
                        f"widget_native_rect={snapshot.get('widget_native_rect')}, "
                        f"widget_global_bottom_right={snapshot.get('widget_global_bottom_right')}"
                    )
                except Exception as e:
                    logger.warning(f"记录窗口选择器映射诊断失败: {e}")

                old_rect = QRect(self._highlight_overlay_rect)
                self._highlight_overlay_rect = QRect(overlay_rect) if overlay_rect else QRect()
                dirty = old_rect.united(self._highlight_overlay_rect)
                if dirty.isEmpty():
                    self.update()
                else:
                    dirty.adjust(-12, -40, 12, 12)
                    self.update(dirty.intersected(self.rect()))

        except Exception as e:
            logger.debug(f"更新鼠标下窗口失败: {e}")

    def paintEvent(self, event):
        """绘制事件 - 绘制绿色边框"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)

        draw_picker_backdrop(
            painter,
            self,
            desktop_pixmap=self.desktop_pixmap,
            dim_color=QColor(0, 0, 0, 80) if self.desktop_pixmap is not None else None,
            fill_color=QColor(18, 18, 18),
        )

        display_rect = self.locked_window_rect if self.is_locked else self.current_window_rect
        display_title = self.locked_window_title if self.is_locked else self.current_window_title

        if display_rect:
            overlay_rect = self._native_rect_to_overlay_rect(display_rect)
            if overlay_rect and not overlay_rect.isEmpty():
                x = overlay_rect.x()
                y = overlay_rect.y()

                if self.is_locked:
                    painter.setPen(QPen(QColor(255, 255, 0), 6))
                else:
                    painter.setPen(QPen(QColor(0, 255, 0), 4))

                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(overlay_rect)

                if display_title:
                    text = f"已锁定: {display_title}" if self.is_locked else f"窗口: {display_title}"
                    apply_overlay_text_style(painter)
                    metrics = painter.fontMetrics()
                    text_rect = metrics.boundingRect(text)
                    text_bg_rect = text_rect.adjusted(-5, -2, 5, 2)
                    text_bg_rect.moveTopLeft(QPoint(x + 10, y + 10))
                    painter.fillRect(text_bg_rect, QColor(0, 0, 0, 150))
                    painter.drawText(x + 10, y + 25, text)

        painter.fillRect(10, 10, 600, 60, QColor(0, 0, 0, 150))
        apply_overlay_text_style(painter)
        if self.is_locked:
            painter.drawText(20, 30, f"已锁定窗口: {self.locked_window_title}")
            painter.drawText(20, 50, "再次点击确认绑定 | 右键或ESC键取消")
        else:
            painter.drawText(20, 30, "移动鼠标到需要绑定的窗口上")
            painter.drawText(20, 50, "点击锁定窗口 | 右键或ESC键取消")

    def mousePressEvent(self, event):
        """鼠标按下事件"""
        logger.info(f"[鼠标事件] 接收到鼠标按下事件: 按钮={event.button()}, 位置={event.pos()}")

        # 接受事件，防止穿透到下层窗口
        event.accept()

        if event.button() == Qt.MouseButton.LeftButton:
            logger.info(f"[鼠标事件] 左键点击，当前锁定状态: {self.is_locked}")
            if not self.is_locked:
                # 第一次点击：锁定窗口前进行基础验证（快速检查，不包括耗时的遮挡检测）
                if not self.current_window_hwnd:
                    desktop_hwnd = self._get_desktop_bind_hwnd()
                    if desktop_hwnd:
                        self._set_current_desktop_target(desktop_hwnd)
                if self.current_window_hwnd:
                    # 快速验证窗口的基本状态
                    if not self._quick_validate_window(self.current_window_hwnd, self.current_window_title):
                        # 快速验证失败，不锁定窗口
                        logger.warning(f"窗口快速验证失败，无法锁定: {self.current_window_title}")
                        return

                    # 验证通过，锁定窗口
                    self.locked_window_hwnd = self.current_window_hwnd
                    self.locked_window_rect = self.current_window_rect
                    self.locked_window_title = self.current_window_title
                    self.is_locked = True
                    logger.info(f"锁定窗口: {self.locked_window_title} (句柄: {self.locked_window_hwnd})")
                    self.update()
                else:
                    logger.warning("[鼠标事件] 左键点击但没有当前窗口")
            else:
                # 第二次点击：确认绑定前进行最终可见性验证
                logger.info(f"准备确认绑定窗口: {self.locked_window_title} (句柄: {self.locked_window_hwnd})")

                # 最终可见性验证：在确认绑定前检查窗口状态
                if not self._validate_window_for_binding(self.locked_window_hwnd, self.locked_window_title):
                    # 验证失败，取消锁定并返回
                    self.is_locked = False
                    self.locked_window_hwnd = None
                    self.locked_window_rect = None
                    self.locked_window_title = ""
                    self.update()
                    return

                # 验证通过，检查是否为模拟器主窗口，如果是则自动绑定渲染窗口
                final_hwnd = self.locked_window_hwnd
                final_title = self.locked_window_title

                try:
                    logger.debug(f"直接绑定窗口: {self.locked_window_title}")
                except Exception as e:
                    logger.error(f"模拟器渲染窗口检测失败，使用原窗口: {e}", exc_info=True)

                # 发送窗口选择信号
                logger.info(f"窗口验证通过，确认绑定: {final_title} (句柄: {final_hwnd})")
                self.window_selected.emit(as_hwnd(final_hwnd), final_title)
                self.close()
        elif event.button() == Qt.MouseButton.RightButton:
            logger.info(f"[鼠标事件] 右键点击，当前锁定状态: {self.is_locked}")
            if self.is_locked:
                # 如果已锁定，右键取消锁定
                logger.info("右键点击，取消锁定")
                self.is_locked = False
                self.locked_window_hwnd = None
                self.locked_window_rect = None
                self.locked_window_title = ""
                self.update()
            else:
                # 如果未锁定，右键退出
                logger.info("右键点击，取消窗口选择")
                self.close()

    def keyPressEvent(self, event):
        """键盘事件"""
        logger.info(f"[键盘事件] 接收到键盘事件: 键={event.key()}")
        if event.key() == Qt.Key.Key_Escape:
            logger.info("ESC键退出")
            self.close()
        event.accept()

    def showEvent(self, event):
        """窗口显示事件"""
        if getattr(self, "_closing", False):
            event.ignore()
            return
        super().showEvent(event)

        # 临时隐藏父窗口和主窗口，避免焦点冲突和ESC键事件被父窗口捕获
        hidden_count = self.window_hider.hide_all()
        logger.info(f"已隐藏 {hidden_count} 个窗口以避免焦点冲突")

        grab_overlay_input(self, log_prefix='窗口选择覆盖层')
        QTimer.singleShot(50, self._ensure_ready_for_input)

    def _ensure_ready_for_input(self):
        """确保覆盖层准备好接收输入"""
        ensure_overlay_ready_for_input(
            self,
            log_prefix='窗口选择覆盖层',
            ready_message='窗口选择器已就绪，可以接收输入',
            retry_message='窗口选择器未能激活（尝试 {attempt}/{max_attempts}）',
            exhausted_message='已达到最大激活尝试次数，继续执行',
        )

    def closeEvent(self, event):
        """关闭事件"""
        self._closing = True
        if hasattr(self, 'mouse_timer'):
            self.mouse_timer.stop()

        release_overlay_input(self)
        restored_count = self.window_hider.restore_all()
        logger.info(f"已恢复 {restored_count} 个窗口显示")

        super().closeEvent(event)
