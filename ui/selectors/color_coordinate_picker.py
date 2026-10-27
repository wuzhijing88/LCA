#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
颜色坐标选择器 - 支持点击屏幕获取坐标和颜色
用于找色功能的多点定位
"""

import logging
import time
import ctypes
import win32gui
from ctypes import wintypes
from typing import Optional, Tuple, List
from PySide6.QtWidgets import (QWidget, QPushButton, QVBoxLayout, QHBoxLayout,
                                QMessageBox, QApplication, QLabel)
from PySide6.QtCore import Signal, QPoint, QRect, Qt, QTimer, QThread, QEvent
from PySide6.QtGui import QCursor, QPainter, QPen, QColor, QBrush, QImage, QPixmap
from shiboken6 import isValid
from themes import get_theme_manager, theme_color
from themes.capture_tools import apply_capture_action_buttons

from utils.window.window_coordinate_common import (
    get_qt_virtual_desktop_rect,
    build_window_info,
    client_relative_to_qt_global,
    get_window_client_physical_size,
    get_window_client_qt_global_rect,
)
from utils.window.window_overlay_utils import (
    apply_overlay_text_style,
    capture_virtual_desktop_pixmap,
    configure_opaque_picker_overlay,
    draw_overlay_frame,
    draw_picker_backdrop,
    get_target_window_overlay_rect,
    numpy_screenshot_to_qpixmap,
    overlay_point_to_client_qpoint,
    overlay_rect_contains_point,
    prime_picker_backdrop,
    sync_overlay_geometry,
)
from utils.window.window_activation_utils import (
    activate_overlay_widget,
    activate_window,
    grab_overlay_input,
    release_overlay_input,
    schedule_overlay_activation_boost,
    schedule_overlay_callback,
    show_and_activate_overlay,
)

logger = logging.getLogger(__name__)

# 导入窗口隐藏管理器
from utils.window.window_hider import WindowHider

import numpy as np


class GlobalInputMonitor(QThread):
    """全局输入监听线程 - 使用Windows钩子监听ESC和右键"""

    ready = Signal()
    failed = Signal(str)
    esc_pressed = Signal()
    right_click = Signal()
    arrow_nudge = Signal(int, int)  # dx, dy（客户区物理像素）

    # Windows钩子常量
    WH_KEYBOARD_LL = 13
    WH_MOUSE_LL = 14
    WM_KEYDOWN = 0x0100
    WM_RBUTTONDOWN = 0x0204
    VK_ESCAPE = 0x1B
    VK_SHIFT = 0x10
    VK_LEFT = 0x25
    VK_UP = 0x26
    VK_RIGHT = 0x27
    VK_DOWN = 0x28
    ARROW_DELTA = {
        0x25: (-1, 0),
        0x26: (0, -1),
        0x27: (1, 0),
        0x28: (0, 1),
    }
    LRESULT = wintypes.LPARAM

    # 定义KBDLLHOOKSTRUCT结构
    class KBDLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [
            ("vkCode", wintypes.DWORD),
            ("scanCode", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_size_t)
        ]

    def __init__(self):
        super().__init__()
        self._running = False
        self.keyboard_hook = None
        self.mouse_hook = None
        self.keyboard_proc = None
        self.mouse_proc = None
        self._native_thread_id = None
        self._user32 = None
        self._kernel32 = None
        self._post_thread_message = None
        self._unhook_windows_hook_ex = None

    def run(self):
        """线程主循环"""
        try:
            if self.isInterruptionRequested():
                return
            self._running = True

            # 使用独立的 WinDLL 实例，避免第三方库（keyboard/mouse/pynput 等）修改 ctypes.windll.user32 原型造成冲突
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            self._user32 = user32
            self._kernel32 = kernel32

            # 记录本线程ID，用于 stop() 唤醒消息循环
            GetCurrentThreadId = kernel32.GetCurrentThreadId
            GetCurrentThreadId.argtypes = []
            GetCurrentThreadId.restype = wintypes.DWORD
            self._native_thread_id = int(GetCurrentThreadId())

            # Win32 API 原型
            HOOKPROC = ctypes.WINFUNCTYPE(self.LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

            SetWindowsHookExW = user32.SetWindowsHookExW
            SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
            SetWindowsHookExW.restype = wintypes.HHOOK

            CallNextHookEx = user32.CallNextHookEx
            CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
            CallNextHookEx.restype = self.LRESULT

            UnhookWindowsHookEx = user32.UnhookWindowsHookEx
            UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
            UnhookWindowsHookEx.restype = wintypes.BOOL
            self._unhook_windows_hook_ex = UnhookWindowsHookEx

            PeekMessageW = user32.PeekMessageW
            PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
            PeekMessageW.restype = wintypes.BOOL

            TranslateMessage = user32.TranslateMessage
            TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
            TranslateMessage.restype = wintypes.BOOL

            DispatchMessageW = user32.DispatchMessageW
            DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
            DispatchMessageW.restype = self.LRESULT

            GetModuleHandleW = kernel32.GetModuleHandleW
            GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
            GetModuleHandleW.restype = wintypes.HMODULE

            PostThreadMessageW = user32.PostThreadMessageW
            PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            PostThreadMessageW.restype = wintypes.BOOL
            self._post_thread_message = PostThreadMessageW

            GetAsyncKeyState = user32.GetAsyncKeyState
            GetAsyncKeyState.argtypes = [ctypes.c_int]
            GetAsyncKeyState.restype = ctypes.c_short

            # 定义钩子回调函数
            def keyboard_callback(nCode, wParam, lParam):
                try:
                    if nCode >= 0 and wParam == self.WM_KEYDOWN:
                        # 正确解析KBDLLHOOKSTRUCT
                        kb_struct = ctypes.cast(lParam, ctypes.POINTER(self.KBDLLHOOKSTRUCT)).contents
                        vk_code = kb_struct.vkCode
                        if vk_code == self.VK_ESCAPE:
                            logger.debug(f"[全局钩子] 检测到ESC键 (VK={vk_code})")
                            self.esc_pressed.emit()
                        else:
                            delta = self.ARROW_DELTA.get(int(vk_code))
                            if delta is not None:
                                step = 10 if (GetAsyncKeyState(self.VK_SHIFT) & 0x8000) else 1
                                self.arrow_nudge.emit(int(delta[0]) * step, int(delta[1]) * step)
                                return 1
                except Exception as e:
                    logger.error(f"[全局钩子] 键盘回调异常: {e}")
                return CallNextHookEx(self.keyboard_hook, nCode, wParam, lParam)

            def mouse_callback(nCode, wParam, lParam):
                try:
                    if nCode >= 0 and wParam == self.WM_RBUTTONDOWN:
                        logger.debug("[全局钩子] 检测到鼠标右键")
                        self.right_click.emit()
                except Exception as e:
                    logger.error(f"[全局钩子] 鼠标回调异常: {e}")
                return CallNextHookEx(self.mouse_hook, nCode, wParam, lParam)

            # 创建回调函数类型（修正签名）
            self.keyboard_proc = HOOKPROC(keyboard_callback)
            self.mouse_proc = HOOKPROC(mouse_callback)

            # 安装钩子
            h_mod = GetModuleHandleW(None)

            self.keyboard_hook = SetWindowsHookExW(self.WH_KEYBOARD_LL, self.keyboard_proc, h_mod, 0)
            self.mouse_hook = SetWindowsHookExW(self.WH_MOUSE_LL, self.mouse_proc, h_mod, 0)

            if not self.keyboard_hook:
                raise OSError(f"键盘钩子安装失败：{ctypes.get_last_error()}")
            if not self.mouse_hook:
                raise OSError(f"鼠标钩子安装失败：{ctypes.get_last_error()}")

            logger.info("全局输入监听器已启动（ESC键和右键）")

            self.ready.emit()
            # 消息循环（使用PeekMessage避免阻塞）
            msg = wintypes.MSG()
            while not self.isInterruptionRequested():
                # 使用PeekMessage检查消息，避免GetMessage阻塞
                if PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):  # PM_REMOVE=1
                    if msg.message == 0x0012:  # WM_QUIT
                        break
                    TranslateMessage(ctypes.byref(msg))
                    DispatchMessageW(ctypes.byref(msg))
                else:
                    # 没有消息时短暂休眠，降低CPU占用
                    import time
                    time.sleep(0.01)

        except Exception as e:
            self.failed.emit(f"全局输入监听器启动或运行失败：{e}")
            logger.error(f"全局输入监听器运行异常: {e}")
            import traceback
            logger.error(traceback.format_exc())
        finally:
            self.cleanup()

    def cleanup(self):
        errors = []
        for name in ('keyboard_hook', 'mouse_hook'):
            handle = getattr(self, name)
            if handle and not self._unhook_windows_hook_ex(handle):
                errors.append(f"卸载输入钩子失败：{ctypes.get_last_error()}")
            setattr(self, name, None)
        self._running = False
        self._native_thread_id = None
        self._post_thread_message = None
        self._unhook_windows_hook_ex = None
        self.keyboard_proc = self.mouse_proc = None
        self._kernel32 = self._user32 = None
        if errors:
            self.failed.emit('；'.join(errors))

    def stop(self):
        # 中断请求在 run 开始之前也有效，不会被启动线程覆盖。
        self.requestInterruption()
        self._running = False

class ColorCoordinatePickerOverlay(QWidget):
    """颜色坐标选择器覆盖层 - 点击获取坐标和颜色"""

    color_coordinate_selected = Signal(int, int, int, int, int)  # x, y, r, g, b
    color_picking_finished = Signal(str)
    picking_closed = Signal()

    def __init__(self, target_window_hwnd: int, parent=None, search_region=None, initial_points: Optional[List[Tuple[int, int, int, int, int]]] = None):
        points = [] if initial_points is None else list(initial_points)
        for point in points:
            if len(point) != 5 or any(type(v) is not int for v in point) or any(v < 0 or v > 255 for v in point[2:]):
                raise ValueError("初始取色点必须包含整数坐标和有效的 RGB 分量")
        super().__init__(None)  # 独立窗口
        self.target_window_hwnd = target_window_hwnd
        self.window_info = None
        self.target_window_title = ""
        self.search_region = search_region  # (x, y, w, h) or None

        # 使用窗口隐藏管理器统一管理窗口隐藏/恢复
        self.window_hider = WindowHider()
        self.window_hider.add_windows_from_parent(parent)
        logger.info(f"窗口隐藏管理器已初始化，管理 {self.window_hider.get_window_count()} 个窗口")

        # 选择状态
        self.click_pos = QPoint()
        self.selected_color = None  # (r, g, b)
        self.mouse_pos = QPoint()  # 当前鼠标位置
        self._aim_client_pos: Optional[Tuple[int, int]] = None  # 当前瞄准的客户区物理像素
        self._aim_overlay_pos: Optional[QPoint] = None  # 键盘微调对应的覆盖层坐标
        self._last_nudge_at = 0.0
        self._last_nudge_delta = (0, 0)
        self.magnifier_enabled = True  # 放大镜功能开关
        self.selected_points: List[Tuple[int, int, int, int, int]] = []
        self.selected_points = [tuple(point) for point in points]
        # 已有颜色串不含原始屏幕位置，覆盖层只标记本轮实际点击的点。
        self._initial_point_count = len(points)
        if points:
            self.selected_color = tuple(points[-1][2:])

        # 静态截图（在显示覆盖层时拍摄）
        self.static_screenshot = None
        self._static_screenshot_pixmap: Optional[QPixmap] = None
        self.desktop_pixmap = None
        self.original_mouse_pos = None  # 保存原始鼠标位置

        # 放大镜刷新节流与缓存（避免全屏重绘导致卡顿）
        self.magnifier_timer = QTimer(self)
        self.magnifier_timer.setInterval(16)
        self.magnifier_timer.timeout.connect(self._update_magnifier)
        self._last_magnifier_mouse_pos = QPoint()
        self._magnifier_cache_center: Optional[Tuple[int, int]] = None
        self._magnifier_cache_pixmap: Optional[QPixmap] = None
        self._magnifier_grid_size = 5
        self._magnifier_pixel_size = 24

        # 缓存窗口截图，避免频繁调用win32 API
        self.cached_screenshot = None
        self.screenshot_cache_time = 0
        self.screenshot_cache_duration = 0.5  # 500ms缓存（更激进）

        # 窗口激活状态标志
        self._is_ready_for_input = False
        self._input_ready_deadline = None

        # 超时保护：30秒后自动关闭，避免长时间占用资源
        self.timeout_timer = QTimer(self)
        self.timeout_timer.setSingleShot(True)
        self.timeout_timer.setInterval(30000)  # 30秒超时
        self.timeout_timer.timeout.connect(self._on_timeout)

        # 全局输入监听器（不依赖窗口激活状态）
        self.input_monitor = GlobalInputMonitor()
        self.input_monitor.esc_pressed.connect(self._on_global_esc)
        self.input_monitor.right_click.connect(self._on_global_right_click)
        self.input_monitor.arrow_nudge.connect(self._on_arrow_nudge)

        configure_opaque_picker_overlay(self)
        self._closing = False
        self._resources_released = False
        self._closed_emitted = False
        self._finishing = False
        self._theme_registered = False
        self._composed_backdrop = None
        self._composed_backdrop_key = None
        self.input_monitor.ready.connect(self._on_monitor_ready)
        self.input_monitor.failed.connect(self._on_monitor_failed)
        if parent is not None:
            parent.destroyed.connect(self._on_owner_destroyed)

        try:
            self._init_action_buttons()
            self._theme_registered = True
            get_theme_manager().register_theme_change_callback(self._on_theme_changed)
            if not self.setup_target_window():
                raise RuntimeError("无法设置取色目标窗口")
        except Exception:
            self._release_capture()
            self.window_hider.clear()
            self.deleteLater()
            raise

    def capture_screenshot_before_show(self):
        if self._closing:
            return False
        try:
            self._capture_static_screenshot()
            if self.static_screenshot is None:
                raise RuntimeError("窗口截图失败")
            window_pixmap = self._get_static_screenshot_pixmap()
            if window_pixmap is None or window_pixmap.isNull():
                raise RuntimeError("取色截图无法生成预览")
            self.desktop_pixmap = capture_virtual_desktop_pixmap()
            if self.desktop_pixmap is None or self.desktop_pixmap.isNull():
                raise RuntimeError("无法截取取色覆盖层底图")
            self._setup_overlay_geometry()
            target_rect = self._get_target_window_rect()
            if target_rect.isEmpty() or not self.rect().intersects(target_rect):
                raise RuntimeError("取色目标客户区不在当前屏幕内")
            prime_picker_backdrop(self, desktop_pixmap=self.desktop_pixmap,
                window_pixmap=window_pixmap, target_rect=target_rect)
            return True
        except Exception:
            logger.exception("无法拍摄取色画面")
            self.close()
            return False

    def setup_target_window(self):
        """设置目标窗口"""
        target_hwnd = self.target_window_hwnd
        if type(target_hwnd) is not int or target_hwnd <= 0 or not win32gui.IsWindow(target_hwnd):
            logger.error(f"无效的窗口句柄: {target_hwnd}")
            return False

        self.target_window_title = win32gui.GetWindowText(target_hwnd)
        logger.info(f"使用窗口句柄: {target_hwnd}, 标题: {self.target_window_title}")

        # 激活可能还原最小化窗口并改变客户区位置，必须先激活再读取几何。
        self._activate_target_window(target_hwnd)
        self.window_info = self._get_window_info(target_hwnd)
        if not self.window_info:
            logger.error("无法获取窗口信息")
            return False

        return True

    def _get_window_info(self, hwnd: int):
        """获取窗口信息（包括DPI处理）"""
        try:
            window_info = build_window_info(hwnd)
            if not window_info:
                return None

            client_screen_pos = window_info['client_screen_pos']
            client_width = window_info['client_width']
            client_height = window_info['client_height']
            window_dpi = window_info['window_dpi']

            logger.info(f"窗口信息: 客户区位置({client_screen_pos}), "
                       f"尺寸({client_width}x{client_height}), DPI={window_dpi}")

            return window_info

        except Exception as e:
            logger.error(f"获取窗口信息失败: {e}")
            return None

    def _activate_target_window(self, hwnd):
        if not activate_window(hwnd, log_prefix='颜色取点'):
            raise RuntimeError("无法激活取色目标窗口")

    def _setup_overlay_geometry(self):
        """Set overlay geometry."""
        if not self.window_info:
            return

        screen_geometry = sync_overlay_geometry(self)
        logger.info(f"Overlay geometry set: {screen_geometry}")

    def _get_target_window_rect(self) -> QRect:
        """Get the target window client rect in overlay coordinates."""
        return get_target_window_overlay_rect(self, self.window_info)

    def _get_relative_coordinates(self, qt_screen_pos):
        if not self.window_info:
            raise ValueError("缺少取色目标窗口信息")
        target_rect = self._get_target_window_rect()
        if target_rect.isEmpty():
            raise ValueError("取色目标客户区为空")
        return overlay_point_to_client_qpoint(self.window_info, target_rect, qt_screen_pos)

    def _get_pixel_color_at_position(self, x: int, y: int) -> Optional[Tuple[int, int, int]]:
        """从静态截图中获取指定客户区坐标位置的像素颜色（RGB格式）。"""
        if not self.window_info:
            logger.warning("window_info为空，无法获取颜色")
            return None

        try:
            return self._get_pixel_color_from_screenshot(x, y)
        except Exception as e:
            logger.error(f"获取像素颜色失败: {e}")
            return None

    def _map_client_coords_to_screenshot_pixels(self, x: int, y: int) -> Optional[Tuple[int, int]]:
        """将客户区逻辑坐标映射到静态截图实际像素坐标。"""
        screenshot = self.static_screenshot
        if screenshot is None or screenshot.size == 0 or not self.window_info:
            return None

        try:
            img_h, img_w = screenshot.shape[:2]
            physical_width, physical_height = get_window_client_physical_size(self.window_info)
            if physical_width <= 0 or physical_height <= 0:
                raise ValueError("取色目标客户区尺寸无效")

            px = int(round(int(x) * (img_w / float(physical_width))))
            py = int(round(int(y) * (img_h / float(physical_height))))
            px = max(0, min(px, img_w - 1))
            py = max(0, min(py, img_h - 1))
            return px, py
        except Exception:
            return None

    def _get_pixel_color_from_screenshot(self, x: int, y: int) -> Optional[Tuple[int, int, int]]:
        """从静态截图中取色，保证预览与实际取色一致。"""
        screenshot = self.static_screenshot
        if screenshot is None or screenshot.size == 0:
            return None

        height, width = screenshot.shape[:2]
        mapped = self._map_client_coords_to_screenshot_pixels(x, y)
        if mapped is None:
            return None
        px, py = mapped
        if 0 <= px < width and 0 <= py < height:
            pixel_bgr = screenshot[py, px]
            b, g, r = int(pixel_bgr[0]), int(pixel_bgr[1]), int(pixel_bgr[2])
            return (r, g, b)
        return None

    def _resolve_aim_client_pos(self, mouse_pos: Optional[QPoint] = None) -> Optional[Tuple[int, int]]:
        """当前瞄准的客户区物理像素。键盘微调以此为准，避免高 DPI 量化丢像素。"""
        if self._aim_client_pos is not None:
            return int(self._aim_client_pos[0]), int(self._aim_client_pos[1])

        pos = mouse_pos if mouse_pos is not None else self.mouse_pos
        if pos is None or not self.window_info or not self._is_point_in_target_window(pos):
            return None
        relative_pos = self._get_relative_coordinates(pos)
        return int(relative_pos.x()), int(relative_pos.y())

    def _clamp_client_pos(self, x: int, y: int) -> Tuple[int, int]:
        width, height = get_window_client_physical_size(self.window_info)
        return (
            max(0, min(int(x), max(0, int(width) - 1))),
            max(0, min(int(y), max(0, int(height) - 1))),
        )

    def _get_aim_marker_repaint_rect(self, overlay_pos: QPoint) -> QRect:
        if overlay_pos is None:
            return QRect()
        return QRect(int(overlay_pos.x()) - 14, int(overlay_pos.y()) - 14, 28, 28)

    def _get_magnifier_layout(self, mouse_pos: QPoint) -> Optional[Tuple[QRect, QRect, int, int]]:
        """计算放大镜与信息框布局。"""
        if not self.window_info:
            return None

        aim = self._resolve_aim_client_pos(mouse_pos)
        if aim is None:
            return None
        center_x, center_y = aim

        grid_size = int(self._magnifier_grid_size)
        pixel_size = int(self._magnifier_pixel_size)
        magnifier_size = grid_size * pixel_size

        mag_x = mouse_pos.x() + 30
        mag_y = mouse_pos.y() + 30

        screen_rect = self.rect()
        if mag_x + magnifier_size > screen_rect.width():
            mag_x = mouse_pos.x() - magnifier_size - 30
        if mag_y + magnifier_size > screen_rect.height():
            mag_y = mouse_pos.y() - magnifier_size - 30

        mag_rect = QRect(int(mag_x), int(mag_y), int(magnifier_size), int(magnifier_size))
        info_rect = QRect(int(mag_x), int(mag_y + magnifier_size + 5), 260, 26)

        if info_rect.right() > screen_rect.width() - 4:
            info_rect.moveRight(screen_rect.width() - 4)
        if info_rect.left() < 4:
            info_rect.moveLeft(4)
        if info_rect.bottom() > screen_rect.height() - 4:
            info_rect.moveBottom(screen_rect.height() - 4)

        return mag_rect, info_rect, center_x, center_y

    def _get_magnifier_repaint_rect(self, mouse_pos: QPoint) -> QRect:
        """获取放大镜需要重绘的脏区域。"""
        if not self._is_point_in_target_window(mouse_pos):
            return QRect()

        layout = self._get_magnifier_layout(mouse_pos)
        if not layout:
            return QRect()

        mag_rect, info_rect, _cx, _cy = layout
        dirty = mag_rect.united(info_rect).adjusted(-2, -2, 2, 2)
        marker = self._get_aim_marker_repaint_rect(mouse_pos)
        if not marker.isEmpty():
            dirty = dirty.united(marker)
        if self._aim_client_pos is not None:
            aim_overlay = self._relative_to_overlay_point(self._aim_client_pos[0], self._aim_client_pos[1])
            if aim_overlay is not None:
                dirty = dirty.united(self._get_aim_marker_repaint_rect(aim_overlay))
        return dirty

    def _request_magnifier_update(self, previous_pos: QPoint, current_pos: QPoint):
        """按旧/新位置局部刷新放大镜与瞄准准星。"""
        old_rect = self._get_magnifier_repaint_rect(previous_pos)
        new_rect = self._get_magnifier_repaint_rect(current_pos)

        dirty_rect = QRect()
        if not old_rect.isEmpty():
            dirty_rect = QRect(old_rect)
        if not new_rect.isEmpty():
            dirty_rect = dirty_rect.united(new_rect) if not dirty_rect.isEmpty() else QRect(new_rect)

        if not dirty_rect.isEmpty():
            self.update(dirty_rect)

    def _build_magnifier_pixmap(self, center_x: int, center_y: int) -> Optional[QPixmap]:
        """从静态截图批量构建放大镜像素图，避免逐像素绘制。"""
        screenshot = self.static_screenshot
        if screenshot is None or getattr(screenshot, 'size', 0) == 0:
            return None

        try:
            grid_size = int(self._magnifier_grid_size)
            pixel_size = int(self._magnifier_pixel_size)
            half_grid = grid_size // 2

            height, width = screenshot.shape[:2]
            mapped_center = self._map_client_coords_to_screenshot_pixels(center_x, center_y)
            if mapped_center is None:
                return None
            center_px, center_py = mapped_center
            src_left = int(center_px - half_grid)
            src_top = int(center_py - half_grid)
            src_right = int(src_left + grid_size)
            src_bottom = int(src_top + grid_size)

            dst = np.zeros((grid_size, grid_size, 3), dtype=np.uint8)

            clip_left = max(0, src_left)
            clip_top = max(0, src_top)
            clip_right = min(width, src_right)
            clip_bottom = min(height, src_bottom)

            if clip_right > clip_left and clip_bottom > clip_top:
                patch = screenshot[clip_top:clip_bottom, clip_left:clip_right, ::-1]  # BGR -> RGB
                dst_left = clip_left - src_left
                dst_top = clip_top - src_top
                patch_h, patch_w = patch.shape[:2]
                dst[dst_top:dst_top + patch_h, dst_left:dst_left + patch_w] = patch

            image = QImage(dst.data, grid_size, grid_size, int(dst.strides[0]), QImage.Format.Format_RGB888).copy()
            scaled = image.scaled(
                grid_size * pixel_size,
                grid_size * pixel_size,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
            return QPixmap.fromImage(scaled)
        except Exception as e:
            logger.debug(f"构建放大镜像素图失败: {e}")
            return None

    def _is_point_in_target_window(self, qt_screen_pos: QPoint) -> bool:
        """Check whether a point is inside the target window client area."""
        if not self.window_info:
            return False

        target_rect = self._get_target_window_rect()
        return overlay_rect_contains_point(target_rect, qt_screen_pos)

    def _init_action_buttons(self):
        """初始化覆盖层操作按钮。"""
        self.finish_button = QPushButton("完成取色", self)
        self.finish_button.setObjectName("colorPickerFinishButton")
        self.finish_button.setFixedSize(84, 34)
        self.finish_button.setAutoDefault(False)
        self.finish_button.setDefault(False)
        self.finish_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.finish_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.finish_button.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.finish_button.clicked.connect(self._on_finish_clicked)

        self.cancel_button = QPushButton("取消", self)
        self.cancel_button.setObjectName("colorPickerCancelButton")
        self.cancel_button.setFixedSize(84, 34)
        self.cancel_button.setAutoDefault(False)
        self.cancel_button.setDefault(False)
        self.cancel_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_button.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.cancel_button.clicked.connect(self._on_cancel_clicked)

        self._apply_action_buttons_theme()
        self.finish_button.show()
        self.cancel_button.show()

    def _is_fullscreen_like_target(self, target_rect: QRect) -> bool:
        overlay_rect = self.rect()
        if overlay_rect.isEmpty() or target_rect.isEmpty():
            return False
        from utils.window.window_identity import is_desktop_window

        if is_desktop_window(self.target_window_hwnd):
            return True
        overlay_area = max(1, overlay_rect.width() * overlay_rect.height())
        target_area = max(0, target_rect.width() * target_rect.height())
        return (target_area / overlay_area) >= 0.85

    def _position_action_buttons(self):
        """普通窗口放在客户区下方；桌面/全屏改到顶部，避免挡住取色。"""
        if not hasattr(self, "finish_button") or not hasattr(self, "cancel_button"):
            return

        gap = 8
        margin = 12
        overlay_rect = self.rect()
        target_rect = self._get_target_window_rect()
        if target_rect.isEmpty():
            return

        total_w = self.finish_button.width() + self.cancel_button.width() + gap
        btn_h = self.finish_button.height()

        if self._is_fullscreen_like_target(target_rect):
            x = overlay_rect.center().x() - total_w // 2
            y = overlay_rect.top() + margin
        else:
            x = target_rect.right() - total_w
            y = target_rect.bottom() + gap
            if y + btn_h > overlay_rect.bottom() - margin:
                x = overlay_rect.center().x() - total_w // 2
                y = overlay_rect.top() + margin

        x = max(margin, min(int(x), overlay_rect.width() - total_w - margin))
        y = max(margin, min(int(y), overlay_rect.height() - btn_h - margin))
        self.finish_button.move(x, y)
        self.cancel_button.move(x + self.finish_button.width() + gap, y)
        self.finish_button.raise_()
        self.cancel_button.raise_()

    def _apply_action_buttons_theme(self):
        apply_capture_action_buttons(self.finish_button, self.cancel_button)

    def _on_theme_changed(self, *_args):
        if not self._resources_released:
            self._apply_action_buttons_theme()
            self._composed_backdrop = None
            self._composed_backdrop_key = None
            self.update()

    def _build_color_string_from_points(self) -> str:
        points = list(getattr(self, "selected_points", []) or [])
        if not points:
            return ""
        if len(points) == 1:
            _x, _y, r, g, b = points[0]
            return f"{int(r)},{int(g)},{int(b)}"
        x0, y0, r0, g0, b0 = points[0]
        parts = [f"{int(r0)},{int(g0)},{int(b0)}"]
        for x, y, r, g, b in points[1:]:
            parts.append(f"{int(x) - int(x0)},{int(y) - int(y0)},{int(r)},{int(g)},{int(b)}")
        return "|".join(parts)

    def _on_finish_clicked(self):
        if self._closing:
            return
        color_text = self._build_color_string_from_points()
        self._finishing = True
        self.close()
        if isValid(self) and color_text:
            self.color_picking_finished.emit(color_text)
        if isValid(self):
            self._finishing = False
            self._notify_closed()

    def _on_cancel_clicked(self):
        """取消取色并关闭覆盖层。"""
        logger.info("取色覆盖层点击取消，关闭覆盖层")
        self._request_close()

    def _request_close(self):
        if getattr(self, "_closing", False):
            return
        self.close()

    def _get_static_screenshot_pixmap(self) -> Optional[QPixmap]:
        """将静态截图转换为可绘制的 QPixmap（懒加载）。"""
        if self._static_screenshot_pixmap is not None:
            return self._static_screenshot_pixmap

        screenshot = self.static_screenshot
        if screenshot is None or getattr(screenshot, 'size', 0) == 0:
            return None

        try:
            self._static_screenshot_pixmap = numpy_screenshot_to_qpixmap(screenshot)
            if self._static_screenshot_pixmap is None or self._static_screenshot_pixmap.isNull():
                logger.warning("静态截图转QPixmap失败")
                self._static_screenshot_pixmap = None
                return None
            return self._static_screenshot_pixmap
        except Exception as e:
            logger.debug(f"静态截图转QPixmap失败: {e}")
            return None

    def _relative_to_overlay_point(self, x: int, y: int) -> Optional[QPoint]:
        """将客户区相对坐标转换为覆盖层坐标。"""
        if not self.window_info:
            return None
        try:
            gx, gy = client_relative_to_qt_global(self.window_info, int(x), int(y))
            return self.mapFromGlobal(QPoint(gx, gy))
        except Exception as e:
            logger.debug(f"坐标转换失败: {e}")
            return None

    def _draw_selected_points(self, painter: QPainter):
        """只绘制本轮实际采到且位于目标客户区内的点。"""
        if not self.window_info:
            return
        target_rect = self._get_target_window_rect()
        if target_rect.isEmpty():
            return
        width, height = get_window_client_physical_size(self.window_info)
        located_points = []
        for index in range(self._initial_point_count, len(self.selected_points)):
            values = self.selected_points[index]
            x, y = values[:2]
            if not (0 <= x < width and 0 <= y < height):
                continue
            point = self._relative_to_overlay_point(x, y)
            if point is not None and target_rect.contains(point):
                located_points.append((index, values, point))
        if not located_points:
            return
        painter.save()
        try:
            painter.setClipRect(target_rect, Qt.ClipOperation.IntersectClip)
            self._paint_selected_point_markers(painter, located_points, target_rect)
        finally:
            painter.restore()

    def _paint_selected_point_markers(self, painter, located_points, target_rect):
        crosshair_outer_color = self._get_picker_color('picker_crosshair_outer')
        crosshair_inner_color = self._get_picker_color('picker_crosshair_inner')
        text_color = self._get_picker_color('picker_text')
        text_bg_color = self._get_picker_color('picker_text_bg')

        for idx, (x, y, r, g, b), point in located_points:
            is_last = idx == located_points[-1][0]
            cross_size = 15 if is_last else 10

            pen_outline = QPen(crosshair_outer_color, 3 if is_last else 2)
            painter.setPen(pen_outline)
            painter.drawLine(point.x() - cross_size, point.y(), point.x() + cross_size, point.y())
            painter.drawLine(point.x(), point.y() - cross_size, point.x(), point.y() + cross_size)

            pen_inner = QPen(crosshair_inner_color, 1)
            painter.setPen(pen_inner)
            painter.drawLine(point.x() - cross_size, point.y(), point.x() + cross_size, point.y())
            painter.drawLine(point.x(), point.y() - cross_size, point.x(), point.y() + cross_size)

            painter.setBrush(QBrush(crosshair_inner_color))
            painter.drawEllipse(point, 2, 2)

            index_text = f"{idx + 1}"
            idx_rect = painter.fontMetrics().boundingRect(index_text)
            idx_pos = point + QPoint(10, -10)
            idx_bg = idx_rect.translated(idx_pos)
            idx_bg.adjust(-4, -2, 4, 2)
            original_pos = idx_bg.topLeft()
            idx_bg.moveLeft(max(target_rect.left(), min(idx_bg.left(), target_rect.right() - idx_bg.width() + 1)))
            idx_bg.moveTop(max(target_rect.top(), min(idx_bg.top(), target_rect.bottom() - idx_bg.height() + 1)))
            idx_pos += idx_bg.topLeft() - original_pos
            painter.setBrush(QBrush(QColor(text_bg_color.red(), text_bg_color.green(), text_bg_color.blue(), 180)))
            painter.setPen(QPen(text_color, 1))
            painter.drawRect(idx_bg)
            painter.drawText(idx_pos, index_text)

        _, (last_x, last_y, last_r, last_g, last_b), last_point = located_points[-1]
        if last_point is not None:
            info_text = f"坐标: ({last_x}, {last_y})  颜色: RGB({last_r},{last_g},{last_b})"
            text_rect = painter.fontMetrics().boundingRect(info_text)
            text_pos = last_point + QPoint(35, -10)
            bg_rect = text_rect.translated(text_pos)
            bg_rect.adjust(-5, -2, 5, 2)
            original_pos = bg_rect.topLeft()
            bg_rect.moveLeft(max(target_rect.left(), min(bg_rect.left(), target_rect.right() - bg_rect.width() + 1)))
            bg_rect.moveTop(max(target_rect.top(), min(bg_rect.top(), target_rect.bottom() - bg_rect.height() + 1)))
            text_pos += bg_rect.topLeft() - original_pos
            painter.setBrush(QBrush(QColor(text_bg_color.red(), text_bg_color.green(), text_bg_color.blue(), 180)))
            painter.setPen(QPen(text_color, 1))
            painter.drawRect(bg_rect)
            painter.drawText(text_pos, info_text)

    def _draw_live_aim_marker(self, painter: QPainter):
        """在当前瞄准像素上画空心准星，中间留出 1px 方便看清目标色。"""
        aim = self._resolve_aim_client_pos()
        if aim is None:
            return
        point = self._relative_to_overlay_point(aim[0], aim[1])
        if point is None:
            return

        outer = self._get_picker_color('picker_crosshair_outer')
        inner = self._get_picker_color('picker_crosshair_inner')
        gap = 2
        arm = 10
        painter.save()
        try:
            painter.setClipRect(self._get_target_window_rect(), Qt.ClipOperation.IntersectClip)
            for pen in (QPen(outer, 3), QPen(inner, 1)):
                painter.setPen(pen)
                painter.drawLine(point.x() - arm, point.y(), point.x() - gap, point.y())
                painter.drawLine(point.x() + gap, point.y(), point.x() + arm, point.y())
                painter.drawLine(point.x(), point.y() - arm, point.x(), point.y() - gap)
                painter.drawLine(point.x(), point.y() + gap, point.x(), point.y() + arm)
        finally:
            painter.restore()

    def _get_picker_color(self, color_key):
        return QColor(theme_color(color_key))

    def paintEvent(self, event):
        """绘制事件"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        apply_overlay_text_style(painter)

        target_rect = self._get_target_window_rect() if self.window_info else QRect()
        draw_picker_backdrop(
            painter,
            self,
            desktop_pixmap=self.desktop_pixmap,
            window_pixmap=self._get_static_screenshot_pixmap(),
            target_rect=target_rect,
        )

        if self.window_info:
            if not target_rect.isEmpty():
                border_color = self._get_picker_color('picker_target_border')
                draw_overlay_frame(painter, target_rect, border_color=border_color, border_width=4)

            # 绘制搜索区域
            if self.search_region and not target_rect.isEmpty():
                region_x, region_y, region_w, region_h = self.search_region
                search_top_left_global = client_relative_to_qt_global(
                    self.window_info,
                    int(region_x),
                    int(region_y),
                )
                search_bottom_right_global = client_relative_to_qt_global(
                    self.window_info,
                    int(region_x) + int(region_w),
                    int(region_y) + int(region_h),
                )
                search_top_left_local = self.mapFromGlobal(
                    QPoint(search_top_left_global[0], search_top_left_global[1])
                )
                search_bottom_right_local = self.mapFromGlobal(
                    QPoint(search_bottom_right_global[0], search_bottom_right_global[1])
                )
                search_rect = QRect(search_top_left_local, search_bottom_right_local).normalized()

                search_border_color = self._get_picker_color('picker_search_border')
                pen_search = QPen(search_border_color, 3)
                painter.setPen(pen_search)
                painter.drawRect(search_rect)

                search_bg_color = self._get_picker_color('picker_search_bg')
                text_color = self._get_picker_color('picker_text')
                painter.setPen(QPen(text_color))
                painter.fillRect(search_rect.topLeft().x(), search_rect.topLeft().y() - 25, 120, 20, QColor(search_bg_color.red(), search_bg_color.green(), search_bg_color.blue(), 180))
                painter.drawText(search_rect.topLeft() + QPoint(5, -10), "搜索区域")

            text_color = self._get_picker_color('picker_text')
            painter.setPen(QPen(text_color))
            if not target_rect.isEmpty():
                painter.drawText(target_rect.topLeft() + QPoint(10, 25),
                               f"目标窗口: {self.target_window_title}")
                painter.drawText(target_rect.topLeft() + QPoint(10, 50),
                               "左键连续取色，方向键微调1像素(Shift=10)，完成后点‘完成取色’")

        # 绘制已选择点
        self._draw_selected_points(painter)
        self._draw_live_aim_marker(painter)

        # 绘制放大镜预览
        if self.magnifier_enabled and self.window_info:
            if self._is_point_in_target_window(self.mouse_pos):
                self._draw_magnifier(painter, self.mouse_pos)

    def _draw_magnifier(self, painter, mouse_pos):
        """绘制放大镜预览区域（缓存+批量渲染）。"""
        try:
            layout = self._get_magnifier_layout(mouse_pos)
            if not layout:
                return

            mag_rect, info_rect, center_x, center_y = layout
            grid_size = int(self._magnifier_grid_size)
            pixel_size = int(self._magnifier_pixel_size)
            half_grid = grid_size // 2

            # 背景与边框。不要用 picker_text 的绿边，那是旧取色器配色。
            painter.fillRect(mag_rect, QColor(theme_color("capture_magnifier_background")))
            frame_color = self._get_picker_color('picker_crosshair_outer')
            painter.setPen(QPen(frame_color, 2))
            painter.drawRect(mag_rect)

            # 复用同一中心点缓存，避免重复构建放大图
            cache_key = (int(center_x), int(center_y))
            if self._magnifier_cache_center != cache_key or self._magnifier_cache_pixmap is None:
                self._magnifier_cache_center = cache_key
                self._magnifier_cache_pixmap = self._build_magnifier_pixmap(center_x, center_y)

            if self._magnifier_cache_pixmap is not None and not self._magnifier_cache_pixmap.isNull():
                painter.drawPixmap(mag_rect, self._magnifier_cache_pixmap)

            # 中心像素高亮框
            center_cell = QRect(
                mag_rect.x() + half_grid * pixel_size,
                mag_rect.y() + half_grid * pixel_size,
                pixel_size,
                pixel_size,
            )
            crosshair_inner_color = self._get_picker_color('picker_crosshair_inner')
            painter.setPen(QPen(crosshair_inner_color, 2))
            painter.drawRect(center_cell)

            # 网格线
            painter.setPen(QPen(QColor(theme_color("capture_magnifier_grid")), 1))
            for i in range(grid_size + 1):
                x = mag_rect.x() + i * pixel_size
                y = mag_rect.y() + i * pixel_size
                painter.drawLine(x, mag_rect.y(), x, mag_rect.y() + mag_rect.height())
                painter.drawLine(mag_rect.x(), y, mag_rect.x() + mag_rect.width(), y)

            # 坐标与颜色文本
            center_color = self._get_pixel_color_from_screenshot(center_x, center_y)

            if center_color:
                r, g, b = center_color
                info_text = f"({center_x},{center_y}) RGB({r},{g},{b})"

                painter.setPen(QPen(frame_color))
                text_rect = painter.fontMetrics().boundingRect(info_text)
                info_bg_rect = QRect(
                    info_rect.x(),
                    info_rect.y(),
                    int(text_rect.width() + 10),
                    int(text_rect.height() + 6),
                )
                text_bg_color = self._get_picker_color('picker_text_bg')
                painter.fillRect(info_bg_rect, QColor(text_bg_color.red(), text_bg_color.green(), text_bg_color.blue(), 200))
                painter.drawText(info_bg_rect.left() + 5, info_bg_rect.top() + text_rect.height() + 2, info_text)

        except Exception as e:
            logger.debug(f"绘制放大镜时出错: {e}")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        try:
            self._position_action_buttons()
        except Exception:
            pass

    def showEvent(self, event):
        """窗口显示事件"""
        if getattr(self, "_closing", False):
            event.ignore()
            return
        super().showEvent(event)

        # 覆盖层已经盖住屏幕，这里不能再截窗口，否则会把黑屏盖层拍进去。
        self._setup_overlay_geometry()
        self.update()

        # 启动放大镜定时器
        if self.magnifier_enabled:
            self.magnifier_timer.start()
            logger.info("放大镜定时器已启动")

        self._position_action_buttons()

        # 不自动关闭覆盖层：由用户点击“完成取色”后再销毁

        self.window_hider.add_visible_app_windows(exclude=(self,))
        hidden_count = self.window_hider.hide_all()
        logger.info(f"已隐藏 {hidden_count} 个窗口以避免颜色干扰找色")

        # 首帧直接读取当前光标，不依赖首次 mouseMoveEvent。
        self.mouse_pos = self.mapFromGlobal(QCursor.pos())
        self._sync_aim_from_mouse(self.mouse_pos)
        self._last_magnifier_mouse_pos = QPoint(self.mouse_pos)
        self._input_ready_deadline = time.monotonic() + 3.0
        self.input_monitor.start()

    def _on_monitor_ready(self):
        if not self._closing:
            schedule_overlay_callback(self, 50, self._ensure_ready_for_input)

    def _on_monitor_failed(self, error):
        if self._closing:
            logger.error(error)
            return
        self.close()
        QMessageBox.critical(None, "取色失败", error)

    def _on_timeout(self):
        """超时自动关闭"""
        if getattr(self, "_closing", False):
            return
        logger.warning("取色器超时（30秒未操作），自动关闭以释放资源")
        self.close()

    def _capture_static_screenshot(self):
        from utils.capture.screenshot_helper import get_screenshot_engine, clear_screenshot_cache
        from tasks.task_utils import capture_window_smart
        if get_screenshot_engine() == 'wgc':
            clear_screenshot_cache()
        self.original_mouse_pos = QCursor.pos()
        try:
            virtual = get_qt_virtual_desktop_rect()
            if virtual is None or virtual.isEmpty():
                raise RuntimeError("无法获取屏幕信息")
            QCursor.setPos(virtual.right() - 10, virtual.bottom() - 10)
            time.sleep(0.15)
            self.static_screenshot = capture_window_smart(int(self.window_info['hwnd']), client_area_only=True)
            if self.static_screenshot is None:
                raise RuntimeError("无法截取取色目标窗口")
            self._static_screenshot_pixmap = None
            self.cached_screenshot = self.static_screenshot
            self.screenshot_cache_time = time.time()
            self._magnifier_cache_center = self._magnifier_cache_pixmap = None
        finally:
            QCursor.setPos(self.original_mouse_pos)
            self.original_mouse_pos = None

    def _ensure_ready_for_input(self):
        """首次原生窗口可能尚未曝光，在有界期限内等待真实输入就绪。"""
        if self._closing or not self.isVisible():
            return False
        if self._is_ready_for_input:
            self._input_ready_deadline = None
            return True
        window = self.windowHandle()
        if window is not None and window.isExposed():
            if grab_overlay_input(self, log_prefix='颜色取点覆盖层', activate=True):
                self._is_ready_for_input = True
                self._input_ready_deadline = None
                return True
        if self._input_ready_deadline is None or time.monotonic() >= self._input_ready_deadline:
            self._on_monitor_failed("取色覆盖层未能完成显示或取得输入焦点，请重新取色")
            return False
        schedule_overlay_callback(self, 50, self._ensure_ready_for_input)
        return False

    def mouseMoveEvent(self, event):
        """鼠标移动事件 - 仅局部刷新放大镜区域，避免全屏重绘卡顿"""
        previous_pos = QPoint(self.mouse_pos)
        self.mouse_pos = event.pos()
        self._sync_aim_from_mouse(event.pos())

        # 用户有活动，重置超时定时器
        if hasattr(self, 'timeout_timer') and self.timeout_timer.isActive():
            self.timeout_timer.start()  # 重新开始计时

        if self.magnifier_enabled:
            self._request_magnifier_update(previous_pos, self.mouse_pos)
            self._last_magnifier_mouse_pos = QPoint(self.mouse_pos)

        event.accept()

    def _update_magnifier(self):
        """读取真实光标，仅在位置变化时刷新，避免首次输入事件缺失。"""
        if getattr(self, "_closing", False):
            return
        if not self.magnifier_enabled:
            return

        cursor_pos = self.mapFromGlobal(QCursor.pos())
        if cursor_pos != self.mouse_pos:
            self.mouse_pos = cursor_pos
            self._sync_aim_from_mouse(cursor_pos)
        if self.mouse_pos == self._last_magnifier_mouse_pos:
            return

        previous_pos = QPoint(self._last_magnifier_mouse_pos)
        self._last_magnifier_mouse_pos = QPoint(self.mouse_pos)
        self._request_magnifier_update(previous_pos, self.mouse_pos)

    def _on_global_esc(self):
        """全局ESC键处理（通过钩子触发，不依赖窗口激活）"""
        if getattr(self, "_closing", False):
            return
        logger.info("[全局钩子] ESC键退出")
        schedule_overlay_callback(self, 0, self._request_close)

    def _on_global_right_click(self):
        """全局右键处理（通过钩子触发，不依赖窗口激活）"""
        if getattr(self, "_closing", False):
            return
        logger.info("[全局钩子] 右键取消选择")
        schedule_overlay_callback(self, 0, self._request_close)

    def mousePressEvent(self, event):
        """鼠标按下事件"""
        logger.info(f"[鼠标事件] 接收到鼠标按下事件: 按钮={event.button()}, 位置={event.pos()}")

        # 接受事件，防止穿透到下层窗口
        event.accept()

        # 用户开始操作，停止超时定时器
        if hasattr(self, 'timeout_timer') and self.timeout_timer.isActive():
            self.timeout_timer.stop()
            logger.debug("用户开始操作，超时定时器已停止")

        if event.button() == Qt.MouseButton.LeftButton:
            child = self.childAt(event.pos())
            if child is getattr(self, "finish_button", None):
                self._on_finish_clicked()
                return
            if child is getattr(self, "cancel_button", None):
                self._on_cancel_clicked()
                return
            logger.info("[鼠标事件] 左键点击")
            if self._is_point_in_target_window(event.pos()):
                logger.info("[鼠标事件] 点击位置在目标窗口内")
                self.click_pos = event.pos()
                self._sync_aim_from_mouse(self.click_pos)

                # 键盘微调后以瞄准像素为准，避免高 DPI 下点击坐标被量化偏移
                aim = self._resolve_aim_client_pos(event.pos())
                if aim is not None:
                    relative_pos = QPoint(int(aim[0]), int(aim[1]))
                else:
                    relative_pos = self._get_relative_coordinates(event.pos())
                logger.info(f"[鼠标事件] 相对坐标: ({relative_pos.x()}, {relative_pos.y()})")

                # 获取该位置的像素颜色
                color = self._get_pixel_color_at_position(relative_pos.x(), relative_pos.y())

                if color:
                    self.selected_color = color
                    r, g, b = color
                    logger.info(f"颜色坐标选择完成: 坐标({relative_pos.x()}, {relative_pos.y()}) -> RGB({r},{g},{b})")

                    # 先更新显示
                    self.update()

                    # 记录并发射信号（支持连续取色）
                    self.selected_points.append((relative_pos.x(), relative_pos.y(), r, g, b))
                    self.color_coordinate_selected.emit(relative_pos.x(), relative_pos.y(), r, g, b)
                else:
                    logger.warning("无法获取像素颜色")
                    self.update()
            else:
                logger.warning("[鼠标事件] 点击位置不在目标窗口内")

        elif event.button() == Qt.MouseButton.RightButton:
            logger.info("[鼠标事件] 右键点击，取消选择")
            self._request_close()

    def _sync_aim_from_mouse(self, overlay_pos: QPoint):
        """鼠标移动时更新瞄准点；若仍停在键盘微调的同一视觉像素上则保持客户区坐标。"""
        if not self._is_point_in_target_window(overlay_pos):
            self._aim_client_pos = self._aim_overlay_pos = None
            return
        locked = self._aim_overlay_pos
        if locked is not None and self._aim_client_pos is not None:
            if abs(int(overlay_pos.x()) - int(locked.x())) <= 1 and abs(int(overlay_pos.y()) - int(locked.y())) <= 1:
                return
        relative_pos = self._get_relative_coordinates(overlay_pos)
        self._aim_client_pos = (int(relative_pos.x()), int(relative_pos.y()))
        self._aim_overlay_pos = None

    def _on_arrow_nudge(self, dx: int, dy: int):
        if getattr(self, "_closing", False):
            return
        self._nudge_picker_by(int(dx), int(dy))

    def _nudge_picker_by(self, dx: int, dy: int):
        """按客户区物理像素移动瞄准点，并同步真实光标。"""
        if getattr(self, "_closing", False) or not self.window_info:
            return
        if not dx and not dy:
            return

        now = time.monotonic()
        delta = (int(dx), int(dy))
        if delta == self._last_nudge_delta and (now - self._last_nudge_at) < 0.02:
            return
        self._last_nudge_at = now
        self._last_nudge_delta = delta

        aim = self._resolve_aim_client_pos()
        if aim is None:
            cursor_local = self.mapFromGlobal(QCursor.pos())
            if cursor_local.isNull():
                return
            relative_pos = self._get_relative_coordinates(cursor_local)
            aim = (int(relative_pos.x()), int(relative_pos.y()))

        next_x, next_y = self._clamp_client_pos(aim[0] + dx, aim[1] + dy)
        overlay_point = self._relative_to_overlay_point(next_x, next_y)
        if overlay_point is None:
            return

        previous_pos = QPoint(self.mouse_pos)
        self._aim_client_pos = (next_x, next_y)
        self._aim_overlay_pos = QPoint(overlay_point)
        QCursor.setPos(self.mapToGlobal(overlay_point))
        self.mouse_pos = QPoint(overlay_point)

        if hasattr(self, 'timeout_timer') and self.timeout_timer.isActive():
            self.timeout_timer.start()

        self._request_magnifier_update(previous_pos, self.mouse_pos)
        self._last_magnifier_mouse_pos = QPoint(self.mouse_pos)
        logger.debug("找色瞄准微调: (%s, %s) -> (%s, %s)", aim[0], aim[1], next_x, next_y)

    def keyPressEvent(self, event):
        """处理覆盖层收到的取消与方向键事件。"""
        logger.info(f"[键盘事件] 接收到键盘事件: 键={event.key()}")
        if event.key() == Qt.Key.Key_Escape:
            logger.info("ESC键退出")
            self._request_close()
            event.accept()
            return

        arrow_delta = {
            Qt.Key.Key_Left: (-1, 0),
            Qt.Key.Key_Right: (1, 0),
            Qt.Key.Key_Up: (0, -1),
            Qt.Key.Key_Down: (0, 1),
        }
        delta = arrow_delta.get(event.key())
        if delta is not None:
            step = 10 if (event.modifiers() & Qt.KeyboardModifier.ShiftModifier) else 1
            self._nudge_picker_by(delta[0] * step, delta[1] * step)
            event.accept()
            return

        event.accept()

    def _release_capture(self):
        if self._resources_released:
            return
        self._resources_released = True
        self._closing = True
        self._input_ready_deadline = None
        release_overlay_input(self)
        self.magnifier_timer.stop()
        self.timeout_timer.stop()
        self.input_monitor.stop()
        self.input_monitor.wait()
        for signal, slot in ((self.input_monitor.esc_pressed, self._on_global_esc),
                             (self.input_monitor.right_click, self._on_global_right_click),
                             (self.input_monitor.arrow_nudge, self._on_arrow_nudge),
                             (self.input_monitor.ready, self._on_monitor_ready),
                             (self.input_monitor.failed, self._on_monitor_failed)):
            signal.disconnect(slot)
        self.input_monitor.deleteLater()
        if self._theme_registered:
            get_theme_manager().unregister_theme_change_callback(self._on_theme_changed)
            self._theme_registered = False
        self.static_screenshot = self.cached_screenshot = self._static_screenshot_pixmap = None
        self.desktop_pixmap = self._composed_backdrop = self._composed_backdrop_key = None
        self._magnifier_cache_center = self._magnifier_cache_pixmap = None
        self._aim_client_pos = self._aim_overlay_pos = self.original_mouse_pos = None
        self.selected_points.clear()
        self._initial_point_count = 0
        self.selected_color = None

    def _notify_closed(self):
        if not self._closed_emitted and not self._finishing:
            self._closed_emitted = True
            self.picking_closed.emit()

    def _on_owner_destroyed(self):
        self.close()
        if isValid(self):
            self.deleteLater()

    def _finish_close(self):
        self._release_capture()
        self.window_hider.restore_all()
        self.window_hider.clear()
        self._notify_closed()

    def close(self):
        # 尚未显示的失败窗口也需要卸载，不能依赖 Qt 是否投递 closeEvent。
        self._release_capture()
        result = super().close()
        if isValid(self):
            self._finish_close()
        return result

    def closeEvent(self, event):
        self._release_capture()
        self.hide()
        self._finish_close()
        super().closeEvent(event)

    def hideEvent(self, event):
        self._finish_close()
        super().hideEvent(event)

    def event(self, event):
        if event.type() == QEvent.Type.DeferredDelete:
            self._release_capture()
            self.hide()
            self._finish_close()
        return super().event(event)

