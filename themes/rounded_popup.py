# -*- coding: utf-8 -*-
"""Theme-owned rounded popup windows.

Windows 的 Popup HWND 本身是直角；不靠 setMask 硬裁（锯齿、不干净），
而是：无边框 + 整窗透明，再自己抗锯齿画圆角卡片。
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import QMenu, QWidget


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
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        # 整窗铺透明：直角 HWND 四角不着色（不靠 setMask）
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(obj.rect(), QColor(0, 0, 0, 0))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        path = QPainterPath()
        path.addRoundedRect(
            0.5,
            0.5,
            max(0, obj.width() - 1),
            max(0, obj.height() - 1),
            self._radius,
            self._radius,
        )
        background, border = popup_surface_colors(self._border_key)
        painter.fillPath(path, QBrush(background))
        painter.setPen(QPen(border, 1))
        painter.drawPath(path)
        painter.end()
        # QMenu 条目由自身 paintEvent 绘制：若吃掉 Paint 会变成空白圆角卡片
        if isinstance(obj, QMenu):
            return False
        # QFrame/下拉容器：必须吃掉 Paint，否则默认绘制会再铺一层黑色直角底
        return True


def _install_painter(widget: QWidget, radius: int, border_key: str) -> None:
    painter = getattr(widget, _PAINTER_ATTR, None)
    if painter is None:
        painter = RoundedPopupPainter(widget, radius, border_key)
        widget.installEventFilter(painter)
        setattr(widget, _PAINTER_ATTR, painter)
        return
    painter.set_style(radius, border_key)


def apply_native_window_corners(widget: QWidget, *, preference: int = 2) -> bool:
    """给顶层窗口套 Windows 11 DWM 圆角（DWMWCP_ROUND=2）。"""
    import os
    import sys

    if os.name != "nt" or os.environ.get("FORCE_CUSTOM_ROUNDED", "0") == "1":
        return False
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        hwnd = int(widget.winId())
        if not hwnd:
            return False
        value = wintypes.DWORD(int(preference))
        result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd,
            33,  # DWMWA_WINDOW_CORNER_PREFERENCE
            ctypes.byref(value),
            ctypes.sizeof(value),
        )
        return result == 0
    except Exception:
        return False


def prepare_rounded_popup_window(widget: QWidget, *, force: bool = False) -> None:
    """无边框 Popup + 透明背景，让圆角由绘制完成而不是裁剪。"""
    flags = widget.windowFlags() | Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
    if hasattr(Qt.WindowType, "NoDropShadowWindowHint"):
        flags |= Qt.WindowType.NoDropShadowWindowHint
    need_reapply = force or (widget.windowFlags() & flags) != flags
    if need_reapply:
        was_visible = widget.isVisible()
        if was_visible:
            widget.hide()
        widget.setWindowFlags(flags)
        if was_visible:
            widget.show()
    widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    widget.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)


def apply_transparent_popup_palette(widget: QWidget) -> None:
    widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    widget.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
    widget.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
    widget.setAutoFillBackground(False)
    widget.setProperty("roundedPopup", True)
    try:
        widget.clearMask()
    except Exception:
        pass
    try:
        from themes.theme_manager import get_theme_manager

        palette = get_theme_manager().build_palette()
    except Exception:
        palette = widget.palette()
    transparent = QColor(0, 0, 0, 0)
    palette.setColor(QPalette.ColorRole.Window, transparent)
    palette.setColor(QPalette.ColorRole.Base, transparent)
    palette.setColor(QPalette.ColorRole.Button, transparent)
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
