from __future__ import annotations

from typing import Callable

import cv2
import numpy as np
_QT_AVAILABLE = True
try:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QMouseEvent, QPixmap
    from PySide6.QtWidgets import (
        QApplication,
        QComboBox,
        QDialog,
        QFileDialog,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMessageBox,
        QPushButton,
        QScrollArea,
        QSpinBox,
        QVBoxLayout,
        QWidget,
    )
except ImportError:
    _QT_AVAILABLE = False

    class _UnavailableWidget:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("地图拼图工具需要 PySide6")

    class QApplication(_UnavailableWidget):
        @staticmethod
        def instance():
            return None

    Qt = QImage = QMouseEvent = QPixmap = _UnavailableWidget
    QComboBox = QDialog = QFileDialog = QHBoxLayout = _UnavailableWidget
    QLabel = QLineEdit = QMessageBox = QPushButton = _UnavailableWidget
    QScrollArea = QSpinBox = QVBoxLayout = QWidget = _UnavailableWidget

from app_core.maps.record import (
    CELL_BLOCKED,
    CELL_WALKABLE,
    MapRecord,
    format_map_option,
    load_map,
)
from app_core.maps.stitch import next_tile_origin, stitch_by_origins
from ui.maps.editor_payload import apply_editor_payload


def _read_image(path: str) -> np.ndarray | None:
    try:
        data = np.fromfile(path, dtype=np.uint8)
    except OSError:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


class _MapCanvas(QLabel):
    def __init__(self, on_click: Callable[[int, int], None], parent=None):
        super().__init__(parent)
        self._on_click = on_click
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.setText("请先导入地图图片")

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.pixmap() is not None:
            point = event.position()
            self._on_click(int(point.x()), int(point.y()))
            return
        super().mousePressEvent(event)


