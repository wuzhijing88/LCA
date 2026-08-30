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
        QButtonGroup,
        QDialog,
        QFrame,
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
    QButtonGroup = QDialog = QFrame = QHBoxLayout = _UnavailableWidget
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
from tasks.task_utils import capture_window_smart
from themes import get_theme_manager, theme_color
from ui.maps.editor_payload import apply_editor_payload
from ui.maps.stitcher_capture import can_capture_minimap, crop_minimap


class _MapCanvas(QLabel):
    def __init__(self, on_click: Callable[[int, int], None], parent=None):
        super().__init__(parent)
        self._on_click = on_click
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.setObjectName("stitcherCanvas")
        self.setText("① 截取小地图\n② 标注终点或线路\n③ 保存进度")

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.pixmap() is not None:
            point = event.position()
            self._on_click(int(point.x()), int(point.y()))
            return
        super().mousePressEvent(event)


class MapStitcherDialog(QDialog):
    def __init__(
        self,
        parent=None,
        record: MapRecord | None = None,
        *,
        minimap_rect: tuple[int, int, int, int] = (0, 0, 0, 0),
        target_hwnd=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("地图拼图工具")
        self.resize(900, 680)
        self.setMinimumSize(640, 480)
        self._minimap_rect = minimap_rect
        self._target_hwnd = target_hwnd
        self._record = record
        self._tiles: list[np.ndarray] = []
        self._origins: list[tuple[int, int]] = []
        self._route: list[tuple[int, int]] = []
        self._goal: tuple[int, int] | None = None
        self._painted_cells: set[tuple[int, int]] = set()
        self._walkability: np.ndarray | None = None
        self.saved_option: str | None = None
        self._active_mode = "goal"

        self._name_edit = QLineEdit(record.name if record is not None else "未命名地图")
        self._name_edit.setObjectName("stitcherNameEdit")
        self._name_edit.setPlaceholderText("地图名称")
        self._origin_x_spin = QSpinBox()
        self._origin_y_spin = QSpinBox()
        for spin in (self._origin_x_spin, self._origin_y_spin):
            spin.setRange(-1_000_000, 1_000_000)
            spin.setEnabled(False)
            spin.valueChanged.connect(self._on_origin_changed)

        self._capture_button = QPushButton("截取小地图")
        self._capture_button.setObjectName("stitcherCaptureButton")
        self._capture_button.setProperty("primary", True)
        self._capture_button.clicked.connect(self._capture_minimap)

        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        self._mode_buttons: dict[str, QPushButton] = {}
        for text, mode in (("终点", "goal"), ("线路", "route"), ("涂墙", "paint")):
            button = QPushButton(text)
            button.setObjectName("stitcherModeButton")
            button.setCheckable(True)
            button.clicked.connect(
                lambda _checked=False, selected_mode=mode: self._set_mode(selected_mode)
            )
            self._mode_group.addButton(button)
            self._mode_buttons[mode] = button
        self._mode_buttons["goal"].setChecked(True)

        clear_route_button = QPushButton("清除标注")
        clear_route_button.clicked.connect(self._clear_annotations)

        save_progress_button = QPushButton("保存进度")
        save_progress_button.setObjectName("stitcherSaveButton")
        save_progress_button.setProperty("primary", True)
        save_progress_button.clicked.connect(self._save_progress)
        complete_button = QPushButton("完成")
        complete_button.setObjectName("stitcherCompleteButton")
        complete_button.setProperty("primary", True)
        complete_button.clicked.connect(self._complete)

        toolbar_frame = QFrame()
        toolbar_frame.setObjectName("stitcherToolbar")
        toolbar_layout = QVBoxLayout(toolbar_frame)
        toolbar_layout.setContentsMargins(10, 10, 10, 10)
        toolbar_layout.setSpacing(8)

        primary_row = QHBoxLayout()
        primary_row.setSpacing(6)
        primary_row.addWidget(QLabel("名称"))
        primary_row.addWidget(self._name_edit, 1)
        primary_row.addWidget(self._capture_button)
        primary_row.addWidget(save_progress_button)
        primary_row.addWidget(complete_button)
        toolbar_layout.addLayout(primary_row)

        edit_row = QHBoxLayout()
        edit_row.setSpacing(6)
        edit_row.addWidget(QLabel("标注"))
        for mode in ("goal", "route", "paint"):
            edit_row.addWidget(self._mode_buttons[mode])
        edit_row.addSpacing(8)
        edit_row.addWidget(QLabel("末图 X"))
        edit_row.addWidget(self._origin_x_spin)
        edit_row.addWidget(QLabel("Y"))
        edit_row.addWidget(self._origin_y_spin)
        edit_row.addStretch(1)
        edit_row.addWidget(clear_route_button)
        toolbar_layout.addLayout(edit_row)

        self._canvas = _MapCanvas(self._on_canvas_click)
        scroll = QScrollArea()
        scroll.setObjectName("stitcherScrollArea")
        scroll.setWidgetResizable(False)
        scroll.setWidget(self._canvas)

        self._status_label = QLabel()
        self._status_label.setObjectName("stitcherStatusLabel")
        self._status_label.setText("折线末端即终点；墙体点击可切换。")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(toolbar_frame)
        layout.addWidget(scroll, 1)
        layout.addWidget(self._status_label)

        if record is not None:
            self._tiles = [record.image_bgr.copy()]
            self._origins = [(0, 0)]
            self._route = list(record.route)
            self._goal = record.goal
            self._walkability = record.walkability.copy()
            ys, xs = np.nonzero(record.painted_blocked)
            self._painted_cells = {(int(x), int(y)) for y, x in zip(ys, xs)}
        self._apply_theme_styles()
        self._update_capture_availability()
        self._sync_origin_controls()
        self._refresh_canvas()

    def _current_image(self) -> np.ndarray | None:
        if not self._tiles:
            return None
        image = stitch_by_origins(self._tiles, self._origins)
        return image if image.size else None

    def _set_mode(self, mode: str) -> None:
        if mode not in self._mode_buttons:
            return
        self._active_mode = mode
        self._mode_buttons[mode].setChecked(True)

    def _capture_gate_reason(self) -> str | None:
        x, y, width, height = self._minimap_rect
        return can_capture_minimap(
            hwnd=self._target_hwnd,
            minimap_x=x,
            minimap_y=y,
            minimap_width=width,
            minimap_height=height,
        )

    def _update_capture_availability(self) -> None:
        reason = self._capture_gate_reason()
        self._capture_button.setEnabled(reason is None)
        self._capture_button.setToolTip(reason or "截取绑定窗口中的小地图区域")
        if reason:
            self._status_label.setText(reason)

    def _capture_minimap(self) -> None:
        reason = self._capture_gate_reason()
        if reason:
            self._status_label.setText(reason)
            return
        try:
            frame = capture_window_smart(self._target_hwnd)
        except Exception as exc:
            self._status_label.setText(f"截取小地图失败：{exc}")
            return
        if frame is None or frame.size == 0:
            self._status_label.setText("截取小地图失败：未获取到窗口画面")
            return
        x, y, width, height = self._minimap_rect
        tile = crop_minimap(frame, x=x, y=y, width=width, height=height)
        if tile is None:
            self._status_label.setText("截取小地图失败：裁切区域为空")
            return
        if tile.ndim == 3 and tile.shape[2] == 4:
            tile = cv2.cvtColor(tile, cv2.COLOR_BGRA2BGR)

        canvas = self._current_image()
        origin = (0, 0) if canvas is None else next_tile_origin(canvas, tile)
        self._tiles.append(tile)
        self._origins.append(origin)
        self._normalize_origins()
        self._sync_origin_controls()
        self._refresh_canvas()
        self._status_label.setText(f"已截取第 {len(self._tiles)} 张小地图")

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
        mode = self._active_mode
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
            self._canvas.setText("① 截取小地图\n② 标注终点或线路\n③ 保存进度")
            self._canvas.setMinimumSize(560, 360)
            self._canvas.adjustSize()
            return
        self._canvas.setMinimumSize(0, 0)
        rgb = cv2.cvtColor(display, cv2.COLOR_BGR2RGB)
        height, width = rgb.shape[:2]
        image = QImage(rgb.data, width, height, width * 3, QImage.Format.Format_RGB888).copy()
        self._canvas.setPixmap(QPixmap.fromImage(image))
        self._canvas.resize(width, height)

    def _save_progress(self) -> bool:
        image = self._current_image()
        if image is None:
            QMessageBox.warning(self, "地图拼图工具", "请先截取至少一张小地图。")
            return False
        if not self._route and self._goal is None:
            QMessageBox.warning(self, "地图拼图工具", "请设置终点或绘制折线。")
            return False
        try:
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
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "保存进度失败", str(exc))
            return False
        self._record = record
        self.saved_option = format_map_option(record.map_id, record.name)
        self._status_label.setText(f"已保存：{record.name}")
        return True

    def _complete(self) -> None:
        if not self._save_progress():
            return
        self.accept()

    def _apply_theme_styles(self) -> None:
        try:
            manager = get_theme_manager()
            colors = {
                key: manager.get_color(key)
                for key in (
                    "background",
                    "surface",
                    "card",
                    "canvas",
                    "text",
                    "text_secondary",
                    "border",
                    "accent",
                    "accent_hover",
                    "accent_pressed",
                    "accent_text",
                    "hover",
                    "pressed",
                    "text_disabled",
                )
            }
        except Exception:
            colors = {
                "background": theme_color("background", "#202124"),
                "surface": theme_color("surface", "#292a2d"),
                "card": theme_color("card", "#303134"),
                "canvas": theme_color("canvas", "#171717"),
                "text": theme_color("text", "#f1f3f4"),
                "text_secondary": theme_color("text_secondary", "#bdc1c6"),
                "border": theme_color("border", "#5f6368"),
                "accent": theme_color("accent", "#4c8bf5"),
                "accent_hover": theme_color("accent_hover", "#5b96f7"),
                "accent_pressed": theme_color("accent_pressed", "#3976d3"),
                "accent_text": theme_color("accent_text", "#ffffff"),
                "hover": theme_color("hover", "#3c4043"),
                "pressed": theme_color("pressed", "#4a4d51"),
                "text_disabled": theme_color("text_disabled", "#80868b"),
            }

        self.setStyleSheet(
            f"""
            QDialog {{
                background-color: {colors["background"]};
                color: {colors["text"]};
            }}
            QFrame#stitcherToolbar {{
                background-color: {colors["surface"]};
                border: 1px solid {colors["border"]};
                border-radius: 8px;
            }}
            QLabel {{
                color: {colors["text"]};
            }}
            QLabel#stitcherStatusLabel {{
                color: {colors["text_secondary"]};
            }}
            QLineEdit, QSpinBox {{
                background-color: {colors["card"]};
                color: {colors["text"]};
                border: 1px solid {colors["border"]};
                border-radius: 4px;
                padding: 4px 6px;
                min-height: 24px;
            }}
            QPushButton {{
                background-color: {colors["card"]};
                color: {colors["text"]};
                border: 1px solid {colors["border"]};
                border-radius: 5px;
                padding: 6px 12px;
                min-height: 24px;
            }}
            QPushButton:hover {{
                background-color: {colors["hover"]};
            }}
            QPushButton:pressed, QPushButton#stitcherModeButton:checked {{
                background-color: {colors["pressed"]};
                border-color: {colors["accent"]};
            }}
            QPushButton[primary="true"] {{
                background-color: {colors["accent"]};
                color: {colors["accent_text"]};
                border-color: {colors["accent"]};
            }}
            QPushButton[primary="true"]:hover {{
                background-color: {colors["accent_hover"]};
                border-color: {colors["accent_hover"]};
            }}
            QPushButton[primary="true"]:pressed {{
                background-color: {colors["accent_pressed"]};
                border-color: {colors["accent_pressed"]};
            }}
            QPushButton:disabled {{
                background-color: {colors["canvas"]};
                color: {colors["text_disabled"]};
                border-color: {colors["border"]};
            }}
            QScrollArea#stitcherScrollArea {{
                background-color: {colors["canvas"]};
                border: 1px solid {colors["border"]};
                border-radius: 8px;
            }}
            QLabel#stitcherCanvas {{
                background-color: {colors["canvas"]};
                color: {colors["text_secondary"]};
                padding: 24px;
            }}
            """
        )


def open_stitcher_dialog(
    parent,
    map_id: str | None,
    *,
    minimap_rect: tuple[int, int, int, int],
    target_hwnd,
) -> str | None:
    if not _QT_AVAILABLE:
        raise ImportError("地图拼图工具需要 PySide6")
    record = load_map(map_id) if map_id else None
    app = QApplication.instance()
    if not isinstance(app, QApplication):
        return None
    dialog_parent = parent if isinstance(parent, QWidget) else None
    dialog = MapStitcherDialog(
        dialog_parent,
        record,
        minimap_rect=minimap_rect,
        target_hwnd=target_hwnd,
    )
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.saved_option
