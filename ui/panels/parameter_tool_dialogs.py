"""参数采集快照的交互界面；不启动输入钩子或执行插件源码。"""
import math
import weakref

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from themes import apply_rounded_popup, get_theme_manager, theme_color


class CaptureCanvas(QWidget):
    selection_changed = Signal(object)
    cancelled = Signal()
    view_changed = Signal(float, bool)

    def __init__(self, image, kind, parent):
        super().__init__(parent)
        self._frame_state = {"image": QImage(image)}
        self._kind = kind
        self._start = None
        self._selection = None
        self._scale = None
        self._center = QPointF(image.width() / 2, image.height() / 2)
        self._pan_anchor = None
        self.setMinimumSize(280, 200)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        owner = weakref.ref(self)
        manager = get_theme_manager()

        def changed(_theme):
            canvas = owner()
            if canvas is not None:
                canvas.update()

        self._theme_changed = changed
        manager.register_theme_change_callback(changed)
        state = self._frame_state

        def dispose(_object=None):
            state["image"] = QImage()
            manager.unregister_theme_change_callback(changed)

        self.destroyed.connect(dispose)

    @property
    def _image(self):
        return self._frame_state["image"]

    def clear_frame(self):
        self._frame_state["image"] = QImage()
        self._selection = None
        self._start = None
        self._scale = None
        self._center = QPointF()
        self._pan_anchor = None
        self.setCursor(Qt.CursorShape.ArrowCursor)
        get_theme_manager().unregister_theme_change_callback(self._theme_changed)
        self.update()

    def view_bounds(self):
        return QRectF(self.rect()).adjusted(8, 8, -8, -8)

    def view_scale(self):
        if self._image.isNull():
            return 1.0
        if self._scale is not None:
            return self._scale
        bounds = self.view_bounds()
        return min(bounds.width() / self._image.width(), bounds.height() / self._image.height())

    def _clamp_center(self):
        if self._scale is None:
            self._center = QPointF(self._image.width() / 2, self._image.height() / 2)
            return
        horizontal = min(max(self._center.x(), 0), self._image.width())
        vertical = min(max(self._center.y(), 0), self._image.height())
        self._center = QPointF(horizontal, vertical)

    def _view_updated(self):
        self.update()
        self.view_changed.emit(self.view_scale(), self._scale is None)

    def fit_to_view(self):
        if self._image.isNull():
            return
        self._scale = None
        self._center = QPointF(self._image.width() / 2, self._image.height() / 2)
        self._view_updated()
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def original_size(self):
        if self._image.isNull():
            return
        self._scale = 1.0
        if self._selection is not None:
            self._center = QRectF(self._selection).center()
        self._clamp_center()
        self._view_updated()
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def zoom_at(self, scale, position):
        if not math.isfinite(scale) or scale <= 0:
            raise ValueError("采集画面的缩放比例必须是有限正数")
        if self._image.isNull():
            return
        bounds = self.view_bounds()
        fitted = min(bounds.width() / self._image.width(), bounds.height() / self._image.height())
        scale = min(max(scale, min(fitted / 4, 1 / 64)), max(fitted, 32.0))
        previous = self.image_rect()
        old_scale = self.view_scale()
        source = QPointF((position.x() - previous.x()) / old_scale, (position.y() - previous.y()) / old_scale)
        self._scale = scale
        self._center = source - (QPointF(position) - bounds.center()) / scale
        self._clamp_center()
        self._view_updated()

    def zoom_in(self):
        self.zoom_at(self.view_scale() * 1.25, self.view_bounds().center())
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def zoom_out(self):
        self.zoom_at(self.view_scale() / 1.25, self.view_bounds().center())
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def image_rect(self):
        if self._image.isNull():
            return QRectF()
        bounds = self.view_bounds()
        scale = self.view_scale()
        width, height = self._image.width() * scale, self._image.height() * scale
        return QRectF(bounds.center().x() - self._center.x() * scale, bounds.center().y() - self._center.y() * scale, width, height)

    def image_point(self, position):
        rect = self.image_rect()
        if rect.isEmpty() or not self.view_bounds().contains(position) or not rect.contains(position):
            return None
        point = QPoint(int((position.x() - rect.x()) * self._image.width() / rect.width()), int((position.y() - rect.y()) * self._image.height() / rect.height()))
        return point if 0 <= point.x() < self._image.width() and 0 <= point.y() < self._image.height() else None

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(theme_color("surface")))
        painter.setClipRect(self.view_bounds())
        target = self.image_rect()
        if not target.isEmpty():
            painter.drawImage(target, self._image)
        if self._selection is not None and not target.isEmpty():
            scale_x, scale_y = target.width() / self._image.width(), target.height() / self._image.height()
            rect = self._selection
            drawn = QRectF(target.x() + rect.x() * scale_x, target.y() + rect.y() * scale_y, rect.width() * scale_x, rect.height() * scale_y)
            painter.fillRect(drawn, QColor(theme_color("selection_anchor_fill")))
            painter.setPen(QPen(QColor(theme_color("selection_anchor")), 2))
            painter.drawRect(drawn)
        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self.cancelled.emit()
            return
        if event.button() == Qt.MouseButton.MiddleButton and not self._image.isNull() and self._start is None:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self._pan_anchor = QPointF(event.position())
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._pan_anchor is None:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self._start = self.image_point(event.position())
            self._selection = None
            self.selection_changed.emit(None)
            self.update()

    def mouseMoveEvent(self, event):
        if self._pan_anchor is not None:
            delta = event.position() - self._pan_anchor
            self._pan_anchor = QPointF(event.position())
            self._scale = self.view_scale()
            self._center -= delta / self._scale
            self._clamp_center()
            self._view_updated()
            event.accept()
            return
        if self._kind == "框选区域" and self._start is not None:
            point = self.image_point(event.position())
            self._selection = QRect(self._start, point).normalized() if point is not None else None
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_anchor = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        if event.button() != Qt.MouseButton.LeftButton or self._start is None:
            return
        point = self.image_point(event.position())
        if point is None:
            self._selection = None
            self._start = None
            self.selection_changed.emit(None)
            self.update()
            return
        self._selection = QRect(self._start, point).normalized() if self._kind == "框选区域" else QRect(point, point)
        self._start = None
        self._emit_selection()

    def wheelEvent(self, event):
        if self._image.isNull():
            event.ignore()
            return
        if self._start is None and self._pan_anchor is None:
            delta = event.angleDelta().y()
            if not delta:
                delta = event.pixelDelta().y() * 2
            if delta:
                steps = min(max(delta / 120, -8), 8)
                self.zoom_at(self.view_scale() * 1.25 ** steps, event.position())
                self.setFocus(Qt.FocusReason.MouseFocusReason)
        event.accept()

    def focusOutEvent(self, event):
        self._pan_anchor = None
        self.setCursor(Qt.CursorShape.ArrowCursor)
        if self._start is not None:
            self._start = None
            self._selection = None
            self.selection_changed.emit(None)
            self.update()
        super().focusOutEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._image.isNull():
            self._clamp_center()
            self._view_updated()

    def _reveal_point(self, point):
        scale = self.view_scale()
        position = QPointF(self.image_rect().topLeft()) + QPointF(point.x() + 0.5, point.y() + 0.5) * scale
        bounds = self.view_bounds().adjusted(2, 2, -2, -2)
        horizontal = min(max(position.x(), bounds.left()), bounds.right())
        vertical = min(max(position.y(), bounds.top()), bounds.bottom())
        self._center += QPointF(position.x() - horizontal, position.y() - vertical) / scale
        self._clamp_center()
        self._view_updated()

    def _emit_selection(self):
        values = {"横坐标": self._selection.x(), "纵坐标": self._selection.y()}
        if self._kind == "框选区域":
            values.update({"宽度": self._selection.width(), "高度": self._selection.height()})
        elif self._kind == "取色":
            color = self._image.pixelColor(self._selection.topLeft())
            values.update({"红": color.red(), "绿": color.green(), "蓝": color.blue(), "颜色": f"{color.red()},{color.green()},{color.blue()}"})
        self.selection_changed.emit(values)
        self.update()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
        elif event.modifiers() == Qt.KeyboardModifier.NoModifier and event.key() == Qt.Key.Key_F:
            self.fit_to_view()
        elif event.modifiers() == Qt.KeyboardModifier.NoModifier and event.key() == Qt.Key.Key_1:
            self.original_size()
        elif event.modifiers() in (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.ShiftModifier) and event.key() in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.zoom_in()
        elif event.modifiers() == Qt.KeyboardModifier.NoModifier and event.key() == Qt.Key.Key_Minus:
            self.zoom_out()
        elif self._selection is not None and event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down):
            horizontal = -1 if event.key() == Qt.Key.Key_Left else 1 if event.key() == Qt.Key.Key_Right else 0
            vertical = -1 if event.key() == Qt.Key.Key_Up else 1 if event.key() == Qt.Key.Key_Down else 0
            rect = QRect(self._selection)
            if self._kind == "框选区域" and event.modifiers() == Qt.KeyboardModifier.ShiftModifier:
                rect.setWidth(rect.width() + horizontal)
                rect.setHeight(rect.height() + vertical)
            elif event.modifiers() == Qt.KeyboardModifier.NoModifier:
                rect.translate(horizontal, vertical)
            else:
                super().keyPressEvent(event)
                return
            if rect.width() > 0 and rect.height() > 0 and QRect(0, 0, self._image.width(), self._image.height()).contains(rect):
                self._selection = rect
                point = rect.bottomRight() if event.modifiers() == Qt.KeyboardModifier.ShiftModifier else rect.center()
                self._reveal_point(point)
                self._emit_selection()
        else:
            super().keyPressEvent(event)

    def hideEvent(self, event):
        self.clear_frame()
        super().hideEvent(event)


