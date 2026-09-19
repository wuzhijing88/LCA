import math
import threading
import time
import weakref
from enum import Enum
from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QPainterPath, QPainterPathStroker, QPen
from PySide6.QtWidgets import QApplication, QGraphicsItem, QGraphicsPathItem
from shiboken6 import isValid as _is_valid_qt_object

from ..workflow_parts.connection_router import _coincident_port_path
from ..workflow_parts.task_card import PORT_TYPE_RANDOM, PORT_TYPE_SEQUENTIAL


_VALID_LINE_TYPES = frozenset(("sequential", "success", "failure", "random"))
_DASH_PATTERN = (12.0, 8.0)
_DASH_UNITS_PER_SECOND = 20.0
_ANIMATION_INTERVAL_MS = 50
_OVERVIEW_ZOOM_THRESHOLD = 0.45
_LINE_ANIMATION_VIEWPORT_MARGIN = 40.0
_CORNER_FILLET = 8.0
_CORNER_FILLET_MIN_SEGMENT = _CORNER_FILLET * 2.0
_POINT_EPS = 1e-9

_animation_timer = None
_animated_lines = weakref.WeakSet()
_animated_lines_lock = threading.Lock()
_animation_pause_reasons = set()
_animation_pause_counts = {}
_animation_pause_lock = threading.Lock()
_dash_phase = 0.0
_last_animation_tick_s = None
_overview_mode_enabled = False
_force_overview_mode = False
_last_zoom_level = 1.0


def _snapshot_registered_lines():
    with _animated_lines_lock:
        return list(_animated_lines)


def _view_visible_scene_rect(view, viewport_rect_cache=None):
    if viewport_rect_cache is not None and view in viewport_rect_cache:
        return viewport_rect_cache[view]
    visible = None
    viewport = view.viewport()
    if viewport is not None and viewport.isVisible() and not viewport.rect().isEmpty():
        visible = view.mapToScene(viewport.rect()).boundingRect()
    if viewport_rect_cache is not None:
        viewport_rect_cache[view] = visible
    return visible


def _line_is_animatable(line, viewport_rect_cache=None) -> bool:
    if line is None or not _is_valid_qt_object(line) or not line.isVisible():
        return False
    scene = line.scene()
    if scene is None:
        return False
    try:
        line_rect = line.sceneBoundingRect()
    except RuntimeError:
        return False
    if line_rect.isEmpty():
        return False
    for view in scene.views():
        if not _is_valid_qt_object(view) or not view.isVisible():
            continue
        visible = _view_visible_scene_rect(view, viewport_rect_cache)
        if visible is None:
            continue
        anim_rect = visible.adjusted(
            -_LINE_ANIMATION_VIEWPORT_MARGIN,
            -_LINE_ANIMATION_VIEWPORT_MARGIN,
            _LINE_ANIMATION_VIEWPORT_MARGIN,
            _LINE_ANIMATION_VIEWPORT_MARGIN,
        )
        if line_rect.intersects(anim_rect):
            return True
    return False


def _has_animatable_lines() -> bool:
    viewport_rect_cache = {}
    return any(_line_is_animatable(line, viewport_rect_cache) for line in _snapshot_registered_lines())


def _is_animation_paused() -> bool:
    with _animation_pause_lock:
        return bool(_animation_pause_reasons)


def _get_animation_timer(*, create: bool):
    global _animation_timer
    if _animation_timer is not None and not _is_valid_qt_object(_animation_timer):
        _animation_timer = None
    if _animation_timer is None and create:
        app = QApplication.instance()
        if app is None:
            raise RuntimeError("创建连线动画计时器前必须先创建 QApplication")
        timer = QTimer(app)
        timer.setTimerType(Qt.TimerType.PreciseTimer)
        timer.timeout.connect(animate_all_lines)
        _animation_timer = timer
    return _animation_timer


def refresh_line_animation_state() -> None:
    """根据当前可见连线启动或停止唯一的动画计时器。"""
    global _last_animation_tick_s
    should_run = (
        not _is_animation_paused()
        and not _force_overview_mode
        and not _overview_mode_enabled
        and _has_animatable_lines()
    )
    timer = _get_animation_timer(create=should_run)
    if timer is None:
        return
    if should_run:
        if not timer.isActive():
            _last_animation_tick_s = None
            timer.start(_ANIMATION_INTERVAL_MS)
    elif timer.isActive():
        timer.stop()
        _last_animation_tick_s = None


def _register_animated_line(line) -> None:
    if not isinstance(line, ConnectionLine):
        raise TypeError("动画注册对象必须是 ConnectionLine")
    if line.scene() is None:
        raise ValueError("未挂载到场景的连线不能注册动画")
    with _animated_lines_lock:
        _animated_lines.add(line)
    refresh_line_animation_state()


