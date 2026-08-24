# -*- coding: utf-8 -*-
from PySide6.QtCore import QObject, QEvent, QPoint, Qt
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import QApplication, QLabel, QWidget, QAbstractItemView, QGraphicsView
from utils.window_activation_utils import show_and_raise_widget

_tooltip_manager = None


class CustomTooltipManager(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._tooltip = QLabel("", None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self._tooltip.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self._tooltip.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._tooltip.setWordWrap(True)
        self._tooltip.setMaximumWidth(520)
        self._tooltip.setTextFormat(Qt.TextFormat.PlainText)
        self.set_theme("light")

    def install(self, app: QApplication) -> None:
        app.installEventFilter(self)

    def set_theme(self, theme_name: str) -> None:
        if theme_name == "dark":
            background = "#2d2d2d"
            text = "#e0e0e0"
            border = "#3e3e3e"
        else:
            background = "#f5f5f5"
            text = "#333333"
            border = "#d0d0d0"
        self._tooltip.setStyleSheet(
            "background-color: %s; color: %s; border: 1px solid %s; "
            "border-radius: 4px; padding: 4px;" % (background, text, border)
        )
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
        self._tooltip.setText(text)
        self._tooltip.adjustSize()
        pos = global_pos or QCursor.pos()
        pos += QPoint(8, 8)
        pos = self._clamp_to_screen(pos)
        self._tooltip.move(pos)
        show_and_raise_widget(self._tooltip, log_prefix='自定义提示')

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
