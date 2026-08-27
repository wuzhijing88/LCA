from __future__ import annotations

from typing import Optional, Sequence, Tuple

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap

OVERLAY_TEXT_COLOR = QColor(0, 255, 0)
OVERLAY_HINT_FONT_FAMILY = "Microsoft YaHei"
OVERLAY_HINT_FONT_POINT_SIZE = 12


def overlay_hint_font() -> QFont:
    return QFont(OVERLAY_HINT_FONT_FAMILY, OVERLAY_HINT_FONT_POINT_SIZE)


def apply_overlay_text_style(painter: QPainter, *, color: Optional[QColor] = None) -> None:
    painter.setFont(overlay_hint_font())
    painter.setPen(QPen(color or OVERLAY_TEXT_COLOR))


def _target_rect_key(target_rect: Optional[QRect]):
    if target_rect is None or target_rect.isEmpty():
        return None
    return (
        int(target_rect.x()),
        int(target_rect.y()),
        int(target_rect.width()),
        int(target_rect.height()),
    )


def _pixmap_cache_id(pixmap: Optional[QPixmap]):
    if pixmap is None or pixmap.isNull():
        return None
    return id(pixmap)


def compose_picker_backdrop(
    size,
    *,
    desktop_pixmap: Optional[QPixmap] = None,
    window_pixmap: Optional[QPixmap] = None,
    target_rect: Optional[QRect] = None,
    mask_alpha: int = 0,
    dim_color: Optional[QColor] = None,
    fill_color: Optional[QColor] = None,
) -> QPixmap:
    width = int(size.width()) if hasattr(size, "width") else int(size[0])
    height = int(size.height()) if hasattr(size, "height") else int(size[1])
    composed = QPixmap(max(1, width), max(1, height))
    composed.fill(fill_color or QColor(32, 32, 32))
    if width <= 0 or height <= 0:
        return composed

    painter = QPainter(composed)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
    try:
        dest = QRect(0, 0, width, height)
        has_desktop = desktop_pixmap is not None and not desktop_pixmap.isNull()
        has_window = window_pixmap is not None and not window_pixmap.isNull()
        has_target = target_rect is not None and not target_rect.isEmpty()

        if has_desktop:
            if desktop_pixmap.width() == width and desktop_pixmap.height() == height:
                painter.drawPixmap(0, 0, desktop_pixmap)
            else:
                painter.drawPixmap(dest, desktop_pixmap)

        if has_window and has_target:
            if (
                window_pixmap.width() == target_rect.width()
                and window_pixmap.height() == target_rect.height()
            ):
                painter.drawPixmap(target_rect.topLeft(), window_pixmap)
            else:
                painter.drawPixmap(target_rect, window_pixmap)

        if dim_color is not None:
            painter.fillRect(dest, dim_color)

        if has_desktop and has_target and int(mask_alpha) > 0:
            painter.fillRect(dest, QColor(0, 0, 0, max(0, min(255, int(mask_alpha)))))
            painter.setClipRect(target_rect)
            if has_window:
                painter.drawPixmap(target_rect, window_pixmap)
            elif desktop_pixmap.width() == width and desktop_pixmap.height() == height:
                painter.drawPixmap(0, 0, desktop_pixmap)
            else:
                painter.drawPixmap(dest, desktop_pixmap)
    finally:
        painter.end()
    return composed


def blit_composed_backdrop(painter: QPainter, composed: Optional[QPixmap], dirty_rect: QRect) -> bool:
    if composed is None or composed.isNull() or dirty_rect is None or dirty_rect.isEmpty():
        return False
    src = dirty_rect.intersected(QRect(0, 0, composed.width(), composed.height()))
    if src.isEmpty():
        return False
    painter.drawPixmap(src, composed, src)
    return True


def _painter_dirty_rect(painter: QPainter, widget) -> QRect:
    widget_rect = widget.rect()
    try:
        clip = painter.clipBoundingRect().toAlignedRect()
    except Exception:
        clip = QRect()
    if clip.isEmpty():
        return widget_rect
    return clip.intersected(widget_rect)

