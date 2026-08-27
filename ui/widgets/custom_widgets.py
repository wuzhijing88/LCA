# -*- coding: utf-8 -*-
"""
Custom UI widgets.
"""

import logging
from PySide6.QtWidgets import (
    QWidget,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QFrame,
    QHBoxLayout,
    QAbstractItemView,
    QSizePolicy,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QStyle,
    QLineEdit,
)
from PySide6.QtCore import Qt, Signal, QSize, QMargins, QEvent, QRect, QPoint
from PySide6.QtGui import QBrush, QColor, QFontMetrics, QIcon, QPainter, QPainterPath, QPen
from utils.window.window_activation_utils import show_and_raise_widget

logger = logging.getLogger(__name__)

def _get_theme_color(key: str, default: str) -> str:
    try:
        from themes import get_theme_manager
        return get_theme_manager().get_color(key)
    except Exception:
        return default


class CenteredTextDelegate(QStyledItemDelegate):
    """Draw full-width selection/hover and text."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._logged_once = False

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        widget = option.widget or self.parent()
        if widget and hasattr(widget, 'viewport'):
            view_rect = widget.viewport().rect()
        elif widget and widget.parent() and hasattr(widget.parent(), 'viewport'):
            view_rect = widget.parent().viewport().rect()
        else:
            view_rect = opt.rect
        if not self._logged_once:
            logger.info(
                "Delegate paint: opt_rect=%s view_rect=%s clip=%s clip_rect=%s",
                opt.rect,
                view_rect,
                painter.hasClipping(),
                painter.clipBoundingRect(),
            )
            self._logged_once = True

        full_rect = QRect(view_rect.left(), opt.rect.top(), view_rect.width(), opt.rect.height())
        is_selected = bool(opt.state & QStyle.State_Selected)
        is_hover = bool(opt.state & QStyle.State_MouseOver)
        if is_selected or is_hover:
            bg_color = QColor(_get_theme_color('hover', '#e8e8e8'))
            painter.save()
            from PySide6.QtCore import QRectF
            clip_path = QPainterPath()
            clip_path.addRoundedRect(
                QRectF(
                    view_rect.left() + 0.5,
                    view_rect.top() + 0.5,
                    max(0.0, float(view_rect.width() - 1)),
                    max(0.0, float(view_rect.height() - 1)),
                ),
                4.0,
                4.0,
            )
            painter.setClipPath(clip_path)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(bg_color))
            draw_rect = QRect(
                full_rect.left(),
                full_rect.top(),
                max(0, full_rect.width()),
                max(0, full_rect.height()),
            )
            painter.drawRect(draw_rect)
            painter.restore()

        text_color = QColor(_get_theme_color('text', '#333333'))
        painter.save()
        painter.setPen(text_color)
        painter.setFont(opt.font)
        text_rect = full_rect.adjusted(10, 0, -10, 0)
        elided = QFontMetrics(opt.font).elidedText(opt.text, Qt.TextElideMode.ElideRight, text_rect.width())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided)
        painter.restore()


class DropdownArrowButton(QPushButton):
    """可编辑下拉的箭头：自己画三角，不用 ▾，避免中文字体画成怪符号。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._arrow_only = False

    def setArrowOnly(self, arrow_only: bool) -> None:
        self._arrow_only = bool(arrow_only)
        if self._arrow_only:
            super().setText("")
            self.setIcon(QIcon())
        self.update()

    def setText(self, text: str) -> None:
        if self._arrow_only:
            super().setText("")
            return
        super().setText(text)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self._arrow_only:
            return
        color = QColor(_get_theme_color("text_secondary", "#666666"))
        if not self.isEnabled():
            color = QColor(_get_theme_color("text_disabled", "#999999"))
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx = self.width() / 2.0
        cy = self.height() / 2.0
        path = QPainterPath()
        path.moveTo(cx - 3.5, cy - 1.5)
        path.lineTo(cx + 3.5, cy - 1.5)
        path.lineTo(cx, cy + 2.5)
        path.closeSubpath()
        painter.fillPath(path, QBrush(color))


class RoundedPopupFrame(QFrame):
    """Rounded popup frame for CustomDropdown."""

    def __init__(self, parent=None, flags=Qt.WindowType.Widget):
        super().__init__(parent, flags)
        self._radius = 5
        self._bg_color = QColor("#ffffff")
        self._border_color = QColor("#d0d0d0")

    def setRadius(self, radius):
        self._radius = radius

    def setBackgroundColor(self, color):
        self._bg_color = QColor(color) if isinstance(color, str) else color

    def setBorderColor(self, color):
        self._border_color = QColor(color) if isinstance(color, str) else color

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        path = QPainterPath()
        path.addRoundedRect(0.5, 0.5, self.width() - 1, self.height() - 1, self._radius, self._radius)
        painter.fillPath(path, QBrush(self._bg_color))
        painter.setPen(QPen(self._border_color, 1))
        painter.drawPath(path)


