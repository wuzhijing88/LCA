import weakref

import logging

from PySide6.QtCore import QEvent, QObject, Qt


logger = logging.getLogger(__name__)


class InputWidgetEventFilter(QObject):
    def __init__(self, widget, widget_name):
        super().__init__(widget)
        self.widget = weakref.ref(widget)
        self.widget_name = widget_name

    def eventFilter(self, obj, event):
        if obj == self.widget():
            if event.type() == QEvent.Type.MouseButtonPress:
                logger.debug("输入控件 %s 接收到鼠标按下事件", self.widget_name)
                return False
            if event.type() == QEvent.Type.FocusIn:
                return False
            if event.type() == QEvent.Type.FocusOut:
                return False
        return False


class WheelEventFilter(QObject):
    def __init__(self, widget_name="", parent=None):
        super().__init__(parent)
        self.widget_name = widget_name

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Wheel:
            logger.debug("拦截控件 '%s' 的滚轮事件，防止意外修改参数", self.widget_name)
            event.ignore()
            return True
        return super().eventFilter(obj, event)


class CheckboxEventFilter(QObject):
    def __init__(self, checkbox, name):
        super().__init__(checkbox)
        self.checkbox = weakref.ref(checkbox)
        self.name = name

    def eventFilter(self, obj, event):
        if obj == self.checkbox() and event.type() == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                logger.info("复选框 '%s' 接收到鼠标按下事件", self.name)
                current_state = obj.isChecked()
                new_state = not current_state
                obj.setChecked(new_state)
                logger.info("复选框 '%s' 状态切换: %s -> %s", self.name, current_state, new_state)
                obj.clicked[bool].emit(new_state)
                event.accept()
                return True
        return False


class FavoritesItemEventFilter(QObject):
    def __init__(self, panel, list_item, parent):
        super().__init__(parent)
        self.panel = weakref.ref(panel)
        self.list_item = list_item

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            panel = self.panel()
            if panel is not None:
                panel._select_favorites_item(self.list_item, event)
        return False