from utils.window.window_coordinate_common import (
    build_window_info,
    get_qt_virtual_desktop_rect,
    get_window_client_logical_size,
    get_window_client_native_rect,
    get_window_client_physical_size,
    get_window_client_qt_global_rect,
    native_rect_to_qt_global_rect,
    overlay_local_point_to_client_relative,
)


def get_overlay_screen_geometry() -> QRect:
    return get_qt_virtual_desktop_rect() or QRect(0, 0, 0, 0)


def sync_overlay_geometry(widget) -> QRect:
    geometry = get_overlay_screen_geometry()
    widget.setGeometry(geometry)
    return geometry


def get_window_client_overlay_metrics(hwnd: int) -> Optional[dict]:
    try:
        hwnd_int = int(hwnd)
    except Exception:
        return None

    window_info = build_window_info(hwnd_int)
    if not window_info:
        return None

    qt_global_rect = get_window_client_qt_global_rect(window_info)
    if qt_global_rect is None or qt_global_rect.isEmpty():
        return None

    native_rect = get_window_client_native_rect(window_info)
    if native_rect and len(native_rect) == 4:
        try:
            native_rect = tuple(int(v) for v in native_rect)
        except Exception:
            native_rect = None
    else:
        native_rect = None

    logical_width, logical_height = get_window_client_logical_size(window_info)
    physical_width, physical_height = get_window_client_physical_size(window_info)

    return {
        "window_info": window_info,
        "native_rect": native_rect,
        "qt_global_rect": QRect(
            int(qt_global_rect.x()),
            int(qt_global_rect.y()),
            max(1, int(qt_global_rect.width())),
            max(1, int(qt_global_rect.height())),
        ),
        "logical_size": (
            max(1, int(logical_width)),
            max(1, int(logical_height)),
        ),
        "physical_size": (
            max(1, int(physical_width)),
            max(1, int(physical_height)),
        ),
    }


def map_qt_global_rect_to_local(widget, qt_global_rect) -> QRect:
    if qt_global_rect is None or qt_global_rect.isEmpty():
        return QRect()

    top_left_local = widget.mapFromGlobal(qt_global_rect.topLeft())
    return QRect(
        int(top_left_local.x()),
        int(top_left_local.y()),
        int(qt_global_rect.width()),
        int(qt_global_rect.height()),
    )


def _rect_from_edge_points(left: int, top: int, right: int, bottom: int) -> QRect:
    """Build a QRect from Win32-style edges where right/bottom are exclusive."""
    x = min(int(left), int(right))
    y = min(int(top), int(bottom))
    width = max(0, abs(int(right) - int(left)))
    height = max(0, abs(int(bottom) - int(top)))
    return QRect(x, y, width, height)


def _map_native_rect_via_widget_geometry(widget, native_rect: Tuple[int, int, int, int]) -> QRect:
    try:
        import win32gui
    except Exception:
        return QRect()

    try:
        hwnd = int(widget.winId())
        if not hwnd or not win32gui.IsWindow(hwnd):
            return QRect()

        widget_native_rect = win32gui.GetWindowRect(hwnd)
        if not widget_native_rect or len(widget_native_rect) != 4:
            return QRect()

        widget_geometry = widget.geometry()
        widget_qt_width = max(1, int(widget_geometry.width()))
        widget_qt_height = max(1, int(widget_geometry.height()))

        widget_native_left, widget_native_top, widget_native_right, widget_native_bottom = [int(v) for v in widget_native_rect]
        widget_native_width = max(1, widget_native_right - widget_native_left)
        widget_native_height = max(1, widget_native_bottom - widget_native_top)

        left, top, right, bottom = [int(v) for v in native_rect]
        scale_x = widget_qt_width / float(widget_native_width)
        scale_y = widget_qt_height / float(widget_native_height)

        local_left = int(round((left - widget_native_left) * scale_x))
        local_top = int(round((top - widget_native_top) * scale_y))
        local_right = int(round((right - widget_native_left) * scale_x))
        local_bottom = int(round((bottom - widget_native_top) * scale_y))
        return _rect_from_edge_points(local_left, local_top, local_right, local_bottom)
    except Exception:
        return QRect()


