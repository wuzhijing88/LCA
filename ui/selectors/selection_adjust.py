#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""框选完成后的几何调整：滚轮缩放、四角调大小、非四角边框拖动整框。"""

from typing import Optional

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import QPushButton


SELECTION_MIN_SIZE = 10
SELECTION_BORDER_MARGIN = 8
SELECTION_WHEEL_STEP = 0.1


def clamp_rect_to_bounds(
    rect: QRect,
    bounds: QRect,
    min_size: int = SELECTION_MIN_SIZE,
) -> QRect:
    if rect is None or rect.isEmpty():
        return QRect()
    if bounds is None or bounds.isEmpty():
        return QRect(rect)

    width = max(1, min(max(min_size, rect.width()), bounds.width()))
    height = max(1, min(max(min_size, rect.height()), bounds.height()))
    max_x = bounds.x() + bounds.width() - width
    max_y = bounds.y() + bounds.height() - height
    x = max(bounds.x(), min(rect.x(), max_x))
    y = max(bounds.y(), min(rect.y(), max_y))
    return QRect(x, y, width, height)


def move_rect_by(
    rect: QRect,
    dx: int,
    dy: int,
    bounds: QRect,
    min_size: int = SELECTION_MIN_SIZE,
) -> QRect:
    moved = QRect(rect)
    moved.translate(int(dx), int(dy))
    return clamp_rect_to_bounds(moved, bounds, min_size)


def scale_rect_around_center(
    rect: QRect,
    bounds: QRect,
    factor: float,
    min_size: int = SELECTION_MIN_SIZE,
) -> QRect:
    if rect is None or rect.isEmpty() or factor <= 0:
        return QRect(rect) if rect is not None else QRect()

    center_x = rect.x() + rect.width() / 2.0
    center_y = rect.y() + rect.height() / 2.0
    new_width = max(min_size, int(round(rect.width() * factor)))
    new_height = max(min_size, int(round(rect.height() * factor)))
    if bounds is not None and not bounds.isEmpty():
        new_width = min(new_width, bounds.width())
        new_height = min(new_height, bounds.height())
    x = int(round(center_x - new_width / 2.0))
    y = int(round(center_y - new_height / 2.0))
    return clamp_rect_to_bounds(QRect(x, y, new_width, new_height), bounds, min_size)


def scale_rect_by_wheel(
    rect: QRect,
    bounds: QRect,
    angle_delta_y: int,
    min_size: int = SELECTION_MIN_SIZE,
    step: float = SELECTION_WHEEL_STEP,
) -> QRect:
    if rect is None or rect.isEmpty() or angle_delta_y == 0:
        return QRect(rect) if rect is not None else QRect()

    notches = angle_delta_y / 120.0
    grow = notches > 0
    factor = (1.0 + step) ** abs(notches)
    if not grow:
        factor = 1.0 / factor

    scaled = scale_rect_around_center(rect, bounds, factor, min_size)
    if scaled.width() != rect.width() or scaled.height() != rect.height():
        return scaled

    pixel_delta = 2 if grow else -2
    fallback_width = max(min_size, rect.width() + pixel_delta)
    fallback_height = max(min_size, rect.height() + pixel_delta)
    fallback_factor = max(
        fallback_width / max(1, rect.width()),
        fallback_height / max(1, rect.height()),
    )
    return scale_rect_around_center(rect, bounds, fallback_factor, min_size)


def wheel_event_delta_y(event) -> int:
    angle = int(event.angleDelta().y())
    if angle != 0:
        return angle
    return int(event.pixelDelta().y())


def hit_test_selection(
    point: QPoint,
    rect: QRect,
    margin: int = SELECTION_BORDER_MARGIN,
) -> Optional[str]:
    """四角返回缩放方向；其余边框和内部返回 move。"""
    if rect is None or rect.isEmpty() or point is None:
        return None

    in_y = rect.top() - margin <= point.y() <= rect.bottom() + margin
    in_x = rect.left() - margin <= point.x() <= rect.right() + margin
    near_left = in_y and abs(point.x() - rect.left()) <= margin
    near_right = in_y and abs(point.x() - rect.right()) <= margin
    near_top = in_x and abs(point.y() - rect.top()) <= margin
    near_bottom = in_x and abs(point.y() - rect.bottom()) <= margin

    if near_left and near_top:
        return "top_left"
    if near_right and near_top:
        return "top_right"
    if near_left and near_bottom:
        return "bottom_left"
    if near_right and near_bottom:
        return "bottom_right"
    if near_left or near_right or near_top or near_bottom or rect.contains(point):
        return "move"
    return None