def _unregister_animated_line(line) -> None:
    if not isinstance(line, ConnectionLine):
        raise TypeError("动画注销对象必须是 ConnectionLine")
    with _animated_lines_lock:
        _animated_lines.discard(line)
    refresh_line_animation_state()


def _normalize_pause_reason(reason: str) -> str:
    if not isinstance(reason, str):
        raise TypeError("连线动画暂停原因必须是字符串")
    normalized = reason.strip()
    if not normalized:
        raise ValueError("连线动画暂停原因不能为空")
    return normalized


def set_line_animation_paused(reason: str, paused: bool) -> None:
    normalized_reason = _normalize_pause_reason(reason)
    with _animation_pause_lock:
        if paused:
            _animation_pause_counts[normalized_reason] = _animation_pause_counts.get(normalized_reason, 0) + 1
            _animation_pause_reasons.add(normalized_reason)
        else:
            remaining = _animation_pause_counts.get(normalized_reason, 0) - 1
            if remaining <= 0:
                _animation_pause_counts.pop(normalized_reason, None)
                _animation_pause_reasons.discard(normalized_reason)
            else:
                _animation_pause_counts[normalized_reason] = remaining
    refresh_line_animation_state()


def pause_line_animation(reason: str = "default") -> None:
    set_line_animation_paused(reason, True)


def resume_line_animation(reason: str = "default") -> None:
    set_line_animation_paused(reason, False)


def _repaint_registered_lines() -> None:
    viewport_rect_cache = {}
    for line in _snapshot_registered_lines():
        if _is_valid_qt_object(line) and _line_is_animatable(line, viewport_rect_cache):
            line.update()


def update_zoom_level(zoom_level: float) -> None:
    global _last_zoom_level, _overview_mode_enabled
    normalized_zoom = float(zoom_level)
    if not math.isfinite(normalized_zoom) or normalized_zoom <= 0.0:
        raise ValueError("连线缩放比例必须是正有限数")
    _last_zoom_level = normalized_zoom
    overview_enabled = normalized_zoom < _OVERVIEW_ZOOM_THRESHOLD
    if overview_enabled == _overview_mode_enabled:
        return
    _overview_mode_enabled = overview_enabled
    refresh_line_animation_state()
    _repaint_registered_lines()


def set_force_overview_mode(enabled: bool) -> None:
    global _force_overview_mode
    normalized_enabled = bool(enabled)
    if normalized_enabled == _force_overview_mode:
        return
    _force_overview_mode = normalized_enabled
    refresh_line_animation_state()
    _repaint_registered_lines()


def get_line_animation_stats():
    timer = _get_animation_timer(create=False)
    lines = _snapshot_registered_lines()
    with _animation_pause_lock:
        pause_reasons = sorted(_animation_pause_reasons)
        pause_counts = dict(_animation_pause_counts)
    return {
        "registered_lines": len(lines),
        "animatable_lines": sum(1 for line in lines if _line_is_animatable(line)),
        "paused": bool(pause_reasons),
        "pause_reasons": pause_reasons,
        "pause_counts": pause_counts,
        "timer_active": bool(timer is not None and timer.isActive()),
        "interval_ms": _ANIMATION_INTERVAL_MS,
    }


def animate_all_lines() -> None:
    global _dash_phase, _last_animation_tick_s
    if _is_animation_paused() or _force_overview_mode or _overview_mode_enabled:
        refresh_line_animation_state()
        return

    lines = _snapshot_registered_lines()
    now_s = time.perf_counter()
    if _last_animation_tick_s is None:
        _last_animation_tick_s = now_s
        return
    elapsed_s = min(max(now_s - _last_animation_tick_s, 0.0), 0.25)
    _last_animation_tick_s = now_s
    if elapsed_s == 0.0:
        return

    _dash_phase = (_dash_phase + elapsed_s * _DASH_UNITS_PER_SECOND) % sum(_DASH_PATTERN)
    updated_count = 0
    stale_lines = []
    viewport_rect_cache = {}
    for line in lines:
        if not _is_valid_qt_object(line):
            stale_lines.append(line)
            continue
        if not _line_is_animatable(line, viewport_rect_cache) or line.path().isEmpty():
            continue
        line.dash_offset = _dash_phase
        line.update()
        updated_count += 1

    if stale_lines:
        with _animated_lines_lock:
            for line in stale_lines:
                _animated_lines.discard(line)
    if updated_count == 0:
        refresh_line_animation_state()


if TYPE_CHECKING:
    from ..workflow_parts.task_card import TaskCard


