#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
颜色坐标选择器 - 支持点击屏幕获取坐标和颜色
用于找色功能的多点定位
"""

import logging
import ctypes
from ctypes import wintypes
from typing import Optional, Tuple, List
from PySide6.QtWidgets import (QWidget, QPushButton, QVBoxLayout, QHBoxLayout,
                                QMessageBox, QApplication, QLabel)
from PySide6.QtCore import Signal, QPoint, QRect, Qt, QTimer, QThread
from PySide6.QtGui import QPainter, QPen, QColor, QBrush, QImage, QPixmap

from utils.window_coordinate_common import (
    get_qt_virtual_desktop_rect,
    build_window_info,
    client_relative_to_qt_global,
    get_window_client_physical_size,
    normalize_window_hwnd,
)
from utils.window_overlay_utils import (
    draw_overlay_frame,
    fill_overlay_event_background,
    get_target_window_overlay_rect,
    overlay_point_to_client_qpoint,
    overlay_rect_contains_point,
    sync_overlay_geometry,
)
from utils.window_activation_utils import (
    activate_overlay_widget,
    activate_window,
    ensure_overlay_ready_for_input,
    show_and_activate_overlay,
)

logger = logging.getLogger(__name__)

try:
    _CCP_USER32 = ctypes.WinDLL("user32", use_last_error=True)

    _CCP_USER32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    _CCP_USER32.ScreenToClient.restype = wintypes.BOOL

    _CCP_USER32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    _CCP_USER32.SetWindowPos.restype = wintypes.BOOL

    _CCP_USER32.SetForegroundWindow.argtypes = [wintypes.HWND]
    _CCP_USER32.SetForegroundWindow.restype = wintypes.BOOL

    _CCP_USER32.SetActiveWindow.argtypes = [wintypes.HWND]
    _CCP_USER32.SetActiveWindow.restype = wintypes.HWND

    _CCP_USER32.EnableWindow.argtypes = [wintypes.HWND, wintypes.BOOL]
    _CCP_USER32.EnableWindow.restype = wintypes.BOOL
except Exception:
    _CCP_USER32 = None

# 导入窗口隐藏管理器
from utils.window_hider import WindowHider

# 导入主题管理器
try:
    from themes import get_theme_manager
    THEME_MANAGER_AVAILABLE = True
except ImportError:
    THEME_MANAGER_AVAILABLE = False
    logger.warning("主题管理器不可用，将使用默认颜色")

try:
    import win32gui
    import win32api
    import win32ui
    from PIL import Image
    import numpy as np
    PYWIN32_AVAILABLE = True
except ImportError:
    PYWIN32_AVAILABLE = False
    logger.warning("pywin32 not available, color coordinate picker may not work properly")


class GlobalInputMonitor(QThread):
    """全局输入监听线程 - 使用Windows钩子监听ESC和右键"""

    esc_pressed = Signal()
    right_click = Signal()

    # Windows钩子常量
    WH_KEYBOARD_LL = 13
    WH_MOUSE_LL = 14
    WM_KEYDOWN = 0x0100
    WM_RBUTTONDOWN = 0x0204
    VK_ESCAPE = 0x1B
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
                logger.error(f"键盘钩子安装失败: {ctypes.get_last_error()}")
                return
            if not self.mouse_hook:
                logger.error(f"鼠标钩子安装失败: {ctypes.get_last_error()}")
                return

            logger.info("全局输入监听器已启动（ESC键和右键）")

            # 消息循环（使用PeekMessage避免阻塞）
            msg = wintypes.MSG()
            while self._running:
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
            logger.error(f"全局输入监听器运行异常: {e}")
            import traceback
            logger.error(traceback.format_exc())
        finally:
            self.cleanup()

    def cleanup(self):
        """清理钩子"""
        try:
            UnhookWindowsHookEx = self._unhook_windows_hook_ex
            if UnhookWindowsHookEx is None:
                user32 = ctypes.WinDLL("user32", use_last_error=True)
                UnhookWindowsHookEx = user32.UnhookWindowsHookEx
                UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
                UnhookWindowsHookEx.restype = wintypes.BOOL
            if self.keyboard_hook:
                UnhookWindowsHookEx(self.keyboard_hook)
                self.keyboard_hook = None
            if self.mouse_hook:
                UnhookWindowsHookEx(self.mouse_hook)
                self.mouse_hook = None
            logger.info("全局输入监听器已停止")
        except Exception as e:
            logger.error(f"清理钩子时出错: {e}")
        finally:
            self._native_thread_id = None
            self._post_thread_message = None
            self._unhook_windows_hook_ex = None
            self._kernel32 = None
            self._user32 = None

    def stop(self):
        """停止监听"""
        self._running = False
        # 发送退出消息到线程
        try:
            if self._native_thread_id:
                PostThreadMessageW = self._post_thread_message
                if PostThreadMessageW is None:
                    user32 = ctypes.WinDLL("user32", use_last_error=True)
                    PostThreadMessageW = user32.PostThreadMessageW
                    PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
                    PostThreadMessageW.restype = wintypes.BOOL
                PostThreadMessageW(int(self._native_thread_id), 0x0012, 0, 0)  # WM_QUIT
        except Exception as e:
            logger.debug(f"发送退出消息失败: {e}")

class ColorCoordinatePickerOverlay(QWidget):
    """颜色坐标选择器覆盖层 - 点击获取坐标和颜色"""

    color_coordinate_selected = Signal(int, int, int, int, int)  # x, y, r, g, b

    def __init__(self, target_window_hwnd: int, parent=None, search_region=None, initial_points: Optional[List[Tuple[int, int, int, int, int]]] = None):
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
        self.magnifier_enabled = True  # 放大镜功能开关
        self.selected_points: List[Tuple[int, int, int, int, int]] = []
        if initial_points:
            for p in initial_points:
                try:
                    x, y, r, g, b = p
                    self.selected_points.append((int(x), int(y), int(r), int(g), int(b)))
                except Exception:
                    continue
            if self.selected_points:
                x, y, r, g, b = self.selected_points[-1]
                self.selected_color = (r, g, b)

        # 静态截图（在显示覆盖层时拍摄）
        self.static_screenshot = None
        self._static_screenshot_pixmap: Optional[QPixmap] = None
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
        self._activation_attempts = 0

        # 超时保护：30秒后自动关闭，避免长时间占用资源
        self.timeout_timer = QTimer(self)
        self.timeout_timer.setSingleShot(True)
        self.timeout_timer.setInterval(30000)  # 30秒超时
        self.timeout_timer.timeout.connect(self._on_timeout)

        # 全局输入监听器（不依赖窗口激活状态）
        self.input_monitor = GlobalInputMonitor()
        self.input_monitor.esc_pressed.connect(self._on_global_esc)
        self.input_monitor.right_click.connect(self._on_global_right_click)

        # 设置窗口属性
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Dialog  # 使用Dialog确保能接收键盘和鼠标事件
        )

        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._init_action_buttons()

        logger.info(f"创建颜色坐标选择器覆盖层，搜索区域: {search_region}")

        # 初始化
        self.setup_target_window()

    def capture_screenshot_before_show(self):
        """在显示覆盖层前拍摄静态截图（由外部调用）"""
        self._capture_static_screenshot()
        return self.static_screenshot is not None

    def setup_target_window(self):
        """设置目标窗口"""
        if not PYWIN32_AVAILABLE:
            logger.error("需要安装pywin32库")
            return False

        target_hwnd = int(self.target_window_hwnd or 0)
        if not target_hwnd:
            logger.error(f"无效的窗口句柄: {target_hwnd}")
            return False

        normalized_hwnd, normalized_title = normalize_window_hwnd(target_hwnd)
        if not normalized_hwnd:
            logger.error(f"窗口句柄无效或不可用: {target_hwnd}")
            return False

        if normalized_hwnd != target_hwnd:
            logger.info(f"窗口句柄已修正: {target_hwnd} -> {normalized_hwnd}")

        target_hwnd = normalized_hwnd
        self.target_window_hwnd = normalized_hwnd
        self.target_window_title = normalized_title or f"窗口{target_hwnd}"
        logger.info(f"使用窗口句柄: {target_hwnd}, 标题: {self.target_window_title}")

        # 获取窗口信息
        self.window_info = self._get_window_info(target_hwnd)
        if not self.window_info:
            logger.error("无法获取窗口信息")
            return False

        # 激活目标窗口
        self._activate_target_window(target_hwnd)

        # 设置覆盖层几何
        self._setup_overlay_geometry()

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

    def _activate_target_window(self, hwnd: int):
        """激活并置顶目标窗口。"""
        try:
            activation_hwnd = activate_window(hwnd, log_prefix='颜色取点')
            if not activation_hwnd:
                return

            logger.info(f"已激活并置顶目标窗口: {self.target_window_title}")

        except Exception as e:
            logger.warning(f"激活目标窗口失败: {e}")

    def _setup_overlay_geometry(self):
        """Set overlay geometry."""
        if not self.window_info:
            return

        screen_geometry = sync_overlay_geometry(self)
        logger.info(f"Overlay geometry set: {screen_geometry}")

    def _get_target_window_rect(self) -> QRect:
        """Get the target window client rect in overlay coordinates."""
        return get_target_window_overlay_rect(self, self.window_info)

    def _get_relative_coordinates(self, qt_screen_pos: QPoint) -> QPoint:
        """Convert Qt screen coordinates to client-relative coordinates."""
        if not self.window_info:
            return qt_screen_pos

        try:
            target_rect = self._get_target_window_rect()
            if target_rect.isEmpty():
                logger.warning("Target window rect is empty; cannot convert color coordinates")
                return qt_screen_pos

            return overlay_point_to_client_qpoint(self.window_info, target_rect, qt_screen_pos)
        except Exception as e:
            logger.error(f"Coordinate conversion error: {e}")
            return qt_screen_pos

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
            physical_width = max(1, int(physical_width or img_w))
            physical_height = max(1, int(physical_height or img_h))

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

    def _get_magnifier_layout(self, mouse_pos: QPoint) -> Optional[Tuple[QRect, QRect, int, int]]:
        """计算放大镜与信息框布局。"""
        if not self.window_info:
            return None

        relative_pos = self._get_relative_coordinates(mouse_pos)
        center_x = int(relative_pos.x())
        center_y = int(relative_pos.y())

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
        if mouse_pos.isNull():
            return QRect()
        if not self._is_point_in_target_window(mouse_pos):
            return QRect()

        layout = self._get_magnifier_layout(mouse_pos)
        if not layout:
            return QRect()

        mag_rect, info_rect, _cx, _cy = layout
        return mag_rect.united(info_rect).adjusted(-2, -2, 2, 2)

    def _request_magnifier_update(self, previous_pos: QPoint, current_pos: QPoint):
        """按旧/新位置局部刷新放大镜区域。"""
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

    def _position_action_buttons(self):
        """根据目标窗口位置摆放覆盖层按钮（优先目标区域右下方）。"""
        if not hasattr(self, "finish_button") or not hasattr(self, "cancel_button"):
            return

        gap = 8
        margin = 12
        anchor_rect = self._get_target_window_rect()
        if anchor_rect.isEmpty():
            anchor_rect = self.rect()

        total_w = self.finish_button.width() + self.cancel_button.width() + gap
        btn_h = self.finish_button.height()

        # 主定位：目标区域右下方（不挡右上角取色）
        x = anchor_rect.right() - total_w
        y = anchor_rect.bottom() + gap

        # 横向边界保护
        if x < margin:
            x = margin
        if x + total_w > self.width() - margin:
            x = self.width() - total_w - margin

        # 纵向边界保护：优先贴近底部，不上移到顶部
        if y + btn_h > self.height() - margin:
            y = self.height() - btn_h - margin
        if y < margin:
            y = margin

        x = int(x)
        y = int(y)
        self.finish_button.move(x, y)
        self.cancel_button.move(x + self.finish_button.width() + gap, y)

    def _apply_action_buttons_theme(self) -> None:
        """应用与截图工具一致的按钮风格。"""
        palette = {
            "text": "#333333",
            "text_disabled": "#999999",
            "surface": "#f5f5f5",
            "border": "#e0e0e0",
            "border_light": "#eeeeee",
            "hover": "#e8e8e8",
            "pressed": "#d8d8d8",
            "accent": "#0078d4",
            "accent_hover": "#1084d8",
            "accent_pressed": "#006cbe",
        }

        if THEME_MANAGER_AVAILABLE:
            try:
                theme_manager = get_theme_manager()
                for key in list(palette.keys()):
                    value = str(theme_manager.get_color(key) or "").strip()
                    if value:
                        palette[key] = value
            except Exception:
                pass

        surface_qc = QColor(palette["surface"])
        hover_qc = QColor(palette["hover"])
        pressed_qc = QColor(palette["pressed"])
        border_qc = QColor(palette["border"])

        if not surface_qc.isValid():
            surface_qc = QColor("#f5f5f5")
        if not hover_qc.isValid():
            hover_qc = QColor("#e8e8e8")
        if not pressed_qc.isValid():
            pressed_qc = QColor("#d8d8d8")
        if not border_qc.isValid():
            border_qc = QColor("#d0d0d0")

        surface_rgba = f"rgba({surface_qc.red()}, {surface_qc.green()}, {surface_qc.blue()}, 228)"
        hover_rgba = f"rgba({hover_qc.red()}, {hover_qc.green()}, {hover_qc.blue()}, 240)"
        pressed_rgba = f"rgba({pressed_qc.red()}, {pressed_qc.green()}, {pressed_qc.blue()}, 246)"
        border_rgba = f"rgba({border_qc.red()}, {border_qc.green()}, {border_qc.blue()}, 235)"

        common_style = (
            "outline: none;"
            "border-radius: 10px;"
            "padding: 0 14px;"
            'font-family: "Microsoft YaHei";'
            "font-size: 12px;"
            "font-weight: 600;"
            "min-height: 30px;"
            "letter-spacing: 0.5px;"
        )

        action_style = (
            f"""
            QPushButton#colorPickerFinishButton {{
                {common_style}
                background-color: {palette['accent']};
                color: #ffffff;
                border: 1px solid {palette['accent']};
            }}
            QPushButton#colorPickerFinishButton:hover {{
                background-color: {palette['accent_hover']};
                border-color: {palette['accent_hover']};
            }}
            QPushButton#colorPickerFinishButton:pressed {{
                background-color: {palette['accent_pressed']};
                border-color: {palette['accent_pressed']};
            }}
            QPushButton#colorPickerFinishButton:focus {{
                outline: none;
                border: 1px solid {palette['accent_hover']};
            }}
            QPushButton#colorPickerFinishButton:disabled {{
                background-color: {palette['surface']};
                color: {palette['text_disabled']};
                border: 1px solid {palette['border_light']};
            }}

            QPushButton#colorPickerCancelButton {{
                {common_style}
                background-color: {surface_rgba};
                color: {palette['text']};
                border: 1px solid {border_rgba};
            }}
            QPushButton#colorPickerCancelButton:hover {{
                background-color: {hover_rgba};
                border-color: {border_rgba};
            }}
            QPushButton#colorPickerCancelButton:pressed {{
                background-color: {pressed_rgba};
                border-color: {border_rgba};
            }}
            QPushButton#colorPickerCancelButton:focus {{
                outline: none;
                border: 1px solid {border_rgba};
            }}
            QPushButton#colorPickerCancelButton:disabled {{
                background-color: {palette['surface']};
                color: {palette['text_disabled']};
                border: 1px solid {palette['border_light']};
            }}
            """
        )

        self.finish_button.setStyleSheet(action_style)
        self.cancel_button.setStyleSheet(action_style)

    def _on_finish_clicked(self):
        """完成取色并关闭覆盖层。"""
        logger.info("取色覆盖层点击完成，关闭覆盖层")
        self.close()

    def _on_cancel_clicked(self):
        """取消取色并关闭覆盖层。"""
        logger.info("取色覆盖层点击取消，关闭覆盖层")
        self.close()

    def _get_static_screenshot_pixmap(self) -> Optional[QPixmap]:
        """将静态截图转换为可绘制的 QPixmap（懒加载）。"""
        if self._static_screenshot_pixmap is not None:
            return self._static_screenshot_pixmap

        screenshot = self.static_screenshot
        if screenshot is None or getattr(screenshot, 'size', 0) == 0:
            return None

        try:
            rgb = screenshot[:, :, ::-1]
            h, w = rgb.shape[:2]
            image = QImage(rgb.data, w, h, int(rgb.strides[0]), QImage.Format.Format_RGB888)
            self._static_screenshot_pixmap = QPixmap.fromImage(image.copy())
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
        """绘制已选择的全部颜色点。"""
        if not self.selected_points:
            return

        crosshair_outer_color = self._get_picker_color('picker_crosshair_outer')
        crosshair_inner_color = self._get_picker_color('picker_crosshair_inner')
        text_color = self._get_picker_color('picker_text')
        text_bg_color = self._get_picker_color('picker_text_bg')

        for idx, (x, y, r, g, b) in enumerate(self.selected_points):
            point = self._relative_to_overlay_point(x, y)
            if point is None:
                continue

            is_last = idx == len(self.selected_points) - 1
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
            painter.setBrush(QBrush(QColor(text_bg_color.red(), text_bg_color.green(), text_bg_color.blue(), 180)))
            painter.setPen(QPen(text_color, 1))
            painter.drawRect(idx_bg)
            painter.drawText(idx_pos, index_text)

        last_x, last_y, last_r, last_g, last_b = self.selected_points[-1]
        last_point = self._relative_to_overlay_point(last_x, last_y)
        if last_point is not None:
            info_text = f"坐标: ({last_x}, {last_y})  颜色: RGB({last_r},{last_g},{last_b})"
            text_rect = painter.fontMetrics().boundingRect(info_text)
            text_pos = last_point + QPoint(35, -10)
            bg_rect = text_rect.translated(text_pos)
            bg_rect.adjust(-5, -2, 5, 2)
            painter.setBrush(QBrush(QColor(text_bg_color.red(), text_bg_color.green(), text_bg_color.blue(), 180)))
            painter.setPen(QPen(text_color, 1))
            painter.drawRect(bg_rect)
            painter.drawText(text_pos, info_text)


    def _get_picker_color(self, color_key: str) -> QColor:
        """从主题管理器获取颜色选择器的颜色"""
        if THEME_MANAGER_AVAILABLE:
            try:
                theme_mgr = get_theme_manager()
                return theme_mgr.get_qcolor(color_key)
            except Exception as e:
                logger.warning(f"从主题管理器获取颜色失败 ({color_key}): {e}")

        # 回退到默认硬编码颜色
        default_colors = {
            'picker_target_border': QColor(0, 255, 0),
            'picker_search_border': QColor(255, 255, 0),
            'picker_search_bg': QColor(255, 255, 0),
            'picker_crosshair_outer': QColor(255, 255, 255),
            'picker_crosshair_inner': QColor(255, 0, 0),
            'picker_text': QColor(255, 255, 255),
            'picker_text_bg': QColor(0, 0, 0),
        }
        return default_colors.get(color_key, QColor(255, 255, 255))

    def paintEvent(self, event):
        """绘制事件"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        fill_overlay_event_background(painter, self)

        if self.window_info:
            target_rect = self._get_target_window_rect()
            if target_rect.isEmpty():
                target_rect = QRect()

            if not target_rect.isEmpty():
                static_pixmap = self._get_static_screenshot_pixmap()
                if static_pixmap is not None and not static_pixmap.isNull():
                    painter.drawPixmap(target_rect, static_pixmap)

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
                               "左键连续取色，完成后点‘完成取色’")

        # 绘制已选择点
        self._draw_selected_points(painter)

        # 绘制放大镜预览
        if self.magnifier_enabled and not self.mouse_pos.isNull() and self.window_info:
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

            # 背景与边框
            painter.fillRect(mag_rect, QColor(40, 40, 40, 220))
            text_color = self._get_picker_color('picker_text')
            painter.setPen(QPen(text_color, 2))
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
            painter.setPen(QPen(QColor(100, 100, 100), 1))
            for i in range(grid_size + 1):
                x = mag_rect.x() + i * pixel_size
                y = mag_rect.y() + i * pixel_size
                painter.drawLine(x, mag_rect.y(), x, mag_rect.y() + mag_rect.height())
                painter.drawLine(mag_rect.x(), y, mag_rect.x() + mag_rect.width(), y)

            # 坐标与颜色文本
            center_color = self._get_pixel_color_from_screenshot(center_x, center_y)
            if center_color is None:
                center_color = self._get_pixel_color_at_position(center_x, center_y)

            if center_color:
                r, g, b = center_color
                info_text = f"({center_x},{center_y}) RGB({r},{g},{b})"

                painter.setPen(QPen(text_color))
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
        super().showEvent(event)

        # 如果还没有拍摄静态截图，现在拍摄（兜底逻辑）
        if self.static_screenshot is None:
            logger.warning("showEvent中检测到静态截图为空，执行兜底截图")
            self._capture_static_screenshot()

        # 启动放大镜定时器
        if self.magnifier_enabled:
            self.magnifier_timer.start()
            logger.info("放大镜定时器已启动")

        self._position_action_buttons()

        # 不自动关闭覆盖层：由用户点击“完成取色”后再销毁

        # 使用窗口隐藏管理器隐藏所有应用窗口，避免颜色干扰找色
        hidden_count = self.window_hider.hide_all()
        logger.info(f"已隐藏 {hidden_count} 个窗口以避免颜色干扰找色")

        # 启动全局输入监听器
        logger.info("准备启动全局输入监听器...")
        self.input_monitor.start()
        # 等待线程启动
        import time
        time.sleep(0.1)
        if self.input_monitor.isRunning():
            logger.info("全局输入监听器线程已启动")
        else:
            logger.error("全局输入监听器线程启动失败")

        # 延迟激活，确保窗口系统完成所有初始化
        QTimer.singleShot(250, self._ensure_ready_for_input)

    def _on_timeout(self):
        """超时自动关闭"""
        logger.warning("取色器超时（30秒未操作），自动关闭以释放资源")
        self.close()

    def _capture_static_screenshot(self):
        """在显示覆盖层时拍摄静态截图，确保鼠标不在游戏画面中"""
        try:
            # 仅在使用 WGC 引擎时清理 WGC 缓存，避免与其他引擎日志混淆
            try:
                from utils.screenshot_helper import get_screenshot_engine
                engine = get_screenshot_engine()
            except Exception:
                engine = "unknown"

            if engine == "wgc":
                try:
                    from utils.screenshot_helper import clear_screenshot_cache
                    clear_screenshot_cache()
                    logger.debug("WGC缓存已清理")
                except Exception as e:
                    logger.debug(f"清理WGC缓存失败: {e}")

            from PySide6.QtGui import QCursor

            # 保存当前鼠标位置
            self.original_mouse_pos = QCursor.pos()
            logger.info(f"保存原始鼠标位置: ({self.original_mouse_pos.x()}, {self.original_mouse_pos.y()})")

            # 将鼠标移到屏幕右下角，远离目标窗口
            virtual_geometry = get_qt_virtual_desktop_rect()
            if not virtual_geometry or virtual_geometry.isEmpty():
                raise RuntimeError("无法获取屏幕信息")
            target_x = int(virtual_geometry.left() + max(1, virtual_geometry.width()) - 10)
            target_y = int(virtual_geometry.top() + max(1, virtual_geometry.height()) - 10)
            QCursor.setPos(target_x, target_y)
            logger.info(f"鼠标移动到屏幕外: ({target_x}, {target_y})")

            # 等待游戏更新画面（移除光标）
            QApplication.processEvents()
            import time
            time.sleep(0.15)  # 150ms延迟，确保游戏有时间更新

            # 截取窗口 - 使用当前截图引擎强制捕获最新帧
            hwnd = int(self.window_info['hwnd'])

            # 导入统一截图功能
            from tasks.task_utils import capture_window_smart
            self.static_screenshot = capture_window_smart(hwnd, client_area_only=True)

            if self.static_screenshot is not None:
                logger.info(f"静态截图成功，尺寸: {self.static_screenshot.shape}")
                # 静态截图变化后重置缓存的QPixmap
                self._static_screenshot_pixmap = None
                # 同时设置为缓存截图
                self.cached_screenshot = self.static_screenshot
                self.screenshot_cache_time = time.time()
                self._magnifier_cache_center = None
                self._magnifier_cache_pixmap = None
            else:
                logger.error("无法截取静态截图")

            # 恢复鼠标位置
            if self.original_mouse_pos:
                QCursor.setPos(self.original_mouse_pos)
                logger.info(f"恢复鼠标位置到: ({self.original_mouse_pos.x()}, {self.original_mouse_pos.y()})")

        except Exception as e:
            logger.error(f"截取静态截图失败: {e}")
            import traceback
            logger.error(traceback.format_exc())

    def _ensure_ready_for_input(self):
        """确保覆盖层准备好接收输入"""
        ensure_overlay_ready_for_input(
            self,
            log_prefix='颜色取点覆盖层',
            ready_message='颜色坐标选择器已就绪，可以接收输入',
            retry_message='颜色坐标选择器未能激活（尝试 {attempt}/{max_attempts}），用户首次点击可能需要激活窗口',
            exhausted_message='已达到最大激活尝试次数，继续执行（用户首次操作将用于激活窗口）',
            auto_show=True,
        )

    def mouseMoveEvent(self, event):
        """鼠标移动事件 - 仅局部刷新放大镜区域，避免全屏重绘卡顿"""
        previous_pos = QPoint(self.mouse_pos)
        self.mouse_pos = event.pos()

        # 用户有活动，重置超时定时器
        if hasattr(self, 'timeout_timer') and self.timeout_timer.isActive():
            self.timeout_timer.start()  # 重新开始计时

        if self.magnifier_enabled:
            self._request_magnifier_update(previous_pos, self.mouse_pos)
            self._last_magnifier_mouse_pos = QPoint(self.mouse_pos)

        event.accept()

    def _update_magnifier(self):
        """定时更新放大镜（仅在鼠标位置变化时局部刷新）"""
        if not self.magnifier_enabled or self.mouse_pos.isNull():
            return

        if self.mouse_pos == self._last_magnifier_mouse_pos:
            return

        previous_pos = QPoint(self._last_magnifier_mouse_pos)
        self._last_magnifier_mouse_pos = QPoint(self.mouse_pos)
        self._request_magnifier_update(previous_pos, self.mouse_pos)

    def _on_global_esc(self):
        """全局ESC键处理（通过钩子触发，不依赖窗口激活）"""
        logger.info("[全局钩子] ESC键退出")
        # 使用QTimer.singleShot确保在主线程中执行close
        QTimer.singleShot(0, self.close)

    def _on_global_right_click(self):
        """全局右键处理（通过钩子触发，不依赖窗口激活）"""
        logger.info("[全局钩子] 右键取消选择")
        # 使用QTimer.singleShot确保在主线程中执行close
        QTimer.singleShot(0, self.close)

    def mousePressEvent(self, event):
        """鼠标按下事件"""
        logger.info(f"[鼠标事件] 接收到鼠标按下事件: 按钮={event.button()}, 位置={event.pos()}")

        # 接受事件，防止穿透到下层窗口
        event.accept()

        # 用户开始操作，停止超时定时器
        if hasattr(self, 'timeout_timer') and self.timeout_timer.isActive():
            self.timeout_timer.stop()
            logger.debug("用户开始操作，超时定时器已停止")

        if not self.isActiveWindow():
            logger.warning("覆盖层未激活，尝试重新激活")
            activate_overlay_widget(self, log_prefix='颜色取点覆盖层', focus=True)
            self._is_ready_for_input = True

        if event.button() == Qt.MouseButton.LeftButton:
            logger.info(f"[鼠标事件] 左键点击")
            if self._is_point_in_target_window(event.pos()):
                logger.info(f"[鼠标事件] 点击位置在目标窗口内")
                self.click_pos = event.pos()

                # 转换为相对坐标
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
                logger.warning(f"[鼠标事件] 点击位置不在目标窗口内")

        elif event.button() == Qt.MouseButton.RightButton:
            logger.info("[鼠标事件] 右键点击，取消选择")
            self.close()

    def keyPressEvent(self, event):
        """键盘事件"""
        logger.info(f"[键盘事件] 接收到键盘事件: 键={event.key()}")
        if event.key() == Qt.Key.Key_Escape:
            logger.info("ESC键退出")
            self.close()
        event.accept()

    def closeEvent(self, event):
        """关闭事件 - 清理所有资源"""
        try:
            # 停止全局输入监听器
            if hasattr(self, 'input_monitor') and self.input_monitor.isRunning():
                self.input_monitor.stop()
                self.input_monitor.wait(1000)  # 等待线程结束
                logger.info("全局输入监听器已停止")

            # 停止所有定时器
            if hasattr(self, 'magnifier_timer') and self.magnifier_timer.isActive():
                self.magnifier_timer.stop()
                logger.info("放大镜定时器已停止")

            if hasattr(self, 'timeout_timer') and self.timeout_timer.isActive():
                self.timeout_timer.stop()
                logger.info("超时定时器已停止")

            # 清理静态截图，释放内存
            if hasattr(self, 'static_screenshot') and self.static_screenshot is not None:
                self.static_screenshot = None
                logger.debug("静态截图已清理")

            if hasattr(self, 'cached_screenshot') and self.cached_screenshot is not None:
                self.cached_screenshot = None
                logger.debug("缓存截图已清理")

            if hasattr(self, '_static_screenshot_pixmap') and self._static_screenshot_pixmap is not None:
                self._static_screenshot_pixmap = None

            self._magnifier_cache_center = None
            self._magnifier_cache_pixmap = None
            self._last_magnifier_mouse_pos = QPoint()
    
            if hasattr(self, 'selected_points'):
                self.selected_points = []

            if hasattr(self, 'original_mouse_pos'):
                self.original_mouse_pos = None

            logger.debug("取色器资源已全部释放")

            # 使用窗口隐藏管理器恢复所有应用窗口
            restored_count = self.window_hider.restore_all()
            logger.info(f"已恢复 {restored_count} 个窗口显示")

        except Exception as e:
            logger.error(f"关闭取色器时出错: {e}")
            import traceback
            logger.error(traceback.format_exc())
        finally:
            super().closeEvent(event)

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
            self.select_button.setText(f"已选择1个点")
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
        color_preview.setStyleSheet(f"background-color: rgb({r}, {g}, {b}); border: 1px solid #999; border-radius: 3px;")
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
        """从编辑器获取绑定的窗口句柄"""
        try:
            current_widget = self.parent()
            level = 0

            while current_widget and level < 10:
                # 检查bound_windows
                if hasattr(current_widget, 'bound_windows'):
                    bound_windows = current_widget.bound_windows
                    if bound_windows and len(bound_windows) > 0:
                        for window_info in bound_windows:
                            if window_info.get('enabled', True):
                                hwnd = window_info.get('hwnd')
                                if hwnd:
                                    logger.info(f"从bound_windows获取窗口句柄: {hwnd}")
                                    return hwnd
                        # 使用第一个窗口
                        hwnd = bound_windows[0].get('hwnd')
                        if hwnd:
                            return hwnd

                # 检查config
                if hasattr(current_widget, 'config'):
                    config = current_widget.config
                    if hasattr(config, 'bound_windows') and config.bound_windows:
                        enabled_windows = [w for w in config.bound_windows if w.get('enabled', True)]
                        if enabled_windows:
                            return enabled_windows[0].get('hwnd')

                current_widget = current_widget.parent()
                level += 1

            return None

        except Exception as e:
            logger.error(f"获取绑定窗口句柄失败: {e}")
            return None

    def _validate_hwnd_silent(self, hwnd):
        """
        静默验证句柄是否在全局绑定列表中
        如果无效，返回第一个有效句柄，不弹窗，不修改self.target_window_hwnd

        Args:
            hwnd: 要验证的窗口句柄

        Returns:
            验证后的有效句柄，如果没有可用窗口则返回None
        """
        try:
            # 查找主窗口
            main_window = None
            current_widget = self.parent()
            while current_widget:
                if hasattr(current_widget, 'is_hwnd_bound'):
                    main_window = current_widget
                    break
                current_widget = current_widget.parent()

            if not main_window:
                logger.warning("未找到主窗口，无法验证句柄")
                return hwnd

            # 验证句柄
            if hwnd and main_window.is_hwnd_bound(hwnd):
                return hwnd

            # 句柄无效，静默获取第一个有效句柄
            logger.warning(f"句柄 {hwnd} 不在绑定列表中，静默切换到第一个有效句柄")
            validated_hwnd, is_original = main_window.validate_hwnd_or_get_first(hwnd)

            if validated_hwnd:
                logger.info(f"已静默切换到有效句柄: {validated_hwnd}（不修改原句柄 {hwnd}）")
            else:
                logger.error(f"句柄 {hwnd} 无效且没有其他可用窗口")

            return validated_hwnd

        except Exception as e:
            logger.error(f"验证句柄失败: {e}")
            return hwnd  # 出错时返回原句柄

    def start_selection(self):
        """开始颜色坐标选择"""
        if self.overlay and not self.overlay.isVisible():
            try:
                self.overlay.deleteLater()
            except Exception:
                pass
            self.overlay = None

        # 如果没有设置目标窗口，尝试自动获取
        if not self.target_window_hwnd:
            self.target_window_hwnd = self._get_bound_window_hwnd()
            if not self.target_window_hwnd:
                QMessageBox.warning(self, "警告", "未找到绑定的窗口，请先绑定目标窗口")
                return

        # 【新增】验证句柄是否在全局绑定列表中（静默处理）
        validated_hwnd = self._validate_hwnd_silent(self.target_window_hwnd)
        if not validated_hwnd:
            QMessageBox.warning(self, "警告", "没有可用的绑定窗口，请先在全局设置中绑定窗口")
            return

        # 找到顶层对话框父窗口
        parent_dialog = self.window()

        if self.overlay and self.overlay.isVisible():
            activate_overlay_widget(self.overlay, log_prefix='颜色取点覆盖层', focus=True)
            return

        # 创建覆盖层，传递父窗口引用和搜索区域，使用验证后的句柄
        # IMPORTANT: 保存为实例变量，防止被垃圾回收
        self.overlay = ColorCoordinatePickerOverlay(
            validated_hwnd,
            parent_dialog,
            search_region=self.search_region,
            initial_points=self.color_points
        )
        self.overlay.color_coordinate_selected.connect(self._on_color_coordinate_selected)
        self.overlay.destroyed.connect(lambda *_: setattr(self, "overlay", None))

        if self.overlay.setup_target_window():
            # 在显示覆盖层前拍摄静态截图
            logger.info("准备拍摄静态截图...")
            if self.overlay.capture_screenshot_before_show():
                logger.info("静态截图拍摄成功，显示覆盖层")
                show_and_activate_overlay(self.overlay, log_prefix='颜色取点覆盖层启动', focus=True)
                logger.info("颜色坐标选择器覆盖层已显示")
            else:
                logger.error("静态截图拍摄失败")
                try:
                    self.overlay.deleteLater()
                except Exception:
                    pass
                self.overlay = None
                QMessageBox.critical(self, "错误", "无法拍摄窗口截图，请重试")
        else:
            try:
                self.overlay.deleteLater()
            except Exception:
                pass
            self.overlay = None
            QMessageBox.critical(self, "错误", "无法设置目标窗口")

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
        """从颜色字符串解析并设置颜色点"""
        try:
            self.color_points = []

            if not color_string:
                self._update_button_text()
                return

            # 检查是否是多点格式
            if '|' in color_string:
                # 多点定位格式: R,G,B|offsetX,offsetY,R,G,B|...
                parts = color_string.split('|')

                # 【闪退修复】使用try-except保护颜色解析
                try:
                    # 第一个点（基准点）
                    base_parts = [int(c.strip()) for c in parts[0].split(',')]
                    if len(base_parts) != 3:
                        logger.error(f"基准点格式错误: 期望3个值，实际{len(base_parts)}个，输入: {parts[0]}")
                        return

                    r0, g0, b0 = base_parts
                except (ValueError, IndexError) as e:
                    logger.error(f"基准点颜色值解析失败: {parts[0] if parts else color_string}, 错误: {e}")
                    return

                x0, y0 = 0, 0  # 基准点坐标需要在实际点击时确定
                self.color_points.append((x0, y0, r0, g0, b0))

                # 后续偏移点
                for i in range(1, len(parts)):
                    try:
                        offset_parts = [int(c.strip()) for c in parts[i].split(',')]
                        if len(offset_parts) != 5:
                            logger.warning(f"偏移点{i}格式错误: 期望5个值，实际{len(offset_parts)}个，输入: {parts[i]}")
                            continue

                        offset_x, offset_y, r, g, b = offset_parts
                    except (ValueError, IndexError) as e:
                        logger.error(f"偏移点{i}解析失败: {parts[i]}, 错误: {e}")
                        continue

                    x = x0 + offset_x
                    y = y0 + offset_y
                    self.color_points.append((x, y, r, g, b))
            else:
                # 单颜色格式: R,G,B
                parts = [int(c.strip()) for c in color_string.split(',')]
                if len(parts) == 3:
                    r, g, b = parts
                    self.color_points.append((0, 0, r, g, b))

            self._update_button_text()

        except Exception as e:
            logger.error(f"解析颜色字符串失败: {e}")