class ColorCoordinatePickerWidget(QWidget):
    """颜色坐标选择器控件 - 支持多点颜色选择"""

    colors_selected = Signal(str)  # 发射完整的颜色字符串 (支持多点格式)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.target_window_hwnd = None
        self.color_points = []  # [(x, y, r, g, b), ...]
        self.search_region = None  # (x, y, w, h) or None
        self.overlay = None

        self.setup_ui()
        self._update_button_text()

    def setup_ui(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # 按钮布局
        button_layout = QHBoxLayout()
        button_layout.setSpacing(8)

        # 选择按钮 - 使用主题样式
        self.select_button = QPushButton("点击屏幕获取颜色")
        self.select_button.setMinimumHeight(32)
        self.select_button.setProperty("class", "primary")
        self.select_button.clicked.connect(self.start_selection)
        button_layout.addWidget(self.select_button)

        # 清除全部按钮 - 使用主题样式
        self.clear_button = QPushButton("清除全部")
        self.clear_button.setMinimumHeight(32)
        self.clear_button.setMinimumWidth(80)
        self.clear_button.setProperty("class", "danger")
        self.clear_button.clicked.connect(self.clear_colors)
        button_layout.addWidget(self.clear_button)

        layout.addLayout(button_layout)

        # 颜色列表容器 - 使用ScrollArea以支持多个颜色点
        from PySide6.QtWidgets import QScrollArea
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setMinimumHeight(100)
        scroll_area.setMaximumHeight(200)
        scroll_area.setObjectName("color_picker_scroll")

        # 颜色列表容器widget
        self.colors_container = QWidget()
        self.colors_layout = QVBoxLayout(self.colors_container)
        self.colors_layout.setContentsMargins(5, 5, 5, 5)
        self.colors_layout.setSpacing(5)
        self.colors_layout.addStretch()

        scroll_area.setWidget(self.colors_container)
        layout.addWidget(scroll_area)

        # 占位标签（初始显示）
        self.placeholder_label = QLabel("未选择颜色")
        self.placeholder_label.setObjectName("color_placeholder_label")
        self.placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.colors_layout.insertWidget(0, self.placeholder_label)

    def _update_button_text(self):
        """更新UI显示 - 显示所有颜色点，带预览和删除按钮"""
        count = len(self.color_points)

        # 更新选择按钮文本
        if count == 0:
            self.select_button.setText("点击屏幕获取颜色")
        elif count == 1:
            self.select_button.setText("已选择1个点")
        else:
            self.select_button.setText(f"已选择{count}个点")

        # 清除所有颜色项widget（保留占位标签和stretch）
        while self.colors_layout.count() > 2:  # 保留占位标签和stretch
            item = self.colors_layout.takeAt(1)  # 总是移除第二个item（第一个是占位标签）
            if item.widget():
                item.widget().deleteLater()

        # 如果没有颜色点，显示占位标签
        if count == 0:
            self.placeholder_label.setVisible(True)
            return

        # 有颜色点，隐藏占位标签
        self.placeholder_label.setVisible(False)

        # 为每个颜色点创建一个item
        for i, (x, y, r, g, b) in enumerate(self.color_points):
            color_item = self._create_color_item(i, x, y, r, g, b)
            # 插入到stretch之前
            self.colors_layout.insertWidget(self.colors_layout.count() - 1, color_item)

    def _create_color_item(self, index: int, x: int, y: int, r: int, g: int, b: int) -> QWidget:
        """创建单个颜色项widget - 符合主程序UI风格"""
        from PySide6.QtWidgets import QFrame

        item_widget = QFrame()
        item_widget.setObjectName("color_item_frame")

        item_layout = QHBoxLayout(item_widget)
        item_layout.setContentsMargins(8, 8, 8, 8)
        item_layout.setSpacing(10)

        # 颜色预览方块（40x40，更大更突出）- 动态背景色必须内联
        color_preview = QLabel()
        color_preview.setFixedSize(40, 40)
        color_preview.setObjectName("captureColorSample")
        swatch = QPixmap(38, 38)
        swatch.fill(QColor(r, g, b))
        color_preview.setPixmap(swatch)
        color_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        item_layout.addWidget(color_preview)

        # 信息文本
        if index == 0:
            # 基准点
            label_text = "基准点"
            coord_text = f"({x}, {y})"
        else:
            # 偏移点
            x0, y0 = self.color_points[0][0], self.color_points[0][1]
            offset_x = x - x0
            offset_y = y - y0
            label_text = f"偏移点 {index}"
            coord_text = f"({offset_x:+d}, {offset_y:+d})"

        color_text = f"RGB({r},{g},{b})"

        # 左侧信息容器
        info_container = QWidget()
        info_layout = QVBoxLayout(info_container)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(2)

        # 标签（基准点/偏移点）
        label = QLabel(label_text)
        label.setObjectName("color_item_label")
        info_layout.addWidget(label)

        # 坐标和颜色信息
        detail_text = f"{coord_text}  {color_text}"
        detail_label = QLabel(detail_text)
        detail_label.setObjectName("color_item_detail")
        info_layout.addWidget(detail_label)

        item_layout.addWidget(info_container, 1)  # stretch=1

        # 删除按钮 - 小型文字按钮
        delete_btn = QPushButton("删除")
        delete_btn.setFixedSize(55, 26)
        delete_btn.setObjectName("color_item_delete_btn")
        delete_btn.clicked.connect(lambda checked=False, idx=index: self._delete_color_point(idx))
        item_layout.addWidget(delete_btn)

        return item_widget

    def _delete_color_point(self, index: int):
        """删除指定索引的颜色点"""
        if 0 <= index < len(self.color_points):
            removed = self.color_points.pop(index)
            logger.info(f"删除颜色点 {index}: {removed}")

            # 更新UI
            self._update_button_text()

            # 重新生成颜色字符串并发射信号
            color_string = self._build_color_string()
            self.colors_selected.emit(color_string)
            logger.info(f"删除后颜色字符串: {color_string}")

    def set_target_hwnd(self, hwnd: int):
        """设置目标窗口句柄"""
        self.target_window_hwnd = hwnd

    def set_search_region(self, x: int, y: int, width: int, height: int):
        """设置搜索区域限制"""
        self.search_region = (x, y, width, height)
        logger.info(f"设置颜色选择器搜索区域: X={x}, Y={y}, W={width}, H={height}")

    def clear_colors(self):
        """清除所有颜色点"""
        self.color_points = []
        self._update_button_text()
        logger.info("已清除所有颜色点")

    def _get_bound_window_hwnd(self) -> Optional[int]:
        from ui.selectors.coordinate_selector import _get_global_bound_window
        return _get_global_bound_window(self)

    def _validate_hwnd_silent(self, hwnd):
        if type(hwnd) is int and hwnd > 0 and hwnd == self._get_bound_window_hwnd():
            return hwnd
        logger.error("目标窗口不是当前唯一启用的全局绑定窗口")
        return None

    def start_selection(self):
        if self.overlay is not None and isValid(self.overlay) and self.overlay.isVisible():
            activate_overlay_widget(self.overlay, log_prefix='颜色取点覆盖层', focus=True)
            return
        self.cleanup()
        try:
            hwnd = self.target_window_hwnd
            if hwnd is None:
                hwnd = self._get_bound_window_hwnd()
            validated = self._validate_hwnd_silent(hwnd)
            if not validated:
                raise ValueError("没有可用的绑定窗口，请先绑定目标窗口")
            overlay = ColorCoordinatePickerOverlay(validated, self.window(),
                search_region=self.search_region, initial_points=self.color_points)
            self.overlay = overlay
            overlay.color_coordinate_selected.connect(self._on_color_coordinate_selected)
            overlay.picking_closed.connect(self._on_picking_closed)
            self.destroyed.connect(overlay._on_owner_destroyed)
            if not overlay.capture_screenshot_before_show():
                raise RuntimeError("无法拍摄窗口截图")
            if not show_and_activate_overlay(overlay, log_prefix='颜色取点覆盖层启动', focus=True):
                raise RuntimeError("无法显示取色覆盖层")
            grab_overlay_input(overlay, log_prefix='颜色取点覆盖层')
            schedule_overlay_activation_boost(overlay, log_prefix='颜色取点覆盖层')
        except Exception as error:
            self.cleanup()
            logger.exception("启动取色工具失败")
            QMessageBox.critical(self, "取色失败", str(error))

    def cleanup(self, *_args):
        overlay, self.overlay = self.overlay, None
        if overlay is not None and isValid(overlay):
            overlay.blockSignals(True)
            overlay.close()
            overlay.deleteLater()

    def _on_picking_closed(self):
        overlay, self.overlay = self.overlay, None
        if overlay is not None and isValid(overlay):
            overlay.deleteLater()

    def event(self, event):
        if event.type() == QEvent.Type.DeferredDelete:
            self.cleanup()
        return super().event(event)

    def closeEvent(self, event):
        self.cleanup()
        super().closeEvent(event)



    def _on_color_coordinate_selected(self, x: int, y: int, r: int, g: int, b: int):
        """处理颜色坐标选择"""
        logger.info(f"颜色坐标选择: ({x}, {y}) -> RGB({r},{g},{b})")

        # 添加到颜色点列表
        self.color_points.append((x, y, r, g, b))

        # 生成颜色字符串
        color_string = self._build_color_string()

        # 更新UI
        self._update_button_text()

        # 发射信号
        self.colors_selected.emit(color_string)

        logger.info(f"当前颜色字符串: {color_string}")

    def _build_color_string(self) -> str:
        """构建颜色字符串
        单点: "R,G,B"
        多点: "R,G,B|offsetX,offsetY,R,G,B|..."
        """
        if not self.color_points:
            return ""

        if len(self.color_points) == 1:
            # 单点模式
            x, y, r, g, b = self.color_points[0]
            return f"{r},{g},{b}"
        else:
            # 多点定位模式
            parts = []
            x0, y0, r0, g0, b0 = self.color_points[0]
            parts.append(f"{r0},{g0},{b0}")

            for i in range(1, len(self.color_points)):
                x, y, r, g, b = self.color_points[i]
                offset_x = x - x0
                offset_y = y - y0
                parts.append(f"{offset_x},{offset_y},{r},{g},{b}")

            return "|".join(parts)

    def get_base_point(self) -> Optional[Tuple[int, int]]:
        """返回基准点坐标（第一个取色点）。"""
        if not self.color_points:
            return None
        x, y, _, _, _ = self.color_points[0]
        return int(x), int(y)

    def get_color_string(self) -> str:
        """获取当前颜色字符串"""
        color_str = self._build_color_string()
        logger.info(f"get_color_string() 被调用，返回: '{color_str}', 点数: {len(self.color_points)}")
        return color_str

    def set_color_string(self, color_string: str):
        """完整校验颜色串后再替换，损坏的偏移点不得被静默丢弃。"""
        if not isinstance(color_string, str):
            raise TypeError("颜色数据必须是字符串")
        points = []
        if color_string:
            for index, part in enumerate(color_string.split('|')):
                try:
                    values = [int(value.strip()) for value in part.split(',')]
                except ValueError as exc:
                    raise ValueError(f"第{index + 1}个颜色点包含无效整数") from exc
                expected = 3 if index == 0 else 5
                if len(values) != expected:
                    raise ValueError(f"第{index + 1}个颜色点需要{expected}个整数")
                if any(value < 0 or value > 255 for value in values[-3:]):
                    raise ValueError(f"第{index + 1}个颜色点的颜色分量必须在0到255之间")
                x, y = (0, 0) if index == 0 else values[:2]
                points.append((x, y, *values[-3:]))
        self.color_points = points
        self._update_button_text()
