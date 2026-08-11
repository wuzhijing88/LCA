#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
坐标选择器 - 支持窗口激活的坐标获取工具
"""

import logging
from typing import Optional, Tuple, List
from PySide6.QtWidgets import QWidget, QPushButton, QVBoxLayout, QMessageBox, QApplication
from PySide6.QtCore import Signal, QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QPainter, QPen, QColor, QBrush

from utils.window_finder import resolve_unique_window_hwnd
from utils.window_coordinate_common import (
    get_qt_virtual_desktop_rect,
    build_window_info,
    client_relative_to_qt_global,
    get_window_client_logical_size,
    get_window_client_physical_size,
    normalize_window_hwnd,
)
from utils.window_overlay_utils import (
    draw_target_window_overlay,
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
    schedule_window_top_boost,
)
from .multi_coordinate_text import (
    MULTI_COORDINATE_BUTTON_TEXT,
    MULTI_COORDINATE_EMPTY_HINT_LINES,
    MULTI_COORDINATE_SELECTED_HINT_LINES,
    format_multi_coordinate_selected_text,
)

logger = logging.getLogger(__name__)

try:
    import win32gui
    import win32api
    PYWIN32_AVAILABLE = True
except ImportError:
    PYWIN32_AVAILABLE = False
    logger.warning("pywin32 not available, coordinate selector may not work properly")

class CoordinateSelectorOverlay(QWidget):
    """坐标选择器覆盖层"""

    coordinate_selected = Signal(int, int)  # x, y
    selection_closed = Signal()

    def __init__(self, target_window_hwnd: int, parent=None):
        super().__init__(None)  # 独立窗口
        self.target_window_hwnd = target_window_hwnd  # 目标窗口句柄
        self.target_hwnd = None
        self.window_info = None
        self.target_window_title = ""  # 从句柄获取的窗口标题，仅用于显示

        # 选择状态
        self.selecting = False
        self.click_pos = QPoint()

        # 窗口激活状态标志
        self._is_ready_for_input = False
        self._activation_attempts = 0

        # 设置窗口属性（移除 BypassWindowManagerHint 以改善事件处理）
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )

        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        
        logger.info("创建坐标选择器覆盖层")

        # 初始化
        self.setup_target_window()
    
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
        """激活并置顶目标窗口。"""
        try:
            activation_hwnd = activate_window(hwnd, log_prefix='坐标选择')
            if not activation_hwnd:
                return

            logger.info(f"已激活并置顶目标窗口: {self.target_window_title}")

        except Exception as e:
            logger.warning(f"激活目标窗口失败: {e}")
            # 即使激活失败也继续执行，不影响坐标选择功能

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
                logger.warning("Target window rect is empty; cannot convert coordinates")
                return qt_screen_pos

            return overlay_point_to_client_qpoint(self.window_info, target_rect, qt_screen_pos)
        except Exception as e:
            logger.error(f"Coordinate conversion error: {e}")
            return qt_screen_pos

    def _is_point_in_target_window(self, qt_screen_pos: QPoint) -> bool:
        """Check whether a point is inside the target window in Qt logical coordinates."""
        if not self.window_info:
            return False

        target_rect = self._get_target_window_rect()
        return overlay_rect_contains_point(target_rect, qt_screen_pos)

    def paintEvent(self, event):
        """Paint overlay."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        fill_overlay_event_background(painter, self)

        if self.window_info:
            target_rect = self._get_target_window_rect()
            draw_target_window_overlay(
                painter,
                target_rect,
                title=f"Target window: {self.target_window_title}",
                subtitle_lines=["Click to select coordinate"],
            )

        
        # 绘制十字光标（点击后显示）
        # 检查点击位置是否有效（不是初始的(0,0)位置）
        if not self.click_pos.isNull() and (self.click_pos.x() != 0 or self.click_pos.y() != 0):
            # 绘制适中大小的十字光标
            cross_size = 15  # 减小十字光标大小

            # 绘制白色外边框（增强可见性）
            pen_outline = QPen(QColor(255, 255, 255), 3)  # 减小外边框粗细
            painter.setPen(pen_outline)
            painter.drawLine(self.click_pos.x() - cross_size, self.click_pos.y(),
                           self.click_pos.x() + cross_size, self.click_pos.y())
            painter.drawLine(self.click_pos.x(), self.click_pos.y() - cross_size,
                           self.click_pos.x(), self.click_pos.y() + cross_size)

            # 绘制红色内部十字
            pen_inner = QPen(QColor(255, 0, 0), 1)  # 减小内部线条粗细
            painter.setPen(pen_inner)
            painter.drawLine(self.click_pos.x() - cross_size, self.click_pos.y(),
                           self.click_pos.x() + cross_size, self.click_pos.y())
            painter.drawLine(self.click_pos.x(), self.click_pos.y() - cross_size,
                           self.click_pos.x(), self.click_pos.y() + cross_size)

            # 绘制中心点
            painter.setBrush(QBrush(QColor(255, 0, 0)))
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

                painter.setBrush(QBrush(QColor(0, 0, 0, 180)))
                painter.setPen(QPen(QColor(255, 255, 255), 1))
                painter.drawRect(bg_rect)

                # 绘制文本
                painter.setPen(QPen(QColor(255, 255, 255), 1))
                painter.drawText(text_pos, coord_text)

    def showEvent(self, event):
        """窗口显示事件 - 延迟激活以确保窗口系统准备就绪"""
        super().showEvent(event)
        # 延迟激活，确保窗口系统完成所有初始化
        from PySide6.QtCore import QTimer
        QTimer.singleShot(250, self._ensure_ready_for_input)

    def _ensure_ready_for_input(self):
        """确保覆盖层准备好接收输入"""
        ensure_overlay_ready_for_input(
            self,
            log_prefix='坐标选择覆盖层',
            ready_message='坐标选择器已就绪，可以接收输入',
            retry_message='坐标选择器未能激活（尝试 {attempt}/{max_attempts}），用户首次点击可能需要激活窗口',
            exhausted_message='已达到最大激活尝试次数，继续执行（用户首次操作将用于激活窗口）',
        )

    def mousePressEvent(self, event):
        """鼠标按下事件（添加窗口激活检查）"""
        # 检查窗口是否真的激活，如果未激活则先激活
        if not self.isActiveWindow():
            logger.warning("覆盖层未激活，尝试重新激活")
            activate_overlay_widget(self, log_prefix='坐标选择覆盖层', focus=True)
            self._is_ready_for_input = True  # 下次点击将正常工作

        if event.button() == Qt.MouseButton.LeftButton:
            # 检查是否在目标窗口内
            if self._is_point_in_target_window(event.pos()):
                self.click_pos = event.pos()
                logger.info(f"设置点击位置: {self.click_pos}")
                self.update()  # 立即更新显示十字光标

                # 转换为相对坐标
                relative_pos = self._get_relative_coordinates(event.pos())

                logger.info(f"坐标选择完成: 屏幕({event.pos().x()}, {event.pos().y()}) -> 客户区({relative_pos.x()}, {relative_pos.y()})")

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
                self.coordinate_selected.emit(relative_pos.x(), relative_pos.y())

                # 延迟关闭，让用户能看到十字光标
                from PySide6.QtCore import QTimer
                QTimer.singleShot(300, self.close)  # 300ms后关闭，减少等待时间
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

    def closeEvent(self, event):
        self.selection_closed.emit()
        super().closeEvent(event)

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
            logger.warning(f"转换偏移基准点失败: {e}")
            return None

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
            logger.warning(f"转换偏移基准区域失败: {e}")
            return None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.window_info and self._is_point_in_target_window(event.pos()):
                self.dragging = True
                self.drag_start = self._get_base_point_qt() or event.pos()
                self.drag_end = event.pos()
                self.click_pos = self.drag_start
                self.update()
            else:
                logger.warning("偏移选择点击位置不在目标窗口内")
        elif event.button() == Qt.MouseButton.RightButton:
            logger.info("偏移选择右键取消")
            self.close()

    def mouseMoveEvent(self, event):
        if self.dragging:
            self.drag_end = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        if self.dragging and event.button() == Qt.MouseButton.LeftButton:
            self.dragging = False
            self.drag_end = event.pos()

            if self.window_info and self.drag_start and self.drag_end:
                start_rel = self._get_relative_coordinates(self.drag_start)
                end_rel = self._get_relative_coordinates(self.drag_end)
                dx = end_rel.x() - start_rel.x()
                dy = end_rel.y() - start_rel.y()
                logger.info(
                    "偏移选择完成: 起点(%s,%s) -> 终点(%s,%s), 偏移(%s,%s)",
                    start_rel.x(), start_rel.y(), end_rel.x(), end_rel.y(), dx, dy
                )
                self.offset_selected.emit(dx, dy)

            QTimer.singleShot(300, self.close)

    def closeEvent(self, event):
        self.selection_closed.emit()
        super().closeEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 绘制近乎透明的全屏遮罩，用于捕获鼠标事件
        painter.fillRect(self.rect(), QColor(0, 0, 0, 1))

        if self.window_info:
            target_rect = self._get_target_window_rect()
            if not target_rect.isEmpty():
                painter.setPen(QPen(QColor(0, 255, 0), 4))
                painter.drawRect(target_rect)
                painter.setPen(QPen(QColor(255, 255, 255)))
                painter.drawText(target_rect.topLeft() + QPoint(10, 25), f"目标窗口: {self.target_window_title}")
                painter.drawText(target_rect.topLeft() + QPoint(10, 50), "拖拽选择偏移")

        # 绘制基准区域
        base_rect = self._get_base_rect_qt()
        if base_rect:
            painter.setPen(QPen(QColor(0, 200, 255), 2))
            painter.setBrush(QBrush(QColor(0, 200, 255, 40)))
            painter.drawRect(base_rect)

        # 绘制基准点
        base_point = self._get_base_point_qt()
        if base_point:
            painter.setPen(QPen(QColor(255, 255, 255), 2))
            painter.setBrush(QBrush(QColor(0, 200, 255)))
            painter.drawEllipse(base_point, 8, 8)
            painter.setPen(QPen(QColor(0, 90, 140), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(base_point, 11, 11)

        if not (self.drag_start and self.drag_end):
            return

        painter.setPen(QPen(QColor(255, 200, 0), 2))
        painter.drawLine(self.drag_start, self.drag_end)

        if self.window_info:
            start_rel = self._get_relative_coordinates(self.drag_start)
            end_rel = self._get_relative_coordinates(self.drag_end)
            dx = end_rel.x() - start_rel.x()
            dy = end_rel.y() - start_rel.y()
            text = f"偏移: ({dx:+d}, {dy:+d})"
            text_rect = painter.fontMetrics().boundingRect(text)
            text_pos = self.drag_end + QPoint(12, -8)
            bg_rect = text_rect.translated(text_pos)
            bg_rect.adjust(-4, -2, 4, 2)
            painter.setBrush(QBrush(QColor(0, 0, 0, 180)))
            painter.setPen(QPen(QColor(255, 255, 255), 1))
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
        self._selection_result_delivered = False
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
        if self._current_overlay:
            if self._current_overlay.isVisible():
                logger.info("偏移选择正在进行，忽略重复启动")
                return
            self._cleanup_previous_overlay()

        self._cleanup_previous_overlay()
        self._selection_result_delivered = False
        self.selection_started.emit()

        if not self.target_window_hwnd:
            self.target_window_hwnd = self._get_bound_window_hwnd()
            if not self.target_window_hwnd:
                QMessageBox.warning(self, "错误", "未找到绑定窗口，请先绑定窗口")
                self.selection_finished.emit()
                return

        overlay = OffsetSelectorOverlay(
            self.target_window_hwnd,
            base_client=self.base_point,
            base_rect=self.base_rect,
        )
        overlay.offset_selected.connect(self._on_offset_selected)
        overlay.selection_closed.connect(self._on_overlay_closed)
        self._current_overlay = overlay

        if overlay.setup_target_window():
            if show_and_activate_overlay(overlay, log_prefix='偏移选择覆盖层启动'):
                logger.info("已使用统一覆盖层激活链启动偏移选择覆盖层")
            schedule_window_top_boost(
                overlay.window_info['hwnd'],
                log_prefix='偏移选择目标窗口',
            )
        else:
            self._cleanup_previous_overlay()
            self.selection_finished.emit()
            QMessageBox.critical(self, "错误", "启动偏移选择失败")

    def _on_overlay_closed(self):
        selection_delivered = self._selection_result_delivered
        if self._current_overlay:
            self._cleanup_previous_overlay()
        if not selection_delivered:
            self.selection_finished.emit()
        self._selection_result_delivered = False

    def _on_offset_selected(self, dx: int, dy: int):
        self.current_offset = (dx, dy)
        self._selection_result_delivered = True
        self.offset_selected.emit(dx, dy)
        self.selection_finished.emit()

    def _cleanup_previous_overlay(self):
        if self._current_overlay:
            try:
                self._current_overlay.offset_selected.disconnect()
            except Exception:
                pass
            try:
                self._current_overlay.selection_closed.disconnect()
            except Exception:
                pass
            self._current_overlay.hide()
            self._current_overlay.deleteLater()
            self._current_overlay = None

    def _get_bound_window_hwnd(self) -> Optional[int]:
        try:
            current_widget = self.parent()
            level = 0
            max_levels = 10

            while current_widget and level < max_levels:
                if hasattr(current_widget, 'config'):
                    config = current_widget.config
                    if hasattr(config, 'target_window_title') and config.target_window_title:
                        return resolve_unique_window_hwnd(config.target_window_title)
                    if hasattr(config, 'bound_windows') and config.bound_windows:
                        enabled_windows = [w for w in config.bound_windows if w.get('enabled', True)]
                        if enabled_windows:
                            return enabled_windows[0].get('hwnd')

                if hasattr(current_widget, 'runner') and hasattr(current_widget.runner, 'config'):
                    config = current_widget.runner.config
                    if hasattr(config, 'target_window_title') and config.target_window_title:
                        return resolve_unique_window_hwnd(config.target_window_title)
                    if hasattr(config, 'bound_windows') and config.bound_windows:
                        enabled_windows = [w for w in config.bound_windows if w.get('enabled', True)]
                        if enabled_windows:
                            return enabled_windows[0].get('hwnd')

                current_widget = current_widget.parent()
                level += 1

            return None
        except Exception as e:
            logger.error(f"获取绑定窗口失败: {e}")
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
        self._selection_result_delivered = False

        self.setup_ui()
        self._update_button_text()
    
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
    
    def _get_bound_window_from_editor(self) -> Optional[str]:
        """从编辑器获取绑定的窗口（支持多窗口模式）"""
        try:
            logger.info("搜索 开始获取绑定的窗口标题...")

            # 向上查找主窗口，直到找到有config或runner属性的窗口
            current_widget = self.parent()
            level = 0

            while current_widget and level < 10:  # 最多向上查找10层
                logger.info(f"搜索 第{level}层窗口: {current_widget}")
                logger.info(f"搜索 第{level}层窗口类型: {type(current_widget)}")

                # 检查是否有bound_windows属性（多窗口模式）
                if hasattr(current_widget, 'bound_windows'):
                    bound_windows = current_widget.bound_windows
                    if bound_windows and len(bound_windows) > 0:
                        # 获取第一个启用的窗口
                        for window_info in bound_windows:
                            if window_info.get('enabled', True):
                                window_title = window_info.get('title')
                                if window_title:
                                    logger.info(f"搜索 从多窗口绑定列表获取第一个启用窗口: {window_title}")
                                    return window_title

                        # 如果没有启用的窗口，使用第一个窗口
                        first_window = bound_windows[0]
                        window_title = first_window.get('title')
                        if window_title:
                            logger.info(f"搜索 从多窗口绑定列表获取第一个窗口: {window_title}")
                            return window_title

                # 检查是否是主窗口（任务编辑器）
                if hasattr(current_widget, 'config'):
                    logger.info(f"搜索 第{level}层窗口有config属性")
                    config = current_widget.config
                    target_window_title = config.get('target_window_title')
                    if target_window_title:
                        logger.info(f"搜索 从第{level}层窗口配置获取目标窗口: {target_window_title}")
                        return target_window_title
                    else:
                        logger.info(f"搜索 第{level}层窗口config中没有target_window_title")

                # 检查是否有runner属性
                if hasattr(current_widget, 'runner'):
                    logger.info(f"搜索 第{level}层窗口有runner属性")
                    runner = current_widget.runner
                    if hasattr(runner, 'target_window_title'):
                        target_window_title = runner.target_window_title
                        logger.info(f"搜索 从第{level}层窗口runner获取目标窗口: {target_window_title}")
                        if target_window_title:
                            return target_window_title
                    else:
                        logger.info(f"搜索 第{level}层窗口runner没有target_window_title属性")

                # 检查是否有直接的target_window_title属性
                if hasattr(current_widget, 'target_window_title'):
                    target_window_title = current_widget.target_window_title
                    logger.info(f"搜索 从第{level}层窗口属性获取目标窗口: {target_window_title}")
                    if target_window_title:
                        return target_window_title

                # 向上查找父窗口
                current_widget = current_widget.parent()
                level += 1

            logger.info(f"搜索 查找了{level}层窗口，未找到绑定的目标窗口")
            return None

        except Exception as e:
            logger.exception(f"获取编辑器绑定窗口时出错: {e}")
            return None
    
    def start_selection(self):
        """开始坐标选择"""
        # 检查是否已经有活动的覆盖层
        if hasattr(self, '_current_overlay') and self._current_overlay:
            try:
                if self._current_overlay.isVisible():
                    logger.info("已有活动的坐标选择覆盖层，跳过重复创建")
                    return
            except RuntimeError:
                self._current_overlay = None

        # 清理之前的覆盖层（如果存在）
        self._cleanup_previous_overlay()
        self._selection_result_delivered = False

        # 发出选择开始信号
        logger.info("发出坐标选择开始信号")
        self.selection_started.emit()

        # 如果没有设置目标窗口句柄，尝试自动获取绑定的窗口
        if not self.target_window_hwnd:
            self.target_window_hwnd = self._get_bound_window_hwnd()
            if not self.target_window_hwnd:
                QMessageBox.warning(self, "警告", "未找到绑定的窗口，请先绑定目标窗口")
                self.selection_finished.emit()
                return

            # 获取窗口标题用于显示
            try:
                import win32gui
                window_title = win32gui.GetWindowText(self.target_window_hwnd)
                self.select_button.setText(f"获取坐标 (已绑定: {window_title})")
                logger.info(f"自动获取绑定的窗口句柄: {self.target_window_hwnd}, 标题: {window_title}")
            except Exception as e:
                logger.error(f"从句柄获取窗口标题失败: {e}")
                self.select_button.setText(f"获取坐标 (已绑定: 窗口{self.target_window_hwnd})")

        # 【新增】验证句柄是否在全局绑定列表中（静默处理）
        validated_hwnd = self._validate_hwnd_silent(self.target_window_hwnd)
        if not validated_hwnd:
            QMessageBox.warning(self, "警告", "没有可用的绑定窗口，请先在全局设置中绑定窗口")
            self.selection_finished.emit()
            return

        # 创建选择覆盖层，使用验证后的句柄
        overlay = CoordinateSelectorOverlay(validated_hwnd)
        # 直接连接到内部处理方法，避免重复发射信号
        overlay.coordinate_selected.connect(self._on_coordinate_selected)
        overlay.selection_closed.connect(self._on_overlay_closed)

        # 保存覆盖层引用
        self._current_overlay = overlay
        
        if overlay.setup_target_window():
            if show_and_activate_overlay(overlay, log_prefix='坐标选择覆盖层启动'):
                logger.info("已使用统一覆盖层激活链启动坐标选择覆盖层")
            schedule_window_top_boost(
                overlay.window_info['hwnd'],
                log_prefix='坐标选择目标窗口',
            )
        else:
            self._cleanup_previous_overlay()
            self.selection_finished.emit()
            QMessageBox.critical(self, "错误", "无法设置目标窗口")

    def _clear_overlay_reference(self):
        """清理覆盖层引用"""
        if hasattr(self, '_current_overlay'):
            logger.info("清理覆盖层引用")
            self._current_overlay = None

    def _cleanup_previous_overlay(self):
        """清理之前的覆盖层"""
        if hasattr(self, '_current_overlay') and self._current_overlay:
            overlay = self._current_overlay
            logger.info("清理之前的坐标选择覆盖层")
            # 断开信号连接，避免触发不必要的信号
            try:
                overlay.coordinate_selected.disconnect()
                logger.info("已断开坐标选择覆盖层信号连接")
            except Exception as e:
                logger.warning(f"断开信号连接失败: {e}")
            try:
                overlay.selection_closed.disconnect()
            except Exception:
                pass

            # 直接删除覆盖层
            overlay.hide()
            overlay.deleteLater()
            logger.info("坐标选择覆盖层已隐藏并标记删除")

            # 清理引用
            self._current_overlay = None

    def _on_overlay_closed(self):
        selection_delivered = self._selection_result_delivered
        self._cleanup_previous_overlay()
        if not selection_delivered:
            self.selection_finished.emit()
        self._selection_result_delivered = False

    def _on_coordinate_selected(self, x: int, y: int):
        """坐标选择完成（直接使用客户区坐标）"""
        logger.info(f"坐标选择完成: ({x}, {y})")

        try:
            # 保存原始坐标
            self.set_coordinate(x, y)
            self._selection_result_delivered = True

            # 发射原始坐标信号
            self.coordinate_selected.emit(x, y)

            # 发出选择结束信号
            self.selection_finished.emit()

            logger.info(f"坐标处理完成: ({x}, {y})")

        except Exception as e:
            logger.error(f"处理坐标选择失败: {e}")
            # 确保即使出错也发射信号
            try:
                self._selection_result_delivered = True
                self.coordinate_selected.emit(x, y)
                self.selection_finished.emit()
            except:
                pass

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
                        return resolve_unique_window_hwnd(config.target_window_title)

                    # 多窗口模式
                    if hasattr(config, 'bound_windows') and config.bound_windows:
                        enabled_windows = [w for w in config.bound_windows if w.get('enabled', True)]
                        if enabled_windows:
                            return enabled_windows[0].get('hwnd')

                # 检查是否有runner属性
                if hasattr(current_widget, 'runner') and hasattr(current_widget.runner, 'config'):
                    config = current_widget.runner.config

                    if hasattr(config, 'target_window_title') and config.target_window_title:
                        return resolve_unique_window_hwnd(config.target_window_title)

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

    def get_coordinate(self) -> Tuple[int, int]:
        """获取当前坐标"""
        return self.current_coordinate

class MultiPointCoordinateSelectorOverlay(QWidget):
    """多点坐标选择器覆盖层 - 支持连续获取多个坐标点"""

    coordinates_selected = Signal(list, list)  # 发射坐标点列表和时间戳列表: [(x1, y1), (x2, y2), ...], [t1, t2, ...]
    selection_closed = Signal()

    def __init__(self, target_window_hwnd: int, parent=None):
        super().__init__(None)  # 独立窗口
        self.target_window_hwnd = target_window_hwnd
        self.target_hwnd = None
        self.window_info = None
        self.target_window_title = ""

        # 坐标点列表
        self.coordinate_points = []
        self.click_positions = []  # 屏幕坐标位置，用于绘制
        self.click_timestamps = []
        self.selection_start_time = None

        # 窗口激活状态标志
        self._is_ready_for_input = False
        self._activation_attempts = 0

        self._setup_overlay()
        if not self._setup_target_window():
            logger.error("设置目标窗口失败")
            return

    def _setup_overlay(self):
        """设置覆盖层（移除 BypassWindowManagerHint 以改善事件处理）"""
        # 设置为全屏覆盖层
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("background: transparent;")

        # 设置全屏
        screen = get_qt_virtual_desktop_rect() or QRect(0, 0, 0, 0)
        self.setGeometry(screen)

        # 设置鼠标追踪和焦点策略
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def _setup_target_window(self):
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

    def _get_window_info(self, hwnd: int) -> dict:
        """获取窗口信息"""
        try:
            if not PYWIN32_AVAILABLE:
                return None

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
        """激活并置顶目标窗口。"""
        try:
            activation_hwnd = activate_window(hwnd, log_prefix='多点坐标选择')
            if not activation_hwnd:
                return

            logger.info(f"已激活并置顶目标窗口: {self.target_window_title}")

        except Exception as e:
            logger.warning(f"激活目标窗口失败: {e}")
            # 即使激活失败也继续执行，不影响坐标选择功能

    def _is_point_in_target_window(self, pos: QPoint) -> bool:
        """Check whether a point is inside the target window."""
        if not self.window_info:
            return False

        target_rect = self._get_target_window_rect()
        return overlay_rect_contains_point(target_rect, pos)

    def _get_relative_coordinates(self, qt_screen_pos: QPoint) -> QPoint:
        """Convert Qt screen coordinates to client-relative coordinates."""
        if not self.window_info:
            return qt_screen_pos

        try:
            target_rect = self._get_target_window_rect()
            if target_rect.isEmpty():
                logger.warning("Target window rect is empty; cannot convert multi-point coordinates")
                return qt_screen_pos

            return overlay_point_to_client_qpoint(self.window_info, target_rect, qt_screen_pos)
        except Exception as e:
            logger.error(f"Coordinate conversion error: {e}")
            return qt_screen_pos

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

    def paintEvent(self, event):
        """Paint overlay."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        fill_overlay_event_background(painter, self)

        if self.window_info:
            target_rect = self._get_target_window_rect()
            draw_target_window_overlay(
                painter,
                target_rect,
                title=f"Target window: {self.target_window_title}",
                subtitle_lines=["Left click to add route points"],
            )

        if len(self.click_positions) > 1:
            pen = QPen(QColor(255, 0, 0), 3)
            painter.setPen(pen)
            for i in range(len(self.click_positions) - 1):
                painter.drawLine(self.click_positions[i], self.click_positions[i + 1])

        if self.click_positions:
            if len(self.click_positions) == 1:
                painter.setBrush(QColor(255, 80, 80, 180))
                painter.setPen(QColor(255, 255, 255))
                painter.drawEllipse(self.click_positions[0], 8, 8)
                painter.drawText(self.click_positions[0] + QPoint(15, 5), "目标")
            else:
                painter.setBrush(QColor(0, 255, 0, 180))
                painter.setPen(QColor(255, 255, 255))
                painter.drawEllipse(self.click_positions[0], 8, 8)
                painter.drawText(self.click_positions[0] + QPoint(15, 5), "起点")

                painter.setBrush(QColor(255, 0, 0, 180))
                painter.drawEllipse(self.click_positions[-1], 8, 8)
                painter.drawText(self.click_positions[-1] + QPoint(15, 5), "终点")

            for i in range(1, max(0, len(self.click_positions) - 1)):
                painter.setBrush(QColor(255, 255, 0, 120))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(self.click_positions[i], 4, 4)

        # 绘制提示信息
        painter.setPen(QColor(255, 255, 255))
        if len(self.coordinate_points) > 0:
            painter.drawText(20, 30, format_multi_coordinate_selected_text(len(self.coordinate_points)))
            painter.drawText(20, 50, MULTI_COORDINATE_SELECTED_HINT_LINES[0])
            painter.drawText(20, 70, MULTI_COORDINATE_SELECTED_HINT_LINES[1])
        else:
            painter.drawText(20, 30, MULTI_COORDINATE_EMPTY_HINT_LINES[0])
            painter.drawText(20, 50, MULTI_COORDINATE_EMPTY_HINT_LINES[1])
            painter.drawText(20, 70, MULTI_COORDINATE_EMPTY_HINT_LINES[2])

    def showEvent(self, event):
        """窗口显示事件 - 延迟激活以确保窗口系统准备就绪"""
        super().showEvent(event)
        # 延迟激活，确保窗口系统完成所有初始化
        from PySide6.QtCore import QTimer
        QTimer.singleShot(250, self._ensure_ready_for_input)

    def _ensure_ready_for_input(self):
        """确保覆盖层准备好接收输入"""
        ensure_overlay_ready_for_input(
            self,
            log_prefix='多点坐标覆盖层',
            ready_message='多点坐标选择器已就绪，可以接收输入',
            retry_message='多点坐标选择器未能激活（尝试 {attempt}/{max_attempts}），用户首次点击可能需要激活窗口',
            exhausted_message='已达到最大激活尝试次数，继续执行（用户首次操作将用于激活窗口）',
        )

    def mousePressEvent(self, event):
        """鼠标按下事件。"""
        if not self.isActiveWindow():
            logger.warning("多点坐标覆盖层未激活，尝试重新激活")
            activate_overlay_widget(self, log_prefix='多点坐标覆盖层', focus=True)
            self._is_ready_for_input = True

        if event.button() == Qt.MouseButton.LeftButton:
            self._append_route_point(event.pos())
        elif event.button() == Qt.MouseButton.RightButton:
            if not self._remove_last_route_point():
                logger.info("当前没有可撤销的路线点")

    def mouseMoveEvent(self, event):
        """鼠标移动事件。"""
        _ = event

    def mouseReleaseEvent(self, event):
        """鼠标释放事件。"""
        _ = event

    def keyPressEvent(self, event):
        """键盘事件"""
        if event.key() == Qt.Key.Key_Escape:
            # ESC键完成选择
            logger.info(f"ESC键完成选择，共选择了 {len(self.coordinate_points)} 个坐标点")
            self._finish_selection()

        elif event.key() == Qt.Key.Key_Z and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            # Ctrl+Z 撤销上一个点
            if not self._remove_last_route_point():
                logger.info("当前没有可撤销的路线点")

    def _finish_selection(self):
        """完成坐标选择"""
        if len(self.coordinate_points) >= 1:
            # 发射坐标列表和时间戳列表信号
            timestamps = self.click_timestamps.copy() if self.click_timestamps else []
            self.coordinates_selected.emit(self.coordinate_points.copy(), timestamps)

            total_duration = timestamps[-1] if timestamps else 0
            logger.info(f"多点坐标选择完成: {len(self.coordinate_points)}个点, 总时长={total_duration:.3f}s")
            logger.debug(f"坐标点: {self.coordinate_points}")
            logger.debug(f"时间戳: {timestamps}")
        else:
            logger.warning("至少需要选择1个坐标点")

        self.close()

    def closeEvent(self, event):
        self.selection_closed.emit()
        super().closeEvent(event)

class MultiPointCoordinateSelectorWidget(QWidget):
    """多点坐标选择器Widget - 支持连续获取多个坐标点"""

    coordinates_selected = Signal(list, list)  # 发射坐标点列表和时间戳列表
    selection_finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.target_window_hwnd = None
        self.coordinate_points = []
        self.coordinate_timestamps = []  # 时间戳列表
        self.overlay = None
        self._selection_result_delivered = False

        self._setup_ui()

    def _setup_ui(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 选择按钮
        self.select_button = QPushButton(MULTI_COORDINATE_BUTTON_TEXT)
        self.select_button.setStyleSheet("""
            QPushButton {
                background-color: #007ACC;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #005A9E;
            }
            QPushButton:pressed {
                background-color: #004578;
            }
        """)
        self.select_button.clicked.connect(self.start_selection)

        layout.addWidget(self.select_button)

        self._update_button_text()

    def start_selection(self):
        """开始多点坐标选择"""
        try:
            if self.overlay:
                try:
                    if self.overlay.isVisible():
                        logger.info("多点坐标选择覆盖层仍在活动，忽略重复启动")
                        return
                except RuntimeError:
                    self.overlay = None
                else:
                    self._cleanup_overlay()

            self._selection_result_delivered = False

            # 如果没有设置目标窗口句柄，尝试自动获取编辑器绑定的窗口
            if not self.target_window_hwnd:
                # 优先直接获取窗口句柄
                self.target_window_hwnd = self._get_bound_window_hwnd()
                if not self.target_window_hwnd:
                    QMessageBox.warning(self, "警告", "未找到绑定的窗口，请先绑定目标窗口")
                    self.selection_finished.emit()
                    return

                # 获取窗口标题用于显示
                try:
                    import win32gui
                    window_title = win32gui.GetWindowText(self.target_window_hwnd)
                    logger.info(f"自动获取绑定的窗口句柄: {self.target_window_hwnd}, 标题: {window_title}")
                except Exception as e:
                    logger.warning(f"从句柄获取窗口标题失败: {e}")

            logger.info(f"开始多点坐标选择，目标窗口句柄: {self.target_window_hwnd}")

            # 【新增】验证句柄是否在全局绑定列表中（静默处理）
            validated_hwnd = self._validate_hwnd_silent(self.target_window_hwnd)
            if not validated_hwnd:
                QMessageBox.warning(self, "警告", "没有可用的绑定窗口，请先在全局设置中绑定窗口")
                self.selection_finished.emit()
                return

            # 创建多点坐标选择器覆盖层，使用验证后的句柄
            self.overlay = MultiPointCoordinateSelectorOverlay(validated_hwnd, self)
            if not getattr(self.overlay, 'window_info', None):
                self._cleanup_overlay()
                self.selection_finished.emit()
                QMessageBox.critical(self, "错误", "无法设置目标窗口")
                return
            self.overlay.coordinates_selected.connect(self._on_coordinates_selected)
            self.overlay.selection_closed.connect(self._on_overlay_closed)

            # 显示覆盖层
            if show_and_activate_overlay(self.overlay, log_prefix='多点坐标覆盖层启动'):
                logger.info("已使用统一覆盖层激活链启动多点坐标选择覆盖层")
            schedule_window_top_boost(
                self.overlay.window_info['hwnd'],
                log_prefix='多点坐标选择目标窗口',
            )

        except Exception as e:
            self._cleanup_overlay()
            self.selection_finished.emit()
            logger.error(f"启动多点坐标选择失败: {e}")
            import traceback
            logger.error(f"错误详情: {traceback.format_exc()}")
            QMessageBox.critical(self, "错误", f"启动坐标选择失败: {e}")

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
        """多点坐标选择完成"""
        logger.info(f"多点坐标选择完成: {len(coordinates)} 个点")

        try:
            # 保存坐标点和时间戳
            self.coordinate_points = coordinates.copy()
            self.coordinate_timestamps = timestamps.copy()
            self._update_button_text()
            self._selection_result_delivered = True

            # 发射坐标和时间戳信号
            self.coordinates_selected.emit(coordinates, timestamps)

            # 发出选择结束信号
            self.selection_finished.emit()

            total_duration = timestamps[-1] if timestamps else 0
            logger.info(f"多点坐标处理完成: {len(coordinates)}个点, 总时长={total_duration:.3f}s")

        except Exception as e:
            logger.error(f"处理多点坐标选择失败: {e}")
            # 确保即使出错也发射信号
            try:
                self._selection_result_delivered = True
                self.coordinates_selected.emit(coordinates, timestamps if timestamps else [])
                self.selection_finished.emit()
            except:
                pass

    def _cleanup_overlay(self):
        if not self.overlay:
            return

        overlay = self.overlay
        self.overlay = None

        try:
            overlay.coordinates_selected.disconnect()
        except Exception:
            pass
        try:
            overlay.selection_closed.disconnect()
        except Exception:
            pass
        try:
            overlay.hide()
        except Exception:
            pass
        try:
            overlay.deleteLater()
        except Exception:
            pass

    def _on_overlay_closed(self):
        selection_delivered = self._selection_result_delivered
        self._cleanup_overlay()
        if not selection_delivered:
            self.selection_finished.emit()
        self._selection_result_delivered = False

    def _get_bound_window_hwnd(self) -> Optional[int]:
        """获取当前绑定的窗口句柄"""
        try:
            # 向上查找主窗口，获取绑定的窗口信息
            current_widget = self.parent()
            level = 0
            max_levels = 10

            while current_widget and level < max_levels:
                logger.debug(f"检查父级窗口 {level}: {type(current_widget).__name__}")

                # 检查是否有config属性（主窗口）
                if hasattr(current_widget, 'config') and hasattr(current_widget.config, 'bound_windows'):
                    config = current_widget.config
                    if config.bound_windows:
                        # 获取第一个启用的窗口
                        enabled_windows = [w for w in config.bound_windows if w.get('enabled', True)]
                        if enabled_windows:
                            hwnd = enabled_windows[0].get('hwnd')
                            logger.info(f"从主窗口config获取窗口句柄: {hwnd}")
                            return hwnd

                # 检查是否有runner属性（参数面板）
                if hasattr(current_widget, 'runner') and hasattr(current_widget.runner, 'config'):
                    config = current_widget.runner.config
                    if hasattr(config, 'bound_windows') and config.bound_windows:
                        # 获取第一个启用的窗口
                        enabled_windows = [w for w in config.bound_windows if w.get('enabled', True)]
                        if enabled_windows:
                            hwnd = enabled_windows[0].get('hwnd')
                            logger.info(f"从runner config获取窗口句柄: {hwnd}")
                            return hwnd

                # 检查是否有bound_windows属性（主窗口直接属性）
                if hasattr(current_widget, 'bound_windows') and current_widget.bound_windows:
                    enabled_windows = [w for w in current_widget.bound_windows if w.get('enabled', True)]
                    if enabled_windows:
                        hwnd = enabled_windows[0].get('hwnd')
                        logger.info(f"从主窗口bound_windows获取窗口句柄: {hwnd}")
                        return hwnd

                # 检查是否有current_target_hwnd属性
                if hasattr(current_widget, 'current_target_hwnd') and current_widget.current_target_hwnd:
                    hwnd = current_widget.current_target_hwnd
                    logger.info(f"从主窗口current_target_hwnd获取窗口句柄: {hwnd}")
                    return hwnd

                current_widget = current_widget.parent()
                level += 1

            logger.warning("未找到任何绑定的窗口句柄")
            return None

        except Exception as e:
            logger.error(f"获取绑定窗口句柄失败: {e}")
            import traceback
            logger.error(f"错误详情: {traceback.format_exc()}")
            return None

    def _get_bound_window_from_editor(self) -> Optional[str]:
        """从编辑器获取绑定的窗口（支持多窗口模式）"""
        try:
            logger.info("搜索 开始获取绑定的窗口标题...")

            # 向上查找主窗口，直到找到有config或runner属性的窗口
            current_widget = self.parent()
            level = 0

            while current_widget and level < 10:  # 最多向上查找10层
                logger.info(f"搜索 第{level}层窗口: {current_widget}")
                logger.info(f"搜索 第{level}层窗口类型: {type(current_widget)}")

                # 检查是否有bound_windows属性（多窗口模式）
                if hasattr(current_widget, 'bound_windows'):
                    bound_windows = current_widget.bound_windows
                    if bound_windows and len(bound_windows) > 0:
                        # 获取第一个启用的窗口
                        for window_info in bound_windows:
                            if window_info.get('enabled', True):
                                window_title = window_info.get('title')
                                if window_title:
                                    logger.info(f"搜索 从多窗口绑定列表获取第一个启用窗口: {window_title}")
                                    return window_title

                        # 如果没有启用的窗口，使用第一个窗口
                        first_window = bound_windows[0]
                        window_title = first_window.get('title')
                        if window_title:
                            logger.info(f"搜索 从多窗口绑定列表获取第一个窗口: {window_title}")
                            return window_title

                # 检查是否是主窗口（任务编辑器）
                if hasattr(current_widget, 'config'):
                    logger.info(f"搜索 第{level}层窗口有config属性")
                    config = current_widget.config
                    target_window_title = config.get('target_window_title')
                    if target_window_title:
                        logger.info(f"搜索 从第{level}层窗口配置获取目标窗口: {target_window_title}")
                        return target_window_title
                    else:
                        logger.info(f"搜索 第{level}层窗口config中没有target_window_title")

                # 检查是否有runner属性
                if hasattr(current_widget, 'runner'):
                    logger.info(f"搜索 第{level}层窗口有runner属性")
                    runner = current_widget.runner
                    if hasattr(runner, 'target_window_title'):
                        target_window_title = runner.target_window_title
                        logger.info(f"搜索 从第{level}层窗口runner获取目标窗口: {target_window_title}")
                        if target_window_title:
                            return target_window_title
                    else:
                        logger.info(f"搜索 第{level}层窗口runner没有target_window_title属性")

                # 检查是否有直接的target_window_title属性
                if hasattr(current_widget, 'target_window_title'):
                    target_window_title = current_widget.target_window_title
                    logger.info(f"搜索 从第{level}层窗口属性获取目标窗口: {target_window_title}")
                    if target_window_title:
                        return target_window_title

                # 向上查找父窗口
                current_widget = current_widget.parent()
                level += 1

            logger.info(f"搜索 查找了{level}层窗口，未找到绑定的目标窗口")
            return None

        except Exception as e:
            logger.exception(f"获取编辑器绑定窗口时出错: {e}")
            return None

    def _find_window_by_title(self, window_title: str) -> Optional[int]:
        """通过窗口标题查找窗口句柄"""
        try:
            normalized_hwnd = resolve_unique_window_hwnd(window_title)
            if normalized_hwnd:
                logger.info(f"通过标题找到窗口句柄: {window_title} -> {normalized_hwnd}")
                return normalized_hwnd
            logger.warning(f"无法通过标题找到窗口: {window_title}")
            return None
        except Exception as e:
            logger.error(f"查找窗口句柄失败: {e}")
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

    def get_coordinates(self) -> List[Tuple[int, int]]:
        """获取当前坐标点列表"""
        return self.coordinate_points.copy()
