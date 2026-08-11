#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OCR区域选择工具
使用截图方式在绑定窗口客户区域内框选OCR识别区域
"""

import logging
from typing import Any, Dict, Optional, Tuple
from PySide6.QtWidgets import (
    QWidget, QPushButton, QVBoxLayout, QMessageBox, QApplication
)
from PySide6.QtCore import Qt, Signal, QRect, QPoint
from PySide6.QtGui import QPainter, QPen, QColor

from utils.window_finder import resolve_unique_window_hwnd

from utils.app_paths import get_config_path
from utils.window_coordinate_common import (
    get_qt_virtual_desktop_rect,
    build_window_info,
    get_window_client_logical_size,
    get_window_client_physical_size,
    overlay_local_rect_to_client_relative,
    normalize_region_binding_hwnd,
    normalize_window_hwnd,
)
from utils.window_overlay_utils import (
    draw_selection_overlay,
    draw_target_window_overlay,
    fill_overlay_event_background,
    map_native_rect_to_local,
    overlay_point_to_client_qpoint,
    overlay_rect_contains_point,
    refresh_target_window_overlay_rect,
    sync_overlay_geometry,
)
from utils.window_activation_utils import (
    activate_overlay_widget,
    activate_window,
    ensure_overlay_ready_for_input,
    schedule_overlay_activation_boost,
    show_and_activate_overlay,
)

# Windows API 相关导入
try:
    import win32gui
    PYWIN32_AVAILABLE = True
except ImportError:
    PYWIN32_AVAILABLE = False

logger = logging.getLogger(__name__)

class OCRRegionSelectorOverlay(QWidget):
    """OCR区域选择覆盖层"""

    region_selected = Signal(int, int, int, int)  # x, y, width, height
    overlay_closed = Signal()  # 覆盖层关闭信号

    def __init__(self, target_window_title: str = None, target_window_hwnd: int = None, parent=None):
        # 重要：不设置parent，让覆盖层完全独立
        super().__init__(None)  # 传入None作为parent
        self.target_window_title = target_window_title
        self.target_hwnd = target_window_hwnd  # 直接使用传入的窗口句柄
        self.window_info = None
        self._closing = False

        # 选择状态
        self.selecting = False
        self.selection_pending = False
        self.start_pos = QPoint()
        self.end_pos = QPoint()
        self.selection_rect = QRect()
        self.selection_info_text = ""
        self.target_window_rect = QRect()

        # 窗口激活状态标志
        self._is_ready_for_input = False
        self._activation_attempts = 0

        # 设置窗口属性（移除有问题的标志以改善事件处理）
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )

        # 强制设置为非模态，完全独立运行
        self.setWindowModality(Qt.WindowModality.NonModal)

        # 设置窗口透明但确保能接收鼠标事件
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        # 设置鼠标追踪和焦点
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        logger.info("创建OCR区域选择覆盖层")

        # 显示提示信息
        logger.info("OCR区域选择器已启动")
        logger.info("使用说明:")
        logger.info("在绿色边框的目标窗口内拖拽鼠标进行选择")
        logger.info("右键点击或按ESC键取消选择")
        logger.info("选择完成后会自动填充坐标参数")
        
    def setup_target_window(self):
        """设置目标窗口并进行截图"""
        if not PYWIN32_AVAILABLE:
            QMessageBox.critical(self, "错误", "需要安装pywin32库")
            return False

        # 优先使用传入句柄，否则按标题查找句柄
        target_hwnd = int(self.target_hwnd or 0)
        if not target_hwnd:
            target_hwnd = self._find_window_by_title(self.target_window_title)
            if not target_hwnd:
                QMessageBox.warning(self, "警告", f"未找到窗口: {self.target_window_title}")
                return False

        normalized_hwnd, normalized_title = normalize_window_hwnd(
            target_hwnd,
            title_hint=self.target_window_title or "",
        )
        if not normalized_hwnd:
            QMessageBox.warning(self, "警告", f"窗口不可用: {self.target_window_title or target_hwnd}")
            return False

        if normalized_hwnd != target_hwnd:
            logger.info(f"[窗口查找] 窗口句柄已修正: {target_hwnd} -> {normalized_hwnd}")

        self.target_hwnd = normalized_hwnd
        self.target_window_title = normalized_title or f"窗口{normalized_hwnd}"
        logger.info(f"[窗口查找] 使用窗口句柄: {self.target_hwnd}, 标题: {self.target_window_title}")

        # 激活并置顶目标窗口
        self._activate_target_window(self.target_hwnd)

        # 获取窗口信息
        self.window_info = self._get_window_info(self.target_hwnd)
        if not self.window_info:
            QMessageBox.warning(self, "警告", "无法获取窗口信息")
            return False

        # 【强制获取新帧】在截图前先强制捕获目标窗口最新帧，确保显示最新内容
        logger.info("[OCR框选] 捕获目标窗口最新帧...")
        try:
            from tasks.task_utils import capture_window_smart
            # 强制获取最新帧
            temp_frame = capture_window_smart(self.target_hwnd, client_area_only=True)
            if temp_frame is not None:
                logger.info(f"[OCR框选] 捕获成功，尺寸: {temp_frame.shape}")
            else:
                logger.warning("[OCR框选] 捕获失败，继续使用全屏截图")
        except Exception as e:
            logger.warning(f"[OCR框选] 捕获异常: {e}，继续使用全屏截图")

        # 进行全屏截图
        if not self._take_screenshot():
            QMessageBox.warning(self, "警告", "无法进行截图")
            return False

        # 设置全屏覆盖
        self._setup_fullscreen_overlay()

        # 验证窗口位置是否正确（通过检查绿色边框是否在正确位置）
        self._verify_window_position()

        return True
        
    def _find_window_by_title(self, title: str) -> Optional[int]:
        """根据标题查找窗口（使用统一的窗口查找工具）"""
        if not title:
            return None

        logger.info(f"[窗口查找] 开始查找窗口: '{title}'")
        normalized_hwnd = resolve_unique_window_hwnd(title)

        if not normalized_hwnd:
            logger.error(f"[窗口查找] 未找到任何匹配窗口: '{title}'")
            return None

        logger.info(f"[窗口查找] 选中窗口: '{title}' (句柄: {normalized_hwnd})")
        return normalized_hwnd

    def _activate_target_window(self, hwnd: int):
        """激活并置顶目标窗口。"""
        try:
            activation_hwnd = activate_window(hwnd, log_prefix='OCR区域选择')
            if not activation_hwnd:
                return

            logger.info(f"已激活并置顶目标窗口: {self.target_window_title}")

        except Exception as e:
            logger.warning(f"激活目标窗口失败: {e}")
            # 即使激活失败也继续执行，不影响框选功能

    def _get_window_info(self, hwnd: int) -> Optional[dict]:
        """获取窗口详细信息（修复版：参考WGC和截图工具的坐标转换）"""
        try:
            # 获取窗口类名和标题用于调试
            window_title = win32gui.GetWindowText(hwnd)
            window_class = win32gui.GetClassName(hwnd)

            logger.info(f" [窗口调试] 目标窗口: '{window_title}' (类名: {window_class}, 句柄: {hwnd})")

            base_info = build_window_info(hwnd)
            if not base_info:
                return None

            qt_device_pixel_ratio = float(base_info.get('qt_device_pixel_ratio', 1.0))
            if qt_device_pixel_ratio <= 0:
                qt_device_pixel_ratio = 1.0
            qt_dpi = 96.0 * qt_device_pixel_ratio
            actual_dpi = int(qt_dpi)

            # 检查是否为雷电模拟器的TheRender窗口
            if window_class == "RenderWindow" and window_title == "TheRender":
                logger.info(" [窗口调试] 检测到雷电模拟器TheRender窗口，查找父窗口...")

                # 获取父窗口（主窗口）
                parent_hwnd = win32gui.GetParent(hwnd)
                if parent_hwnd:
                    parent_title = win32gui.GetWindowText(parent_hwnd)
                    parent_class = win32gui.GetClassName(parent_hwnd)
                    logger.info(f" [窗口调试] 父窗口: '{parent_title}' (类名: {parent_class}, 句柄: {parent_hwnd})")

                    # 如果父窗口是LDPlayerMainFrame，使用混合策略
                    if parent_class == "LDPlayerMainFrame":
                        logger.info(" [窗口调试] 使用混合策略：父窗口用于截图，TheRender用于坐标")

                        # 保持TheRender句柄用于坐标计算，但增加父窗口句柄用于截图
                        window_info = dict(base_info)
                        window_rect = window_info['window_rect']
                        client_rect = window_info['client_rect']
                        client_screen_pos = window_info.get('client_qt_screen_pos', window_info['client_screen_pos'])
                        window_info.update({
                            'parent_hwnd': parent_hwnd,
                            'qt_dpi': qt_dpi,
                            'qt_device_pixel_ratio': qt_device_pixel_ratio,
                            'actual_dpi': actual_dpi,
                            'scale_factor': qt_device_pixel_ratio,
                            'is_ldplayer': True,
                        })

                        logger.info(f" [窗口调试] 混合策略设置完成")
                        logger.info(f" [窗口调试] TheRender窗口矩形: {window_rect}")
                        logger.info(f" [窗口调试] TheRender客户区矩形: {client_rect}")
                        logger.info(f" [窗口调试] TheRender客户区屏幕位置(逻辑坐标): {client_screen_pos}")
                        logger.info(f" [关键验证] 客户区位置: {client_screen_pos}")

                        return window_info

            # 标准窗口处理（包括非雷电模拟器窗口和雷电其他情况）
            window_info = dict(base_info)
            window_rect = window_info['window_rect']
            client_rect = window_info['client_rect']
            client_screen_pos = window_info.get('client_qt_screen_pos', window_info['client_screen_pos'])
            window_info.update({
                'qt_dpi': qt_dpi,
                'qt_device_pixel_ratio': qt_device_pixel_ratio,
                'actual_dpi': actual_dpi,
                'scale_factor': qt_device_pixel_ratio,
            })
            logical_width, logical_height = get_window_client_logical_size(window_info)
            physical_width = int(window_info.get('client_physical_width', 0) or 0)
            physical_height = int(window_info.get('client_physical_height', 0) or 0)

            logger.info(f" [窗口调试] 最终窗口矩形: {window_rect}")
            logger.info(f" [窗口调试] 最终客户区矩形: {client_rect}")
            logger.info(f" [窗口调试] 最终客户区屏幕位置(逻辑坐标): {client_screen_pos}")
            logger.info(f"窗口信息: 客户区位置({client_screen_pos}), "
                       f"逻辑尺寸({logical_width}x{logical_height}), "
                       f"物理尺寸({physical_width}x{physical_height})")
            logger.info(f"DPI信息: Qt逻辑DPI={qt_dpi:.1f}, 设备像素比={qt_device_pixel_ratio:.2f}, 实际DPI={actual_dpi}")
            logger.info(f"缩放百分比: {qt_device_pixel_ratio*100:.0f}%")

            logger.info(f" [关键验证] 客户区位置: {client_screen_pos}")

            return window_info

        except Exception as e:
            logger.error(f"获取窗口信息失败: {e}")
            return None
            
    def _take_screenshot(self) -> bool:
        """进行全屏截图"""
        try:
            from PySide6.QtWidgets import QApplication
            from PySide6.QtGui import QPainter, QPixmap

            screens = QApplication.screens()
            primary = QApplication.primaryScreen()
            if not screens or not primary:
                logger.error("无法获取屏幕信息")
                return False

            virtual_geometry = get_qt_virtual_desktop_rect()
            if virtual_geometry.isEmpty():
                logger.error("虚拟桌面范围为空")
                return False

            screenshot = QPixmap(virtual_geometry.size())
            screenshot.fill(Qt.GlobalColor.transparent)

            painter = QPainter(screenshot)
            for screen in screens:
                shot = screen.grabWindow(0)
                if shot.isNull():
                    continue
                offset = screen.geometry().topLeft() - virtual_geometry.topLeft()
                painter.drawPixmap(offset, shot)
            painter.end()

            self.screenshot = screenshot
            if self.screenshot.isNull():
                logger.error("截图失败")
                return False

            logger.info(f"截图成功 (Qt备用): {self.screenshot.width()}x{self.screenshot.height()}")
            return True

        except Exception as e:
            logger.error(f"截图失败: {e}")
            return False

    def _setup_fullscreen_overlay(self):
        """Set fullscreen overlay geometry."""
        screen_geometry = sync_overlay_geometry(self)
        self._refresh_target_window_rect(force=True)
        logger.info(f"Fullscreen overlay set: {screen_geometry}")

    def _native_rect_to_overlay_rect(self, native_rect: Tuple[int, int, int, int]) -> QRect:
        """Convert a Win32 native rect to an overlay-local Qt rect."""
        return map_native_rect_to_local(self, native_rect)

    def _refresh_target_window_rect(self, *, force: bool = False) -> QRect:
        """Refresh the target window client rect in overlay coordinates."""
        if not self.window_info:
            self.target_window_rect = QRect()
            return QRect()

        if self.selecting and not force and not self.target_window_rect.isEmpty():
            return QRect(self.target_window_rect)

        target_rect = refresh_target_window_overlay_rect(self, self.window_info)
        self.target_window_rect = QRect(target_rect)
        return QRect(self.target_window_rect)

    def _get_target_window_rect(self, refresh: bool = False) -> QRect:
        """Get the target window client rect in overlay coordinates."""
        if refresh:
            self._refresh_target_window_rect(force=True)

        if not self.target_window_rect or self.target_window_rect.isEmpty():
            return QRect()
        return QRect(self.target_window_rect)

    def _clamp_point_to_target_window(self, overlay_pos: QPoint) -> QPoint:
        """Clamp overlay point into the cached target window rect."""
        target_rect = self._get_target_window_rect(refresh=False)
        if target_rect.isEmpty():
            return QPoint(overlay_pos)

        x = max(target_rect.left(), min(int(overlay_pos.x()), target_rect.right()))
        y = max(target_rect.top(), min(int(overlay_pos.y()), target_rect.bottom()))
        return QPoint(x, y)

    @staticmethod
    def _get_selection_label_rect(selection_rect: QRect) -> QRect:
        """Get the info label paint rect for the current selection."""
        if selection_rect.isEmpty():
            return QRect()

        label_pos = selection_rect.topLeft() + QPoint(5, -10)
        return QRect(
            int(label_pos.x() - 2),
            int(label_pos.y() - 15),
            200,
            20,
        )

    def _get_selection_paint_bounds(self, selection_rect: QRect) -> QRect:
        """Get the full paint bounds occupied by the selection overlay."""
        if selection_rect.isEmpty():
            return QRect()

        bounds = QRect(selection_rect)
        label_rect = self._get_selection_label_rect(selection_rect)
        if not label_rect.isEmpty():
            bounds = bounds.united(label_rect)

        bounds.adjust(-6, -6, 6, 6)
        return bounds.intersected(self.rect())

    def _build_selection_visual_state(self, end_pos: Optional[QPoint] = None) -> Tuple[QRect, str]:
        """Build the current selection rect and overlay text."""
        current_end_pos = QPoint(end_pos) if end_pos is not None else QPoint(self.end_pos)
        selection_rect = QRect(self.start_pos, current_end_pos).normalized()
        if selection_rect.isEmpty() or self.start_pos == current_end_pos:
            return QRect(), ""

        if self.window_info:
            relative_start = self._get_relative_coordinates(self.start_pos)
            relative_end = self._get_relative_coordinates(current_end_pos)
            relative_rect = QRect(relative_start, relative_end).normalized()
            info_text = (
                f"({relative_rect.x()}, {relative_rect.y()}) "
                f"{relative_rect.width()}x{relative_rect.height()}"
            )
        else:
            info_text = (
                f"({selection_rect.x()}, {selection_rect.y()}) "
                f"{selection_rect.width()}x{selection_rect.height()}"
            )

        return selection_rect, info_text

    def _update_selection_visual_state(self, selection_rect: QRect, info_text: str) -> None:
        """Update only the dirty region touched by the selection overlay."""
        old_bounds = self._get_selection_paint_bounds(self.selection_rect)
        self.selection_rect = QRect(selection_rect)
        self.selection_info_text = str(info_text or "")
        new_bounds = self._get_selection_paint_bounds(self.selection_rect)

        dirty_rect = old_bounds.united(new_bounds)
        if dirty_rect.isEmpty():
            return
        self.update(dirty_rect)

    @staticmethod
    def _get_drag_start_threshold() -> int:
        """Return the minimum cursor movement before showing a selection box."""
        try:
            return max(3, int(QApplication.startDragDistance()))
        except Exception:
            return 4

    def _release_mouse_capture(self) -> None:
        """Release mouse grab safely when selection ends or closes."""
        try:
            mouse_grabber = QWidget.mouseGrabber()
        except Exception:
            mouse_grabber = None

        try:
            if mouse_grabber is self:
                self.releaseMouse()
        except Exception:
            pass

    def _verify_window_position(self):
        """Validate target window placement inside the overlay."""
        if not self.window_info:
            return

        try:
            overlay_geometry = self.geometry()
            client_screen_pos = self.window_info.get("client_qt_screen_pos", self.window_info["client_screen_pos"])
            target_rect = self._refresh_target_window_rect(force=True)
            if target_rect.isEmpty():
                logger.warning(" [verify] target window rect is empty")
                return
            qt_x = target_rect.x()
            qt_y = target_rect.y()

            logger.info(f" [verify] overlay geometry: {overlay_geometry}")
            logger.info(f" [verify] client screen pos: {client_screen_pos}")
            logger.info(f" [verify] target rect top-left: ({qt_x}, {qt_y})")

            overlay_local_rect = self.rect()
            if not overlay_local_rect.intersects(target_rect):
                logger.warning(f" [verify] target rect ({qt_x}, {qt_y}) is outside overlay {overlay_geometry}")
                logger.warning(" [verify] window position data may be inaccurate")
            else:
                logger.info(" [verify] window position is valid")

        except Exception as e:
            logger.error(f"窗口位置校验失败: {e}")

    def _get_relative_coordinates(self, overlay_pos: QPoint) -> QPoint:
        """Convert overlay coordinates to client-relative coordinates."""
        if not self.window_info:
            return overlay_pos

        try:
            target_rect = self._get_target_window_rect(refresh=False)
            if target_rect.isEmpty():
                target_rect = self._get_target_window_rect(refresh=True)
            if target_rect.isEmpty():
                logger.warning(" [coord] target rect is empty; cannot convert")
                return overlay_pos

            relative_pos = overlay_point_to_client_qpoint(self.window_info, target_rect, overlay_pos)
            client_width, client_height = get_window_client_physical_size(self.window_info)
            if relative_pos.x() < 0 or relative_pos.y() < 0 or relative_pos.x() >= client_width or relative_pos.y() >= client_height:
                logger.warning(f" [coord] converted point ({relative_pos.x()}, {relative_pos.y()}) is outside ({client_width}x{client_height})")
            else:
                logger.debug(" [coord] converted point is within range")

            return relative_pos
        except Exception as e:
            logger.error(f"OCR 坐标转换失败: {e}")
            return overlay_pos

    def _convert_rect_to_relative_coordinates(self, overlay_rect: QRect) -> QRect:
        """Convert an overlay rect to client-relative coordinates."""
        if not self.window_info:
            return overlay_rect

        try:
            client_width, client_height = get_window_client_physical_size(self.window_info)
            target_rect = self._get_target_window_rect(refresh=False)
            if target_rect.isEmpty():
                target_rect = self._get_target_window_rect(refresh=True)
            if target_rect.isEmpty():
                logger.warning(" [rect] target window rect is empty; cannot convert")
                return overlay_rect

            relative_rect = overlay_local_rect_to_client_relative(
                self.window_info,
                target_rect,
                overlay_rect,
            )
            if not relative_rect:
                logger.warning(" [rect] selection has no overlap with target window")
                return QRect()

            logger.info(f" [rect] overlay rect(Qt): ({overlay_rect.x()}, {overlay_rect.y()}) {overlay_rect.width()}x{overlay_rect.height()}")
            logger.info(f" [rect] target rect(Qt): ({target_rect.x()}, {target_rect.y()}) {target_rect.width()}x{target_rect.height()}")
            logger.info(f" [rect] client screen pos(Qt): {self.window_info.get('client_qt_screen_pos', (0, 0))}")
            relative_x, relative_y, rect_width, rect_height = relative_rect

            logger.info(f" [rect] client result: ({relative_x}, {relative_y}) {rect_width}x{rect_height}")

            if (
                relative_x < 0
                or relative_y < 0
                or relative_x + rect_width > client_width
                or relative_y + rect_height > client_height
            ):
                logger.warning(f" [rect] converted rect ({relative_x}, {relative_y}) {rect_width}x{rect_height} exceeds ({client_width}x{client_height})")
            else:
                logger.info(" [rect] converted rect is within target bounds")

            return QRect(relative_x, relative_y, rect_width, rect_height)

        except Exception as e:
            logger.error(f"OCR 区域转换失败: {e}")
            import traceback
            logger.error(f"堆栈: {traceback.format_exc()}")
            return overlay_rect

    def _save_selection_debug_image(self, x: int, y: int, width: int, height: int):
        """调试图像保存功能已禁用"""
        pass

    def _is_point_in_target_window(self, qt_screen_pos: QPoint) -> bool:
        """Check whether a point is inside the target window client area in Qt logical coordinates."""
        if not self.window_info:
            return False

        target_rect = self._get_target_window_rect(refresh=False)
        if target_rect.isEmpty():
            target_rect = self._refresh_target_window_rect(force=True)
        return overlay_rect_contains_point(target_rect, qt_screen_pos)

    def paintEvent(self, event):
        """Paint overlay with transparent background and selection."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        fill_overlay_event_background(painter, self)

        if self.window_info:
            target_rect = self._get_target_window_rect(refresh=False)
            draw_target_window_overlay(painter, target_rect)

        if self.selecting and not self.selection_rect.isEmpty():
            draw_selection_overlay(painter, self.selection_rect, info_text=self.selection_info_text)

        painter.setPen(QPen(QColor(255, 255, 255)))
        painter.drawText(50, 50, "Drag to select | Right click or ESC to cancel")

    def mousePressEvent(self, event):
        """Handle mouse press and ensure the overlay stays active."""
        if not self.isActiveWindow():
            logger.warning("OCR overlay is not active, trying to reactivate")
            activate_overlay_widget(self, log_prefix='OCR覆盖层', focus=True)
            event.accept()
            return

        if event.button() == Qt.MouseButton.LeftButton:
            if not self._is_ready_for_input:
                logger.info("OCR overlay not ready yet; use this click only to activate")
                activate_overlay_widget(self, log_prefix='OCR覆盖层', focus=True)
                event.accept()
                return

            if self.window_info and not self._is_point_in_target_window(event.pos()):
                logger.debug("Left click outside target window; ignore selection start")
                self.setCursor(Qt.CursorShape.ArrowCursor)
                event.accept()
                return

            self._refresh_target_window_rect(force=True)
            self.start_pos = self._clamp_point_to_target_window(event.pos())
            self.end_pos = self.start_pos
            self.selecting = False
            self.selection_pending = True
            self._update_selection_visual_state(QRect(), "")

            if self.window_info:
                relative_pos = self._get_relative_coordinates(self.start_pos)
                logger.debug(f"Mouse press converted to client coordinates: {relative_pos}")

            try:
                self.grabMouse()
            except Exception as e:
                logger.warning(f"抓取鼠标失败，拖拽可能不稳定: {e}")

            self.setCursor(Qt.CursorShape.CrossCursor)
            event.accept()
        elif event.button() == Qt.MouseButton.RightButton:
            logger.info("Right click detected, closing selector")
            self.close()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """鼠标移动事件"""
        if self.selection_pending or self.selecting:
            new_end_pos = self._clamp_point_to_target_window(event.pos())

            if self.selection_pending:
                drag_delta = new_end_pos - self.start_pos
                if drag_delta.manhattanLength() < self._get_drag_start_threshold():
                    event.accept()
                    return
                self.selection_pending = False
                self.selecting = True

            if self.selecting and new_end_pos != self.end_pos:
                self.end_pos = new_end_pos
                selection_rect, info_text = self._build_selection_visual_state(new_end_pos)
                self._update_selection_visual_state(selection_rect, info_text)
            event.accept()
        else:
            # 设置鼠标样式
            if self.window_info and self._is_point_in_target_window(event.pos()):
                self.setCursor(Qt.CursorShape.CrossCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, event):
        """鼠标释放事件"""
        if event.button() == Qt.MouseButton.LeftButton and (self.selection_pending or self.selecting):
            was_selecting = self.selecting
            self.selection_pending = False
            self.selecting = False
            self._release_mouse_capture()

            if not was_selecting:
                self._update_selection_visual_state(QRect(), "")
                event.accept()
                return

            release_pos = self._clamp_point_to_target_window(event.pos())

            # 计算选择区域
            rect = QRect(self.start_pos, release_pos).normalized()
            logger.info(f"鼠标释放: 矩形={rect}")

            if rect.width() > 10 and rect.height() > 10:
                if self.window_info:
                    # 统一裁剪到目标窗口客户区，允许拖拽略微越界
                    relative_rect = self._convert_rect_to_relative_coordinates(rect)
                    if relative_rect.isEmpty():
                        logger.warning("选择区域与目标窗口没有有效交集")
                        self.setCursor(Qt.CursorShape.ArrowCursor)
                        self._update_selection_visual_state(QRect(), "")
                        event.accept()
                        return

                    logger.info(f"===== 区域选择完成诊断 =====")
                    logger.info(f"区域选择完成: ({relative_rect.x()}, {relative_rect.y()}, {relative_rect.width()}, {relative_rect.height()})")
                    logger.info(f"这些坐标应该是相对于客户区左上角的物理像素坐标")

                    # 打印窗口信息用于验证
                    if self.window_info:
                        import win32gui
                        window_rect = win32gui.GetWindowRect(self.window_info['hwnd'])
                        client_screen_pos = self.window_info['client_screen_pos']
                        logger.info(f"窗口矩形(屏幕): {window_rect}")
                        logger.info(f"客户区屏幕位置: {client_screen_pos}")
                        logger.info(f"标题栏高度估算: {client_screen_pos[1] - window_rect[1]}px")
                        logger.info(f"客户区尺寸: {self.window_info['client_width']}x{self.window_info['client_height']}")

                    # 发射选择信号
                    self.region_selected.emit(relative_rect.x(), relative_rect.y(),
                                            relative_rect.width(), relative_rect.height())
                else:
                    logger.warning("没有窗口信息，使用屏幕坐标")
                    self.region_selected.emit(rect.x(), rect.y(), rect.width(), rect.height())

                self.close()
            else:
                logger.warning(f"选择区域太小: {rect.width()}x{rect.height()}")
                self.setCursor(Qt.CursorShape.ArrowCursor)
                self._update_selection_visual_state(QRect(), "")

            event.accept()
                
    def keyPressEvent(self, event):
        """键盘事件"""
        if event.key() == Qt.Key.Key_Escape:
            logger.info("ESC键取消选择")
            self.selecting = False
            self.selection_pending = False
            self._release_mouse_capture()
            self.close()
            event.accept()
        else:
            super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event):
        """双击事件 - 关闭覆盖层"""
        logger.info("双击关闭覆盖层")
        self.selecting = False
        self.selection_pending = False
        self._release_mouse_capture()
        self.close()
        event.accept()

    def showEvent(self, event):
        """显示事件 - 延迟激活以确保窗口系统准备就绪"""
        logger.info("OCR区域选择器显示事件触发")
        super().showEvent(event)

        # 延迟激活，确保窗口系统完成所有初始化
        from PySide6.QtCore import QTimer
        QTimer.singleShot(250, self._ensure_ready_for_input)

    def _ensure_ready_for_input(self):
        """确保覆盖层准备好接收输入"""
        ensure_overlay_ready_for_input(
            self,
            log_prefix='OCR覆盖层',
            ready_message='OCR区域选择器已就绪，可以接收输入',
            retry_message='OCR区域选择器未能激活（尝试 {attempt}/{max_attempts}），用户首次点击可能需要激活窗口',
            exhausted_message='已达到最大激活尝试次数，继续执行（用户首次操作将用于激活窗口）',
            allow_closed_skip=True,
        )

    def closeEvent(self, event):
        """关闭事件"""
        self._closing = True
        self.selecting = False
        self.selection_pending = False
        self._release_mouse_capture()
        logger.info("OCR区域选择器关闭，发出关闭信号")
        self.overlay_closed.emit()
        super().closeEvent(event)