class CaptureDialog(QDialog):
    def __init__(self, snapshot, kind, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setWindowTitle(kind)
        apply_rounded_popup(self, frameless=False)
        self.resize(860, 620)
        self.selected_value = None
        self.window_snapshot = snapshot.window
        layout = QVBoxLayout(self)
        text = QLabel("滚轮缩放，中键拖动画面；拖动框选，方向键逐像素移动，Shift＋方向键调整大小。" if kind == "框选区域" else "滚轮缩放，中键拖动画面；单击选择，方向键逐像素微调，确认后写入。", self)
        text.setWordWrap(True)
        layout.addWidget(text)
        self.canvas = CaptureCanvas(snapshot.image, kind, self)
        self.canvas.selection_changed.connect(self._selection_changed)
        self.canvas.cancelled.connect(self.reject)
        navigation = QHBoxLayout()
        self.fit_button = QPushButton("适应窗口", self)
        self.original_button = QPushButton("原始比例", self)
        self.zoom_out_button = QPushButton("缩小", self)
        self.zoom_in_button = QPushButton("放大", self)
        for button, action in ((self.fit_button, self.canvas.fit_to_view), (self.original_button, self.canvas.original_size), (self.zoom_out_button, self.canvas.zoom_out), (self.zoom_in_button, self.canvas.zoom_in)):
            button.setAutoDefault(False)
            button.clicked.connect(action)
            navigation.addWidget(button)
        self.scale_label = QLabel(self)
        self.scale_label.setToolTip("滚轮缩放；鼠标中键拖动平移；F 适应窗口，1 原始比例，＋／－缩放。原始比例下一个原图像素对应一个界面逻辑像素，采集值始终使用原图物理像素。")
        navigation.addWidget(self.scale_label)
        navigation.addStretch()
        layout.addLayout(navigation)
        self.canvas.setToolTip(self.scale_label.toolTip())
        self.canvas.view_changed.connect(self._view_changed)
        self._view_changed(self.canvas.view_scale(), True)
        layout.addWidget(self.canvas, 1)
        self.status = QLabel("尚未选择；坐标使用目标客户区物理像素，取消不修改参数。", self)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        row.addStretch()
        cancel = QPushButton("取消", self)
        cancel.clicked.connect(self.reject)
        self.confirm = QPushButton("写入参数", self)
        self.confirm.setDefault(True)
        cancel.setAutoDefault(False)
        self.confirm.setEnabled(False)
        self.confirm.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(self.confirm)
        layout.addLayout(row)

    def _view_changed(self, scale, fitted):
        self.scale_label.setText(f"{'适应' if fitted else '缩放'}：{scale * 100:.6g}%")

    def _selection_changed(self, values):
        self.selected_value = values
        self.confirm.setEnabled(values is not None)
        self.status.setText("尚未选择" if values is None else "；".join(f"{name}：{value}" for name, value in values.items()))

    def accept(self):
        if self.selected_value is not None:
            super().accept()

    def hideEvent(self, event):
        self.canvas.clear_frame()
        super().hideEvent(event)


class WindowChoiceDialog(QDialog):
    def __init__(self, choices, current_hwnd, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setWindowTitle("选择目标窗口")
        apply_rounded_popup(self, frameless=False)
        self.resize(680, 460)
        self.selected_value = None
        self.window_snapshot = None
        self._choices = list(choices)
        layout = QVBoxLayout(self)
        label = QLabel("选择其他进程的可见应用窗口；列表为当前快照，状态变化请取消后重新打开。", self)
        label.setWordWrap(True)
        layout.addWidget(label)
        self.table = QTableWidget(len(choices), 3, self)
        self.table.setHorizontalHeaderLabels(["窗口标题", "句柄", "客户区"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        selected_index = None
        for index, choice in enumerate(choices):
            window = choice["window"]
            fields = [choice["error"], str(choice["hwnd"]), "不可用"] if window is None else [window.title or "（无标题）", str(window.hwnd), f"{window.width}×{window.height}"]
            for column, value in enumerate(fields):
                item = QTableWidgetItem(value)
                if window is None:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled & ~Qt.ItemFlag.ItemIsSelectable)
                self.table.setItem(index, column, item)
            if window is not None and window.hwnd == current_hwnd:
                self.table.selectRow(index)
                selected_index = index
        if selected_index is None:
            self.table.clearSelection()
            self.table.setCurrentCell(-1, -1)
        self.table.itemDoubleClicked.connect(self.accept)
        layout.addWidget(self.table)
        row = QHBoxLayout()
        row.addStretch()
        cancel, confirm = QPushButton("取消", self), QPushButton("选择窗口", self)
        cancel.setAutoDefault(False)
        confirm.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        confirm.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(confirm)
        layout.addLayout(row)
        cancel.setFocus()

    def accept(self, *_args):
        selected = self.table.selectionModel().selectedRows()
        index = selected[0].row() if len(selected) == 1 else -1
        if 0 <= index < len(self._choices):
            window = self._choices[index]["window"]
            if window is not None:
                self.window_snapshot = window
                self.selected_value = {"句柄": window.hwnd, "标题": window.title}
                super().accept()

    def hideEvent(self, event):
        self._choices.clear()
        self.table.setRowCount(0)
        super().hideEvent(event)