def _widget_global_coord_mode(widget) -> str:
    """判断当前覆盖层接收的是 Qt 逻辑全局坐标还是原生物理全局坐标。"""
    try:
        import win32gui
    except Exception:
        return "qt_logical"

    try:
        hwnd = int(widget.winId())
        if not hwnd or not win32gui.IsWindow(hwnd):
            return "qt_logical"

        native_rect = win32gui.GetWindowRect(hwnd)
        if not native_rect or len(native_rect) != 4:
            return "qt_logical"

        native_width = max(1, int(native_rect[2]) - int(native_rect[0]))
        native_height = max(1, int(native_rect[3]) - int(native_rect[1]))
        widget_geometry = widget.geometry()
        qt_width = max(1, int(widget_geometry.width()))
        qt_height = max(1, int(widget_geometry.height()))
        dpr = max(1.0, float(widget.devicePixelRatioF()))

        physical_error = abs(native_width - qt_width) + abs(native_height - qt_height)
        logical_error = abs(native_width - int(round(qt_width * dpr))) + abs(native_height - int(round(qt_height * dpr)))
        return "native_physical" if physical_error < logical_error else "qt_logical"
    except Exception:
        return "qt_logical"


def get_overlay_debug_snapshot(widget, native_rect: Optional[Tuple[int, int, int, int]] = None) -> dict:
    snapshot = {
        "coord_mode": "unknown",
        "widget_qt_geometry": None,
        "widget_native_rect": None,
        "widget_global_bottom_right": None,
        "input_native_rect": None,
        "mapped_local_rect": None,
    }

    try:
        snapshot["coord_mode"] = _widget_global_coord_mode(widget)
    except Exception:
        pass

    try:
        geometry = widget.geometry()
        snapshot["widget_qt_geometry"] = (
            int(geometry.x()),
            int(geometry.y()),
            int(geometry.width()),
            int(geometry.height()),
        )
    except Exception:
        pass

    try:
        import win32gui

        hwnd = int(widget.winId())
        if hwnd and win32gui.IsWindow(hwnd):
            native = win32gui.GetWindowRect(hwnd)
            if native and len(native) == 4:
                snapshot["widget_native_rect"] = tuple(int(v) for v in native)
    except Exception:
        pass

    try:
        point = widget.mapToGlobal(QPoint(max(0, int(widget.width()) - 1), max(0, int(widget.height()) - 1)))
        snapshot["widget_global_bottom_right"] = (int(point.x()), int(point.y()))
    except Exception:
        pass

    if native_rect and len(native_rect) == 4:
        try:
            snapshot["input_native_rect"] = tuple(int(v) for v in native_rect)
            mapped = map_native_rect_to_local(widget, native_rect)
            snapshot["mapped_local_rect"] = (
                int(mapped.x()),
                int(mapped.y()),
                int(mapped.width()),
                int(mapped.height()),
            )
        except Exception:
            pass

    return snapshot


def map_native_rect_to_local(widget, native_rect: Tuple[int, int, int, int]) -> QRect:
    if not native_rect or len(native_rect) != 4:
        return QRect()

    mapped_via_widget = _map_native_rect_via_widget_geometry(widget, native_rect)
    if mapped_via_widget and not mapped_via_widget.isEmpty():
        return mapped_via_widget

    qt_global_rect = native_rect_to_qt_global_rect(native_rect)
    if qt_global_rect is None or qt_global_rect.isEmpty():
        return QRect()
    return map_qt_global_rect_to_local(widget, qt_global_rect)


def get_target_window_overlay_rect(widget, window_info) -> QRect:
    native_rect = get_window_client_native_rect(window_info)
    if native_rect:
        return map_native_rect_to_local(widget, native_rect)

    qt_global_rect = get_window_client_qt_global_rect(window_info)
    if qt_global_rect is None or qt_global_rect.isEmpty():
        return QRect()
    return map_qt_global_rect_to_local(widget, qt_global_rect)


