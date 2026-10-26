#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
坐标选择器 - 支持窗口激活的坐标获取工具
"""

import logging
from typing import Optional, Tuple, List
from PySide6.QtWidgets import QWidget, QPushButton, QVBoxLayout, QMessageBox
from PySide6.QtCore import Signal, QPoint, QPointF, QRect, Qt, QTimer, QEvent, QObject
from shiboken6 import isValid
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen
from themes import theme_color

from utils.window.window_coordinate_common import (
    build_window_info,
    client_relative_to_qt_global,
    get_window_client_logical_size,
    get_window_client_physical_size,
    normalize_window_hwnd,
)
from utils.window.window_overlay_utils import (
    apply_overlay_text_style,
    overlay_hint_font,
    capture_virtual_desktop_pixmap,
    capture_window_client_pixmap,
    configure_opaque_picker_overlay,
    draw_picker_backdrop,
    draw_target_window_overlay,
    get_target_window_overlay_rect,
    overlay_point_to_client_qpoint,
    overlay_rect_contains_point,
    prime_picker_backdrop,
    sync_overlay_geometry,
)
from utils.window.window_activation_utils import (
    activate_window,
    grab_overlay_input,
    release_overlay_input,
    show_and_activate_overlay,
)
from .multi_coordinate_text import (
    MULTI_COORDINATE_BUTTON_TEXT,
    MULTI_COORDINATE_DRAWING_HINT,
    MULTI_COORDINATE_EMPTY_HINT_LINES,
    MULTI_COORDINATE_SELECTED_HINT_LINES,
    format_multi_coordinate_selected_text,
    overlay_point_distance_sq,
    should_finish_route_on_release,
    should_sample_route_point,
)

logger = logging.getLogger(__name__)


def _get_global_bound_window(widget):
    current = widget.parent()
    while current is not None:
        host = getattr(current, "main_window", None)
        if host is None and hasattr(current, "bound_windows"):
            host = current
        if host is not None:
            windows = getattr(host, "bound_windows", None)
            if not isinstance(windows, list) or any(not isinstance(item, dict) or type(item.get("enabled")) is not bool for item in windows):
                logger.error("全局窗口绑定尚未就绪")
                return None
            enabled = [item for item in windows if item["enabled"]]
            if len(enabled) != 1:
                logger.error("请在全局设置中仅启用一个目标窗口")
                return None
            hwnd = enabled[0].get("hwnd")
            if type(hwnd) is not int or hwnd <= 0:
                logger.error("全局绑定窗口句柄无效")
                return None
            return hwnd
        current = current.parent()
    logger.error("未找到全局窗口绑定的所有者")
    return None



def _picker_qcolor(key: str, alpha: int = 255) -> QColor:
    color = QColor(theme_color(key))
    color.setAlpha(max(0, min(255, int(alpha))))
    return color


def build_smooth_route_path(points) -> QPainterPath:
    path = QPainterPath()
    cleaned = []
    for point in points or ():
        if point is None:
            continue
        cleaned.append(QPointF(float(point.x()), float(point.y())))
    if not cleaned:
        return path
    path.moveTo(cleaned[0])
    if len(cleaned) == 1:
        return path
    if len(cleaned) == 2:
        path.lineTo(cleaned[1])
        return path
    padded = [cleaned[0], *cleaned, cleaned[-1]]
    for index in range(1, len(padded) - 2):
        previous = padded[index - 1]
        current = padded[index]
        nxt = padded[index + 1]
        following = padded[index + 2]
        control_out = QPointF(
            current.x() + (nxt.x() - previous.x()) / 6.0,
            current.y() + (nxt.y() - previous.y()) / 6.0,
        )
        control_in = QPointF(
            nxt.x() - (following.x() - current.x()) / 6.0,
            nxt.y() - (following.y() - current.y()) / 6.0,
        )
        path.cubicTo(control_out, control_in, nxt)
    return path

import win32gui

class CoordinateSelectorOverlay(QWidget):
    """坐标选择器覆盖层"""

    coordinate_selected = Signal(int, int)  # x, y
    selection_closed = Signal()

    def __init__(self, target_window_hwnd: int, parent=None):
        super().__init__(parent)  # 顶层窗口归创建者所有
        self.target_window_hwnd = target_window_hwnd  # 目标窗口句柄
        self.target_hwnd = None
        self.window_info = None
        self.target_window_title = ""  # 从句柄获取的窗口标题，仅用于显示
        self.backdrop_pixmap = None
        self.desktop_pixmap = None
        self._composed_backdrop = None
        self._composed_backdrop_key = None
        self._capture_released = False
        self._activation_timers = []
        for delay in (50, 150, 300):
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(delay)
            timer.timeout.connect(self._ensure_ready_for_input)
            self._activation_timers.append(timer)
        self._preview_close_timer = QTimer(self)
        self._preview_close_timer.setSingleShot(True)
        self._preview_close_timer.setInterval(300)
        self._preview_close_timer.timeout.connect(self._close_after_preview)

        # 选择状态
        self.selecting = False
        self.click_pos = QPoint()

        # 窗口激活状态标志
        self._is_ready_for_input = False
        self._activation_attempts = 0

        configure_opaque_picker_overlay(self)
        if parent is not None:
            parent.destroyed.connect(self._release_capture)

        logger.info("创建坐标选择器覆盖层")

        # 初始化失败的独立窗口也必须销毁。
        try:
            self.setup_target_window()
        except Exception:
            self._release_capture()
            self.deleteLater()
            raise
    
    def setup_target_window(self):
        """设置目标窗口"""
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
        self._refresh_backdrop()
        
        return True

    def _refresh_backdrop(self) -> None:
        hwnd = int(self.target_window_hwnd or 0)
        self.backdrop_pixmap = capture_window_client_pixmap(hwnd) if hwnd else None
        self.desktop_pixmap = capture_virtual_desktop_pixmap()
        prime_picker_backdrop(
            self,
            desktop_pixmap=self.desktop_pixmap,
            window_pixmap=self.backdrop_pixmap,
            target_rect=self._get_target_window_rect() if self.window_info else QRect(),
        )

    def _paint_backdrop(self, painter) -> None:
        target_rect = self._get_target_window_rect() if self.window_info else QRect()
        draw_picker_backdrop(
            painter,
            self,
            desktop_pixmap=self.desktop_pixmap,
            window_pixmap=self.backdrop_pixmap,
            target_rect=target_rect,
        )

    def _get_window_info(self, hwnd: int):
        """获取窗口信息（包括DPI处理）"""
        try:
            window_title = win32gui.GetWindowText(hwnd)
            class_name = win32gui.GetClassName(hwnd)
            use_window_rect = (
                self.target_window_title == "TheRender" or class_name == "RenderWindow"
            )
            if use_window_rect:
                logger.info("检测到渲染窗口，使用窗口矩形")

            window_info = build_window_info(
                hwnd,
                use_window_rect_as_client=use_window_rect,
                include_system_metrics=True,
            )
            if not window_info:
                return None

            window_info['window_title'] = window_title
            window_info['class_name'] = class_name
            logical_width, logical_height = get_window_client_logical_size(window_info)
            physical_width = int(window_info.get('client_physical_width', 0) or 0)
            physical_height = int(window_info.get('client_physical_height', 0) or 0)

            logger.info(f"窗口矩形: {window_info['window_rect']}")
            logger.info(f"客户区矩形: {window_info['client_rect']}")
            logger.info(f"窗口类名: {class_name}")
            logger.info(f"窗口信息: 客户区逻辑位置({window_info.get('client_qt_screen_pos', window_info['client_screen_pos'])}), "
                       f"逻辑尺寸({logical_width}x{logical_height}), "
                       f"物理尺寸({physical_width}x{physical_height})")
            logger.info(f"DPI信息: 窗口DPI={window_info['window_dpi']}, 系统DPI={window_info['system_dpi']}, Qt DPI={window_info['qt_dpi']:.1f}")
            logger.info(f"缩放因子: 窗口={window_info['window_scale_factor']:.2f}, 系统={window_info['system_scale_factor']:.2f}, Qt={window_info['qt_device_pixel_ratio']:.2f}")

            return window_info

        except Exception as e:
            logger.error(f"获取窗口信息失败: {e}")
            return None

    def _activate_target_window(self, hwnd: int):
        """激活失败必须停止采集，不能继续使用未确认的目标窗口。"""
        if not activate_window(hwnd, log_prefix='坐标选择'):
            raise RuntimeError("无法激活目标窗口，不能启动坐标采集")
        logger.info(f"已激活并置顶目标窗口：{self.target_window_title}")

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
        """只返回客户区坐标，转换失败不得用屏幕坐标替代。"""
        if not self.window_info:
            raise ValueError("目标窗口信息缺失，无法转换坐标")
        target_rect = self._get_target_window_rect()
        if target_rect.isEmpty():
            raise ValueError("目标窗口客户区为空，无法转换坐标")
        return overlay_point_to_client_qpoint(self.window_info, target_rect, qt_screen_pos)

    def _is_point_in_target_window(self, qt_screen_pos: QPoint) -> bool:
        """Check whether a point is inside the target window in Qt logical coordinates."""
        if not self.window_info:
            return False

        target_rect = self._get_target_window_rect()
        return overlay_rect_contains_point(target_rect, qt_screen_pos)

    def paintEvent(self, event):
        if self._capture_released:
            return
        """Paint overlay."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)

        self._paint_backdrop(painter)

        if self.window_info:
            target_rect = self._get_target_window_rect()
            draw_target_window_overlay(
                painter,
                target_rect,
                title=f"目标窗口: {self.target_window_title}",
                subtitle_lines=["点击选择坐标"],
            )

        
        # 绘制十字光标（点击后显示）
        # 检查点击位置是否有效（不是初始的(0,0)位置）
        if not self.click_pos.isNull() and (self.click_pos.x() != 0 or self.click_pos.y() != 0):
            # 绘制适中大小的十字光标
            cross_size = 15  # 减小十字光标大小

            # 绘制白色外边框（增强可见性）
            pen_outline = QPen(QColor(theme_color('selection_text')), 3)  # 减小外边框粗细
            painter.setPen(pen_outline)
            painter.drawLine(self.click_pos.x() - cross_size, self.click_pos.y(),
                           self.click_pos.x() + cross_size, self.click_pos.y())
            painter.drawLine(self.click_pos.x(), self.click_pos.y() - cross_size,
                           self.click_pos.x(), self.click_pos.y() + cross_size)

            # 绘制红色内部十字
            pen_inner = QPen(QColor(theme_color('selection_marker')), 1)  # 减小内部线条粗细
            painter.setPen(pen_inner)
            painter.drawLine(self.click_pos.x() - cross_size, self.click_pos.y(),
                           self.click_pos.x() + cross_size, self.click_pos.y())
            painter.drawLine(self.click_pos.x(), self.click_pos.y() - cross_size,
                           self.click_pos.x(), self.click_pos.y() + cross_size)

            # 绘制中心点
            painter.setBrush(QBrush(QColor(theme_color('selection_marker'))))
            painter.drawEllipse(self.click_pos, 2, 2)  # 减小中心点大小

            # 显示坐标信息（带背景）
            if self.window_info:
                relative_pos = self._get_relative_coordinates(self.click_pos)
                coord_text = f"坐标: ({relative_pos.x()}, {relative_pos.y()})"

                # 绘制文本背景
                text_rect = painter.fontMetrics().boundingRect(coord_text)
                text_pos = self.click_pos + QPoint(35, -10)
                bg_rect = text_rect.translated(text_pos)
                bg_rect.adjust(-5, -2, 5, 2)

                painter.setBrush(QBrush(QColor(theme_color('selection_backdrop'))))
                apply_overlay_text_style(painter)
                painter.drawRect(bg_rect)
                painter.drawText(text_pos, coord_text)

    def showEvent(self, event):
        """窗口显示事件 - 先抓输入，再补一次激活。"""
        super().showEvent(event)
        grab_overlay_input(self, log_prefix='坐标选择覆盖层')
        for timer in self._activation_timers:
            timer.start()

    def _ensure_ready_for_input(self):
        """只有成功抓取输入后才标记就绪。"""
        if self._closing or not self.isVisible() or getattr(self, "dragging", False):
            return
        self._is_ready_for_input = grab_overlay_input(
            self, log_prefix='坐标选择覆盖层', activate=True,
        )

    def mousePressEvent(self, event):
        """鼠标按下事件。第一次点击直接选点，不拿来激活窗口。"""
        if event.button() == Qt.MouseButton.LeftButton:
            # 检查是否在目标窗口内
            if self._is_point_in_target_window(event.position().toPoint()):
                self.click_pos = event.position().toPoint()
                logger.info(f"设置点击位置: {self.click_pos}")
                self.update()  # 立即更新显示十字光标

                # 转换为相对坐标
                relative_pos = self._get_relative_coordinates(event.position().toPoint())

                logger.info(f"坐标选择完成: 屏幕({event.position().toPoint().x()}, {event.position().toPoint().y()}) -> 客户区({relative_pos.x()}, {relative_pos.y()})")

                # 验证坐标转换是否正确
                if self.window_info:
                    hwnd = self.window_info['hwnd']
                    logger.debug(f"目标窗口句柄: {hwnd}")

                    # 验证客户区坐标是否在合理范围内
                    try:
                        client_width, client_height = get_window_client_physical_size(self.window_info)

                        if 0 <= relative_pos.x() <= client_width and 0 <= relative_pos.y() <= client_height:
                            logger.debug(f"客户区坐标有效: ({relative_pos.x()}, {relative_pos.y()}) 在范围 {client_width}x{client_height} 内")
                        else:
                            logger.warning(f"客户区坐标可能无效: ({relative_pos.x()}, {relative_pos.y()}) 超出范围 {client_width}x{client_height}")
                    except Exception as e:
                        logger.debug(f"坐标验证失败: {e}")

                # 直接发射坐标信号（不使用通用坐标系统标准化）
                self._preview_close_timer.start()
                self.coordinate_selected.emit(relative_pos.x(), relative_pos.y())
            else:
                logger.warning("点击位置不在目标窗口内")

        elif event.button() == Qt.MouseButton.RightButton:
            logger.info("右键点击，取消选择")
            self.close()
    
    def keyPressEvent(self, event):
        """键盘事件"""
        if event.key() == Qt.Key.Key_Escape:
            logger.info("ESC键退出")
            self.close()

    def _close_after_preview(self):
        if not self._capture_released:
            self.close()

    def _release_capture(self):
        if self._capture_released:
            return False
        self._capture_released = True
        self._closing = True
        self._is_ready_for_input = False
        for timer in self._activation_timers:
            timer.stop()
        self._preview_close_timer.stop()
        release_overlay_input(self)
        self.backdrop_pixmap = None
        self.desktop_pixmap = None
        self._composed_backdrop = None
        self._composed_backdrop_key = None
        return True

    def closeEvent(self, event):
        if self._release_capture():
            self.selection_closed.emit()
        super().closeEvent(event)

    def hideEvent(self, event):
        if self._release_capture():
            self.selection_closed.emit()
        super().hideEvent(event)

    def event(self, event):
        if event.type() == QEvent.Type.DeferredDelete:
            self._release_capture()
        return super().event(event)

