from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

_QT_AVAILABLE = True
try:
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import (
        QApplication,
        QButtonGroup,
        QDialog,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMessageBox,
        QPushButton,
        QToolButton,
        QVBoxLayout,
        QWidget,
    )
except ImportError:
    _QT_AVAILABLE = False

    class _Unavailable:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("小地图制图器需要 PySide6")

        @staticmethod
        def instance():
            return None

    QApplication = QDialog = QWidget = QPushButton = QToolButton = _Unavailable
    QHBoxLayout = QVBoxLayout = QLabel = QLineEdit = QMessageBox = _Unavailable
    QButtonGroup = QTimer = Qt = _Unavailable

from app_core.maps.cartography.crop import can_capture_minimap, crop_minimap
from app_core.maps.cartography.export_record import export_to_map_record
from app_core.maps.cartography.register import CartographyState, append_frame, start_session
from app_core.maps.cartography.session import (
    AnnotationState,
    SessionData,
    load_session,
    save_session,
)
from app_core.maps.record import (
    CELL_BLOCKED,
    CELL_WALKABLE,
    MapRecord,
    format_map_option,
    load_map,
    maps_root,
)
from ui.maps.cartographer.canvas import MapCanvas

_CAPTURE_INTERVAL_MS = 500


class CartographerDialog(QDialog):
    def __init__(
        self,
        parent=None,
        *,
        record: MapRecord | None = None,
        minimap_rect: tuple[int, int, int, int] = (0, 0, 0, 0),
        target_hwnd=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("小地图制图器")
        self.resize(1100, 720)
        self.setMinimumSize(800, 560)

        self._record = record
        self._minimap_rect = tuple(int(v) for v in minimap_rect)
        self._target_hwnd = target_hwnd
        self._state = CartographyState()
        self._annotations = AnnotationState(
            name=record.name if record is not None else "未命名地图"
        )
        self._mode = "goal"
        self._dirty = False
        self.saved_option: str | None = None

        self._name_edit = QLineEdit(self._annotations.name)
        self._status = QLabel("")
        self._capture_btn = QPushButton("开始采集")
        self._snap_btn = QPushButton("截一帧")
        self._clear_btn = QPushButton("清除标注")
        self._save_btn = QPushButton("保存")
        self._done_btn = QPushButton("完成")
        self._capture_btn.setCheckable(True)

        self._mode_group = QButtonGroup(self)
        self._mode_goal = QToolButton()
        self._mode_route = QToolButton()
        self._mode_paint = QToolButton()
        for button, text, mode in (
            (self._mode_goal, "终点", "goal"),
            (self._mode_route, "线路", "route"),
            (self._mode_paint, "涂墙", "paint"),
        ):
            button.setText(text)
            button.setCheckable(True)
            button.setProperty("mode", mode)
            self._mode_group.addButton(button)
        self._mode_goal.setChecked(True)
        self._mode_group.buttonClicked.connect(self._on_mode_button)

        self._timer = QTimer(self)
        self._timer.setInterval(_CAPTURE_INTERVAL_MS)
        self._timer.timeout.connect(self._capture_once)

        self._canvas = MapCanvas(self._on_canvas_click, self)
        self._canvas.set_empty_text(
            "1. 绑定窗口并框选小地图区域\n2. 点「开始采集」后在游戏中移动\n3. 标终点或线路后保存"
        )

        self._capture_btn.clicked.connect(self._toggle_capture)
        self._snap_btn.clicked.connect(self._capture_once)
        self._clear_btn.clicked.connect(self._clear_annotations)
        self._save_btn.clicked.connect(lambda: self._persist(close=False))
        self._done_btn.clicked.connect(lambda: self._persist(close=True))
        self._name_edit.textChanged.connect(self._on_name_changed)

        top = QHBoxLayout()
        top.addWidget(QLabel("名称"))
        top.addWidget(self._name_edit, 1)
        top.addWidget(self._capture_btn)
        top.addWidget(self._snap_btn)
        top.addWidget(self._mode_goal)
        top.addWidget(self._mode_route)
        top.addWidget(self._mode_paint)
        top.addWidget(self._clear_btn)
        top.addWidget(self._save_btn)
        top.addWidget(self._done_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        layout.addLayout(top)
        layout.addWidget(self._canvas, 1)
        layout.addWidget(self._status)

        self._apply_theme_styles()
        self._load_initial(record)
        self._refresh_capture_enabled()
        self._refresh_view()

    def _apply_theme_styles(self) -> None:
        try:
            from themes.theme_manager import theme_color

            background = theme_color("background", "#1e1e1e")
            surface = theme_color("surface", "#2a2a2a")
            text = theme_color("text", "#e8e8e8")
            secondary = theme_color("text_secondary", "#aaaaaa")
            border = theme_color("border", "#444444")
            accent = theme_color("accent", "#3d7eff")
            hover = theme_color("hover", "#333333")
        except Exception:
            background, surface, text = "#1e1e1e", "#2a2a2a", "#e8e8e8"
            secondary, border, accent, hover = "#aaaaaa", "#444444", "#3d7eff", "#333333"

        self._canvas.set_theme_colors(background, secondary)
        self.setStyleSheet(
            f"""
            QDialog {{ background-color: {background}; color: {text}; }}
            QLabel {{ color: {text}; }}
            QLineEdit {{
                background-color: {surface};
                color: {text};
                border: 1px solid {border};
                border-radius: 4px;
                padding: 4px 8px;
                min-height: 26px;
            }}
            QPushButton, QToolButton {{
                background-color: {surface};
                color: {text};
                border: 1px solid {border};
                border-radius: 4px;
                padding: 6px 12px;
                min-height: 28px;
            }}
            QPushButton:hover, QToolButton:hover {{ background-color: {hover}; }}
            QPushButton:checked, QToolButton:checked {{
                background-color: {accent};
                color: #ffffff;
                border-color: {accent};
            }}
            QPushButton:disabled, QToolButton:disabled {{
                color: {secondary};
                background-color: {background};
            }}
            """
        )

    def _load_initial(self, record: MapRecord | None) -> None:
        if record is None:
            return
        root = maps_root() / record.map_id
        session = load_session(root)
        if session is not None:
            self._state = session.state
            self._annotations = session.annotations
            self._name_edit.setText(self._annotations.name)
            if session.minimap_rect != (0, 0, 0, 0):
                self._minimap_rect = session.minimap_rect
            return
        # Fall back to existing map image as mosaic base (no frame history).
        self._state = start_session(record.image_bgr)
        self._annotations = AnnotationState(
            name=record.name,
            route=list(record.route),
            goal=record.goal,
            painted_cells=[
                (int(x), int(y))
                for y, x in zip(*np.nonzero(record.painted_blocked))
            ],
        )
        self._name_edit.setText(self._annotations.name)

    def _on_name_changed(self, text: str) -> None:
        self._annotations.name = text.strip() or "未命名地图"
        self._dirty = True

    def _on_mode_button(self, button) -> None:
        self._mode = str(button.property("mode") or "goal")

    def _refresh_capture_enabled(self) -> None:
        reason = can_capture_minimap(
            hwnd=self._target_hwnd,
            minimap_x=self._minimap_rect[0],
            minimap_y=self._minimap_rect[1],
            minimap_width=self._minimap_rect[2],
            minimap_height=self._minimap_rect[3],
        )
        enabled = reason is None
        self._capture_btn.setEnabled(enabled)
        self._snap_btn.setEnabled(enabled)
        if reason:
            self._status.setText(reason)
        elif not self._status.text():
            self._status.setText("就绪：开始采集或截一帧")

    def _toggle_capture(self, checked: bool) -> None:
        if checked:
            self._capture_btn.setText("停止采集")
            self._timer.start()
            self._status.setText("采集中…请在游戏中缓慢移动，保持小地图重叠")
            self._capture_once()
        else:
            self._timer.stop()
            self._capture_btn.setText("开始采集")
            self._status.setText("已停止采集")

    def _capture_once(self) -> None:
        reason = can_capture_minimap(
            hwnd=self._target_hwnd,
            minimap_x=self._minimap_rect[0],
            minimap_y=self._minimap_rect[1],
            minimap_width=self._minimap_rect[2],
            minimap_height=self._minimap_rect[3],
        )
        if reason:
            self._status.setText(reason)
            self._timer.stop()
            self._capture_btn.setChecked(False)
            self._capture_btn.setText("开始采集")
            return
        from tasks.task_utils import capture_window_smart

        frame = capture_window_smart(self._target_hwnd)
        tile = crop_minimap(
            frame,
            x=self._minimap_rect[0],
            y=self._minimap_rect[1],
            width=self._minimap_rect[2],
            height=self._minimap_rect[3],
        )
        if tile is None:
            self._status.setText("截取失败：小地图区域无效")
            return
        if self._state.mosaic is None:
            self._state = start_session(tile)
            ok = True
        else:
            ok = append_frame(self._state, tile)
        if not ok:
            self._status.setText(self._state.last_error or "配准失败")
            return
        self._dirty = True
        self._status.setText(f"已收录 {len(self._state.frames)} 帧 · 画布 {self._state.mosaic.shape[1]}×{self._state.mosaic.shape[0]}")
        self._refresh_view()

    def _clear_annotations(self) -> None:
        self._annotations.route.clear()
        self._annotations.goal = None
        self._annotations.painted_cells.clear()
        self._dirty = True
        self._refresh_view()

    def _on_canvas_click(self, x: int, y: int) -> None:
        if self._mode == "goal":
            self._annotations.goal = (x, y)
            self._annotations.route.clear()
        elif self._mode == "route":
            self._annotations.route.append((x, y))
            self._annotations.goal = None
        else:
            cell = (x, y)
            if cell in self._annotations.painted_cells:
                self._annotations.painted_cells.remove(cell)
            else:
                self._annotations.painted_cells.append(cell)
        self._dirty = True
        self._refresh_view()

    def _display_image(self) -> np.ndarray | None:
        if self._state.mosaic is None:
            return None
        display = self._state.mosaic.copy()
        if self._record is not None and self._record.walkability.shape[:2] == display.shape[:2]:
            overlay = display.copy()
            overlay[self._record.walkability == CELL_WALKABLE] = (60, 180, 60)
            overlay[self._record.walkability == CELL_BLOCKED] = (40, 40, 220)
            known = self._record.walkability != 0
            display[known] = cv2.addWeighted(display, 0.55, overlay, 0.45, 0)[known]
        for x, y in self._annotations.painted_cells:
            if 0 <= y < display.shape[0] and 0 <= x < display.shape[1]:
                display[y, x] = (40, 40, 255)
        if len(self._annotations.route) > 1:
            cv2.polylines(
                display,
                [np.asarray(self._annotations.route, dtype=np.int32)],
                False,
                (0, 220, 255),
                2,
            )
        for point in self._annotations.route:
            cv2.circle(display, point, 3, (0, 220, 255), -1)
        if self._annotations.goal is not None:
            cv2.drawMarker(display, self._annotations.goal, (0, 255, 255), cv2.MARKER_CROSS, 14, 2)
        return display

    def _refresh_view(self) -> None:
        self._canvas.set_image(self._display_image())

    def _persist(self, *, close: bool) -> None:
        if self._state.mosaic is None:
            QMessageBox.warning(self, "小地图制图器", "请先采集至少一帧小地图。")
            return
        if not self._annotations.route and self._annotations.goal is None:
            QMessageBox.warning(self, "小地图制图器", "请设置终点或绘制线路。")
            return
        self._annotations.name = self._name_edit.text().strip() or "未命名地图"
        root_base = maps_root()
        record = export_to_map_record(
            self._state.mosaic,
            self._annotations,
            existing=self._record,
            root=root_base,
        )
        save_session(
            root_base / record.map_id,
            SessionData(
                state=self._state,
                annotations=self._annotations,
                minimap_rect=self._minimap_rect,
            ),
        )
        self._record = record
        self._dirty = False
        self.saved_option = format_map_option(record.map_id, record.name)
        self._status.setText(f"已保存：{self.saved_option}")
        if close:
            self._timer.stop()
            self.accept()


def open_cartographer_dialog(
    parent,
    map_id: str | None,
    *,
    minimap_rect: tuple[int, int, int, int],
    target_hwnd,
) -> str | None:
    if not _QT_AVAILABLE:
        raise ImportError("小地图制图器需要 PySide6")
    record = None
    if map_id:
        try:
            record = load_map(map_id)
        except Exception:
            record = None
    app = QApplication.instance()
    if not isinstance(app, QApplication):
        return None
    dialog_parent = parent if isinstance(parent, QWidget) else None
    dialog = CartographerDialog(
        dialog_parent,
        record=record,
        minimap_rect=minimap_rect,
        target_hwnd=target_hwnd,
    )
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.saved_option