def refresh_target_window_overlay_rect(widget, window_info, *, attr_name: str = 'target_window_rect') -> QRect:
    target_rect = get_target_window_overlay_rect(widget, window_info)
    setattr(widget, attr_name, QRect(target_rect))
    return QRect(target_rect)


def overlay_point_to_client_qpoint(window_info, target_rect, overlay_pos) -> QPoint:
    if not window_info or target_rect is None or target_rect.isEmpty():
        try:
            return QPoint(int(overlay_pos.x()), int(overlay_pos.y()))
        except Exception:
            return QPoint()

    client_x, client_y = overlay_local_point_to_client_relative(
        window_info,
        target_rect,
        overlay_pos,
    )
    return QPoint(int(client_x), int(client_y))


def overlay_rect_contains_point(target_rect, point) -> bool:
    return bool(target_rect and not target_rect.isEmpty() and target_rect.contains(point))


def fill_overlay_event_background(painter: QPainter, widget, *, alpha: int = 220) -> None:
    painter.fillRect(widget.rect(), QColor(0, 0, 0, max(0, min(255, int(alpha)))))


def configure_opaque_picker_overlay(widget) -> None:
    """采集覆盖层必须用不透明顶层窗。半透明 Tool 窗在 Windows 上会被点穿。"""
    widget.setWindowFlags(
        Qt.WindowType.Window
        | Qt.WindowType.FramelessWindowHint
        | Qt.WindowType.WindowStaysOnTopHint
    )
    widget.setWindowModality(Qt.WindowModality.ApplicationModal)
    widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
    widget.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
    widget.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, False)
    widget.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
    widget.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
    widget.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
    widget._closing = False
    widget.setAutoFillBackground(True)
    widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    widget.setMouseTracking(True)
    widget.setCursor(Qt.CursorShape.CrossCursor)


def numpy_screenshot_to_qpixmap(screenshot) -> Optional[QPixmap]:
    if screenshot is None:
        return None
    try:
        import numpy as np

        array = np.ascontiguousarray(screenshot)
        if array.ndim != 3 or array.shape[2] < 3:
            return None
        rgb = np.ascontiguousarray(array[:, :, :3][:, :, ::-1])
        height, width = rgb.shape[:2]
        image = QImage(rgb.data, width, height, int(rgb.strides[0]), QImage.Format.Format_RGB888)
        return QPixmap.fromImage(image.copy())
    except Exception:
        return None


def capture_window_client_pixmap(hwnd: int) -> Optional[QPixmap]:
    try:
        from tasks.task_utils import capture_window_smart

        frame = capture_window_smart(int(hwnd), client_area_only=True)
    except Exception:
        return None
    return numpy_screenshot_to_qpixmap(frame)


def capture_virtual_desktop_pixmap() -> Optional[QPixmap]:
    try:
        from PySide6.QtWidgets import QApplication

        screens = QApplication.screens()
        if not screens:
            return None
        virtual_geometry = get_qt_virtual_desktop_rect()
        if virtual_geometry is None or virtual_geometry.isEmpty():
            return None
        screenshot = QPixmap(virtual_geometry.size())
        screenshot.fill(Qt.GlobalColor.black)
        painter = QPainter(screenshot)
        try:
            for screen in screens:
                shot = screen.grabWindow(0)
                if shot.isNull():
                    continue
                offset = screen.geometry().topLeft() - virtual_geometry.topLeft()
                painter.drawPixmap(offset, shot)
        finally:
            painter.end()
        return None if screenshot.isNull() else screenshot
    except Exception:
        return None


