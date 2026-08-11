import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton


logger = logging.getLogger(__name__)


class CloseButton(QPushButton):
    STYLE_NORMAL = """
        QPushButton {
            background-color: transparent;
            border: none;
            border-radius: 4px;
            color: #666666;
            font-family: "Segoe UI Symbol", "Segoe UI Emoji", "Arial";
            font-size: 12px;
        }
    """
    STYLE_HOVER = """
        QPushButton {
            background-color: #f44336;
            border: none;
            border-radius: 4px;
            color: #ffffff;
            font-family: "Segoe UI Symbol", "Segoe UI Emoji", "Arial";
            font-size: 12px;
        }
    """
    STYLE_PRESSED = """
        QPushButton {
            background-color: #d32f2f;
            border: none;
            border-radius: 4px;
            color: #ffffff;
            font-family: "Segoe UI Symbol", "Segoe UI Emoji", "Arial";
            font-size: 12px;
        }
    """

    def __init__(self, parent=None):
        super().__init__("✕", parent)
        self.setObjectName("windowButton")
        self.setToolTip("关闭")
        self.setFixedSize(36, 28)
        self.setStyleSheet(self.STYLE_NORMAL)

    def enterEvent(self, event):
        self.setStyleSheet(self.STYLE_HOVER)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setStyleSheet(self.STYLE_NORMAL)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setStyleSheet(self.STYLE_PRESSED)
            self.clicked.emit()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self.setStyleSheet(self.STYLE_NORMAL)
        super().mouseReleaseEvent(event)

    def resetStyle(self):
        self.setStyleSheet(self.STYLE_NORMAL)


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