def _point_toward(origin: tuple[float, float], target: tuple[float, float], distance: float) -> tuple[float, float]:
    ox, oy = origin
    tx, ty = target
    if abs(oy - ty) < _POINT_EPS:
        direction = 1.0 if tx > ox else -1.0
        return (ox + direction * distance, oy)
    if abs(ox - tx) < _POINT_EPS:
        direction = 1.0 if ty > oy else -1.0
        return (ox, oy + direction * distance)
    raise ValueError("连线路径必须是水平或垂直折线")


def painter_path_from_points(points: list) -> QPainterPath:
    """把正交折线转成绘制路径；足够长的拐角用 8px 二次贝塞尔倒圆。"""
    if not isinstance(points, list) or len(points) < 2:
        raise ValueError("连线路径点不足")
    converted: list[tuple[float, float]] = []
    for raw in points:
        if not isinstance(raw, (tuple, list)) or len(raw) != 2:
            raise TypeError("连线路径点必须是 (x, y)")
        x = float(raw[0])
        y = float(raw[1])
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError("连线路径点必须是有限数字")
        if converted and abs(converted[-1][0] - x) < _POINT_EPS and abs(converted[-1][1] - y) < _POINT_EPS:
            continue
        converted.append((x, y))
    if len(converted) < 2:
        converted = _coincident_port_path(converted[0] if converted else (0.0, 0.0))
    path = QPainterPath(QPointF(converted[0][0], converted[0][1]))
    last_index = len(converted) - 1
    for index in range(1, last_index):
        prev = converted[index - 1]
        curr = converted[index]
        nxt = converted[index + 1]
        first_len = math.hypot(curr[0] - prev[0], curr[1] - prev[1])
        second_len = math.hypot(nxt[0] - curr[0], nxt[1] - curr[1])
        if first_len >= _CORNER_FILLET_MIN_SEGMENT and second_len >= _CORNER_FILLET_MIN_SEGMENT:
            start_fillet = _point_toward(curr, prev, _CORNER_FILLET)
            end_fillet = _point_toward(curr, nxt, _CORNER_FILLET)
            path.lineTo(QPointF(start_fillet[0], start_fillet[1]))
            path.quadTo(QPointF(curr[0], curr[1]), QPointF(end_fillet[0], end_fillet[1]))
        else:
            path.lineTo(QPointF(curr[0], curr[1]))
    path.lineTo(QPointF(converted[-1][0], converted[-1][1]))
    return path