def cursor_for_selection_hit(mode: Optional[str]):
    if mode in ("top_left", "bottom_right"):
        return Qt.CursorShape.SizeFDiagCursor
    if mode in ("top_right", "bottom_left"):
        return Qt.CursorShape.SizeBDiagCursor
    if mode == "move":
        return Qt.CursorShape.SizeAllCursor
    return Qt.CursorShape.CrossCursor


def resize_rect_by_corner(
    rect: QRect,
    mode: str,
    dx: int,
    dy: int,
    bounds: QRect,
    min_size: int = SELECTION_MIN_SIZE,
) -> QRect:
    if rect is None or rect.isEmpty() or not mode:
        return QRect(rect) if rect is not None else QRect()

    left = rect.left()
    right = rect.right()
    top = rect.top()
    bottom = rect.bottom()
    client = bounds if bounds is not None and not bounds.isEmpty() else QRect(rect)

    if "left" in mode:
        left += dx
        left = max(client.left(), min(left, right - min_size + 1))
    if "right" in mode:
        right += dx
        right = min(client.right(), max(right, left + min_size - 1))
    if "top" in mode:
        top += dy
        top = max(client.top(), min(top, bottom - min_size + 1))
    if "bottom" in mode:
        bottom += dy
        bottom = min(client.bottom(), max(bottom, top + min_size - 1))

    resized = QRect(QPoint(left, top), QPoint(right, bottom)).normalized()
    if resized.width() < min_size or resized.height() < min_size:
        return QRect(rect)
    return clamp_rect_to_bounds(resized, client, min_size)


def create_overlay_adjust_buttons(parent, on_confirm, on_reselect):
    confirm_button = QPushButton("确定", parent)
    confirm_button.setObjectName("overlayAdjustConfirmButton")
    confirm_button.setFixedSize(84, 34)
    confirm_button.setAutoDefault(False)
    confirm_button.setDefault(False)
    confirm_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    confirm_button.setCursor(Qt.CursorShape.PointingHandCursor)
    confirm_button.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    confirm_button.clicked.connect(on_confirm)
    confirm_button.hide()

    reselect_button = QPushButton("重选", parent)
    reselect_button.setObjectName("overlayAdjustReselectButton")
    reselect_button.setFixedSize(84, 34)
    reselect_button.setAutoDefault(False)
    reselect_button.setDefault(False)
    reselect_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    reselect_button.setCursor(Qt.CursorShape.PointingHandCursor)
    reselect_button.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    reselect_button.clicked.connect(on_reselect)
    reselect_button.hide()

    apply_overlay_adjust_button_style(confirm_button, reselect_button)
    return confirm_button, reselect_button


def apply_overlay_adjust_button_style(confirm_button, reselect_button) -> None:
    from themes.capture_tools import apply_capture_action_buttons
    apply_capture_action_buttons(confirm_button, reselect_button)


def update_adjust_buttons_position(
    confirm_button,
    reselect_button,
    selection_rect: QRect,
    overlay_rect: QRect,
) -> None:
    if confirm_button is None or reselect_button is None or selection_rect.isEmpty():
        return

    gap = 8
    total_w = confirm_button.width() + reselect_button.width() + gap
    x = selection_rect.right() + 12
    y = selection_rect.bottom() - confirm_button.height()
    overlay_w = overlay_rect.width()
    overlay_h = overlay_rect.height()

    if x + total_w > overlay_w - 8:
        x = selection_rect.left() - total_w - 12
    if x < 8:
        x = 8
    if y < 8:
        y = selection_rect.bottom() + 12
    if y + confirm_button.height() > overlay_h - 8:
        y = overlay_h - confirm_button.height() - 8

    confirm_button.move(x, y)
    reselect_button.move(x + confirm_button.width() + gap, y)
    confirm_button.raise_()
    reselect_button.raise_()
