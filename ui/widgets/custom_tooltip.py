# -*- coding: utf-8 -*-
from PySide6.QtCore import QEvent, QObject, QPoint, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QCursor, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractItemView, QApplication, QGraphicsView, QLabel, QWidget
from shiboken6 import isValid

from themes import get_theme_manager, theme_color

from utils.window.window_activation_utils import show_and_raise_widget

_tooltip_manager = None
_TOOLTIP_RADIUS = 6.0


class RoundedTooltip(QLabel):
    """无边框提示：自己画圆角，避免 Windows 垫一层直角底。"""

    def __init__(self) -> None:
        flags = Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint
        super().__init__(None, flags)
        self.setObjectName("customRoundedTooltip")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setWordWrap(True)
        self.setMaximumWidth(520)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.apply_theme()

    def apply_theme(self) -> None:
        self._bg = QColor(theme_color("surface"))
        self._border = QColor(theme_color("border"))
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
        super().__init__(QApplication.instance() if parent is None else parent)
        self._application = None
        self._application_connections = []
        self._disposed = False
        self._tooltip = RoundedTooltip()
        self._tooltip_destroyed_connection = self._tooltip.destroyed.connect(self.shutdown)
        # 自身或所属窗口被直接销毁时，仍须释放独立的顶层提示窗口。
        # 使用普通 Python 回调，避免 QObject 销毁后跳过发给自身的槽。
        self.destroyed.connect(lambda: self.shutdown())

    def install(self, app: QApplication) -> None:
        if self._disposed:
            raise RuntimeError("提示框管理器已关闭")
        if self._application is app:
            return
        if self._application is not None:
            raise RuntimeError("提示框管理器已经绑定应用程序")
        self._application = app
        app.installEventFilter(self)
        self._application_connections = [
            app.aboutToQuit.connect(self.shutdown),
            app.destroyed.connect(self.shutdown),
        ]

    def shutdown(self) -> None:
        """先摘除全局过滤器，再销毁提示框，避免窗口销毁事件重入。"""
        if self._disposed:
            return
        self._disposed = True
        app, self._application = self._application, None
        if app is not None and isValid(app) and isValid(self):
            app.removeEventFilter(self)
        for connection in self._application_connections:
            QObject.disconnect(connection)
        self._application_connections.clear()
        get_theme_manager().unregister_theme_change_callback(self.set_theme)
        tooltip, self._tooltip = self._tooltip, None
        if tooltip is not None and isValid(tooltip):
            QObject.disconnect(self._tooltip_destroyed_connection)
            if isValid(self):
                tooltip.hide()
            tooltip.deleteLater()

    def set_theme(self, theme_name: str = "") -> None:
        if self._disposed:
            return
        self._tooltip.apply_theme()
        app = QApplication.instance()
        if app:
            self._tooltip.setFont(app.font())

    def eventFilter(self, obj, event):
        # PySide 在 QWidget 析构期间会先使 Python 包装对象失效，再派发隐藏事件。
        # destroyed 信号尚未到达时也不能再调用该包装对象的方法。
        if self._disposed or not isValid(self._tooltip):
            return False
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
        if self._disposed:
            raise RuntimeError("提示框管理器已关闭")
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
        if not self._disposed and isValid(self._tooltip):
            self._tooltip.hide()

    def _resolve_tooltip_text(self, obj, event) -> str:
        view = None
        if isinstance(obj, QAbstractItemView):
            view = obj
        elif isinstance(obj, QWidget) and isinstance(obj.parent(), QAbstractItemView):
            view = obj.parent()
        if view is not None:
            index = view.indexAt(event.pos())
            if index.isValid():
                data = index.data(Qt.ItemDataRole.ToolTipRole)
                if data:
                    return str(data)
            return view.toolTip()

        gv = None
        if isinstance(obj, QGraphicsView):
            gv = obj
        elif isinstance(obj, QWidget) and isinstance(obj.parent(), QGraphicsView):
            gv = obj.parent()
        if gv is not None:
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
        return event.globalPos()

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
    if _tooltip_manager is None or not isValid(_tooltip_manager):
        _tooltip_manager = CustomTooltipManager()
    return _tooltip_manager