class MapStitcherDialog(QDialog):
    def __init__(self, parent=None, record: MapRecord | None = None):
        super().__init__(parent)
        self.setWindowTitle("地图拼图工具")
        self.resize(900, 680)
        self.setMinimumSize(640, 480)
        self._record = record
        self._tiles: list[np.ndarray] = []
        self._origins: list[tuple[int, int]] = []
        self._route: list[tuple[int, int]] = []
        self._goal: tuple[int, int] | None = None
        self._painted_cells: set[tuple[int, int]] = set()
        self._walkability: np.ndarray | None = None
        self.saved_option: str | None = None

        self._name_edit = QLineEdit(record.name if record is not None else "未命名地图")
        self._name_edit.setPlaceholderText("地图名称")
        self._mode = QComboBox()
        self._mode.addItem("设置终点", "goal")
        self._mode.addItem("绘制折线", "route")
        self._mode.addItem("涂抹墙体", "paint")
        self._origin_x_spin = QSpinBox()
        self._origin_y_spin = QSpinBox()
        for spin in (self._origin_x_spin, self._origin_y_spin):
            spin.setRange(-1_000_000, 1_000_000)
            spin.setEnabled(False)
            spin.valueChanged.connect(self._on_origin_changed)

        import_button = QPushButton("导入图片")
        clear_route_button = QPushButton("清除标注")
        save_button = QPushButton("保存")
        cancel_button = QPushButton("取消")
        import_button.clicked.connect(self._import_images)
        clear_route_button.clicked.connect(self._clear_annotations)
        save_button.clicked.connect(self._save)
        cancel_button.clicked.connect(self.reject)

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("名称"))
        toolbar.addWidget(self._name_edit, 1)
        toolbar.addWidget(import_button)
        toolbar.addWidget(QLabel("点击模式"))
        toolbar.addWidget(self._mode)
        toolbar.addWidget(QLabel("末图 X"))
        toolbar.addWidget(self._origin_x_spin)
        toolbar.addWidget(QLabel("Y"))
        toolbar.addWidget(self._origin_y_spin)
        toolbar.addWidget(clear_route_button)

        self._canvas = _MapCanvas(self._on_canvas_click)
        scroll = QScrollArea()
        scroll.setWidgetResizable(False)
        scroll.setWidget(self._canvas)

        footer = QHBoxLayout()
        footer.addWidget(QLabel("折线末端即终点；墙体点击可切换。"))
        footer.addStretch(1)
        footer.addWidget(save_button)
        footer.addWidget(cancel_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addLayout(toolbar)
        layout.addWidget(scroll, 1)
        layout.addLayout(footer)

        if record is not None:
            self._tiles = [record.image_bgr.copy()]
            self._origins = [(0, 0)]
            self._route = list(record.route)
            self._goal = record.goal
            self._walkability = record.walkability.copy()
            ys, xs = np.nonzero(record.painted_blocked)
            self._painted_cells = {(int(x), int(y)) for y, x in zip(ys, xs)}
        self._sync_origin_controls()
        self._refresh_canvas()

    def _current_image(self) -> np.ndarray | None:
        if not self._tiles:
            return None
        image = stitch_by_origins(self._tiles, self._origins)
        return image if image.size else None

    def _import_images(self) -> None:
        paths, _selected = QFileDialog.getOpenFileNames(
            self,
            "导入地图图片",
            "",
            "图片 (*.png *.jpg *.jpeg *.bmp *.webp);;所有文件 (*.*)",
        )
        for path in paths:
            tile = _read_image(path)
            if tile is None:
                continue
            if not self._tiles:
                origin = (0, 0)
            else:
                canvas = self._current_image()
                origin = next_tile_origin(canvas, tile) if canvas is not None else (0, 0)
            self._tiles.append(tile)
            self._origins.append(origin)
            self._normalize_origins()
        self._sync_origin_controls()
        self._refresh_canvas()

    def _sync_origin_controls(self) -> None:
        enabled = bool(self._origins)
        self._origin_x_spin.setEnabled(enabled)
        self._origin_y_spin.setEnabled(enabled)
        if not enabled:
            return
        x, y = self._origins[-1]
        self._origin_x_spin.blockSignals(True)
        self._origin_y_spin.blockSignals(True)
        try:
            self._origin_x_spin.setValue(int(x))
            self._origin_y_spin.setValue(int(y))
        finally:
            self._origin_x_spin.blockSignals(False)
            self._origin_y_spin.blockSignals(False)

    def _on_origin_changed(self, _value: int) -> None:
        if not self._origins:
            return
        self._origins[-1] = (self._origin_x_spin.value(), self._origin_y_spin.value())
        self._normalize_origins()
        self._sync_origin_controls()
        self._refresh_canvas()

    def _normalize_origins(self) -> None:
        if not self._origins:
            return
        min_x = min(x for x, _y in self._origins)
        min_y = min(y for _x, y in self._origins)
        dx = -int(min_x)
        dy = -int(min_y)
        if dx or dy:
            self._origins = [(x + dx, y + dy) for x, y in self._origins]
            self._painted_cells = {(x + dx, y + dy) for x, y in self._painted_cells}
            self._route = [(x + dx, y + dy) for x, y in self._route]
            if self._goal is not None:
                self._goal = (self._goal[0] + dx, self._goal[1] + dy)
            self._shift_walkability(dx, dy)
        self._resize_layers()

    def _shift_walkability(self, dx: int, dy: int) -> None:
        if self._walkability is None:
            return
        image = self._current_image()
        if image is None:
            return
        shifted = np.zeros(image.shape[:2], dtype=np.uint8)
        source = self._walkability
        source_x = max(0, -dx)
        source_y = max(0, -dy)
        target_x = max(0, dx)
        target_y = max(0, dy)
        width = min(source.shape[1] - source_x, shifted.shape[1] - target_x)
        height = min(source.shape[0] - source_y, shifted.shape[0] - target_y)
        if width > 0 and height > 0:
            shifted[target_y : target_y + height, target_x : target_x + width] = source[
                source_y : source_y + height,
                source_x : source_x + width,
            ]
        self._walkability = shifted

    def _resize_layers(self) -> None:
        image = self._current_image()
        if image is None:
            return
        shape = image.shape[:2]
        if self._walkability is None:
            self._walkability = np.zeros(shape, dtype=np.uint8)
        elif self._walkability.shape[:2] != shape:
            resized = np.zeros(shape, dtype=np.uint8)
            height = min(shape[0], self._walkability.shape[0])
            width = min(shape[1], self._walkability.shape[1])
            resized[:height, :width] = self._walkability[:height, :width]
            self._walkability = resized
        height, width = shape
        self._painted_cells = {
            (x, y) for x, y in self._painted_cells if 0 <= x < width and 0 <= y < height
        }

    def _clear_annotations(self) -> None:
        self._route.clear()
        self._goal = None
        self._painted_cells.clear()
        self._refresh_canvas()

    def _on_canvas_click(self, x: int, y: int) -> None:
        image = self._current_image()
        if image is None or x < 0 or y < 0 or x >= image.shape[1] or y >= image.shape[0]:
            return
        mode = self._mode.currentData()
        if mode == "goal":
            self._goal = (x, y)
            self._route.clear()
        elif mode == "route":
            self._route.append((x, y))
            self._goal = None
        else:
            cell = (x, y)
            if cell in self._painted_cells:
                self._painted_cells.remove(cell)
            else:
                self._painted_cells.add(cell)
        self._refresh_canvas()

    def _display_image(self) -> np.ndarray | None:
        image = self._current_image()
        if image is None:
            return None
        display = image.copy()
        if self._walkability is not None and self._walkability.shape == image.shape[:2]:
            overlay = display.copy()
            overlay[self._walkability == CELL_WALKABLE] = (60, 180, 60)
            overlay[self._walkability == CELL_BLOCKED] = (40, 40, 220)
            known = self._walkability != 0
            display[known] = cv2.addWeighted(display, 0.55, overlay, 0.45, 0)[known]
        for x, y in self._painted_cells:
            display[y, x] = (40, 40, 255)
        if len(self._route) > 1:
            cv2.polylines(display, [np.asarray(self._route, dtype=np.int32)], False, (0, 220, 255), 2)
        for point in self._route:
            cv2.circle(display, point, 3, (0, 220, 255), -1)
        if self._goal is not None:
            cv2.drawMarker(display, self._goal, (0, 255, 255), cv2.MARKER_CROSS, 14, 2)
        return display

    def _refresh_canvas(self) -> None:
        display = self._display_image()
        if display is None:
            self._canvas.clear()
            self._canvas.setText("请先导入地图图片")
            self._canvas.adjustSize()
            return
        rgb = cv2.cvtColor(display, cv2.COLOR_BGR2RGB)
        height, width = rgb.shape[:2]
        image = QImage(rgb.data, width, height, width * 3, QImage.Format.Format_RGB888).copy()
        self._canvas.setPixmap(QPixmap.fromImage(image))
        self._canvas.resize(width, height)

    def _save(self) -> None:
        image = self._current_image()
        if image is None:
            QMessageBox.warning(self, "地图拼图工具", "请先导入至少一张图片。")
            return
        if not self._route and self._goal is None:
            QMessageBox.warning(self, "地图拼图工具", "请设置终点或绘制折线。")
            return
        record = apply_editor_payload(
            self._record,
            {
                "name": self._name_edit.text(),
                "image_bgr": image,
                "route": self._route,
                "goal": self._goal,
                "walkability": self._walkability,
                "painted_cells": sorted(self._painted_cells),
            },
        )
        self._record = record
        self.saved_option = format_map_option(record.map_id, record.name)
        self.accept()


def open_stitcher_dialog(parent, map_id: str | None) -> str | None:
    if not _QT_AVAILABLE:
        raise ImportError("地图拼图工具需要 PySide6")
    record = load_map(map_id) if map_id else None
    app = QApplication.instance()
    if not isinstance(app, QApplication):
        return None
    dialog_parent = parent if isinstance(parent, QWidget) else None
    dialog = MapStitcherDialog(dialog_parent, record)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.saved_option