class OCRRegionSelectorWidget(QWidget):
    """OCR区域选择器控件"""

    region_selected = Signal(int, int, int, int)  # x, y, width, height
    selection_started = Signal()  # 选择开始信号
    selection_finished = Signal()  # 选择结束信号（无论成功还是取消）
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.target_window_title = None
        self.target_window_hwnd = None  # 添加窗口句柄属性
        self.current_region = (0, 0, 0, 0)
        self.current_region_binding = {}
        self._current_overlay = None

        self.setup_ui()
        
    def setup_ui(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        # 选择按钮
        self.select_button = QPushButton("框选识别指定区域")
        self.select_button.clicked.connect(self.start_selection)
        layout.addWidget(self.select_button)

        # 不再显示区域信息，避免与参数界面的显示重复
        # 区域信息将通过 region_coordinates 参数显示
        
    def set_target_window(self, window_title: str):
        """设置目标窗口"""
        self.target_window_title = window_title
        if window_title:
            self.select_button.setText(f"框选区域 (目标: {window_title})")
            self.select_button.setToolTip(f"在窗口 '{window_title}' 中框选OCR识别区域")
        else:
            self.select_button.setText("框选识别指定区域")
            self.select_button.setToolTip("请先绑定目标窗口")

    def set_target_window_hwnd(self, window_hwnd: int):
        """设置目标窗口句柄"""
        self.target_window_hwnd = window_hwnd
        if window_hwnd:
            # 获取窗口标题用于显示
            try:
                import win32gui
                window_title = win32gui.GetWindowText(window_hwnd)
                self.target_window_title = window_title
                self.select_button.setText(f"框选区域 (目标: {window_title})")
                self.select_button.setToolTip(f"在窗口 '{window_title}' (HWND: {window_hwnd}) 中框选OCR识别区域")
                logger.info(f"设置目标窗口句柄: {window_hwnd}, 标题: {window_title}")
            except Exception as e:
                logger.warning(f"获取窗口标题失败: {e}")
                self.target_window_title = f"窗口{window_hwnd}"
                self.select_button.setText(f"框选区域 (目标: 窗口{window_hwnd})")
                self.select_button.setToolTip(f"在窗口 {window_hwnd} 中框选OCR识别区域")
        else:
            self.select_button.setText("框选识别指定区域")
            self.select_button.setToolTip("请先绑定目标窗口")

    # 添加别名方法，方便调用
    def set_target_hwnd(self, window_hwnd: int):
        """设置目标窗口句柄（set_target_window_hwnd的别名）"""
        self.set_target_window_hwnd(window_hwnd)

    def refresh_bound_window_display(self):
        """刷新绑定窗口显示（在全局设置更新后调用）"""
        try:
            window_title = self._get_bound_window_from_editor()
            if window_title:
                self.target_window_title = window_title
                self.select_button.setText(f"框选区域 (已绑定: {window_title})")
                self.select_button.setToolTip(f"在窗口 '{window_title}' 中框选OCR识别区域")
                logger.info(f"刷新绑定窗口显示: {window_title}")
            else:
                self.select_button.setText("框选识别指定区域")
                self.select_button.setToolTip("请先在全局设置中绑定目标窗口")
                logger.debug("未找到绑定窗口，恢复默认按钮文本")
        except Exception as e:
            logger.error(f"刷新绑定窗口显示失败: {e}")

    def _get_bound_window_from_editor(self) -> Optional[str]:
        """从编辑器获取已绑定的窗口标题（支持多窗口模式）"""
        try:
            # 方法1: 从配置文件获取
            import json
            import os
            config_file = get_config_path()
            if os.path.exists(config_file):
                try:
                    with open(config_file, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                        target_window_title = config.get('target_window_title')
                        if target_window_title:
                            logger.info(f"从配置文件获取目标窗口: {target_window_title}")
                            return target_window_title
                except Exception as e:
                    logger.warning(f"读取配置文件失败: {e}")

            # 方法2: 从父窗口获取绑定的窗口列表（支持多窗口）
            current_widget = self.parent()
            level = 0
            while current_widget and level < 10:  # 最多查找10层
                # 检查是否有bound_windows属性（多窗口模式）
                if hasattr(current_widget, 'bound_windows'):
                    bound_windows = current_widget.bound_windows
                    if bound_windows and len(bound_windows) > 0:
                        # 获取第一个启用的窗口
                        for window_info in bound_windows:
                            if window_info.get('enabled', True):
                                window_title = window_info.get('title')
                                if window_title:
                                    logger.info(f"从多窗口绑定列表获取第一个启用窗口: {window_title}")
                                    return window_title

                        # 如果没有启用的窗口，使用第一个窗口
                        first_window = bound_windows[0]
                        window_title = first_window.get('title')
                        if window_title:
                            logger.info(f"从多窗口绑定列表获取第一个窗口: {window_title}")
                            return window_title

                # 检查是否有runner属性（单窗口模式）
                if hasattr(current_widget, 'runner'):
                    runner = current_widget.runner
                    if hasattr(runner, 'target_window_title'):
                        target_window_title = runner.target_window_title
                        if target_window_title:
                            logger.info(f"从第{level}层窗口runner获取目标窗口: {target_window_title}")
                            return target_window_title

                # 检查是否有直接的target_window_title属性
                if hasattr(current_widget, 'target_window_title'):
                    target_window_title = current_widget.target_window_title
                    if target_window_title:
                        logger.info(f"从第{level}层窗口属性获取目标窗口: {target_window_title}")
                        return target_window_title

                # 向上查找父窗口
                current_widget = current_widget.parent()
                level += 1

            logger.warning("未找到编辑器绑定的目标窗口")
            return None

        except Exception as e:
            logger.error(f"获取编辑器绑定窗口时出错: {e}")
            return None
            
    def start_selection(self):
        """开始区域选择"""
        try:
            logger.info("start_selection 方法被调用")

            current_overlay = self._current_overlay
            if current_overlay is not None:
                try:
                    if current_overlay.isVisible() and not getattr(current_overlay, "_closing", False):
                        logger.info("OCR区域选择覆盖层仍在活动，忽略重复启动")
                        return
                except RuntimeError:
                    pass
                self._cleanup_previous_overlay()

            # 发出选择开始信号
            self.selection_started.emit()

            # 优先使用窗口句柄，否则使用窗口标题
            if self.target_window_hwnd:
                # 【新增】验证句柄是否在全局绑定列表中（静默处理）
                validated_hwnd = self._validate_hwnd_silent(self.target_window_hwnd)
                if not validated_hwnd:
                    QMessageBox.warning(self, "警告", "没有可用的绑定窗口，请先在全局设置中绑定窗口")
                    self.selection_finished.emit()
                    return
                # 使用验证后的句柄创建覆盖层
                logger.info(f"开始创建覆盖层，使用验证后的窗口句柄: {validated_hwnd}")
                overlay = OCRRegionSelectorOverlay(target_window_hwnd=validated_hwnd)
            elif self.target_window_title:
                # 使用窗口标题创建覆盖层
                logger.info(f"开始创建覆盖层，使用窗口标题: {self.target_window_title}")
                overlay = OCRRegionSelectorOverlay(self.target_window_title)
            else:
                # 如果没有设置目标窗口，尝试自动获取编辑器绑定的窗口
                logger.info("尝试自动获取编辑器绑定的窗口")
                self.target_window_hwnd = self._get_bound_window_hwnd()
                if self.target_window_hwnd:
                    # 【新增】验证句柄是否在全局绑定列表中（静默处理）
                    validated_hwnd = self._validate_hwnd_silent(self.target_window_hwnd)
                    if not validated_hwnd:
                        QMessageBox.warning(self, "警告", "没有可用的绑定窗口，请先在全局设置中绑定窗口")
                        self.selection_finished.emit()
                        return
                    # 获取窗口标题用于显示
                    try:
                        import win32gui
                        window_title = win32gui.GetWindowText(validated_hwnd)
                        self.target_window_title = window_title
                        self.select_button.setText(f"框选区域 (已绑定: {window_title})")
                        logger.info(f"自动获取编辑器绑定的窗口句柄: {validated_hwnd}, 标题: {window_title}")
                    except Exception as e:
                        logger.warning(f"从句柄获取窗口标题失败: {e}")
                    overlay = OCRRegionSelectorOverlay(target_window_hwnd=validated_hwnd)
                else:
                    logger.error("未找到编辑器绑定的窗口")
                    QMessageBox.warning(self, "警告", "未找到编辑器绑定的窗口，请先在编辑器中绑定目标窗口")
                    self.selection_finished.emit()
                    return

            # 创建选择覆盖层并保持引用
            if overlay is None:
                logger.error("覆盖层对象为 None")
                QMessageBox.critical(self, "错误", "覆盖层对象创建失败")
                self.selection_finished.emit()
                return

            overlay.region_selected.connect(self._on_region_selected)
            overlay.overlay_closed.connect(self._on_overlay_closed)

            # 保存覆盖层引用
            self._current_overlay = overlay

            # 当覆盖层销毁时清理引用
            def on_overlay_destroyed():
                if self._current_overlay is overlay:
                    self._current_overlay = None
            overlay.destroyed.connect(on_overlay_destroyed)

            setup_result = overlay.setup_target_window()

            if setup_result:
                self.current_region_binding = self._build_region_binding_info(getattr(overlay, 'target_hwnd', None))
                if show_and_activate_overlay(overlay, log_prefix='OCR覆盖层启动', focus=True):
                    logger.info("已使用统一覆盖层激活链启动OCR覆盖层")
                schedule_overlay_activation_boost(
                    overlay,
                    log_prefix='OCR覆盖层置顶',
                    intervals_ms=(50, 150, 300, 500),
                    focus=True,
                )
            else:
                logger.error("设置目标窗口失败")
                overlay._closing = True
                overlay.deleteLater()
                if self._current_overlay is overlay:
                    self._current_overlay = None
                self.selection_finished.emit()

        except Exception as e:
            logger.error(f"start_selection 执行失败: {e}")
            import traceback
            logger.error(f"详细错误信息:\n{traceback.format_exc()}")
            QMessageBox.critical(self, "错误", f"OCR区域选择失败: {str(e)}")
            self.selection_finished.emit()
            
    def _on_region_selected(self, x: int, y: int, width: int, height: int):
        """处理区域选择完成（直接使用原始坐标，不进行DPI转换）"""
        logger.info(f"OCR区域选择完成: ({x}, {y}, {width}, {height})")

        try:
            binding_info = self.current_region_binding or {}
            bound_hwnd = int(binding_info.get('region_hwnd') or 0)

            if bound_hwnd:
                logger.info(f"OCR区域基于窗口 HWND:{bound_hwnd}: ({x}, {y}, {width}, {height})")
            else:
                logger.warning(f"OCR区域（无窗口句柄）: ({x}, {y}, {width}, {height})")

            # 直接使用原始坐标，不进行任何DPI转换
            # 这样可以避免重复缩放导致的坐标偏移问题
            self.current_region = (x, y, width, height)
            self.region_selected.emit(x, y, width, height)

            logger.info(f"OCR区域选择处理完成，使用原始坐标: ({x}, {y}, {width}, {height})")

        except Exception as e:
            logger.error(f"处理OCR区域选择失败: {e}")
            # 回退到原始处理方式
            self.current_region = (x, y, width, height)
            self.region_selected.emit(x, y, width, height)

    def _get_bound_window_hwnd(self) -> Optional[int]:
        """获取当前绑定的窗口句柄"""
        try:
            # 向上查找主窗口，获取绑定的窗口信息
            current_widget = self.parent()
            level = 0
            max_levels = 10

            while current_widget and level < max_levels:
                # 检查是否有config属性（主窗口）
                if hasattr(current_widget, 'config'):
                    config = current_widget.config

                    # 单窗口模式
                    if hasattr(config, 'target_window_title') and config.target_window_title:
                        return self._find_window_by_title(config.target_window_title)

                    # 多窗口模式
                    if hasattr(config, 'bound_windows') and config.bound_windows:
                        enabled_windows = [w for w in config.bound_windows if w.get('enabled', True)]
                        if enabled_windows:
                            return enabled_windows[0].get('hwnd')

                # 检查是否有runner属性
                if hasattr(current_widget, 'runner') and hasattr(current_widget.runner, 'config'):
                    config = current_widget.runner.config

                    if hasattr(config, 'target_window_title') and config.target_window_title:
                        return self._find_window_by_title(config.target_window_title)

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

    def _find_window_by_title(self, title: str) -> Optional[int]:
        """通过标题查找窗口句柄"""
        try:
            return resolve_unique_window_hwnd(title)

        except Exception as e:
            logger.error(f"查找窗口失败: {e}")
            return None

    def _cleanup_previous_overlay(self):
        """清理之前的覆盖层"""
        overlay = self._current_overlay
        if overlay:
            logger.info("清理之前的覆盖层")
            overlay._closing = True
            overlay.selecting = False
            overlay.start_pos = QPoint()
            overlay.end_pos = QPoint()
            try:
                overlay.overlay_closed.disconnect()
                overlay.region_selected.disconnect()
                overlay.destroyed.disconnect()
            except Exception as e:
                logger.warning(f"断开信号连接失败: {e}")

            self._current_overlay = None

            try:
                overlay.hide()
            except Exception:
                pass
            overlay.deleteLater()

    def _on_overlay_closed(self):
        """覆盖层关闭时的处理"""
        logger.info("OCR覆盖层关闭，发出选择结束信号")
        self.selection_finished.emit()

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

    def get_region(self) -> Tuple[int, int, int, int]:
        """获取当前选择的区域"""
        return self.current_region

    def get_region_binding_info(self) -> Dict[str, Any]:
        """获取当前区域录制时所基于的窗口信息。"""
        return dict(self.current_region_binding or {})
        
    def set_region(self, x: int, y: int, width: int, height: int):
        """设置区域"""
        self.current_region = (x, y, width, height)
        # 不再更新UI显示，区域信息将通过参数界面的 region_coordinates 显示

    def _build_region_binding_info(self, hwnd: Optional[int]) -> Dict[str, Any]:
        info: Dict[str, Any] = {
            'region_hwnd': 0,
            'region_window_title': '',
            'region_window_class': '',
            'region_client_width': 0,
            'region_client_height': 0,
        }

        try:
            hwnd_int = int(hwnd or 0)
        except Exception:
            return info

        if hwnd_int <= 0:
            return info

        normalized_hwnd, normalized_title, normalized_class, normalized_width, normalized_height = (
            normalize_region_binding_hwnd(hwnd_int)
        )
        if normalized_hwnd > 0:
            info['region_hwnd'] = normalized_hwnd
            info['region_window_title'] = normalized_title
            info['region_window_class'] = normalized_class
            info['region_client_width'] = normalized_width
            info['region_client_height'] = normalized_height
            return info

        info['region_hwnd'] = hwnd_int

        try:
            import win32gui

            info['region_window_title'] = str(win32gui.GetWindowText(hwnd_int) or "").strip()
            info['region_window_class'] = str(win32gui.GetClassName(hwnd_int) or "").strip()
            client_rect = win32gui.GetClientRect(hwnd_int)
            info['region_client_width'] = max(0, int(client_rect[2] - client_rect[0]))
            info['region_client_height'] = max(0, int(client_rect[3] - client_rect[1]))
        except Exception:
            pass

        return info