class OffsetSelectorOverlay(CoordinateSelectorOverlay):
    """偏移选择覆盖层（拖拽选择偏移）"""

    offset_selected = Signal(int, int)  # dx, dy
    selection_closed = Signal()

    def __init__(self, target_window_hwnd: int, base_client: Optional[Tuple[int, int]] = None,
                 base_rect: Optional[Tuple[int, int, int, int]] = None, parent=None):
        super().__init__(target_window_hwnd, parent)
        self.dragging = False
        self.drag_start = None
        self.drag_end = None
        self.base_client = base_client
        self.base_rect = base_rect

    def _get_base_point_qt(self) -> Optional[QPoint]:
        if not (self.window_info and self.base_client):
            return None
        try:
            qt_x, qt_y = client_relative_to_qt_global(
                self.window_info,
                int(self.base_client[0]),
                int(self.base_client[1]),
            )
            return self.mapFromGlobal(QPoint(qt_x, qt_y))
        except Exception as e:
            raise ValueError(f"转换偏移基准点失败：{e}") from e

    def _get_base_rect_qt(self) -> Optional[QRect]:
        if not (self.window_info and self.base_rect):
            return None
        try:
            rect_x, rect_y, rect_w, rect_h = self.base_rect
            left, top = client_relative_to_qt_global(
                self.window_info,
                int(rect_x),
                int(rect_y),
            )
            right, bottom = client_relative_to_qt_global(
                self.window_info,
                int(rect_x) + int(rect_w),
                int(rect_y) + int(rect_h),
            )
            top_left_local = self.mapFromGlobal(QPoint(left, top))
            bottom_right_local = self.mapFromGlobal(QPoint(right, bottom))
            return QRect(top_left_local, bottom_right_local).normalized()
        except Exception as e:
            raise ValueError(f"转换偏移基准区域失败：{e}") from e

    def mousePressEvent(self, event):
        if self._capture_released:
            return
        if event.button() == Qt.MouseButton.LeftButton:
            if self.window_info and self._is_point_in_target_window(event.pos()):
                self.dragging = True
                base_point = self._get_base_point_qt()
                self.drag_start = base_point if base_point is not None else event.pos()
                self.drag_end = event.pos()
                self.click_pos = self.drag_start
                self.update()
            else:
                logger.warning("偏移选择点击位置不在目标窗口内")
        elif event.button() == Qt.MouseButton.RightButton:
            logger.info("偏移选择右键取消")
            self.close()

    def mouseMoveEvent(self, event):
        if self._capture_released:
            return
        if self.dragging:
            self.drag_end = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        if self._capture_released:
            return
        if self.dragging and event.button() == Qt.MouseButton.LeftButton:
            self.dragging = False
            self.drag_end = event.pos()

            if self.window_info and self.drag_start is not None and self.drag_end is not None:
                start_rel = self._get_relative_coordinates(self.drag_start)
                end_rel = self._get_relative_coordinates(self.drag_end)
                dx = end_rel.x() - start_rel.x()
                dy = end_rel.y() - start_rel.y()
                logger.info(
                    "偏移选择完成: 起点(%s,%s) -> 终点(%s,%s), 偏移(%s,%s)",
                    start_rel.x(), start_rel.y(), end_rel.x(), end_rel.y(), dx, dy
                )
                self.offset_selected.emit(dx, dy)

            self.update()
            self._preview_close_timer.start()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)

        self._paint_backdrop(painter)

        if self.window_info:
            target_rect = self._get_target_window_rect()
            if not target_rect.isEmpty():
                painter.setPen(QPen(QColor(theme_color('selection_target')), 4))
                painter.drawRect(target_rect)
                apply_overlay_text_style(painter)
                painter.drawText(target_rect.topLeft() + QPoint(10, 25), f"目标窗口: {self.target_window_title}")
                painter.drawText(target_rect.topLeft() + QPoint(10, 50), "拖拽选择偏移")

        # 绘制基准区域
        base_rect = self._get_base_rect_qt()
        if base_rect:
            painter.setPen(QPen(QColor(theme_color('selection_anchor')), 2))
            painter.setBrush(QBrush(QColor(theme_color('selection_anchor_fill'))))
            painter.drawRect(base_rect)

        # 绘制基准点
        base_point = self._get_base_point_qt()
        if base_point is not None:
            painter.setPen(QPen(QColor(theme_color('selection_text')), 2))
            painter.setBrush(QBrush(QColor(theme_color('selection_anchor'))))
            painter.drawEllipse(base_point, 8, 8)
            painter.setPen(QPen(QColor(theme_color('selection_anchor_edge')), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(base_point, 11, 11)

        if not (self.drag_start and self.drag_end):
            return

        painter.setPen(QPen(QColor(theme_color('selection_route')), 2))
        painter.drawLine(self.drag_start, self.drag_end)

        if self.window_info:
            start_rel = self._get_relative_coordinates(self.drag_start)
            end_rel = self._get_relative_coordinates(self.drag_end)
            dx = end_rel.x() - start_rel.x()
            dy = end_rel.y() - start_rel.y()
            text = f"偏移: ({dx:+d}, {dy:+d})"
            apply_overlay_text_style(painter)
            text_rect = painter.fontMetrics().boundingRect(text)
            text_pos = self.drag_end + QPoint(12, -8)
            bg_rect = text_rect.translated(text_pos)
            bg_rect.adjust(-4, -2, 4, 2)
            painter.setBrush(QBrush(QColor(theme_color('selection_backdrop'))))
            painter.drawRect(bg_rect)
            painter.drawText(text_pos, text)


class OffsetSelectorWidget(QWidget):
    """偏移选择控件"""

    offset_selected = Signal(int, int)  # dx, dy
    selection_started = Signal()
    selection_finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.target_window_hwnd = None
        self.current_offset = (0, 0)
        self.base_point = None
        self.base_rect = None
        self._current_overlay = None
        self._pending_offset = None
        self._overlay_connections = []
        self._result_timer = QTimer(self)
        self._result_timer.setSingleShot(True)
        self._result_timer.timeout.connect(self._deliver_selection)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        self.select_button = QPushButton("拖拽选择偏移")
        self.select_button.clicked.connect(self.start_selection)
        layout.addWidget(self.select_button)

    def set_base_point(self, x: int, y: int):
        self.base_point = (x, y)

    def set_base_rect(self, x: int, y: int, w: int, h: int):
        self.base_rect = (x, y, w, h)

    def start_selection(self):
        """取坐标期间不重复创建窗口，结果在预览关闭后提交。"""
        if self._current_overlay is not None and isValid(self._current_overlay) and self._current_overlay.isVisible():
            return
        self._cleanup_previous_overlay()
        self.selection_started.emit()
        hwnd = self.target_window_hwnd
        if hwnd is None:
            hwnd = self._get_bound_window_hwnd()
        if not hwnd or not self._validate_hwnd_silent(hwnd):
            QMessageBox.warning(self, "警告", "没有可用的绑定窗口，请先在全局设置中绑定窗口")
            self.selection_finished.emit()
            return
        try:
            self.target_window_hwnd = hwnd
            overlay = OffsetSelectorOverlay(hwnd, base_client=self.base_point, base_rect=self.base_rect, parent=self)
            self._current_overlay = overlay
            if not overlay.window_info:
                raise ValueError("无法设置目标窗口")
            self._overlay_connections = [
                overlay.offset_selected.connect(self._on_offset_selected),
                overlay.selection_closed.connect(self._on_overlay_closed),
            ]
            if not show_and_activate_overlay(overlay, log_prefix='坐标选择覆盖层启动'):
                raise RuntimeError("无法显示坐标采集窗口")
            grab_overlay_input(overlay, log_prefix='坐标选择覆盖层')
        except Exception as error:
            self._cleanup_previous_overlay()
            logger.exception("启动坐标选择失败")
            QMessageBox.critical(self, "错误", f"启动坐标选择失败：{error}")
            self.selection_finished.emit()

    def _on_offset_selected(self, x: int, y: int):
        self._pending_offset = (x, y)

    def _on_overlay_closed(self):
        result = self._pending_offset
        self._cleanup_previous_overlay(close_overlay=False)
        self._pending_offset = result
        self._result_timer.start(0)

    def _deliver_selection(self):
        result = self._pending_offset
        self._pending_offset = None
        if result is not None:
            self.current_offset = result
            self.offset_selected.emit(*result)
        if isValid(self) and self._current_overlay is None:
            self.selection_finished.emit()

    def _cleanup_previous_overlay(self, *, close_overlay=True):
        self._result_timer.stop()
        self._pending_offset = None
        overlay = self._current_overlay
        self._current_overlay = None
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

    def _get_bound_window_hwnd(self) -> Optional[int]:
        return _get_global_bound_window(self)

    def _validate_hwnd_silent(self, hwnd):
        try:
            current = self.parent()
            while current is not None:
                host = getattr(current, "main_window", None)
                if host is None and hasattr(current, "is_hwnd_bound"):
                    host = current
                if host is not None:
                    if type(hwnd) is int and hwnd > 0 and host.is_hwnd_bound(hwnd):
                        return hwnd
                    logger.error("目标窗口未绑定，不能启动坐标采集")
                    return None
                current = current.parent()
            logger.error("未找到主窗口，不能验证目标窗口绑定")
        except Exception as error:
            logger.error(f"验证目标窗口绑定失败：{error}")
        return None

class CoordinateSelectorWidget(QWidget):
    """坐标选择器控件"""

    coordinate_selected = Signal(int, int)  # x, y
    selection_started = Signal()  # 选择开始信号
    selection_finished = Signal()  # 选择结束信号

    def __init__(self, parent=None):
        super().__init__(parent)
        self.target_window_hwnd = None  # 目标窗口句柄
        self.current_coordinate = (0, 0)
        self._current_overlay = None
        self._pending_coordinate = None
        self._overlay_connections = []
        self._result_timer = QTimer(self)
        self._result_timer.setSingleShot(True)
        self._result_timer.timeout.connect(self._deliver_selection)

        try:
            self.setup_ui()
            self._update_button_text()
        except Exception:
            self.deleteLater()
            raise
    
    def setup_ui(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        # 选择按钮
        self.select_button = QPushButton("点击获取坐标")
        self.select_button.clicked.connect(self.start_selection)
        layout.addWidget(self.select_button)

    def _update_button_text(self):
        """更新按钮文本以显示当前坐标"""
        if hasattr(self, 'select_button'):
            x, y = self.current_coordinate
            if x == 0 and y == 0:
                self.select_button.setText("点击获取坐标")
            else:
                self.select_button.setText(f"坐标: ({x}, {y})")

    def set_coordinate(self, x: int, y: int):
        """设置坐标值"""
        self.current_coordinate = (x, y)
        self._update_button_text()
        logger.info(f"坐标选择器坐标已设置为: ({x}, {y})")
    
    def start_selection(self):
        """取坐标期间不重复创建窗口，结果在预览关闭后提交。"""
        if self._current_overlay is not None and isValid(self._current_overlay) and self._current_overlay.isVisible():
            return
        self._cleanup_previous_overlay()
        self.selection_started.emit()
        hwnd = self.target_window_hwnd
        if hwnd is None:
            hwnd = self._get_bound_window_hwnd()
        if not hwnd or not self._validate_hwnd_silent(hwnd):
            QMessageBox.warning(self, "警告", "没有可用的绑定窗口，请先在全局设置中绑定窗口")
            self.selection_finished.emit()
            return
        try:
            self.target_window_hwnd = hwnd
            overlay = CoordinateSelectorOverlay(hwnd, self)
            self._current_overlay = overlay
            if not overlay.window_info:
                raise ValueError("无法设置目标窗口")
            self._overlay_connections = [
                overlay.coordinate_selected.connect(self._on_coordinate_selected),
                overlay.selection_closed.connect(self._on_overlay_closed),
            ]
            if not show_and_activate_overlay(overlay, log_prefix='坐标选择覆盖层启动'):
                raise RuntimeError("无法显示坐标采集窗口")
            grab_overlay_input(overlay, log_prefix='坐标选择覆盖层')
        except Exception as error:
            self._cleanup_previous_overlay()
            logger.exception("启动坐标选择失败")
            QMessageBox.critical(self, "错误", f"启动坐标选择失败：{error}")
            self.selection_finished.emit()

    def _on_coordinate_selected(self, x: int, y: int):
        self._pending_coordinate = (x, y)

    def _on_overlay_closed(self):
        result = self._pending_coordinate
        self._cleanup_previous_overlay(close_overlay=False)
        self._pending_coordinate = result
        self._result_timer.start(0)

    def _deliver_selection(self):
        result = self._pending_coordinate
        self._pending_coordinate = None
        if result is not None:
            self.set_coordinate(*result)
            self.coordinate_selected.emit(*result)
        if isValid(self) and self._current_overlay is None:
            self.selection_finished.emit()

    def _cleanup_previous_overlay(self, *, close_overlay=True):
        self._result_timer.stop()
        self._pending_coordinate = None
        overlay = self._current_overlay
        self._current_overlay = None
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

    def _get_bound_window_hwnd(self) -> Optional[int]:
        return _get_global_bound_window(self)

    def _validate_hwnd_silent(self, hwnd):
        try:
            current = self.parent()
            while current is not None:
                host = getattr(current, "main_window", None)
                if host is None and hasattr(current, "is_hwnd_bound"):
                    host = current
                if host is not None:
                    if type(hwnd) is int and hwnd > 0 and host.is_hwnd_bound(hwnd):
                        return hwnd
                    logger.error("目标窗口未绑定，不能启动坐标采集")
                    return None
                current = current.parent()
            logger.error("未找到主窗口，不能验证目标窗口绑定")
        except Exception as error:
            logger.error(f"验证目标窗口绑定失败：{error}")
        return None

    def get_coordinate(self) -> Tuple[int, int]:
        """获取当前坐标"""
        return self.current_coordinate

class MultiPointCoordinateSelectorOverlay(QWidget):
    """多点坐标选择器覆盖层 - 支持连续获取多个坐标点"""

    coordinates_selected = Signal(list, list)  # 发射坐标点列表和时间戳列表: [(x1, y1), (x2, y2), ...], [t1, t2, ...]
    selection_closed = Signal()

    def __init__(self, target_window_hwnd: int, parent=None):
        super().__init__(parent)  # 顶层覆盖层仍归采集工具所有
        self.target_window_hwnd = target_window_hwnd
        self.target_hwnd = None
        self.window_info = None
        self.target_window_title = ""

        # 坐标点列表
        self.coordinate_points = []
        self.click_positions = []  # 屏幕坐标位置，用于绘制
        self.click_timestamps = []
        self.selection_start_time = None
        self._drawing = False
        self._stroke_moved = False
        self._hover_pos = None
        self._closing = False
        self._finishing = False
        self._activation_timers = []
        for delay in (50, 150, 300):
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(delay)
            timer.timeout.connect(self._ensure_ready_for_input)
            self._activation_timers.append(timer)

        # 窗口激活状态标志
        self._is_ready_for_input = False
        self._activation_attempts = 0
        self.backdrop_pixmap = None
        self.desktop_pixmap = None
        self._composed_backdrop = None
        self._composed_backdrop_key = None

        try:
            self._setup_overlay()
            if parent is not None:
                parent.destroyed.connect(self._release_capture)
            if not self._setup_target_window():
                logger.error("设置目标窗口失败")
        except Exception:
            self._release_capture()
            self.deleteLater()
            raise

    def _setup_overlay(self):
        """设置覆盖层为不透明顶层窗，避免 Windows 点穿。"""
        configure_opaque_picker_overlay(self)
        sync_overlay_geometry(self)

    def _setup_target_window(self):
        """设置目标窗口"""
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
        hwnd = int(self.target_window_hwnd or 0)
        self.backdrop_pixmap = capture_window_client_pixmap(hwnd) if hwnd else None
        self.desktop_pixmap = capture_virtual_desktop_pixmap()
        prime_picker_backdrop(
            self,
            desktop_pixmap=self.desktop_pixmap,
            window_pixmap=self.backdrop_pixmap,
            target_rect=self._get_target_window_rect() if self.window_info else QRect(),
        )

        return True

    def _get_window_info(self, hwnd: int) -> dict:
        """获取窗口信息"""
        try:
            import win32gui
            if not win32gui.IsWindow(hwnd):
                return None

            window_info = build_window_info(hwnd)
            if not window_info:
                return None

            window_title = win32gui.GetWindowText(hwnd)
            client_top_left = window_info['client_screen_pos']
            client_width = window_info['client_width']
            client_height = window_info['client_height']
            qt_device_pixel_ratio = window_info['qt_device_pixel_ratio']

            logger.debug(f"窗口信息: 标题={window_title}, 客户区屏幕位置={client_top_left}, "
                        f"客户区大小=({client_width}, {client_height}), DPI比例={qt_device_pixel_ratio}")

            return {
                'hwnd': hwnd,
                'title': window_title,
                'client_screen_pos': client_top_left,
                'client_width': client_width,
                'client_height': client_height,
                'qt_device_pixel_ratio': qt_device_pixel_ratio
            }
        except Exception as e:
            logger.error(f"获取窗口信息失败: {e}")
            return None

    def _setup_overlay_geometry(self):
        """Set overlay geometry."""
        try:
            screen = sync_overlay_geometry(self)
            logger.info(f"Overlay geometry set to fullscreen: {screen}")
        except Exception as e:
            logger.error(f"设置悬浮层几何信息失败：{e}")

    def _get_target_window_rect(self) -> QRect:
        """Get the target window client rect in overlay coordinates."""
        return get_target_window_overlay_rect(self, self.window_info)

    def _activate_target_window(self, hwnd: int):
        """激活失败必须停止采集，不能继续使用未确认的目标窗口。"""
        if not activate_window(hwnd, log_prefix='多点坐标选择'):
            raise RuntimeError("无法激活目标窗口，不能启动坐标采集")
        logger.info(f"已激活并置顶目标窗口：{self.target_window_title}")

    def _is_point_in_target_window(self, pos: QPoint) -> bool:
        """Check whether a point is inside the target window."""
        if not self.window_info:
            return False

        target_rect = self._get_target_window_rect()
        return overlay_rect_contains_point(target_rect, pos)

    def _get_relative_coordinates(self, qt_screen_pos: QPoint) -> QPoint:
        """只返回客户区坐标，转换失败不得用屏幕坐标替代。"""
        if not self.window_info:
            raise ValueError("目标窗口信息缺失，无法转换坐标")
        target_rect = self._get_target_window_rect()
        if target_rect.isEmpty():
            raise ValueError("目标窗口客户区为空，无法转换坐标")
        return overlay_point_to_client_qpoint(self.window_info, target_rect, qt_screen_pos)

    def _append_route_point(self, overlay_pos: QPoint) -> bool:
        """追加一个路线点。"""
        if not self._is_point_in_target_window(overlay_pos):
            logger.warning("点击位置不在目标窗口内")
            return False

        try:
            import time

            relative_pos = self._get_relative_coordinates(overlay_pos)
            point = (relative_pos.x(), relative_pos.y())
            if self.coordinate_points and self.coordinate_points[-1] == point:
                logger.info(f"忽略重复路线点: {point}")
                return False

            if self.selection_start_time is None:
                self.selection_start_time = time.time()
                elapsed_time = 0.0
            else:
                elapsed_time = max(0.0, time.time() - self.selection_start_time)

            self.coordinate_points.append(point)
            self.click_positions.append(QPoint(overlay_pos))
            self.click_timestamps.append(elapsed_time)
            logger.info(
                f"追加路线点 #{len(self.coordinate_points)}: 屏幕({overlay_pos.x()}, {overlay_pos.y()}) -> "
                f"客户区({point[0]}, {point[1]}), 时间戳={elapsed_time:.3f}s"
            )
            self.update()
            return True
        except Exception as e:
            logger.error(f"追加路线点失败: {e}")
            return False

    def _remove_last_route_point(self) -> bool:
        """撤销最后一个路线点。"""
        if not self.coordinate_points:
            return False

        removed_point = self.coordinate_points.pop()
        if self.click_positions:
            self.click_positions.pop()
        if self.click_timestamps:
            self.click_timestamps.pop()
        if not self.coordinate_points:
            self.selection_start_time = None

        logger.info(f"撤销路线点: {removed_point}")
        self.update()
        return True

    def _paint_route_marker(self, painter: QPainter, center: QPoint, label: str) -> None:
        accent = _picker_qcolor("accent")
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(accent))
        painter.drawEllipse(center, 3, 3)
        painter.setPen(QPen(accent))
        painter.setFont(overlay_hint_font())
        painter.drawText(center + QPoint(8, 4), label)

    def _paint_route(self, painter: QPainter, points) -> None:
        if not points:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        path = build_smooth_route_path(points)
        if len(points) > 1:
            stroke = QPen(_picker_qcolor("accent"), 2)
            stroke.setCapStyle(Qt.PenCapStyle.RoundCap)
            stroke.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(stroke)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)

        if len(points) == 1:
            self._paint_route_marker(painter, points[0], "目标")
        else:
            self._paint_route_marker(painter, points[0], "起点")
            self._paint_route_marker(painter, points[-1], "终点")
        painter.restore()

    def paintEvent(self, event):
        """Paint overlay."""
        if self._closing:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)

        target_rect = self._get_target_window_rect() if self.window_info else QRect()
        draw_picker_backdrop(
            painter,
            self,
            desktop_pixmap=self.desktop_pixmap,
            window_pixmap=self.backdrop_pixmap,
            target_rect=target_rect,
        )

        if self.window_info:
            draw_target_window_overlay(
                painter,
                target_rect,
                title=f"目标窗口: {self.target_window_title}",
                subtitle_lines=["按住左键划线，松开完成"],
            )

        route_points = list(self.click_positions)
        if self._drawing and self._hover_pos is not None:
            if not route_points or overlay_point_distance_sq(route_points[-1], self._hover_pos) > 0:
                route_points.append(self._hover_pos)
        self._paint_route(painter, route_points)

        apply_overlay_text_style(painter)
        if self._drawing and self.coordinate_points:
            painter.drawText(20, 30, format_multi_coordinate_selected_text(len(self.coordinate_points)))
            painter.drawText(20, 50, MULTI_COORDINATE_DRAWING_HINT)
        elif self.coordinate_points:
            painter.drawText(20, 30, format_multi_coordinate_selected_text(len(self.coordinate_points)))
            painter.drawText(20, 50, MULTI_COORDINATE_SELECTED_HINT_LINES[0])
            painter.drawText(20, 70, MULTI_COORDINATE_SELECTED_HINT_LINES[1])
        else:
            painter.drawText(20, 30, MULTI_COORDINATE_EMPTY_HINT_LINES[0])
            painter.drawText(20, 50, MULTI_COORDINATE_EMPTY_HINT_LINES[1])
            painter.drawText(20, 70, MULTI_COORDINATE_EMPTY_HINT_LINES[2])

    def showEvent(self, event):
        super().showEvent(event)
        if self._closing:
            return
        grab_overlay_input(self, log_prefix='多点坐标覆盖层')
        for timer in self._activation_timers:
            timer.start()

    def _ensure_ready_for_input(self):
        if self._closing or not self.isVisible() or self._drawing:
            return
        self._is_ready_for_input = grab_overlay_input(
            self, log_prefix='多点坐标覆盖层', activate=True,
        )

    def mousePressEvent(self, event):
        """鼠标按下事件。"""
        if self._closing or self._finishing:
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._drawing = True
            self._stroke_moved = False
            self._hover_pos = event.position().toPoint()
            self._append_route_point(event.position().toPoint())
        elif event.button() == Qt.MouseButton.RightButton:
            if not self._remove_last_route_point():
                logger.info("当前没有可撤销的路线点")

    def mouseMoveEvent(self, event):
        if self._closing or self._finishing:
            return
        if not self._drawing:
            return
        pos = event.position().toPoint()
        self._hover_pos = pos
        last = self.click_positions[-1] if self.click_positions else None
        if last is not None and overlay_point_distance_sq(last, pos) > 0:
            self._stroke_moved = True
        if should_sample_route_point(last, pos):
            self._append_route_point(pos)
        else:
            self.update()

    def mouseReleaseEvent(self, event):
        if self._closing or self._finishing:
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._drawing = False
        self._hover_pos = None
        if should_finish_route_on_release(
            point_count=len(self.coordinate_points),
            stroke_moved=self._stroke_moved,
        ):
            self._finish_selection()
            return
        self.update()

    def mouseDoubleClickEvent(self, event):
        if self._closing or self._finishing:
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self.coordinate_points:
            self._finish_selection()

    def keyPressEvent(self, event):
        """键盘事件。"""
        if self._closing or self._finishing:
            return
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            logger.info(f"完成路径选择，共 {len(self.coordinate_points)} 个坐标点")
            self._finish_selection()

        elif event.key() == Qt.Key.Key_Z and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            if not self._remove_last_route_point():
                logger.info("当前没有可撤销的路线点")

    def _finish_selection(self):
        """只记录一次结果；由工具在鼠标事件退出后提交给参数面板。"""
        if self._closing or self._finishing:
            return
        self._finishing = True
        if self.coordinate_points:
            points = self.coordinate_points.copy()
            timestamps = self.click_timestamps.copy()
            logger.info(f"多点坐标选择完成：{len(points)} 个点")
            self.coordinates_selected.emit(points, timestamps)
        if isValid(self):
            self.close()

    def _release_capture(self):
        if self._closing:
            return
        self._closing = True
        self._drawing = False
        self._hover_pos = None
        self._is_ready_for_input = False
        for timer in self._activation_timers:
            timer.stop()
        release_overlay_input(self)
        self.backdrop_pixmap = None
        self.desktop_pixmap = None
        self._composed_backdrop = None
        self._composed_backdrop_key = None
        self.coordinate_points.clear()
        self.click_positions.clear()
        self.click_timestamps.clear()
        self.selection_start_time = None
        self.selection_closed.emit()

    def closeEvent(self, event):
        self._release_capture()
        super().closeEvent(event)

    def hideEvent(self, event):
        self._release_capture()
        super().hideEvent(event)

    def event(self, event):
        if event.type() == QEvent.Type.DeferredDelete:
            self._release_capture()
        return super().event(event)


