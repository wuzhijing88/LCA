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
from PySide6.QtCore import Qt, Signal, QRect, QPoint, QTimer, QEvent, QObject
from shiboken6 import isValid
from PySide6.QtGui import QPainter, QPen, QColor


from utils.app_paths import get_config_path
from utils.window.window_coordinate_common import (
    build_window_info,
    get_window_client_logical_size,
    get_window_client_physical_size,
    overlay_local_rect_to_client_relative,
    normalize_region_binding_hwnd,
    normalize_window_hwnd,
)
from utils.window.window_overlay_utils import (
    apply_overlay_text_style,
    capture_virtual_desktop_pixmap,
    capture_window_client_pixmap,
    configure_opaque_picker_overlay,
    draw_picker_backdrop,
    draw_selection_overlay,
    draw_target_window_overlay,
    map_native_rect_to_local,
    prime_picker_backdrop,
    overlay_point_to_client_qpoint,
    overlay_rect_contains_point,
    refresh_target_window_overlay_rect,
    sync_overlay_geometry,
)
from utils.window.window_activation_utils import (
    activate_window,
    ensure_overlay_ready_for_input,
    grab_overlay_input,
    schedule_overlay_activation_boost,
    schedule_overlay_callback,
    release_overlay_input,
    show_and_activate_overlay,
)
from themes import get_theme_manager
from ui.selectors.selection_adjust import (
    apply_overlay_adjust_button_style,
    create_overlay_adjust_buttons,
    cursor_for_selection_hit,
    hit_test_selection,
    move_rect_by,
    resize_rect_by_corner,
    scale_rect_by_wheel,
    update_adjust_buttons_position,
    wheel_event_delta_y,
)

import win32gui
from ui.selectors.coordinate_selector import _get_global_bound_window

logger = logging.getLogger(__name__)

