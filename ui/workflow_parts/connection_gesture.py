"""拖线状态机。临时图元只由本次手势持有，所有出口统一销毁。"""
from enum import Enum, auto

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QGraphicsPathItem, QGraphicsView
from shiboken6 import delete, isValid

from themes import get_theme_manager, theme_color
from .connection_geometry import EdgeRequest, LINE_TYPES
from .connection_line import painter_path_from_points, set_line_animation_paused
from .connection_tracks import OrthogonalRouter


class GestureState(Enum):
    IDLE = auto()
    CONNECTING = auto()
    SNAPPED = auto()


class _PreviewLine(QGraphicsPathItem):
    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        super().paint(painter, option, widget)


class ConnectionGesture:
    def __init__(self, view):
        self.view = view
        self.state = GestureState.IDLE
        self.source = self.target = self.preview = None
        self.kind = None
        self.theme_registered = False
        self.router = OrthogonalRouter()
        view.destroyed.connect(self.dispose)

    @property
    def active(self):
        return self.state is not GestureState.IDLE

    def begin(self, card, kind):
        view = self.view
        if self.active or not view.editing_enabled or view._block_edit_if_running("拖拽连线"):
            return False
        if kind not in LINE_TYPES or view.cards.get(card.card_id) is not card or card.scene() is not view.scene:
            return False
        if kind in ("success", "failure") and card.restricted_outputs:
            return False
        if (kind == "random") != (card.restricted_outputs == "random_only"):
            return False
        view._sync_connections_with_scene()
        self.source, self.kind = card, kind
        self.state = GestureState.CONNECTING
        try:
            self.preview = _PreviewLine()
            self.preview.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self.preview.setZValue(6)
            view.scene.addItem(self.preview)
            get_theme_manager().register_theme_change_callback(self.theme_changed)
            self.theme_registered = True
            view.setDragMode(QGraphicsView.DragMode.NoDrag)
            view.set_canvas_drag_paused(True)
            self.move(card.get_output_port_scene_pos(kind) + QPointF(24, 0))
        except Exception:
            self.cancel()
            raise
        return True

    def theme_changed(self, _theme):
        if self.preview is not None:
            pen = QPen(QColor(theme_color("connection_" + self.kind if self.target else "connection_preview")), 2.0)
            pen.setStyle(Qt.PenStyle.DashLine)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            self.preview.setPen(pen)

    def move(self, position):
        try:
            return self._update(position)
        except Exception:
            self.cancel()
            raise

    def _update(self, position):
        if not self.active:
            return False
        view = self.view
        if view.cards.get(self.source.card_id) is not self.source:
            self.cancel()
            return False
        nearest, minimum = None, 15.0 ** 2
        kind = "sequential" if self.kind == "random" else self.kind
        for card in view.cards.values():
            if card is self.source or card.no_input_ports:
                continue
            if view._validate_special_connection_rule(self.source, card, self.kind):
                continue
            point = card.get_input_port_scene_pos(kind)
            distance = (point.x() - position.x()) ** 2 + (point.y() - position.y()) ** 2
            if distance <= minimum:
                nearest, minimum = card, distance
        self.target = nearest
        self.state = GestureState.SNAPPED if nearest is not None else GestureState.CONNECTING
        end = nearest.get_input_port_scene_pos(kind) if nearest is not None else position
        start = self.source.get_output_port_scene_pos(self.kind)
        target_bounds = view._connection_controller.bounds(nearest) if nearest is not None else (end.x(), end.y() - 15, 0, 30)
        request = EdgeRequest((self.source.card_id, nearest.card_id if nearest else -1, self.kind),
                              (start.x(), start.y()), (end.x(), end.y()),
                              view._connection_controller.bounds(self.source), target_bounds)
        route = self.router.plan([request])[request.key]
        self.preview.setPath(painter_path_from_points(route.points))
        self.theme_changed(None)
        return nearest is not None

    def finish(self, position):
        if not self.active:
            return False
        try:
            self.move(position)
            if self.target is None:
                return False
            line = self.view.add_connection(self.source, self.target, self.kind)
            if line is not None:
                self.view.update_card_sequence_display()
            return line is not None
        finally:
            self.cancel()

    def cancel(self):
        if not self.active:
            return
        if self.theme_registered:
            get_theme_manager().unregister_theme_change_callback(self.theme_changed)
            self.theme_registered = False
        if self.source is not None and isValid(self.source):
            scene = self.source.scene()
            if scene is not None and scene.mouseGrabberItem() is self.source:
                self.source.ungrabMouse()
        if self.preview is not None and isValid(self.preview):
            scene = self.preview.scene()
            if scene is not None:
                scene.removeItem(self.preview)
            delete(self.preview)
        self.preview = self.source = self.target = None
        self.kind = None
        self.state = GestureState.IDLE
        if isValid(self.view):
            try:
                self.view.setDragMode(self.view._original_drag_mode)
            finally:
                self.view.set_canvas_drag_paused(False)
        elif self.view._canvas_connections_paused:
            self.view._canvas_connections_paused = False
            set_line_animation_paused("canvas_drag", False)

    def dispose(self):
        view = self.view
        self.cancel()
        if view is not None and view._canvas_connections_paused:
            view._canvas_connections_paused = False
            set_line_animation_paused("canvas_drag", False)
        self.view = None