class FullBleedListWidget(QListWidget):
    """Force viewport to fill the entire widget rect."""

    def resizeEvent(self, event):
        super().resizeEvent(event)
        try:
            viewport = self.viewport()
            if not viewport:
                return
            margins = self.contentsMargins()
            viewport_margins = self.viewportMargins() if hasattr(self, "viewportMargins") else QMargins(0, 0, 0, 0)
            # Avoid fighting style-driven frame paddings; this can cause popup instability.
            if any((margins.left(), margins.top(), margins.right(), margins.bottom(),
                    viewport_margins.left(), viewport_margins.top(),
                    viewport_margins.right(), viewport_margins.bottom())):
                return
            target_rect = QRect(0, 0, self.width(), self.height())
            if viewport.geometry() != target_rect:
                viewport.setGeometry(target_rect)
        except RuntimeError:
            return


class CustomDropdown(QWidget):
    """Custom dropdown using a popup QListWidget to avoid native scrollbars."""

    currentTextChanged = Signal(str)
    currentIndexChanged = Signal(int)
    activated = Signal(int)
    editTextChanged = Signal(str)

    class SizeAdjustPolicy:
        AdjustToContents = 0

    class InsertPolicy:
        NoInsert = 0

    class _ModelWrapper:
        """Provide a minimal model() API compatible with QComboBox."""

        def __init__(self, list_widget):
            self.list_widget = list_widget

        def item(self, index):
            return self.list_widget.item(index)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_text = ""
        self._current_index = -1
        self._items = []
        self._item_data = {}
        self._tooltip = ""
        self._item_height = 32
        self._max_visible_items = 8
        self._popup_padding = 0
        self._size_adjust_policy = self.SizeAdjustPolicy.AdjustToContents
        self._editable = False
        self._line_edit = None
        self._insert_policy = self.InsertPolicy.NoInsert
        self._min_contents_length = 0
        self._syncing_item_widths = False
        self._showing_popup = False

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.display_button = DropdownArrowButton()
        self.display_button.setObjectName("customDropdownButton")
        self.display_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.display_button.clicked.connect(self._toggle_popup)
        self.display_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(self.display_button)

        flags = Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
        if hasattr(Qt.WindowType, "NoDropShadowWindowHint"):
            flags |= Qt.WindowType.NoDropShadowWindowHint
        popup_parent = None
        try:
            if parent:
                popup_parent = parent.window()
        except RuntimeError:
            popup_parent = None
        # Use top-level parent for popup stability inside complex containers like ParameterPanel.
        self.popup_frame = RoundedPopupFrame(popup_parent, flags)
        self.popup_frame.setObjectName("customDropdownPopup")
        self.popup_frame.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.popup_frame.setContentsMargins(0, 0, 0, 0)
        self.popup_frame.hide()

        self.list_widget = FullBleedListWidget(self.popup_frame)
        self.list_widget.setObjectName("customDropdownList")
        self.list_widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_widget.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list_widget.setFrameShape(QFrame.Shape.NoFrame)
        self.list_widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list_widget.setMouseTracking(True)
        self.list_widget.setSpacing(0)
        self.list_widget.setContentsMargins(0, 0, 0, 0)
        self.list_widget.setViewportMargins(0, 0, 0, 0)
        self.list_widget.installEventFilter(self)
        self.list_widget.itemClicked.connect(self._on_item_selected)

        self.list_widget.setItemDelegate(CenteredTextDelegate(self.list_widget))

        self.list_widget.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self.list_widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.list_widget.setAutoFillBackground(False)
        viewport = self.list_widget.viewport()
        viewport.setAutoFillBackground(False)
        viewport.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        viewport.setContentsMargins(0, 0, 0, 0)
        viewport.installEventFilter(self)

        self._model_wrapper = self._ModelWrapper(self.list_widget)
        self._apply_styles()
        self.destroyed.connect(self._cleanup_popup)
        logger.info(
            "CustomDropdown init: parent=%s list_widget=%s",
            type(parent).__name__ if parent else "None",
            type(self.list_widget).__name__,
        )

    def _apply_styles(self):
        self.display_button.setStyleSheet("")
        self.popup_frame.setStyleSheet("")
        self.list_widget.setStyleSheet("")

    def _apply_popup_theme(self) -> None:
        card = _get_theme_color("card", "#ffffff")
        text = _get_theme_color("text", "#333333")
        border = _get_theme_color("border", "#d0d0d0")
        hover = _get_theme_color("hover", "#e8e8e8")
        self.popup_frame.setBackgroundColor(card)
        self.popup_frame.setBorderColor(border)
        self.list_widget.setStyleSheet(
            f"""
            QListWidget#customDropdownList,
            QListWidget#customDropdownList::viewport {{
                background-color: {card};
                color: {text};
                border: none;
                outline: none;
            }}
            QListWidget#customDropdownList::item {{
                background-color: {card};
                color: {text};
                padding: 0px;
                min-height: 18px;
                margin: 0px;
            }}
            QListWidget#customDropdownList::item:hover,
            QListWidget#customDropdownList::item:selected,
            QListWidget#customDropdownList::item:selected:hover {{
                background-color: {hover};
                color: {text};
            }}
            """
        )

    def _cleanup_popup(self, *_):
        popup = getattr(self, "popup_frame", None)
        if not popup:
            return
        try:
            popup.hide()
            popup.deleteLater()
        except RuntimeError:
            return

    def _normalize_popup_layout(self):
        try:
            self.list_widget.setContentsMargins(0, 0, 0, 0)
            if hasattr(self.list_widget, "setViewportMargins"):
                self.list_widget.setViewportMargins(0, 0, 0, 0)
            viewport = self.list_widget.viewport()
            if viewport:
                viewport.setContentsMargins(0, 0, 0, 0)
        except RuntimeError:
            return

    def _toggle_popup(self):
        try:
            if self.popup_frame.isVisible():
                self.popup_frame.hide()
            else:
                self.showPopup()
        except RuntimeError:
            return

    def _show_popup(self):
        if self._showing_popup:
            return
        self._showing_popup = True
        try:
            if not self._items or not self.isVisible() or not self.isEnabled():
                return

            if getattr(self, "_line_edit", None) is not None:
                global_pos = self.mapToGlobal(QPoint(0, self.height()))
                popup_width = max(1, self.width())
            else:
                button_rect = self.display_button.rect()
                global_pos = self.display_button.mapToGlobal(button_rect.bottomLeft())
                popup_width = max(1, self.display_button.width(), self.width())

            self._normalize_popup_layout()
            self.popup_frame.setFixedWidth(popup_width)
            self.list_widget.setFixedWidth(popup_width)
            self._sync_item_widths()

            apply_popup_theme = getattr(self, "_apply_popup_theme", None)
            if callable(apply_popup_theme):
                apply_popup_theme()

            visible_items = min(len(self._items), self._max_visible_items)
            row_height = self.list_widget.sizeHintForRow(0) if self.list_widget.count() > 0 else self._item_height
            if row_height <= 0:
                row_height = self._item_height
            spacing = self.list_widget.spacing() if hasattr(self.list_widget, "spacing") else 0
            list_margins = self.list_widget.contentsMargins()
            viewport_margins = self.list_widget.viewportMargins() if hasattr(self.list_widget, "viewportMargins") else QMargins(0, 0, 0, 0)
            list_height = (
                (row_height * visible_items)
                + max(0, visible_items - 1) * spacing
                + list_margins.top()
                + list_margins.bottom()
                + viewport_margins.top()
                + viewport_margins.bottom()
            )
            if list_height <= 0:
                list_height = max(self._item_height, row_height)
            self.list_widget.setFixedHeight(list_height)
            popup_height = list_height
            self.popup_frame.setFixedHeight(popup_height)
            self.list_widget.setGeometry(0, 0, popup_width, list_height)

            self.popup_frame.move(global_pos)
            show_and_raise_widget(self.popup_frame, log_prefix='自定义下拉弹层')
            logger.info(
                "CustomDropdown popup shown: popup=%s list=%s viewport=%s",
                self.popup_frame.geometry(),
                self.list_widget.geometry(),
                self.list_widget.viewport().geometry(),
            )
        except RuntimeError:
            return
        finally:
            self._showing_popup = False

    def showPopup(self):
        try:
            logger.info(
                "CustomDropdown showPopup: list_geom=%s viewport_geom=%s contents=%s viewport_margins=%s",
                self.list_widget.geometry(),
                self.list_widget.viewport().geometry(),
                self.list_widget.contentsMargins(),
                self.list_widget.viewportMargins(),
            )
            self._show_popup()
        except RuntimeError:
            return

    def hidePopup(self):
        try:
            if self.popup_frame and self.popup_frame.isVisible():
                self.popup_frame.hide()
        except RuntimeError:
            return

    def _on_item_selected(self, item):
        try:
            if not item:
                return
            old_text = self._current_text
            old_index = self._current_index
            row = self.list_widget.row(item)
            self._current_index = row
            self._current_text = item.text()
            self._sync_display_text(self._current_text)
            self.hidePopup()

            self.activated.emit(row)
            if old_index != self._current_index:
                self.currentIndexChanged.emit(row)
            if old_text != self._current_text:
                self.currentTextChanged.emit(self._current_text)
        except RuntimeError:
            return

    def eventFilter(self, obj, event):
        try:
            if event.type() == QEvent.Type.Resize and obj in (self.list_widget, self.list_widget.viewport()):
                self._sync_item_widths()
            return super().eventFilter(obj, event)
        except RuntimeError:
            return False

    def _sync_item_widths(self):
        if self._syncing_item_widths:
            return
        self._syncing_item_widths = True
        try:
            list_width = self.list_widget.width()
            if list_width <= 0:
                return
            list_margins = self.list_widget.contentsMargins()
            viewport_margins = self.list_widget.viewportMargins() if hasattr(self.list_widget, "viewportMargins") else QMargins(0, 0, 0, 0)
            item_width = max(
                0,
                list_width
                - list_margins.left()
                - list_margins.right()
                - viewport_margins.left()
                - viewport_margins.right(),
            )
            for i in range(self.list_widget.count()):
                item = self.list_widget.item(i)
                if not item:
                    continue
                height = item.sizeHint().height()
                if height <= 0:
                    height = self._item_height
                item.setSizeHint(QSize(item_width, height))
        except RuntimeError:
            return
        finally:
            self._syncing_item_widths = False

    def addItem(self, text: str, data=None):
        self._items.append(text)
        item = QListWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        font_metrics = QFontMetrics(self.list_widget.font())
        text_width = font_metrics.horizontalAdvance(text)
        item_height = max(self._item_height, font_metrics.height() + 12)
        item.setSizeHint(QSize(text_width + 30, item_height))
        self._item_height = max(self._item_height, item_height)
        self.list_widget.addItem(item)

        if data is not None:
            self._item_data[len(self._items) - 1] = data

        if len(self._items) == 1:
            self._current_index = 0
            self._current_text = text
            self._sync_display_text(text)

        self._sync_item_widths()

    def addItems(self, texts: list):
        for text in texts:
            self.addItem(text)

    def clear(self):
        self._items.clear()
        self._item_data.clear()
        self.list_widget.clear()
        self._current_text = ""
        self._current_index = -1
        self._sync_display_text("")

    def currentText(self) -> str:
        if self._line_edit is not None:
            return self._line_edit.text()
        return self._current_text

    def itemText(self, index: int) -> str:
        """Return an item's display text, matching ``QComboBox``'s API."""
        if 0 <= int(index) < len(self._items):
            return self._items[int(index)]
        return ""

    def currentIndex(self) -> int:
        return self._current_index

    def currentData(self):
        if self._current_index >= 0:
            return self._item_data.get(self._current_index, None)
        return None

    def setCurrentText(self, text: str):
        old_index = self._current_index
        old_text = self._current_text
        if text in self._items:
            self._current_index = self._items.index(text)
            self._current_text = text
            self._sync_display_text(text)
        elif self._editable:
            self._current_index = -1
            self._current_text = text
            self._sync_display_text(text)
        if old_index != self._current_index:
            self.currentIndexChanged.emit(self._current_index)
        if old_text != self._current_text:
            self.currentTextChanged.emit(self._current_text)

    def setCurrentIndex(self, index: int):
        if 0 <= index < len(self._items):
            old_index = self._current_index
            old_text = self._current_text
            self._current_index = index
            self._current_text = self._items[index]
            self._sync_display_text(self._current_text)
            if old_index != self._current_index:
                self.currentIndexChanged.emit(index)
            if old_text != self._current_text:
                self.currentTextChanged.emit(self._current_text)

    def count(self) -> int:
        return len(self._items)

    def setItemData(self, index: int, data):
        if 0 <= index < len(self._items):
            self._item_data[index] = data

    def itemData(self, index: int):
        return self._item_data.get(index, None)

    def setItemText(self, index: int, text: str):
        if 0 <= index < len(self._items):
            self._items[index] = text
            item = self.list_widget.item(index)
            if item:
                item.setText(text)
            if index == self._current_index:
                self._current_text = text
                self._sync_display_text(text)

    def findText(self, text: str) -> int:
        try:
            return self._items.index(text)
        except ValueError:
            return -1

    def findData(self, data):
        for index, item_data in self._item_data.items():
            if item_data == data:
                return index
        return -1

    def model(self):
        return self._model_wrapper

    def view(self):
        return self.list_widget

    def setItemDelegate(self, delegate):
        self.list_widget.setItemDelegate(delegate)

    def setMaxVisibleItems(self, count: int):
        if isinstance(count, int) and count > 0:
            self._max_visible_items = count

    def setToolTip(self, tooltip: str):
        self._tooltip = tooltip
        self.display_button.setToolTip(tooltip)
        if self._line_edit is not None:
            self._line_edit.setToolTip(tooltip)

    def setMinimumWidth(self, width: int):
        super().setMinimumWidth(width)
        if self._line_edit is None:
            self.display_button.setMinimumWidth(width)

    def setMaximumWidth(self, width: int):
        super().setMaximumWidth(width)
        if self._line_edit is None:
            self.display_button.setMaximumWidth(width)

    def setFixedWidth(self, width: int):
        super().setFixedWidth(width)
        if self._line_edit is None:
            self.display_button.setFixedWidth(width)

    def setEnabled(self, enabled: bool):
        super().setEnabled(enabled)
        self.display_button.setEnabled(enabled)
        if self._line_edit is not None:
            self._line_edit.setEnabled(enabled)

    def isEditable(self) -> bool:
        return bool(self._editable)

    def lineEdit(self):
        return self._line_edit

    def setEditText(self, text: str):
        self.setCurrentText("" if text is None else str(text))

    def setEditable(self, editable: bool):
        editable = bool(editable)
        if self._editable == editable and bool(self._line_edit) == editable:
            return
        self._editable = editable
        if editable:
            self._ensure_line_edit()
        else:
            self._remove_line_edit()

    def _sync_display_text(self, text: str):
        if self._line_edit is not None:
            if self._line_edit.text() != text:
                self._line_edit.blockSignals(True)
                self._line_edit.setText(text)
                self._line_edit.blockSignals(False)
            return
        self.display_button.setText(text)

    def _on_line_edit_text_changed(self, text: str):
        old_text = self._current_text
        old_index = self._current_index
        self._current_text = text
        if text in self._items:
            self._current_index = self._items.index(text)
        else:
            self._current_index = -1
        self.editTextChanged.emit(text)
        if old_index != self._current_index:
            self.currentIndexChanged.emit(self._current_index)
        if old_text != text:
            self.currentTextChanged.emit(text)

    def _ensure_line_edit(self):
        if self._line_edit is not None:
            return
        self._line_edit = QLineEdit(self)
        self._line_edit.setObjectName("customDropdownEdit")
        self._line_edit.setText(self._current_text)
        self._line_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        if self._tooltip:
            self._line_edit.setToolTip(self._tooltip)
        self._line_edit.textChanged.connect(self._on_line_edit_text_changed)
        layout = self.layout()
        layout.insertWidget(0, self._line_edit)
        self.display_button.setObjectName("customDropdownArrow")
        self.display_button.setArrowOnly(True)
        self.display_button.setFixedWidth(28)
        self.display_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.display_button.style().unpolish(self.display_button)
        self.display_button.style().polish(self.display_button)

    def _remove_line_edit(self):
        if self._line_edit is None:
            return
        try:
            self._line_edit.textChanged.disconnect(self._on_line_edit_text_changed)
        except (TypeError, RuntimeError):
            pass
        layout = self.layout()
        layout.removeWidget(self._line_edit)
        self._line_edit.deleteLater()
        self._line_edit = None
        self.display_button.setArrowOnly(False)
        self.display_button.setObjectName("customDropdownButton")
        self.display_button.setMinimumWidth(0)
        self.display_button.setMaximumWidth(16777215)
        self.display_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.display_button.setText(self._current_text)
        self.display_button.style().unpolish(self.display_button)
        self.display_button.style().polish(self.display_button)

    def setInsertPolicy(self, policy):
        self._insert_policy = policy

    def setSizeAdjustPolicy(self, policy):
        self._size_adjust_policy = policy

    def sizeAdjustPolicy(self):
        return self._size_adjust_policy

    def setMinimumContentsLength(self, length: int):
        self._min_contents_length = max(0, int(length))

    def adjustWidthToContents(self):
        font_metrics = QFontMetrics(self.display_button.font())
        max_width = 0
        for text in self._items:
            max_width = max(max_width, font_metrics.horizontalAdvance(text))
        total_width = max_width + 62
        self.setFixedWidth(total_width)

    def wheelEvent(self, event):
        event.ignore()

    def hideEvent(self, event):
        self.hidePopup()
        super().hideEvent(event)