def _backdrop_cache_key(
    widget,
    *,
    desktop_pixmap: Optional[QPixmap] = None,
    window_pixmap: Optional[QPixmap] = None,
    target_rect: Optional[QRect] = None,
    mask_alpha: int = 0,
    dim_color: Optional[QColor] = None,
    fill_color: Optional[QColor] = None,
):
    return (
        int(widget.width()),
        int(widget.height()),
        _pixmap_cache_id(desktop_pixmap),
        _pixmap_cache_id(window_pixmap),
        _target_rect_key(target_rect),
        int(mask_alpha),
        None if dim_color is None else (
            dim_color.red(),
            dim_color.green(),
            dim_color.blue(),
            dim_color.alpha(),
        ),
        None if fill_color is None else (
            fill_color.red(),
            fill_color.green(),
            fill_color.blue(),
            fill_color.alpha(),
        ),
    )


def prime_picker_backdrop(widget, **kwargs) -> None:
    if widget is None or widget.width() <= 0 or widget.height() <= 0:
        return
    cache_key = _backdrop_cache_key(widget, **kwargs)
    widget._composed_backdrop = compose_picker_backdrop(widget.size(), **kwargs)
    widget._composed_backdrop_key = cache_key


def draw_picker_backdrop(
    painter: QPainter,
    widget,
    *,
    desktop_pixmap: Optional[QPixmap] = None,
    window_pixmap: Optional[QPixmap] = None,
    target_rect: Optional[QRect] = None,
    mask_alpha: int = 0,
    dim_color: Optional[QColor] = None,
    fill_color: Optional[QColor] = None,
) -> None:
    widget_size = widget.size()
    if widget_size.width() <= 0 or widget_size.height() <= 0:
        painter.fillRect(widget.rect(), fill_color or QColor(32, 32, 32))
        return

    cache_key = _backdrop_cache_key(
        widget,
        desktop_pixmap=desktop_pixmap,
        window_pixmap=window_pixmap,
        target_rect=target_rect,
        mask_alpha=mask_alpha,
        dim_color=dim_color,
        fill_color=fill_color,
    )
    cache = getattr(widget, "_composed_backdrop", None)
    if getattr(widget, "_composed_backdrop_key", None) != cache_key or cache is None or cache.isNull():
        cache = compose_picker_backdrop(
            widget_size,
            desktop_pixmap=desktop_pixmap,
            window_pixmap=window_pixmap,
            target_rect=target_rect,
            mask_alpha=mask_alpha,
            dim_color=dim_color,
            fill_color=fill_color,
        )
        widget._composed_backdrop = cache
        widget._composed_backdrop_key = cache_key

    if not blit_composed_backdrop(painter, cache, _painter_dirty_rect(painter, widget)):
        painter.drawPixmap(widget.rect(), cache)


def draw_overlay_frame(
    painter: QPainter,
    rect: QRect,
    *,
    border_color: Optional[QColor] = None,
    border_width: int = 4,
    fill_color: Optional[QColor] = None,
) -> None:
    if rect is None or rect.isEmpty():
        return

    if fill_color is not None:
        painter.fillRect(rect, fill_color)

    pen = QPen(border_color or QColor(0, 255, 0), int(border_width))
    painter.setPen(pen)
    painter.drawRect(rect)


def draw_overlay_text_lines(
    painter: QPainter,
    anchor: QPoint,
    lines: Sequence[str],
    *,
    text_color: Optional[QColor] = None,
    line_height: int = 25,
) -> None:
    if not lines:
        return

    apply_overlay_text_style(painter, color=text_color)
    for index, line in enumerate(lines):
        if not line:
            continue
        painter.drawText(anchor + QPoint(0, int(index * line_height)), str(line))


def compute_dynamic_center_crosshair_style(
    rect: QRect,
    *,
    size_ratio: float = 0.2,
    min_half_size: int = 3,
    max_half_size: int = 28,
    line_ratio: float = 0.03,
    min_line_width: int = 1,
    max_line_width: int = 3,
) -> Tuple[int, int]:
    if rect is None or rect.isEmpty():
        return 0, 0

    min_side = max(1, min(int(rect.width()), int(rect.height())))
    half_size = int(round(min_side * float(size_ratio)))
    line_width = int(round(min_side * float(line_ratio)))
    half_size = max(int(min_half_size), min(int(max_half_size), half_size))
    line_width = max(int(min_line_width), min(int(max_line_width), line_width))
    return half_size, line_width


