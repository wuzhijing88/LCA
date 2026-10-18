"""使用统一主题的标准下拉框，弹出列表随亮暗切换同步更新。"""

import weakref

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QComboBox, QListView, QStyle, QStyledItemDelegate, QStyleOptionComboBox,
    QStylePainter,
)

from .theme_manager import get_theme_manager


class ThemedComboBox(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("unifiedTheme", True)
        view = QListView(self)
        view.setObjectName("themedComboList")
        self.setView(view)
        # QComboBox 的默认委托按平台菜单绘制，绕开列表项的统一主题。
        self.setItemDelegate(QStyledItemDelegate(view))
        manager = get_theme_manager()
        owner = weakref.ref(self)

        def changed(_theme):
            combo = owner()
            if combo is not None:
                combo._apply_popup_theme()

        manager.register_theme_change_callback(changed)
        self.destroyed.connect(lambda _=None: manager.unregister_theme_change_callback(changed))
        self._apply_popup_theme()

    def _apply_popup_theme(self):
        view = self.view()
        get_theme_manager().apply_combo_popup_theme(view.window(), view)
        self.update()

    def paintEvent(self, event):
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        # 标签和边框继续走统一 QSS，箭头不交给平台的独立按钮绘制。
        option.subControls = (
            QStyle.SubControl.SC_ComboBoxFrame | QStyle.SubControl.SC_ComboBoxEditField
        )
        painter = QStylePainter(self)
        painter.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, option)
        painter.drawControl(QStyle.ControlElement.CE_ComboBoxLabel, option)

        arrow = self.style().subControlRect(
            QStyle.ComplexControl.CC_ComboBox, option,
            QStyle.SubControl.SC_ComboBoxArrow, self,
        )
        center = QRectF(arrow).center()
        color_key = "text_secondary" if self.isEnabled() else "text_disabled"
        pen = QPen(QColor(get_theme_manager().get_color(color_key)), 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(pen)
        path = QPainterPath()
        path.moveTo(center.x() - 4, center.y() - 2)
        path.lineTo(center.x(), center.y() + 2)
        path.lineTo(center.x() + 4, center.y() - 2)
        painter.drawPath(path)
        painter.end()

    def showPopup(self):
        self._apply_popup_theme()
        super().showPopup()

