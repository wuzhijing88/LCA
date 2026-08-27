# -*- coding: utf-8 -*-
"""Theme-owned rounded popup windows.

Windows keeps a rectangular HWND under QSS border-radius. These helpers make
the window transparent and paint the themed rounded card themselves.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import QWidget


MENU_RADIUS = 8
COMBO_RADIUS = 6
TOOLTIP_RADIUS = 6
_PAINTER_ATTR = "_theme_rounded_popup_painter"


def popup_surface_colors(border_key: str = "border") -> tuple[QColor, QColor]:
    try:
        from themes.theme_manager import get_theme_manager

        manager = get_theme_manager()
        return QColor(manager.get_color("card")), QColor(manager.get_color(border_key))
    except Exception:
        return QColor("#ffffff"), QColor("#d0d0d0")


class RoundedPopupPainter(QObject):
    def __init__(self, widget: QWidget, radius: int, border_key: str):
        super().__init__(widget)
        self._radius = int(radius)
        self._border_key = str(border_key)

    def set_style(self, radius: int, border_key: str) -> None:
        self._radius = int(radius)
        self._border_key = str(border_key)

    def eventFilter(self, obj, event):
        if obj is not self.parent() or event.type() != QEvent.Type.Paint:
            return False
        painter = QPainter(obj)
        if not painter.isActive():
            return False
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        path = QPainterPath()
        path.addRoundedRect(0.5, 0.5, max(0, obj.width() - 1), max(0, obj.height() - 1), self._radius, self._radius)
        background, border = popup_surface_colors(self._border_key)
        painter.fillPath(path, QBrush(background))
        painter.setPen(QPen(border, 1))
        painter.drawPath(path)
        painter.end()
        return False


def _install_painter(widget: QWidget, radius: int, border_key: str) -> None:
    painter = getattr(widget, _PAINTER_ATTR, None)
    if painter is None:
        painter = RoundedPopupPainter(widget, radius, border_key)
        widget.installEventFilter(painter)
        setattr(widget, _PAINTER_ATTR, painter)
        return
    painter.set_style(radius, border_key)


def prepare_rounded_popup_window(widget: QWidget, *, force: bool = False) -> None:
    flags = widget.windowFlags() | Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
    if hasattr(Qt.WindowType, "NoDropShadowWindowHint"):
        flags |= Qt.WindowType.NoDropShadowWindowHint
    if force or not widget.isVisible():
        widget.setWindowFlags(flags)
    widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)


def apply_transparent_popup_palette(widget: QWidget) -> None:
    widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    widget.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
    widget.setAutoFillBackground(False)
    widget.setProperty("roundedPopup", True)
    try:
        from themes.theme_manager import get_theme_manager

        palette = get_theme_manager().build_palette()
    except Exception:
        palette = widget.palette()
    transparent = QColor(0, 0, 0, 0)
    palette.setColor(QPalette.ColorRole.Window, transparent)
    palette.setColor(QPalette.ColorRole.Base, transparent)
    widget.setPalette(palette)


def apply_rounded_popup(
    widget: QWidget,
    *,
    radius: int = MENU_RADIUS,
    border_key: str = "border",
    frameless: bool = True,
    force_window: bool = False,
    paint: bool = True,
) -> QWidget:
    if frameless:
        prepare_rounded_popup_window(widget, force=force_window)
    if widget.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground) or force_window:
        apply_transparent_popup_palette(widget)
        if paint:
            _install_painter(widget, radius, border_key)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    return widget
