# -*- coding: utf-8 -*-
from PySide6.QtCore import QEvent, QObject, QPoint, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QCursor, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractItemView, QApplication, QGraphicsView, QLabel, QWidget

from utils.window.window_activation_utils import show_and_raise_widget

_tooltip_manager = None
_TOOLTIP_RADIUS = 6.0


def _theme_color(key: str, default: str) -> QColor:
    try:
        from themes import get_theme_manager

        return get_theme_manager().get_qcolor(key)
    except Exception:
        return QColor(default)


class RoundedTooltip(QLabel):
    """无边框提示：自己画圆角，避免 Windows 垫一层直角底。"""

    def __init__(self) -> None:
        flags = Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint
        if hasattr(Qt.WindowType, "NoDropShadowWindowHint"):
            flags |= Qt.WindowType.NoDropShadowWindowHint
        super().__init__(None, flags)
        self.setObjectName("customRoundedTooltip")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setWordWrap(True)
        self.setMaximumWidth(520)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self._bg = QColor("#f5f5f5")
        self._fg = QColor("#333333")
        self._border = QColor("#e0e0e0")
        self.apply_theme()

    def apply_theme(self) -> None:
        self._bg = _theme_color("surface", "#f5f5f5")
        self._fg = _theme_color("text", "#333333")
        self._border = _theme_color("border", "#e0e0e0")
        self.setStyleSheet(
            "QLabel#customRoundedTooltip {"
            "background: transparent;"
            f"color: {self._fg.name()};"
            "border: none;"
            "padding: 6px 8px;"
            "}"
        )
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, _TOOLTIP_RADIUS, _TOOLTIP_RADIUS)
        painter.fillPath(path, QBrush(self._bg))
        painter.setPen(QPen(self._border, 1))
        painter.drawPath(path)
        painter.end()
        super().paintEvent(event)


class CustomTooltipManager(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._tooltip = RoundedTooltip()

    def install(self, app: QApplication) -> None:
        app.installEventFilter(self)

    def set_theme(self, theme_name: str = "") -> None:
        self._tooltip.apply_theme()
        app = QApplication.instance()
        if app:
            self._tooltip.setFont(app.font())

    def eventFilter(self, obj, event):
        if obj is self._tooltip:
            return False
        if event.type() == QEvent.Type.ToolTip:
            text = self._resolve_tooltip_text(obj, event)
            if text:
                pos = self._resolve_tooltip_pos(obj, event)
                self.show_text(text, pos)
            else:
                self.hide()
            return True
        if event.type() in (
            QEvent.Type.Leave,
            QEvent.Type.Hide,
            QEvent.Type.MouseButtonPress,
        ):
            self.hide()
        return False

    def show_text(self, text: str, global_pos: QPoint = None) -> None:
        if not text:
            self.hide()
            return
        self._tooltip.apply_theme()
        self._tooltip.setText(text)
        self._tooltip.adjustSize()
        pos = global_pos or QCursor.pos()
        pos += QPoint(8, 8)
        pos = self._clamp_to_screen(pos)
        self._tooltip.move(pos)
        show_and_raise_widget(self._tooltip, log_prefix="自定义提示")

    def hide(self) -> None:
        self._tooltip.hide()

    def _resolve_tooltip_text(self, obj, event) -> str:
        view = None
        if isinstance(obj, QAbstractItemView):
            view = obj
        elif isinstance(obj, QWidget) and isinstance(obj.parent(), QAbstractItemView):
            view = obj.parent()
        if view is not None:
            index = view.indexAt(event.pos()) if hasattr(event, "pos") else None
            if index is not None and index.isValid():
                data = index.data(Qt.ItemDataRole.ToolTipRole)
                if data:
                    return str(data)
            return view.toolTip()

        gv = None
        if isinstance(obj, QGraphicsView):
            gv = obj
        elif isinstance(obj, QWidget) and isinstance(obj.parent(), QGraphicsView):
            gv = obj.parent()
        if gv is not None and hasattr(event, "pos"):
            item = gv.itemAt(event.pos())
            if item:
                item_text = item.toolTip()
                if item_text:
                    return item_text
            return gv.toolTip()

        if isinstance(obj, QWidget):
            return obj.toolTip()
        return ""

    def _resolve_tooltip_pos(self, obj, event) -> QPoint:
        if hasattr(event, "globalPos"):
            return event.globalPos()
        if isinstance(obj, QWidget) and hasattr(event, "pos"):
            return obj.mapToGlobal(event.pos())
        return QCursor.pos()

    def _clamp_to_screen(self, pos: QPoint) -> QPoint:
        screen = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
        if not screen:
            return pos
        geo = screen.availableGeometry()
        x = min(max(pos.x(), geo.left()), geo.right() - self._tooltip.width())
        y = min(max(pos.y(), geo.top()), geo.bottom() - self._tooltip.height())
        return QPoint(x, y)


def get_tooltip_manager() -> CustomTooltipManager:
    global _tooltip_manager
    if _tooltip_manager is None:
        _tooltip_manager = CustomTooltipManager()
    return _tooltip_manager
