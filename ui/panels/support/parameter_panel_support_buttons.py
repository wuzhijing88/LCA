import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton


logger = logging.getLogger(__name__)


class CloseButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__("✕", parent)
        self.setObjectName("parameterPanelCloseButton")
        self.setToolTip("关闭")
        self.setFixedSize(36, 28)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setDown(True)
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setDown(False)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def resetStyle(self):
        self.setDown(False)
        self.update()


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
