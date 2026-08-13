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

from ..workflow_parts.task_card import PORT_TYPE_RANDOM, PORT_TYPE_SEQUENTIAL


_VALID_LINE_TYPES = frozenset(("sequential", "success", "failure", "random"))
_DASH_PATTERN = (12.0, 8.0)
_DASH_UNITS_PER_SECOND = 20.0
_ANIMATION_INTERVAL_MS = 16
_OVERVIEW_ZOOM_THRESHOLD = 0.45

_animation_timer = None
_animated_lines = weakref.WeakSet()
_animated_lines_lock = threading.Lock()
_animation_pause_reasons = set()
_animation_pause_lock = threading.Lock()
_dash_phase = 0.0
_last_animation_tick_s = None
_overview_mode_enabled = False
_force_overview_mode = False
_last_zoom_level = 1.0


def _snapshot_registered_lines():
    with _animated_lines_lock:
        return list(_animated_lines)


def _line_is_animatable(line) -> bool:
    if line is None or not _is_valid_qt_object(line) or not line.isVisible():
        return False
    scene = line.scene()
    if scene is None:
        return False
    for view in scene.views():
        if not _is_valid_qt_object(view) or not view.isVisible():
            continue
        viewport = view.viewport()
        if viewport is not None and viewport.isVisible() and not viewport.rect().isEmpty():
            return True
    return False


def _has_animatable_lines() -> bool:
    return any(_line_is_animatable(line) for line in _snapshot_registered_lines())


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
            _animation_pause_reasons.add(normalized_reason)
        else:
            _animation_pause_reasons.discard(normalized_reason)
    refresh_line_animation_state()


def pause_line_animation(reason: str = "default") -> None:
    set_line_animation_paused(reason, True)


def resume_line_animation(reason: str = "default") -> None:
    set_line_animation_paused(reason, False)


def _repaint_registered_lines() -> None:
    for line in _snapshot_registered_lines():
        if _is_valid_qt_object(line):
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
    return {
        "registered_lines": len(lines),
        "animatable_lines": sum(1 for line in lines if _line_is_animatable(line)),
        "paused": _is_animation_paused(),
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
    for line in lines:
        if not _is_valid_qt_object(line):
            stale_lines.append(line)
            continue
        if not _line_is_animatable(line) or line.path().isEmpty():
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
        self.setBrush(Qt.BrushStyle.NoBrush)
        self.setZValue(5)
        self.setCacheMode(QGraphicsPathItem.CacheMode.NoCache)
        self.setAcceptHoverEvents(True)
        self.update_path()

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
        self._set_path(QPainterPath())

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

        start_pos = self.get_start_pos()
        end_pos = self.get_end_pos()
        anchor_pos = QPointF(start_pos)
        local_end = end_pos - anchor_pos
        path = QPainterPath(QPointF(0.0, 0.0))
        control_x = local_end.x() * 0.5
        path.cubicTo(
            QPointF(control_x, 0.0),
            QPointF(control_x, local_end.y()),
            local_end,
        )
        self.setPos(anchor_pos)
        self._set_path(path)
        self.update()

    def paint(self, painter, option, widget=None):
        path = self.path()
        if path.isEmpty() or self.scene() is None:
            return
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)
        draw_pen = QPen(self.pen)
        draw_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        draw_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        if _overview_mode_enabled or _force_overview_mode:
            draw_pen.setStyle(Qt.PenStyle.SolidLine)
            zoom = max(0.05, _last_zoom_level)
            zoom_ratio = min(1.0, zoom / _OVERVIEW_ZOOM_THRESHOLD)
            draw_pen.setWidthF(max(self._normal_width * (0.75 + 0.15 * zoom_ratio), 0.55 / zoom))
        else:
            draw_pen.setStyle(Qt.PenStyle.DashLine)
            draw_pen.setDashPattern(list(_DASH_PATTERN))
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
