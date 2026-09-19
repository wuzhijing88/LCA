# -*- coding: utf-8 -*-
"""点阵字库制作：框选、点字取色、排除单个像素、提取点阵、标注后保存为大漠/OP 文本字库。"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QImage,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsScene,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from themes import get_theme_manager, theme_color
from utils.window.window_coordinate_common import clamp_preferred_window_size, get_available_geometry_for_widget

_SOURCE_ZOOM_STEP = 1.15
_SOURCE_MAX_SCALE = 64.0

logger = logging.getLogger(__name__)


def _bgr_to_pixmap(image: np.ndarray) -> QPixmap:
    if image is None or image.size == 0:
        return QPixmap()
    if image.ndim == 2:
        rgb = np.repeat(image[:, :, None], 3, axis=2)
    else:
        rgb = image[:, :, ::-1].copy()
    height, width = rgb.shape[:2]
    qimage = QImage(rgb.data, width, height, rgb.strides[0], QImage.Format.Format_RGB888)
    return QPixmap.fromImage(qimage.copy())


def _binary_to_preview(
    binary: np.ndarray,
    boxes: Optional[List[Any]] = None,
    selected: Optional[List[int]] = None,
) -> np.ndarray:
    preview = np.zeros((*binary.shape[:2], 3), dtype=np.uint8)
    preview[:] = (32, 32, 32)
    preview[binary > 0] = (240, 240, 240)
    if not boxes:
        return preview
    selected_set = set(selected or [])
    for index, item in enumerate(boxes):
        x1 = max(0, int(item.x))
        y1 = max(0, int(item.y))
        x2 = min(preview.shape[1] - 1, x1 + int(item.width) - 1)
        y2 = min(preview.shape[0] - 1, y1 + int(item.height) - 1)
        if x2 <= x1 or y2 <= y1:
            continue
        color = (50, 160, 255) if index in selected_set else (80, 220, 80)
        preview[y1, x1 : x2 + 1] = color
        preview[y2, x1 : x2 + 1] = color
        preview[y1 : y2 + 1, x1] = color
        preview[y1 : y2 + 1, x2] = color
    return preview


def _pixel_preview_pixmap(bitmap: np.ndarray, max_w: int = 80, max_h: int = 52) -> QPixmap:
    pixmap = _bgr_to_pixmap(_binary_to_preview(bitmap))
    if pixmap.isNull() or pixmap.width() <= 0 or pixmap.height() <= 0:
        return pixmap
    scale = max(1, min(max_w // pixmap.width(), max_h // pixmap.height()))
    return pixmap.scaled(
        pixmap.width() * scale,
        pixmap.height() * scale,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.FastTransformation,
    )


class _SourceImageView(QGraphicsView):
    pick_requested = Signal(int, int, object)
    exclude_toggled = Signal(int, int)

    def __init__(self, placeholder: str, parent=None):
        super().__init__(parent)
        self.setObjectName("dictSourceView")
        self._placeholder = placeholder
        self._image: Optional[np.ndarray] = None
        self._item = None
        self._excluded: set = set()
        self._fitted = True
        self._panning = False
        self._pan_last: Optional[QPointF] = None
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(240, 140)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setFocusPolicy(Qt.FocusPolicy.WheelFocus)
        self.setMouseTracking(False)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        self.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.apply_theme()
        self._rebuild_scene()

    def apply_theme(self) -> None:
        border = theme_color("border", "#3e3e3e")
        background = theme_color("canvas", "#252525")
        self.setStyleSheet(
            f"QGraphicsView#dictSourceView {{ border: 1px solid {border}; background: {background}; border-radius: 4px; }}"
        )

    def refresh_theme(self) -> None:
        self.apply_theme()
        self._rebuild_scene()
        if self._fitted:
            self.fit_image()

    def set_image(self, image: Optional[np.ndarray], *, reset_view: bool = True) -> None:
        self._image = image
        if reset_view:
            self._excluded = set()
        self._rebuild_scene()
        if self._item is None:
            self._fitted = True
            self.resetTransform()
            return
        if reset_view:
            self._fitted = True
            self.fit_image()

    def set_excluded_pixels(self, pixels) -> None:
        self._excluded = {(int(x), int(y)) for x, y in pixels}
        self._rebuild_scene()

    def current_scale(self) -> float:
        return abs(self.transform().m11())

    def fit_image(self) -> None:
        if self._item is None:
            return
        self.resetTransform()
        self.fitInView(self._item, Qt.AspectRatioMode.KeepAspectRatio)
        self._fitted = True

    def zoom_by(self, factor: float) -> None:
        if self._item is None or factor <= 0:
            return
        fit = self._fit_scale()
        current = self.current_scale()
        if current <= 0:
            return
        target = min(_SOURCE_MAX_SCALE, max(fit, current * factor))
        applied = target / current
        if abs(applied - 1.0) < 1e-6:
            return
        self.scale(applied, applied)
        self._fitted = abs(target - fit) <= 1e-4

    def _fit_scale(self) -> float:
        if self._item is None:
            return 1.0
        view_rect = self.viewport().rect()
        source = self._item.boundingRect()
        if source.width() <= 0 or source.height() <= 0 or view_rect.width() <= 0 or view_rect.height() <= 0:
            return 1.0
        return min(view_rect.width() / source.width(), view_rect.height() / source.height())

    def _rebuild_scene(self) -> None:
        self._scene.clear()
        self._item = None
        if self._image is None or self._image.size == 0:
            self._show_placeholder()
            self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
            return
        pixmap = _bgr_to_pixmap(self._image)
        if pixmap.isNull():
            self._show_placeholder()
            self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
            return
        item = self._scene.addPixmap(pixmap)
        item.setTransformationMode(Qt.TransformationMode.FastTransformation)
        self._item = item
        self._scene.setSceneRect(item.boundingRect())
        self._draw_exclusions()
        self.viewport().setCursor(Qt.CursorShape.CrossCursor)

    def _show_placeholder(self) -> None:
        text = self._scene.addSimpleText(self._placeholder)
        text.setBrush(QBrush(QColor(theme_color("text_secondary", "#888888"))))
        self._scene.setSceneRect(text.boundingRect())
        self.resetTransform()

    def _draw_exclusions(self) -> None:
        if self._item is None or not self._excluded:
            return
        color = QColor(theme_color("error", "#e81123"))
        color.setAlpha(180)
        brush = QBrush(color)
        pen = QPen(Qt.PenStyle.NoPen)
        height, width = self._image.shape[:2]
        for x, y in self._excluded:
            if 0 <= x < width and 0 <= y < height:
                mark = self._scene.addRect(float(x), float(y), 1.0, 1.0)
                mark.setPen(pen)
                mark.setBrush(brush)
                mark.setZValue(1)

    def _image_pos(self, event: QMouseEvent) -> Optional[Tuple[int, int]]:
        if self._image is None or self._item is None:
            return None
        scene_pos = self.mapToScene(event.position().toPoint())
        image_x = int(scene_pos.x() // 1)
        image_y = int(scene_pos.y() // 1)
        height, width = self._image.shape[:2]
        if 0 <= image_x < width and 0 <= image_y < height:
            return image_x, image_y
        return None

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self._item is None:
            event.ignore()
            return
        delta = event.angleDelta().y()
        if delta == 0:
            event.ignore()
            return
        self.zoom_by(_SOURCE_ZOOM_STEP if delta > 0 else 1.0 / _SOURCE_ZOOM_STEP)
        event.accept()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._fitted:
            self.fit_image()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_last = event.position()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        pos = self._image_pos(event)
        if pos is None:
            return super().mousePressEvent(event)
        image_x, image_y = pos
        pixel = self._image[image_y, image_x]
        if event.button() == Qt.MouseButton.LeftButton:
            self.pick_requested.emit(image_x, image_y, pixel)
            event.accept()
            return
        if event.button() == Qt.MouseButton.RightButton:
            self.exclude_toggled.emit(image_x, image_y)
            event.accept()
            return
        return super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._panning and self._pan_last is not None:
            delta = event.position() - self._pan_last
            self._pan_last = event.position()
            horizontal = self.horizontalScrollBar()
            vertical = self.verticalScrollBar()
            horizontal.setValue(horizontal.value() - int(delta.x()))
            vertical.setValue(vertical.value() - int(delta.y()))
            event.accept()
            return
        return super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.MiddleButton and self._panning:
            self._panning = False
            self._pan_last = None
            cursor = Qt.CursorShape.CrossCursor if self._item is not None else Qt.CursorShape.ArrowCursor
            self.viewport().setCursor(cursor)
            event.accept()
            return
        return super().mouseReleaseEvent(event)


class _ClickImageLabel(QLabel):
    def __init__(self, on_click, placeholder: str, parent=None, on_right_click=None):
        super().__init__(parent)
        self._on_click = on_click
        self._on_right_click = on_right_click
        self._image: Optional[np.ndarray] = None
        self._scale = 1.0
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(240, 140)
        self.setText(placeholder)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.apply_theme()

    def apply_theme(self) -> None:
        border = theme_color("border", "#3e3e3e")
        muted = theme_color("text_secondary", "#888888")
        background = theme_color("canvas", "#252525")
        self.setStyleSheet(
            f"QLabel {{ border: 1px solid {border}; background: {background}; color: {muted}; border-radius: 4px; }}"
        )

    def set_image(self, image: Optional[np.ndarray]) -> None:
        self._image = image
        if image is None or image.size == 0:
            self.clear()
            self.setText("还没有取样图")
            return
        pixmap = _bgr_to_pixmap(image)
        fitted = pixmap.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation)
        if pixmap.width() > 0:
            self._scale = fitted.width() / float(pixmap.width())
        self.setPixmap(fitted)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._image is not None:
            self.set_image(self._image)

    def mousePressEvent(self, event: QMouseEvent):
        if self._image is None:
            return super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            handler = self._on_click
        elif event.button() == Qt.MouseButton.RightButton:
            handler = self._on_right_click
        else:
            return super().mousePressEvent(event)
        if handler is None:
            return super().mousePressEvent(event)
        pixmap = self.pixmap()
        if pixmap is None or pixmap.isNull():
            return
        x0 = (self.width() - pixmap.width()) // 2
        y0 = (self.height() - pixmap.height()) // 2
        local_x = int(event.position().x() - x0)
        local_y = int(event.position().y() - y0)
        if local_x < 0 or local_y < 0 or local_x >= pixmap.width() or local_y >= pixmap.height():
            return
        image_x = int(local_x / max(self._scale, 1e-6))
        image_y = int(local_y / max(self._scale, 1e-6))
        height, width = self._image.shape[:2]
        if 0 <= image_x < width and 0 <= image_y < height:
            handler(image_x, image_y, self._image[image_y, image_x])


class _GlyphRow(QFrame):
    clicked = Signal(int)
    text_edited = Signal(int, str)
    advance_requested = Signal(int)

    def __init__(self, index: int, item, parent=None):
        super().__init__(parent)
        self.index = int(index)
        self.item = item
        self.setObjectName("dictGlyphRow")
        self.setProperty("selected", False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(10)

        self.preview = QLabel()
        self.preview.setFixedSize(80, 52)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setObjectName("dictGlyphPreview")
        self.preview.setPixmap(_pixel_preview_pixmap(item.bitmap))
        layout.addWidget(self.preview)

        self.text_edit = QLineEdit()
        self.text_edit.setFixedWidth(52)
        self.text_edit.setMaxLength(4)
        self.text_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = QFont(self.text_edit.font())
        font.setPointSize(max(13, font.pointSize() + 3))
        self.text_edit.setFont(font)
        self.text_edit.setText(str(item.text or ""))
        self.text_edit.setPlaceholderText("字")
        self.text_edit.textChanged.connect(self._on_text_changed)
        self.text_edit.returnPressed.connect(lambda: self.advance_requested.emit(self.index))
        layout.addWidget(self.text_edit)
        layout.addStretch(1)

    def text(self) -> str:
        return str(self.text_edit.text() or "").strip()[:1]

    def set_text(self, value: str) -> None:
        current = str(value or "").strip()[:1]
        if self.text_edit.text() != current:
            self.text_edit.setText(current)

    def focus_input(self) -> None:
        self.text_edit.setFocus()
        self.text_edit.selectAll()

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", bool(selected))
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def _on_text_changed(self, value: str) -> None:
        self.text_edited.emit(self.index, str(value or "").strip()[:1])

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.index)
        return super().mousePressEvent(event)


class DictMakerDialog(QDialog):
    def __init__(
        self,
        parent=None,
        *,
        target_hwnd: Optional[int] = None,
        params: Optional[Dict[str, Any]] = None,
        images_dir: str = "",
        dicts_dir: str = "",
    ):
        super().__init__(parent)
        self.setWindowTitle("制作点阵字库")
        self._hwnd = int(target_hwnd or 0)
        self._params = dict(params or {})
        self._images_dir = str(images_dir or "").strip()
        self._dicts_dir_value = str(dicts_dir or "").strip()
        self._roi: Optional[np.ndarray] = None
        self._binary: Optional[np.ndarray] = None
        self._excluded_pixels: set = set()
        self._region: Tuple[int, int, int, int] = (0, 0, 0, 0)
        self._glyphs: List[Any] = []
        self._rows: List[_GlyphRow] = []
        self._selected_indexes: List[int] = []
        self._syncing_labels = False
        self._selector = None
        self.saved_dict_path = ""
        self.saved_color_format = ""
        self._build_ui()
        self._load_initial_state()
        self._register_theme_callback()

    def _build_ui(self) -> None:
        available = get_available_geometry_for_widget(self.parentWidget() or self)
        width, height = clamp_preferred_window_size(980, 640, available)
        self.resize(width, height)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        file_row = QHBoxLayout()
        file_row.setSpacing(6)
        file_row.addWidget(QLabel("字库"))
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("images/dicts/ui.txt")
        file_row.addWidget(self.path_edit, 1)
        browse = QPushButton("浏览")
        browse.clicked.connect(self._browse_file)
        new_btn = QPushButton("新建")
        new_btn.clicked.connect(self._new_file)
        file_row.addWidget(browse)
        file_row.addWidget(new_btn)
        layout.addLayout(file_row)

        action_row = QHBoxLayout()
        action_row.setSpacing(6)
        pick_region = QPushButton("框选取样")
        pick_region.clicked.connect(self._pick_region)
        recapture = QPushButton("再截一张")
        recapture.clicked.connect(self._capture_current_region)
        extract_one = QPushButton("提取单个")
        extract_one.setToolTip("当前框里的全部笔画做成一个字")
        extract_one.clicked.connect(lambda: self._extract_glyphs("single"))
        extract_many = QPushButton("提取多个")
        extract_many.setToolTip("按行列切开。切碎了加大列间距，粘在一起就减小")
        extract_many.clicked.connect(lambda: self._extract_glyphs("multiple"))
        action_row.addWidget(pick_region)
        action_row.addWidget(recapture)
        action_row.addWidget(extract_one)
        action_row.addWidget(extract_many)
        action_row.addSpacing(12)
        action_row.addWidget(QLabel("行距"))
        self.row_gap_spin = QSpinBox()
        self.row_gap_spin.setRange(0, 40)
        self.row_gap_spin.setValue(4)
        self.row_gap_spin.setToolTip("同一行里，竖直空隙小于这个值会算同一行")
        action_row.addWidget(self.row_gap_spin)
        action_row.addWidget(QLabel("列距"))
        self.col_gap_spin = QSpinBox()
        self.col_gap_spin.setRange(0, 40)
        self.col_gap_spin.setValue(8)
        self.col_gap_spin.setToolTip("同一字内部的空隙小于这个值会合在一起")
        action_row.addWidget(self.col_gap_spin)
        action_row.addStretch(1)
        self.status_label = QLabel("还没有取样图")
        self.status_label.setObjectName("dictStatusLabel")
        action_row.addWidget(self.status_label)
        layout.addLayout(action_row)

        sample_box = QGroupBox("取样")
        sample_layout = QVBoxLayout(sample_box)
        sample_layout.setContentsMargins(10, 8, 10, 10)
        sample_layout.setSpacing(6)

        self.source_view = _SourceImageView("框选后显示原图，左键取色，右键排除像素，滚轮放大", self)
        self.source_view.setToolTip("滚轮放大；左键取色；右键排除单个像素（再点一次取消）；中键拖动平移")
        self.source_view.pick_requested.connect(self._on_preview_click)
        self.source_view.exclude_toggled.connect(self._toggle_excluded_pixel)
        self.binary_label = _ClickImageLabel(
            self._on_binary_click,
            "二值预览",
            self,
            on_right_click=self._on_binary_exclude,
        )
        self.binary_label.setToolTip("左键点绿框选中点阵；右键排除单个像素")
        sample_layout.addWidget(self._titled("原图", self.source_view), 1)
        sample_layout.addWidget(self._titled("二值", self.binary_label), 1)

        color_row = QHBoxLayout()
        color_row.setSpacing(6)
        color_row.addWidget(QLabel("颜色"))
        self.color_edit = QLineEdit()
        self.color_edit.setPlaceholderText("点原图取色，或填写 ffffff-101010")
        self.color_edit.textChanged.connect(self._refresh_binary)
        color_row.addWidget(self.color_edit, 1)
        color_row.addWidget(QLabel("偏色"))
        self.delta_spin = QSpinBox()
        self.delta_spin.setRange(0, 80)
        self.delta_spin.setValue(16)
        self.delta_spin.valueChanged.connect(self._refresh_binary)
        color_row.addWidget(self.delta_spin)
        clear_color = QPushButton("清除")
        clear_color.clicked.connect(self.color_edit.clear)
        color_row.addWidget(clear_color)
        sample_layout.addLayout(color_row)

        self.label_box = QGroupBox("标注")
        label_layout = QVBoxLayout(self.label_box)
        label_layout.setContentsMargins(10, 8, 10, 10)
        label_layout.setSpacing(6)

        fill_row = QHBoxLayout()
        fill_row.setSpacing(6)
        self.batch_edit = QLineEdit()
        self.batch_edit.setPlaceholderText("整句填入，回车写入右侧")
        self.batch_edit.returnPressed.connect(self._apply_batch_labels)
        fill_row.addWidget(self.batch_edit, 1)
        fill_btn = QPushButton("填入")
        fill_btn.clicked.connect(self._apply_batch_labels)
        fill_row.addWidget(fill_btn)
        label_layout.addLayout(fill_row)

        self.glyph_host = QWidget()
        self.glyph_list = QVBoxLayout(self.glyph_host)
        self.glyph_list.setContentsMargins(0, 0, 0, 0)
        self.glyph_list.setSpacing(4)
        self.glyph_list.addStretch(1)
        self._show_glyph_empty()

        scroller = QScrollArea()
        scroller.setWidgetResizable(True)
        scroller.setFrameShape(QFrame.Shape.NoFrame)
        scroller.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroller.setWidget(self.glyph_host)
        label_layout.addWidget(scroller, 1)

        edit_row = QHBoxLayout()
        merge = QPushButton("合并")
        merge.setToolTip("按住 Ctrl 点选多个点阵后合并成一个字")
        merge.clicked.connect(self._merge_selected)
        remove = QPushButton("删除")
        remove.clicked.connect(self._remove_selected)
        edit_row.addWidget(merge)
        edit_row.addWidget(remove)
        edit_row.addStretch(1)
        label_layout.addLayout(edit_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(sample_box)
        splitter.addWidget(self.label_box)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([620, 320])
        layout.addWidget(splitter, 1)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        append_btn = QPushButton("追加到字库")
        append_btn.clicked.connect(lambda: self._save(append=True))
        overwrite = QPushButton("覆盖保存")
        overwrite.clicked.connect(lambda: self._save(append=False))
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.reject)
        bottom.addWidget(append_btn)
        bottom.addWidget(overwrite)
        bottom.addWidget(close_btn)
        layout.addLayout(bottom)
        self._apply_styles()

    def _register_theme_callback(self) -> None:
        try:
            get_theme_manager().register_theme_change_callback(self._on_theme_changed)
        except Exception:
            return
        self.destroyed.connect(self._forget_theme_callback)

    def _forget_theme_callback(self, _=None) -> None:
        try:
            get_theme_manager().unregister_theme_change_callback(self._on_theme_changed)
        except Exception:
            pass

    def done(self, result: int) -> None:
        self._forget_theme_callback()
        super().done(int(result))

    def closeEvent(self, event) -> None:
        self._forget_theme_callback()
        super().closeEvent(event)

    def _on_theme_changed(self, _theme=None) -> None:
        self._apply_styles()

    def _titled(self, title: str, widget: QWidget) -> QWidget:
        wrap = QWidget()
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        label = QLabel(title)
        label.setObjectName("dictSectionHint")
        layout.addWidget(label)
        layout.addWidget(widget, 1)
        return wrap

    def _apply_styles(self) -> None:
        muted = theme_color("text_secondary", "#888888")
        hover = theme_color("hover", "#3a3a3a")
        accent = theme_color("accent", "#0078d4")
        preview_bg = "#111111"
        self.label_box.setStyleSheet(
            f"""
            QLabel#dictGlyphEmpty {{
                color: {muted};
            }}
            QFrame#dictGlyphRow {{
                background: transparent;
                border: 1px solid transparent;
                border-radius: 6px;
            }}
            QFrame#dictGlyphRow:hover {{
                background: {hover};
            }}
            QFrame#dictGlyphRow[selected="true"] {{
                background: {hover};
                border: 1px solid {accent};
            }}
            QLabel#dictGlyphPreview {{
                background: {preview_bg};
                border-radius: 4px;
            }}
            """
        )
        self.status_label.setStyleSheet(f"color: {muted};")
        self.source_view.refresh_theme()
        self.binary_label.apply_theme()

    def _load_initial_state(self) -> None:
        from task_workflow.resource_path import unwrap_resource_path

        path = unwrap_resource_path(self._params.get("dict_file")) or ""
        if path:
            self.path_edit.setText(path)
        color = str(self._params.get("color_format") or "").strip()
        if color:
            self.color_edit.setText(color)

    def _dicts_dir(self) -> str:
        from task_workflow.resource_context import current_dicts_dir

        if self._dicts_dir_value:
            return self._dicts_dir_value
        bound = str(current_dicts_dir() or "").strip()
        if bound:
            return bound
        from utils.app_paths import get_dicts_dir

        return get_dicts_dir("LCA")

    def _browse_file(self) -> None:
        start = str(self.path_edit.text() or "").strip() or self._dicts_dir()
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择字库文件",
            start,
            "字库文件 (*.txt);;所有文件 (*.*)",
        )
        if path:
            self.path_edit.setText(path)

    def _new_file(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "新建字库文件",
            os.path.join(self._dicts_dir(), "ui.txt"),
            "字库文件 (*.txt);;所有文件 (*.*)",
        )
        if not path:
            return
        if not os.path.splitext(path)[1]:
            path += ".txt"
        if not os.path.exists(path):
            os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8"):
                pass
        self.path_edit.setText(path)

    def _pick_region(self) -> None:
        if self._hwnd <= 0:
            QMessageBox.warning(self, "制作字库", "请先绑定目标窗口")
            return
        from ui.selectors.ocr_region_selector import OCRRegionSelectorWidget

        self._selector = OCRRegionSelectorWidget(self)
        self._selector.set_target_window_hwnd(self._hwnd)
        self._selector.region_selected.connect(self._on_region_selected)
        self._selector.start_selection()

    def _on_region_selected(self, x: int, y: int, width: int, height: int) -> None:
        self._region = (int(x), int(y), int(width), int(height))
        self._capture_current_region()

    def _capture_current_region(self) -> None:
        if self._hwnd <= 0:
            QMessageBox.warning(self, "制作字库", "请先绑定目标窗口")
            return
        from tasks.ocr_region_recognition import (
            _align_window_image_to_client_area,
            _capture_window_for_ocr,
            _extract_effective_ocr_roi,
        )

        image = _capture_window_for_ocr(self._hwnd, timeout=4.0)
        if image is None:
            QMessageBox.warning(self, "制作字库", "截图失败")
            return
        image = _align_window_image_to_client_area(image, self._hwnd)
        x, y, width, height = self._region
        roi, final_x, final_y, final_w, final_h, desc = _extract_effective_ocr_roi(
            window_image=image,
            region_mode="指定区域" if width > 0 and height > 0 else "整个窗口",
            region_x=x,
            region_y=y,
            region_width=width,
            region_height=height,
        )
        if roi is None or roi.size == 0:
            QMessageBox.warning(self, "制作字库", "截到的区域是空的")
            return
        self._region = (final_x, final_y, final_w, final_h)
        self._set_sample_image(roi)
        self.status_label.setText(f"已截图 {desc}")

    def _set_sample_image(self, roi: np.ndarray) -> None:
        self._roi = roi
        self._excluded_pixels.clear()
        self._glyphs = []
        self._reload_glyphs()
        self.source_view.set_image(roi)
        self._refresh_binary()

    def _on_preview_click(self, _x: int, _y: int, pixel) -> None:
        from services.dict_ocr_service import merge_damo_colors, rgb_to_damo_color

        blue, green, red = (
            (int(pixel[0]), int(pixel[1]), int(pixel[2]))
            if len(pixel) >= 3
            else (int(pixel), int(pixel), int(pixel))
        )
        color = rgb_to_damo_color(red, green, blue, self.delta_spin.value())
        self.color_edit.setText(merge_damo_colors(self.color_edit.text(), color))

    def _toggle_excluded_pixel(self, x: int, y: int) -> None:
        if self._roi is None:
            return
        height, width = self._roi.shape[:2]
        image_x = int(x)
        image_y = int(y)
        if not (0 <= image_x < width and 0 <= image_y < height):
            return
        key = (image_x, image_y)
        if key in self._excluded_pixels:
            self._excluded_pixels.discard(key)
        else:
            self._excluded_pixels.add(key)
        self.source_view.set_excluded_pixels(self._excluded_pixels)
        self._refresh_binary()
        count = len(self._excluded_pixels)
        self.status_label.setText(f"已排除 {count} 个像素" if count else "已取消排除")

    def _apply_pixel_exclusions(self, binary: np.ndarray) -> np.ndarray:
        if binary is None or not self._excluded_pixels:
            return binary
        height, width = binary.shape[:2]
        for image_x, image_y in self._excluded_pixels:
            if 0 <= image_x < width and 0 <= image_y < height:
                binary[image_y, image_x] = 0
        return binary

    def _refresh_binary(self) -> None:
        if self._roi is None:
            return
        from services.dict_ocr_service import binarize_image

        try:
            self._binary = self._apply_pixel_exclusions(
                binarize_image(self._roi, self.color_edit.text().strip())
            )
        except Exception as exc:
            logger.warning("二值化失败: %s", exc)
            self._binary = None
            return
        self._update_binary_preview()

    def _update_binary_preview(self) -> None:
        if self._binary is None:
            return
        self.binary_label.set_image(_binary_to_preview(self._binary, self._glyphs, self._selected_indexes))

    def _extract_glyphs(self, mode: str = "multiple") -> None:
        if self._roi is None:
            QMessageBox.warning(self, "制作字库", "请先框选并截图")
            return
        self._refresh_binary()
        if self._binary is None:
            QMessageBox.warning(self, "制作字库", "二值化失败，先点文字取样，或把偏色调大一点")
            return
        from services.dict_ocr_service import extract_glyphs_from_binary

        self._glyphs = extract_glyphs_from_binary(
            self._binary,
            mode=mode,
            row_gap=int(self.row_gap_spin.value()),
            col_gap=int(self.col_gap_spin.value()),
        )
        self._reload_glyphs()
        self._update_binary_preview()
        kind = "单个" if mode == "single" else "多个"
        self.status_label.setText(f"{kind}提取到 {len(self._glyphs)} 个")
        if self._rows:
            self._rows[0].focus_input()
        if not self._glyphs:
            QMessageBox.information(self, "制作字库", "没有提取到点阵。再点一下文字颜色，或把框选收紧到只有字。")
        elif mode == "multiple" and len(self._glyphs) > 8:
            self.status_label.setText(f"提取到 {len(self._glyphs)} 个，切碎了就加大列距")

    def _on_binary_exclude(self, x: int, y: int, _pixel) -> None:
        self._toggle_excluded_pixel(x, y)

    def _on_binary_click(self, x: int, y: int, _pixel) -> None:
        if not self._glyphs:
            return
        for index, item in enumerate(self._glyphs):
            if item.x <= x < item.x + item.width and item.y <= y < item.y + item.height:
                self._select_indexes([index], toggle=True)
                if 0 <= index < len(self._rows):
                    self._rows[index].focus_input()
                return

    def _clear_glyph_list(self) -> None:
        while self.glyph_list.count():
            taken = self.glyph_list.takeAt(0)
            widget = taken.widget() if taken is not None else None
            if widget is not None:
                widget.deleteLater()

    def _show_glyph_empty(self) -> None:
        empty = QLabel("提取后按从左到右列在这里，每行填一个字。")
        empty.setWordWrap(True)
        empty.setObjectName("dictGlyphEmpty")
        self.glyph_list.insertWidget(0, empty)

    def _reload_glyphs(self) -> None:
        existing = [row.text() for row in self._rows]
        self._rows = []
        self._selected_indexes = []
        self._clear_glyph_list()
        self.glyph_list.addStretch(1)
        if not self._glyphs:
            self._show_glyph_empty()
            self.label_box.setTitle("标注")
            return
        for index, item in enumerate(self._glyphs):
            if not item.text and index < len(existing):
                item.text = existing[index]
            row = _GlyphRow(index, item, self.glyph_host)
            row.clicked.connect(self._on_row_clicked)
            row.text_edited.connect(self._on_row_text_edited)
            row.advance_requested.connect(self._focus_next_row)
            self._rows.append(row)
            self.glyph_list.insertWidget(self.glyph_list.count() - 1, row)
        self.label_box.setTitle(f"标注  {len(self._glyphs)}")

    def _apply_batch_labels(self) -> None:
        text = str(self.batch_edit.text() or "").strip()
        if not text or not self._rows:
            return
        self._syncing_labels = True
        chars = list(text)
        for index, row in enumerate(self._rows):
            value = chars[index] if index < len(chars) else ""
            row.set_text(value)
            if index < len(self._glyphs):
                self._glyphs[index].text = value
        self._syncing_labels = False
        self._rows[0].focus_input()

    def _on_row_text_edited(self, index: int, value: str) -> None:
        if self._syncing_labels:
            return
        if 0 <= index < len(self._glyphs):
            self._glyphs[index].text = value

    def _focus_next_row(self, index: int) -> None:
        next_index = int(index) + 1
        if 0 <= next_index < len(self._rows):
            self._select_indexes([next_index])
            self._rows[next_index].focus_input()

    def _select_indexes(self, indexes: List[int], *, toggle: bool = False) -> None:
        multi = bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier)
        if multi and toggle:
            current = list(self._selected_indexes)
            for index in indexes:
                if index in current:
                    current = [item for item in current if item != index]
                else:
                    current.append(index)
            self._selected_indexes = current
        elif multi:
            merged = list(self._selected_indexes)
            for index in indexes:
                if index not in merged:
                    merged.append(index)
            self._selected_indexes = merged
        else:
            self._selected_indexes = list(indexes)
        for row in self._rows:
            row.set_selected(row.index in self._selected_indexes)
        self._update_binary_preview()

    def _on_row_clicked(self, index: int) -> None:
        self._select_indexes([index], toggle=True)

    def _sync_row_texts(self) -> None:
        for row in self._rows:
            if 0 <= row.index < len(self._glyphs):
                self._glyphs[row.index].text = row.text()

    def _collect_labeled_glyphs(self):
        self._sync_row_texts()
        labeled = []
        for extracted in self._glyphs:
            glyph = extracted.to_glyph()
            if glyph is not None:
                labeled.append(glyph)
        return labeled

    def _remove_selected(self) -> None:
        if not self._selected_indexes:
            QMessageBox.information(self, "制作字库", "先点选一行，再删除。")
            return
        self._sync_row_texts()
        self._glyphs = [item for index, item in enumerate(self._glyphs) if index not in set(self._selected_indexes)]
        self._reload_glyphs()
        self._update_binary_preview()

    def _merge_selected(self) -> None:
        if len(self._selected_indexes) < 2:
            QMessageBox.information(self, "制作字库", "按住 Ctrl 点选至少两行，再合并。")
            return
        if self._binary is None:
            return
        from services.dict_ocr_service import ExtractedGlyph, sort_glyphs_reading_order

        self._sync_row_texts()
        indexes = sorted(self._selected_indexes)
        items = [self._glyphs[index] for index in indexes]
        left = min(item.x for item in items)
        top = min(item.y for item in items)
        right = max(item.x + item.width for item in items)
        bottom = max(item.y + item.height for item in items)
        crop = self._binary[top:bottom, left:right]
        if crop is None or crop.size == 0:
            return
        merged = ExtractedGlyph(
            bitmap=(crop > 0).astype(crop.dtype),
            x=left,
            y=top,
            width=int(crop.shape[1]),
            height=int(crop.shape[0]),
            bit_count=int((crop > 0).sum()),
            text=str(items[0].text or ""),
        )
        self._glyphs = [item for index, item in enumerate(self._glyphs) if index not in set(indexes)]
        self._glyphs.insert(min(indexes), merged)
        self._glyphs = sort_glyphs_reading_order(self._glyphs)
        self._reload_glyphs()
        for index, item in enumerate(self._glyphs):
            if item is merged:
                self._select_indexes([index])
                break
        self._update_binary_preview()

    def _save(self, append: bool) -> None:
        path = str(self.path_edit.text() or "").strip()
        if not path:
            self._new_file()
            path = str(self.path_edit.text() or "").strip()
        if not path:
            return
        labeled = self._collect_labeled_glyphs()
        if not labeled:
            QMessageBox.warning(self, "制作字库", "还没有标注文字。在右侧列表里填字，或在上方整句填入。")
            return
        from services.dict_ocr_service import write_dict_text_file

        try:
            added = write_dict_text_file(path, labeled, append=append, fmt="damo")
        except Exception as exc:
            QMessageBox.warning(self, "制作字库", f"保存失败: {exc}")
            return
        self.saved_dict_path = os.path.abspath(path)
        self.saved_color_format = str(self.color_edit.text() or "").strip()
        self.path_edit.setText(self.saved_dict_path)
        verb = "追加" if append else "覆盖保存"
        QMessageBox.information(self, "制作字库", f"{verb}完成，写入 {added} 个新字形。\n{self.saved_dict_path}")
        self.accept()


def apply_dict_maker_result_to_panel(panel, path: str, color_format: str) -> None:
    if panel is None:
        return
    updates: Dict[str, Any] = {}
    if path:
        panel.current_parameters["dict_file"] = path
        updates["dict_file"] = path
        widget = getattr(panel, "widgets", {}).get("dict_file")
        if widget is not None and hasattr(widget, "setText"):
            widget.setText(path)
    if color_format:
        panel.current_parameters["color_format"] = color_format
        updates["color_format"] = color_format
        widget = getattr(panel, "widgets", {}).get("color_format")
        if widget is not None and hasattr(widget, "setText"):
            widget.setText(color_format)
    if updates and hasattr(panel, "parameters_changed") and getattr(panel, "current_card_id", None) is not None:
        panel.parameters_changed.emit(panel.current_card_id, updates)