class OCRRegionSelectorOverlay(QWidget):
    """OCR区域选择覆盖层"""

    region_selected = Signal(int, int, int, int)  # x, y, width, height
    overlay_closed = Signal()  # 覆盖层关闭信号

    def __init__(self, target_window_title: str = None, target_window_hwnd: int = None, parent=None):
        # 重要：不设置parent，让覆盖层完全独立
        super().__init__(parent)
        self.target_window_title = target_window_title
        self.target_hwnd = target_window_hwnd  # 直接使用传入的窗口句柄
        self.window_info = None
        self._closing = False
        self._resources_released = False
        self._finishing = False
        self._theme_registered = False
        self._composed_backdrop = None
        self._composed_backdrop_key = None

        # 选择状态
        self.selecting = False
        self.selection_pending = False
        self.selection_ready = False
        self.dragging_selection = False
        self.resizing_selection = False
        self.resize_mode = None
        self.resize_margin = 8
        self.drag_last_pos = QPoint()
        self.start_pos = QPoint()
        self.end_pos = QPoint()
        self.selection_rect = QRect()
        self.selection_info_text = ""
        self.target_window_rect = QRect()
        self.screenshot = None
        self.window_pixmap = None
        self.hint_text = "拖动框选 | 右键或 ESC 取消"

        # 窗口激活状态标志
        self._is_ready_for_input = False
        self._activation_attempts = 0

        try:
            configure_opaque_picker_overlay(self)
            self.confirm_button, self.reselect_button = create_overlay_adjust_buttons(
                self,
                self._confirm_selection,
                self._reset_selection,
            )
            if parent is not None:
                parent.destroyed.connect(self._release_capture)
            self._theme_registered = True
            get_theme_manager().register_theme_change_callback(self._on_adjust_theme_changed)
        except Exception:
            self._release_capture()
            self.deleteLater()
            raise

        logger.info("创建OCR区域选择覆盖层")
        logger.info("OCR区域选择器已启动")
        logger.info("使用说明:")
        logger.info("在绿色边框的目标窗口内拖拽鼠标进行选择")
        logger.info("框选后可用滚轮缩放、四角调大小、拖动边框移动，再点确定")
        logger.info("右键点击或按ESC键取消选择")
        
    def setup_target_window(self):
        """设置目标窗口并进行截图"""
        # 框选只使用明确的目标句柄。
        target_hwnd = int(self.target_hwnd or 0)
        if not target_hwnd:
            raise ValueError("未设置目标窗口句柄，不能框选区域")

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

        logger.info("[OCR框选] 捕获目标窗口最新帧...")
        self.window_pixmap = capture_window_client_pixmap(self.target_hwnd)
        if self.window_pixmap is not None:
            logger.info(
                "[OCR框选] 窗口截图成功，尺寸: %sx%s",
                self.window_pixmap.width(),
                self.window_pixmap.height(),
            )
        else:
            raise RuntimeError("目标窗口截图失败，不能框选区域")

        if not self._take_screenshot():
            QMessageBox.warning(self, "警告", "无法进行截图")
            return False

        # 设置全屏覆盖
        self._setup_fullscreen_overlay()
        prime_picker_backdrop(
            self,
            desktop_pixmap=self.screenshot,
            window_pixmap=self.window_pixmap,
            target_rect=self.target_window_rect,
        )

        # 验证窗口位置是否正确（通过检查绿色边框是否在正确位置）
        self._verify_window_position()

        return True
        


    def _activate_target_window(self, hwnd: int):
        if not activate_window(hwnd, log_prefix='OCR区域选择'):
            raise RuntimeError("目标窗口激活失败，不能框选区域")

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

            qt_device_pixel_ratio = float(base_info['qt_device_pixel_ratio'])
            if qt_device_pixel_ratio <= 0:
                raise ValueError("目标窗口缩放比例无效")
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

                        logger.info(" [窗口调试] 混合策略设置完成")
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
        self.screenshot = capture_virtual_desktop_pixmap()
        if self.screenshot is None or self.screenshot.isNull():
            logger.error("截图失败")
            self.screenshot = None
            return False
        logger.info(f"桌面底图捕获成功: {self.screenshot.width()}x{self.screenshot.height()}")
        return True

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

        if (
            (self.selection_ready or self.dragging_selection or self.resizing_selection)
            and not self.target_window_rect.isEmpty()
        ):
            return QRect(self.target_window_rect)

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
            relative_start = self._overlay_to_client_point_fast(self.start_pos)
            relative_end = self._overlay_to_client_point_fast(current_end_pos)
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

    def _overlay_to_client_point_fast(self, overlay_pos: QPoint) -> QPoint:
        if not self.window_info:
            raise ValueError("目标窗口信息缺失，无法转换坐标")
        target_rect = self._get_target_window_rect(refresh=False)
        if target_rect.isEmpty():
            raise ValueError("目标窗口客户区为空，无法转换坐标")
        return overlay_point_to_client_qpoint(self.window_info, target_rect, overlay_pos)

    def _get_relative_coordinates(self, overlay_pos: QPoint) -> QPoint:
        return self._overlay_to_client_point_fast(overlay_pos)

    def _convert_rect_to_relative_coordinates(self, overlay_rect: QRect) -> QRect:
        if not self.window_info:
            raise ValueError("目标窗口信息缺失，无法转换区域")
        target_rect = self._get_target_window_rect(refresh=False)
        if target_rect.isEmpty():
            raise ValueError("目标窗口客户区为空，无法转换区域")
        x, y, width, height = overlay_local_rect_to_client_relative(self.window_info, target_rect, overlay_rect)
        return QRect(x, y, width, height)



    def _on_adjust_theme_changed(self, _theme=None) -> None:
        apply_overlay_adjust_button_style(self.confirm_button, self.reselect_button)

    def _selection_bounds(self) -> QRect:
        target = self._get_target_window_rect(refresh=False)
        if target.isEmpty():
            return QRect(self.rect())
        return QRect(target)

    def _apply_selection_rect(self, rect: QRect) -> None:
        self.start_pos = rect.topLeft()
        self.end_pos = QPoint(rect.right(), rect.bottom())
        _, info_text = self._build_selection_visual_state(self.end_pos)
        self._update_selection_visual_state(rect, info_text)
        if self.selection_ready:
            self._update_action_buttons_position()

    def _set_selection_ready(self, ready: bool) -> None:
        self.selection_ready = bool(ready)
        self.dragging_selection = False
        self.resizing_selection = False
        self.resize_mode = None
        if self.selection_ready:
            self.hint_text = "滚轮缩放 | 四角调大小 | 拖动边框移动 | 点“确定”保存 | 右键或 ESC 取消"
            self._release_mouse_capture()
            self.confirm_button.show()
            self.reselect_button.show()
            self._update_action_buttons_position()
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.hint_text = "拖动框选 | 右键或 ESC 取消"
            self.confirm_button.hide()
            self.reselect_button.hide()
            self.setCursor(Qt.CursorShape.CrossCursor)
        self.update()

    def _update_action_buttons_position(self) -> None:
        if not self.selection_ready or self.selection_rect.isEmpty():
            return
        update_adjust_buttons_position(
            self.confirm_button,
            self.reselect_button,
            self.selection_rect,
            self.rect(),
        )

    def _confirm_selection(self) -> None:
        if self.selection_rect.isEmpty() or not self.selection_ready:
            QMessageBox.warning(self, "提示", "请先框选有效区域")
            return
        self._emit_region_and_close(QRect(self.selection_rect))

    def _reset_selection(self) -> None:
        self.selecting = False
        self.selection_pending = False
        self._release_mouse_capture()
        self.start_pos = QPoint()
        self.end_pos = QPoint()
        self._update_selection_visual_state(QRect(), "")
        self._set_selection_ready(False)

    def _emit_region_and_close(self, rect: QRect) -> None:
        if rect.width() <= 10 or rect.height() <= 10:
            QMessageBox.warning(self, "提示", "请先框选有效区域")
            return

        if self._closing or self._finishing:
            return
        relative_rect = self._convert_rect_to_relative_coordinates(rect)
        if relative_rect.isEmpty():
            QMessageBox.warning(self, "提示", "选择区域与目标窗口没有有效交集")
            return
        self._finishing = True
        self.region_selected.emit(relative_rect.x(), relative_rect.y(), relative_rect.width(), relative_rect.height())
        if isValid(self):
            self.close()

    def _is_point_in_target_window(self, qt_screen_pos: QPoint) -> bool:
        """Check whether a point is inside the target window client area in Qt logical coordinates."""
        if not self.window_info:
            return False

        target_rect = self._get_target_window_rect(refresh=False)
        if target_rect.isEmpty():
            target_rect = self._refresh_target_window_rect(force=True)
        return overlay_rect_contains_point(target_rect, qt_screen_pos)

    def paintEvent(self, event):
        """Paint frozen window image and selection."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)

        target_rect = self._get_target_window_rect(refresh=False) if self.window_info else QRect()
        draw_picker_backdrop(
            painter,
            self,
            desktop_pixmap=self.screenshot,
            window_pixmap=self.window_pixmap,
            target_rect=target_rect,
        )

        if self.window_info:
            draw_target_window_overlay(painter, target_rect)

        if not self.selection_rect.isEmpty():
            draw_selection_overlay(painter, self.selection_rect, info_text=self.selection_info_text)

        apply_overlay_text_style(painter)
        painter.drawText(50, 50, self.hint_text)

    def mousePressEvent(self, event):
        """按下后立刻开始框选，中途不再抢前台，避免把拖拽掐断。"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._refresh_target_window_rect(force=True)
            click_pos = self._clamp_point_to_target_window(event.pos())

            if self.selection_ready and not self.selection_rect.isEmpty():
                hit_mode = hit_test_selection(click_pos, self.selection_rect, self.resize_margin)
                if hit_mode:
                    self.drag_last_pos = click_pos
                    if hit_mode == "move":
                        self.dragging_selection = True
                        self.resizing_selection = False
                        self.resize_mode = None
                    else:
                        self.dragging_selection = False
                        self.resizing_selection = True
                        self.resize_mode = hit_mode
                    self.setCursor(cursor_for_selection_hit(hit_mode))
                    try:
                        self.grabMouse()
                    except Exception as exc:
                        logger.warning(f"抓取鼠标失败，拖拽可能不稳定: {exc}")
                    event.accept()
                    return

            self._set_selection_ready(False)
            self.start_pos = click_pos
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
            return

        if self.dragging_selection:
            new_pos = self._clamp_point_to_target_window(event.pos())
            delta = new_pos - self.drag_last_pos
            if delta.x() != 0 or delta.y() != 0:
                self._apply_selection_rect(
                    move_rect_by(self.selection_rect, delta.x(), delta.y(), self._selection_bounds())
                )
                self.drag_last_pos = new_pos
            event.accept()
            return

        if self.resizing_selection:
            new_pos = self._clamp_point_to_target_window(event.pos())
            delta = new_pos - self.drag_last_pos
            if delta.x() != 0 or delta.y() != 0:
                self._apply_selection_rect(
                    resize_rect_by_corner(
                        self.selection_rect,
                        self.resize_mode,
                        delta.x(),
                        delta.y(),
                        self._selection_bounds(),
                    )
                )
                self.drag_last_pos = new_pos
            event.accept()
            return

        if self.selection_ready and not self.selection_rect.isEmpty():
            hit_mode = hit_test_selection(event.pos(), self.selection_rect, self.resize_margin)
            if hit_mode:
                self.setCursor(cursor_for_selection_hit(hit_mode))
            elif self.window_info and self._is_point_in_target_window(event.pos()):
                self.setCursor(Qt.CursorShape.CrossCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
        elif self.window_info and self._is_point_in_target_window(event.pos()):
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, event):
        """鼠标释放事件"""
        if event.button() != Qt.MouseButton.LeftButton:
            return

        if self.dragging_selection or self.resizing_selection:
            self.dragging_selection = False
            self.resizing_selection = False
            self.resize_mode = None
            if self.selection_ready:
                self._release_mouse_capture()
                self._update_action_buttons_position()
            event.accept()
            return

        if self.selection_pending or self.selecting:
            was_selecting = self.selecting
            self.selection_pending = False
            self.selecting = False
            self._release_mouse_capture()

            if not was_selecting:
                self._update_selection_visual_state(QRect(), "")
                event.accept()
                return

            release_pos = self._clamp_point_to_target_window(event.pos())
            rect = QRect(self.start_pos, release_pos).normalized()
            logger.info(f"鼠标释放: 矩形={rect}")

            if rect.width() > 10 and rect.height() > 10:
                self.end_pos = release_pos
                selection_rect, info_text = self._build_selection_visual_state(release_pos)
                self._update_selection_visual_state(selection_rect, info_text)
                self._set_selection_ready(True)
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
            return

        if self.selection_ready and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._confirm_selection()
            event.accept()
            return

        super().keyPressEvent(event)

    def wheelEvent(self, event):
        if (
            not self.selection_ready
            or self.selection_rect.isEmpty()
            or self.selecting
            or self.dragging_selection
            or self.resizing_selection
        ):
            event.ignore()
            return

        delta_y = wheel_event_delta_y(event)
        if delta_y == 0:
            event.accept()
            return

        self._apply_selection_rect(
            scale_rect_by_wheel(self.selection_rect, self._selection_bounds(), delta_y)
        )
        event.accept()

    def mouseDoubleClickEvent(self, event):
        if self.selection_ready and not self.selection_rect.isEmpty():
            self._confirm_selection()
            event.accept()
            return
        logger.info("双击关闭覆盖层")
        self.selecting = False
        self.selection_pending = False
        self._release_mouse_capture()
        self.close()
        event.accept()

    def showEvent(self, event):
        """显示事件 - 延迟激活以确保窗口系统准备就绪"""
        if getattr(self, "_closing", False):
            event.ignore()
            return
        logger.info("OCR区域选择器显示事件触发")
        super().showEvent(event)
        grab_overlay_input(self, log_prefix='OCR覆盖层')
        schedule_overlay_callback(self, 50, self._ensure_ready_for_input)

    def _ensure_ready_for_input(self):
        """确保覆盖层准备好接收输入"""
        ensure_overlay_ready_for_input(
            self,
            log_prefix='OCR覆盖层',
            ready_message='OCR区域选择器已就绪，可以接收输入',
            retry_message='OCR区域选择器未能激活（尝试 {attempt}/{max_attempts}），用户首次点击可能需要激活窗口',
            exhausted_message='无法取得输入焦点，区域选择已取消',
        )

    def _release_capture(self):
        if self._resources_released:
            return False
        self._resources_released = True
        self._closing = True
        self.selecting = self.selection_pending = self.selection_ready = False
        self.dragging_selection = self.resizing_selection = False
        release_overlay_input(self)
        if self._theme_registered:
            self._theme_registered = False
            get_theme_manager().unregister_theme_change_callback(self._on_adjust_theme_changed)
        self.screenshot = None
        self.window_pixmap = None
        self._composed_backdrop = None
        self._composed_backdrop_key = None
        self.start_pos = QPoint()
        self.end_pos = QPoint()
        self.selection_rect = QRect()
        return True

    def closeEvent(self, event):
        if self._release_capture():
            self.overlay_closed.emit()
        super().closeEvent(event)

    def hideEvent(self, event):
        if self._release_capture():
            self.overlay_closed.emit()
        super().hideEvent(event)

    def event(self, event):
        if event.type() == QEvent.Type.DeferredDelete:
            self._release_capture()
        return super().event(event)