def draw_dynamic_center_crosshair(
    painter: QPainter,
    rect: QRect,
    *,
    color: Optional[QColor] = None,
    inset: int = 1,
    size_ratio: float = 0.2,
    min_half_size: int = 3,
    max_half_size: int = 28,
    line_ratio: float = 0.03,
    min_line_width: int = 1,
    max_line_width: int = 3,
) -> None:
    if rect is None or rect.isEmpty():
        return

    inner_inset = max(0, int(inset))
    inner_rect = rect.adjusted(inner_inset, inner_inset, -inner_inset, -inner_inset)
    if inner_rect.isEmpty() or inner_rect.width() <= 0 or inner_rect.height() <= 0:
        return

    half_size, line_width = compute_dynamic_center_crosshair_style(
        inner_rect,
        size_ratio=size_ratio,
        min_half_size=min_half_size,
        max_half_size=max_half_size,
        line_ratio=line_ratio,
        min_line_width=min_line_width,
        max_line_width=max_line_width,
    )
    if half_size <= 0 or line_width <= 0:
        return

    center = inner_rect.center()
    max_half_x = max(1, inner_rect.width() // 2 - line_width)
    max_half_y = max(1, inner_rect.height() // 2 - line_width)
    clamped_half = max(1, min(half_size, max_half_x, max_half_y))

    left = max(inner_rect.left(), center.x() - clamped_half)
    right = min(inner_rect.right(), center.x() + clamped_half)
    top = max(inner_rect.top(), center.y() - clamped_half)
    bottom = min(inner_rect.bottom(), center.y() + clamped_half)

    painter.save()
    painter.setClipRect(inner_rect)
    pen = QPen(color or QColor(255, 0, 0), line_width)
    pen.setCapStyle(Qt.PenCapStyle.FlatCap)
    painter.setPen(pen)
    painter.drawLine(left, center.y(), right, center.y())
    painter.drawLine(center.x(), top, center.x(), bottom)
    painter.restore()


def draw_target_window_overlay(
    painter: QPainter,
    rect: QRect,
    *,
    title: str = '',
    subtitle_lines: Optional[Sequence[str]] = None,
    border_color: Optional[QColor] = None,
    border_width: int = 4,
    text_color: Optional[QColor] = None,
) -> None:
    if rect is None or rect.isEmpty():
        return

    draw_overlay_frame(
        painter,
        rect,
        border_color=border_color or QColor(0, 255, 0),
        border_width=border_width,
    )

    lines = []
    if title:
        lines.append(title)
    if subtitle_lines:
        lines.extend([str(line) for line in subtitle_lines if line])
    if lines:
        draw_overlay_text_lines(
            painter,
            rect.topLeft() + QPoint(10, 25),
            lines,
            text_color=text_color,
        )


def draw_selection_overlay(
    painter: QPainter,
    rect: QRect,
    *,
    info_text: str = '',
    border_color: Optional[QColor] = None,
    border_width: int = 3,
    fill_color: Optional[QColor] = None,
    text_color: Optional[QColor] = None,
    text_bg_color: Optional[QColor] = None,
) -> None:
    if rect is None or rect.isEmpty():
        return

    draw_overlay_frame(
        painter,
        rect,
        border_color=border_color or QColor(255, 0, 0),
        border_width=border_width,
        fill_color=fill_color or QColor(255, 0, 0, 50),
    )

    if not info_text:
        return

    label_pos = rect.topLeft() + QPoint(5, -10)
    painter.fillRect(
        label_pos.x() - 2,
        label_pos.y() - 15,
        200,
        20,
        text_bg_color or QColor(0, 0, 0, 150),
    )
    apply_overlay_text_style(painter, color=text_color)
    painter.drawText(label_pos, str(info_text))