class MultiPointCoordinateSelectorWidget(QWidget):
    """多点坐标选择器Widget - 支持连续获取多个坐标点"""

    coordinates_selected = Signal(list, list)  # 发射坐标点列表和时间戳列表
    selection_finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.target_window_hwnd = None
        self.coordinate_points = []
        self.coordinate_timestamps = []
        self.overlay = None
        self._overlay_connections = []
        self._pending_result = None
        self._result_timer = QTimer(self)
        self._result_timer.setSingleShot(True)
        self._result_timer.timeout.connect(self._deliver_selection)
        try:
            self._setup_ui()
        except Exception:
            self.deleteLater()
            raise

    def _setup_ui(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 选择按钮
        self.select_button = QPushButton(MULTI_COORDINATE_BUTTON_TEXT)
        self.select_button.setObjectName("parameterMultiCoordinateButton")
        self.select_button.clicked.connect(self.start_selection)

        layout.addWidget(self.select_button)

        self._update_button_text()

    def start_selection(self):
        """同一工具同时只允许一轮采集。"""
        if self.overlay is not None and isValid(self.overlay) and self.overlay.isVisible():
            logger.info("多点坐标选择覆盖层仍在活动，忽略重复启动")
            return
        self._cleanup_previous_overlay()
        hwnd = self.target_window_hwnd
        if hwnd is None:
            hwnd = self._get_bound_window_hwnd()
        if not hwnd or not self._validate_hwnd_silent(hwnd):
            QMessageBox.warning(self, "警告", "没有可用的绑定窗口，请先在全局设置中绑定窗口")
            self.selection_finished.emit()
            return
        try:
            self.target_window_hwnd = hwnd
            overlay = MultiPointCoordinateSelectorOverlay(hwnd, self)
            self.overlay = overlay
            if not overlay.window_info:
                raise ValueError("无法设置目标窗口")
            self._overlay_connections = [
                overlay.coordinates_selected.connect(self._on_coordinates_selected),
                overlay.selection_closed.connect(self._on_overlay_closed),
            ]
            if not show_and_activate_overlay(overlay, log_prefix='多点坐标覆盖层启动'):
                raise RuntimeError("无法显示坐标采集窗口")
            grab_overlay_input(overlay, log_prefix='多点坐标覆盖层')
        except Exception as error:
            self._cleanup_previous_overlay()
            logger.exception("启动多点坐标选择失败")
            QMessageBox.critical(self, "错误", f"启动坐标选择失败：{error}")
            self.selection_finished.emit()

    def _update_button_text(self):
        """更新按钮文本以显示当前坐标点数量"""
        if hasattr(self, 'select_button'):
            count = len(self.coordinate_points)
            if count == 0:
                self.select_button.setText(MULTI_COORDINATE_BUTTON_TEXT)
            else:
                self.select_button.setText(format_multi_coordinate_selected_text(count))

    def set_coordinates(self, coordinates: List[Tuple[int, int]]):
        """设置坐标点列表"""
        self.coordinate_points = coordinates.copy()
        self._update_button_text()
        logger.info(f"多点坐标选择器坐标已设置: {len(coordinates)} 个点")

    def _on_coordinates_selected(self, coordinates: List[Tuple[int, int]], timestamps: List[float]):
        # 覆盖层还在鼠标事件中，此处不能刷新面板或向外发射信号。
        if len(coordinates) != len(timestamps):
            raise ValueError("采集坐标与时间戳数量不一致")
        self._pending_result = (coordinates.copy(), timestamps.copy())

    def _on_overlay_closed(self):
        result = self._pending_result
        self._cleanup_previous_overlay(close_overlay=False)
        self._pending_result = result
        self._result_timer.start(0)

    def _deliver_selection(self):
        result = self._pending_result
        self._pending_result = None
        if result is not None:
            self.coordinate_points, self.coordinate_timestamps = result
            self._update_button_text()
        self.selection_finished.emit()
        # 结束通知可能销毁工具；结果通知必须是本轮最后一次访问。
        if result is not None and isValid(self):
            self.coordinates_selected.emit(*result)

    def _cleanup_previous_overlay(self, *, close_overlay=True):
        self._result_timer.stop()
        self._pending_result = None
        overlay = self.overlay
        self.overlay = None
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

    def _get_bound_window_hwnd(self) -> Optional[int]:
        return _get_global_bound_window(self)

    def _validate_hwnd_silent(self, hwnd):
        try:
            current = self.parent()
            while current is not None:
                host = getattr(current, "main_window", None)
                if host is None and hasattr(current, "is_hwnd_bound"):
                    host = current
                if host is not None:
                    if type(hwnd) is int and hwnd > 0 and host.is_hwnd_bound(hwnd):
                        return hwnd
                    logger.error("目标窗口未绑定，不能启动坐标采集")
                    return None
                current = current.parent()
            logger.error("未找到主窗口，不能验证目标窗口绑定")
        except Exception as error:
            logger.error(f"验证目标窗口绑定失败：{error}")
        return None

    def get_coordinates(self) -> List[Tuple[int, int]]:
        """获取当前坐标点列表"""
        return self.coordinate_points.copy()
