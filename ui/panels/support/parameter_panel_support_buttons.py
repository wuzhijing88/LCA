import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton


logger = logging.getLogger(__name__)


class CloseButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__("✕", parent)
        self.setObjectName("windowButton")
        self.setToolTip("关闭")
        self.setFixedSize(36, 28)
        self.setStyleSheet(self._style("normal"))

    def _style(self, kind: str) -> str:
        from themes import theme_color

        if kind == "hover":
            background = theme_color("error", "#e81123")
            color = "#ffffff"
        elif kind == "pressed":
            background = theme_color("error", "#e81123")
            color = "#ffffff"
        else:
            background = "transparent"
            color = theme_color("text_secondary", "#666666")
        return f"""
        QPushButton {{
            background-color: {background};
            border: none;
            border-radius: 4px;
            color: {color};
            font-family: "Segoe UI Symbol", "Segoe UI Emoji", "Arial";
            font-size: 12px;
        }}
        """

    def enterEvent(self, event):
        self.setStyleSheet(self._style("hover"))
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setStyleSheet(self._style("normal"))
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setStyleSheet(self._style("pressed"))
            self.clicked.emit()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self.setStyleSheet(self._style("normal"))
        super().mouseReleaseEvent(event)

    def resetStyle(self):
        self.setStyleSheet(self._style("normal"))


class ResponsiveButton(QPushButton):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, False)

    def mousePressEvent(self, event):
        logger.info("ResponsiveButton '%s' 接收到鼠标按下事件", self.text())
        if event.button() == Qt.MouseButton.LeftButton:
            logger.info("ResponsiveButton '%s' 发射点击信号", self.text())
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)