class OCRRegionSelectorWidget(QWidget):
    """对当前绑定窗口框选区域，关闭覆盖层后提交结果。"""
    region_selected = Signal(int, int, int, int)
    selection_started = Signal()
    selection_finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.target_window_hwnd = None
        self.target_window_title = ""
        self.current_region = (0, 0, 0, 0)
        self.current_region_binding = {}
        self._current_overlay = None
        self._pending_region = None
        self._overlay_connections = []
        self._result_timer = QTimer(self)
        self._result_timer.setSingleShot(True)
        self._result_timer.timeout.connect(self._deliver_selection)
        try:
            self.setup_ui()
        except Exception:
            self.deleteLater()
            raise

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        self.select_button = QPushButton("框选识别指定区域")
        self.select_button.clicked.connect(self.start_selection)
        layout.addWidget(self.select_button)

    def set_target_window_hwnd(self, hwnd: int):
        if type(hwnd) is not int or hwnd <= 0:
            raise ValueError("区域采集窗口句柄无效")
        self.target_window_hwnd = hwnd
        self.target_window_title = win32gui.GetWindowText(hwnd)
        self.select_button.setText(f"框选区域 (目标: {self.target_window_title or '窗口' + str(hwnd)})")

    def refresh_bound_window_display(self):
        hwnd = self._get_bound_window_hwnd()
        if hwnd is None:
            self.target_window_hwnd = None
            self.target_window_title = ""
            self.select_button.setText("框选识别指定区域")
        else:
            self.set_target_window_hwnd(hwnd)

    def _get_bound_window_hwnd(self):
        return _get_global_bound_window(self)

    def _validate_hwnd_silent(self, hwnd):
        current = self.parent()
        while current is not None:
            host = getattr(current, 'main_window', None)
            if host is None and hasattr(current, 'is_hwnd_bound'):
                host = current
            if host is not None:
                return hwnd if type(hwnd) is int and hwnd > 0 and host.is_hwnd_bound(hwnd) else None
            current = current.parent()
        return None

    def start_selection(self):
        if self._current_overlay is not None and isValid(self._current_overlay) and self._current_overlay.isVisible():
            return
        self._cleanup_previous_overlay()
        self.selection_started.emit()
        try:
            hwnd = self.target_window_hwnd
            if hwnd is None:
                hwnd = self._get_bound_window_hwnd()
            if not self._validate_hwnd_silent(hwnd):
                raise ValueError("没有可用的绑定窗口，请先绑定目标窗口")
            self.target_window_hwnd = hwnd
            overlay = OCRRegionSelectorOverlay(target_window_hwnd=hwnd, parent=self)
            self._current_overlay = overlay
            self._overlay_connections = [
                overlay.region_selected.connect(self._on_region_selected),
                overlay.overlay_closed.connect(self._on_overlay_closed),
            ]
            if not overlay.setup_target_window():
                raise RuntimeError("无法设置目标窗口")
            self.current_region_binding = self._build_region_binding_info(hwnd)
            if not show_and_activate_overlay(overlay, log_prefix='OCR覆盖层启动', focus=True):
                raise RuntimeError("无法显示区域选择窗口")
            schedule_overlay_activation_boost(overlay, log_prefix='OCR覆盖层')
        except Exception as error:
            self._cleanup_previous_overlay()
            logger.exception("启动区域选择失败")
            QMessageBox.warning(self, "错误", f"启动区域选择失败：{error}")
            self.selection_finished.emit()

    def _on_region_selected(self, x, y, width, height):
        self._pending_region = (x, y, width, height)

    def _on_overlay_closed(self):
        result = self._pending_region
        self._cleanup_previous_overlay(close_overlay=False)
        self._pending_region = result
        self._result_timer.start(0)

    def _deliver_selection(self):
        result = self._pending_region
        self._pending_region = None
        if result is not None:
            self.current_region = result
            self.region_selected.emit(*result)
        if isValid(self) and self._current_overlay is None:
            self.selection_finished.emit()

    def _cleanup_previous_overlay(self, *, close_overlay=True):
        self._result_timer.stop()
        self._pending_region = None
        overlay, self._current_overlay = self._current_overlay, None
        for connection in self._overlay_connections:
            QObject.disconnect(connection)
        self._overlay_connections.clear()
        if overlay is not None and isValid(overlay):
            if close_overlay:
                overlay.close()
            overlay.hide()
            overlay.deleteLater()

    def closeEvent(self, event):
        self._cleanup_previous_overlay()
        super().closeEvent(event)

    def hideEvent(self, event):
        self._cleanup_previous_overlay()
        super().hideEvent(event)

    def event(self, event):
        if event.type() == QEvent.Type.DeferredDelete:
            self._cleanup_previous_overlay()
        return super().event(event)

    def get_region(self) -> Tuple[int, int, int, int]:
        return self.current_region

    def get_region_binding_info(self) -> Dict[str, Any]:
        return dict(self.current_region_binding)

    def set_region(self, x, y, width, height):
        self.current_region = (x, y, width, height)

    def _build_region_binding_info(self, hwnd):
        bound, title, class_name, width, height = normalize_region_binding_hwnd(hwnd)
        if not bound or width <= 0 or height <= 0:
            raise ValueError("无法确认框选窗口的身份与客户区尺寸")
        return dict(region_hwnd=bound, region_window_title=title, region_window_class=class_name,
                    region_client_width=width, region_client_height=height)