class ConnectionType(Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    RANDOM = "random"


class ConnectionLine(QGraphicsPathItem):
    def __init__(self, start_item: "TaskCard", end_item: "TaskCard", line_type: str, parent=None):
        if start_item is None or end_item is None:
            raise ValueError("连线必须同时提供起点和终点")
        if line_type not in _VALID_LINE_TYPES:
            raise ValueError(f"不支持的连线类型: {line_type!r}")
        super().__init__(parent)
        self.start_item = start_item
        self.end_item = end_item
        self.line_type = line_type
        self.dash_offset = 0.0
        self._normal_width = 2.0
        self._hover_width = 4.0
        self._normal_color = self._color_for_line_type(line_type)
        self._shape_cache = QPainterPath()
        self._shape_cache_dirty = True

        self.pen = QPen(self._normal_color)
        self.pen.setWidthF(self._normal_width)
        self.pen.setStyle(Qt.PenStyle.DashLine)
        self.pen.setDashPattern(list(_DASH_PATTERN))
        self.pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        self.pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        self.pen.setCosmetic(False)
        self.setPen(self.pen)
        self._paint_pen = QPen(self.pen)
        self.setBrush(Qt.BrushStyle.NoBrush)
        self.setZValue(5)
        self.setCacheMode(QGraphicsPathItem.CacheMode.NoCache)
        self.setAcceptHoverEvents(True)
        self._route_points: list[tuple[float, float]] = []

    @staticmethod
    def _color_for_line_type(line_type: str) -> QColor:
        if line_type == ConnectionType.SUCCESS.value:
            return QColor(60, 160, 60)
        if line_type == ConnectionType.FAILURE.value:
            return QColor(210, 80, 80)
        if line_type == ConnectionType.RANDOM.value:
            return QColor(147, 51, 234)
        return QColor(60, 140, 210)

    def itemChange(self, change, value):
        result = super().itemChange(change, value)
        if change == QGraphicsItem.GraphicsItemChange.ItemSceneHasChanged:
            if value is None:
                _unregister_animated_line(self)
            else:
                _register_animated_line(self)
        return result

    def set_line_color(self):
        self._normal_color = self._color_for_line_type(self.line_type)
        self.pen.setColor(self._normal_color)
        self.setPen(self.pen)

    def get_start_pos(self) -> QPointF:
        if self.start_item is None or not _is_valid_qt_object(self.start_item):
            raise RuntimeError("连线起点已失效")
        return self.start_item.get_output_port_scene_pos(self.line_type)

    def get_end_pos(self) -> QPointF:
        if self.end_item is None or not _is_valid_qt_object(self.end_item):
            raise RuntimeError("连线终点已失效")
        input_type = PORT_TYPE_SEQUENTIAL if self.line_type == PORT_TYPE_RANDOM else self.line_type
        return self.end_item.get_input_port_scene_pos(input_type)

    def _set_path(self, path: QPainterPath) -> None:
        self.setPath(path)
        self._shape_cache_dirty = True

    def clear_path(self) -> None:
        self._route_points = []
        self._set_path(QPainterPath())

    def route_points(self) -> list[tuple[float, float]]:
        return list(self._route_points)

    def apply_route_points(self, points: list) -> bool:
        if not isinstance(points, list) or len(points) < 2:
            raise ValueError("连线路由点不足")
        scene_points: list[tuple[float, float]] = []
        for raw in points:
            if not isinstance(raw, (tuple, list)) or len(raw) != 2:
                raise TypeError("连线路由点必须是 (x, y)")
            x = float(raw[0])
            y = float(raw[1])
            if not math.isfinite(x) or not math.isfinite(y):
                raise ValueError("连线路由点必须是有限数字")
            scene_points.append((x, y))
        unique_scene: list[tuple[float, float]] = []
        for point in scene_points:
            if (
                unique_scene
                and abs(unique_scene[-1][0] - point[0]) < _POINT_EPS
                and abs(unique_scene[-1][1] - point[1]) < _POINT_EPS
            ):
                continue
            unique_scene.append(point)
        if len(unique_scene) < 2:
            unique_scene = _coincident_port_path(unique_scene[0] if unique_scene else scene_points[0])
        if len(self._route_points) == len(unique_scene) and all(
            abs(old[0] - new[0]) < _POINT_EPS and abs(old[1] - new[1]) < _POINT_EPS
            for old, new in zip(self._route_points, unique_scene)
        ):
            return False
        origin = unique_scene[0]
        local_points = [(x - origin[0], y - origin[1]) for x, y in unique_scene]
        self._route_points = unique_scene
        self.setPos(QPointF(origin[0], origin[1]))
        self._set_path(painter_path_from_points(local_points))
        self.update()
        return True

    def update_path(self) -> None:
        if self.start_item is None or self.end_item is None:
            self.clear_path()
            return
        if not _is_valid_qt_object(self.start_item) or not _is_valid_qt_object(self.end_item):
            self.clear_path()
            return
        if self.start_item.scene() is None or self.end_item.scene() is None:
            self.clear_path()
            return
        if self.start_item.scene() is not self.end_item.scene():
            raise RuntimeError("连线两端不在同一场景")
        view = getattr(self.start_item, "view", None)
        if view is None or not callable(getattr(view, "reroute_connections", None)):
            raise RuntimeError("连线起点未绑定可路由的工作流视图")
        if getattr(view, "_loading_workflow", False):
            return
        if getattr(view, "_rerouting_connections", False):
            return
        view.reroute_connections()

    def paint(self, painter, option, widget=None):
        path = self.path()
        if path.isEmpty() or self.scene() is None:
            return
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)
        if _overview_mode_enabled or _force_overview_mode:
            draw_pen = QPen(self.pen)
            draw_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            draw_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            draw_pen.setStyle(Qt.PenStyle.SolidLine)
            zoom = max(0.05, _last_zoom_level)
            zoom_ratio = min(1.0, zoom / _OVERVIEW_ZOOM_THRESHOLD)
            draw_pen.setWidthF(max(self._normal_width * (0.75 + 0.15 * zoom_ratio), 0.55 / zoom))
            painter.setPen(draw_pen)
        else:
            draw_pen = self._paint_pen
            draw_pen.setColor(self.pen.color())
            draw_pen.setWidthF(self.pen.widthF())
            draw_pen.setDashOffset(-self.dash_offset)
            painter.setPen(draw_pen)
        painter.drawPath(path)

    def shape(self):
        if not self._shape_cache_dirty:
            return self._shape_cache
        path = self.path()
        if path.isEmpty():
            self._shape_cache = QPainterPath()
        else:
            stroker = QPainterPathStroker()
            stroker.setWidth(10.0)
            stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
            stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            self._shape_cache = stroker.createStroke(path)
        self._shape_cache_dirty = False
        return self._shape_cache

    def hoverEnterEvent(self, event):
        self.pen.setWidthF(self._hover_width)
        self.pen.setColor(self._normal_color.lighter(130))
        self.setPen(self.pen)
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.pen.setWidthF(self._normal_width)
        self.pen.setColor(self._normal_color)
        self.setPen(self.pen)
        self.update()
        super().hoverLeaveEvent(event)

    def cleanup(self) -> None:
        if self.scene() is not None:
            _unregister_animated_line(self)
        self.start_item = None
        self.end_item = None
        self.clear_path()
