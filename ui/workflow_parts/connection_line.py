import threading
import time
import weakref
import math
from bisect import bisect_right
from enum import Enum
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QGraphicsPathItem, QApplication, QGraphicsItem
from PySide6.QtCore import Qt, QPointF, QTimer
from PySide6.QtGui import QPen, QColor, QPainterPath, QPainterPathStroker

from .workflow_debug_utils import debug_print
from ..workflow_parts.task_card import PORT_TYPE_SEQUENTIAL, PORT_TYPE_RANDOM

_global_animation_timer = None
_animated_lines = weakref.WeakSet()
_animated_lines_lock = threading.Lock()
_animation_pause_reasons = set()
_animation_pause_lock = threading.Lock()
_unified_dash_pattern = (12.0, 8.0)
_dash_units_per_second = 20.0
_global_dash_phase = 0.0
_last_animation_tick_s = None
_overview_mode_enabled = False
_overview_mode_zoom_threshold = 0.45
_last_zoom_level = 1.0
_animation_interval_ms = 16
_force_overview_mode = False

try:
    from shiboken6 import isValid as _shiboken_is_valid
except Exception:
    _shiboken_is_valid = None


def _register_animated_line(line):
    if line is None:
        return

    with _animated_lines_lock:
        try:
            _animated_lines.add(line)
            setattr(line, "_animation_registered", True)
        except TypeError:
            return

    _sync_animation_timer_state()


def _unregister_animated_line(line):
    if line is None:
        return

    with _animated_lines_lock:
        _animated_lines.discard(line)
        setattr(line, "_animation_registered", False)

    _sync_animation_timer_state()


def ensure_line_animation_registered(line):
    if line is None:
        return
    _register_animated_line(line)


def _is_view_animatable(view) -> bool:
    try:
        if view is None or not hasattr(view, "viewport"):
            return False
        if hasattr(view, "isVisible") and not view.isVisible():
            return False
        viewport = view.viewport()
        if viewport is None or not viewport.isVisible():
            return False
        rect = viewport.rect()
        return rect.width() > 0 and rect.height() > 0
    except Exception:
        return False


def _has_animatable_registered_lines() -> bool:
    with _animated_lines_lock:
        lines = list(_animated_lines)

    if not lines:
        return False

    for line in lines:
        if not _is_valid_qt_object(line):
            continue
        try:
            if hasattr(line, "isVisible") and not line.isVisible():
                continue
        except Exception:
            continue
        try:
            scene = line.scene()
        except Exception:
            scene = None
        if scene is None:
            continue
        try:
            views = list(scene.views())
        except Exception:
            views = []
        if any(_is_view_animatable(view) for view in views):
            return True
    return False


def _normalize_pause_reason(reason) -> str:
    try:
        normalized = str(reason or "default").strip()
    except Exception:
        normalized = "default"
    return normalized or "default"


def _is_animation_paused() -> bool:
    with _animation_pause_lock:
        return bool(_animation_pause_reasons)


def set_line_animation_paused(reason: str, paused: bool) -> None:
    normalized_reason = _normalize_pause_reason(reason)
    with _animation_pause_lock:
        if paused:
            _animation_pause_reasons.add(normalized_reason)
        else:
            _animation_pause_reasons.discard(normalized_reason)
    _sync_animation_timer_state()


def _sync_animation_timer_state():
    global _last_animation_tick_s
    should_run = (not _is_animation_paused()) and _has_animatable_registered_lines()

    timer = get_global_animation_timer(create_if_missing=should_run)
    if timer is None:
        return

    try:
        if should_run:
            if not timer.isActive():
                timer.start(_animation_interval_ms)
        elif timer.isActive():
            timer.stop()
            _last_animation_tick_s = None
    except Exception:
        pass


def get_line_animation_stats():
    """Return lightweight global animation registry stats for diagnostics."""
    line_count = 0
    animatable = False
    with _animated_lines_lock:
        line_count = len(_animated_lines)
    animatable = _has_animatable_registered_lines()

    timer_created = _global_animation_timer is not None
    timer_active = False
    if timer_created:
        try:
            timer_active = bool(_global_animation_timer.isActive())
        except Exception:
            timer_active = False

    return {
        "registered_lines": line_count,
        "registered_ids": line_count,
        "registered_scenes": 0,
        "animatable": bool(animatable),
        "paused": _is_animation_paused(),
        "timer_created": timer_created,
        "timer_active": timer_active,
        "interval_ms": int(_animation_interval_ms),
    }


def get_global_animation_timer(create_if_missing: bool = True):
    global _global_animation_timer
    if _global_animation_timer is None:
        if not create_if_missing:
            return None
        app = QApplication.instance()
        if app is None:
            return None
        _global_animation_timer = QTimer(app)
        _global_animation_timer.setTimerType(Qt.TimerType.PreciseTimer)
        _global_animation_timer.timeout.connect(animate_all_lines)
        try:
            if not _is_animation_paused():
                _global_animation_timer.start(_animation_interval_ms)
        except Exception:
            pass
    return _global_animation_timer


def stop_animation_timer():
    global _global_animation_timer
    _sync_animation_timer_state()
    debug_print("[Animation] stop_animation_timer ignored (compat)")


def restart_animation_timer():
    global _global_animation_timer
    _sync_animation_timer_state()
    debug_print("[Animation] restart_animation_timer ignored (compat)")


def pause_line_animation(reason: str = "default"):
    set_line_animation_paused(reason, True)
    debug_print("[Animation] Lines paused")


def resume_line_animation(reason: str = "default"):
    set_line_animation_paused(reason, False)
    debug_print("[Animation] Lines resumed")


def update_zoom_level(zoom_level: float):
    global _overview_mode_enabled, _last_zoom_level
    try:
        _last_zoom_level = max(0.01, float(zoom_level))
        new_overview_mode = _last_zoom_level < _overview_mode_zoom_threshold
    except Exception:
        return

    if new_overview_mode == _overview_mode_enabled:
        return

    _overview_mode_enabled = new_overview_mode
    if _overview_mode_enabled:
        pause_line_animation("zoom_overview")
    else:
        resume_line_animation("zoom_overview")

    # Trigger a one-time repaint for registered lines when mode changes.
    with _animated_lines_lock:
        lines = list(_animated_lines)
    for line in lines:
        if not _is_valid_qt_object(line):
            continue
        try:
            line.update()
        except Exception:
            pass


def set_force_overview_mode(enabled: bool):
    global _force_overview_mode
    enabled = bool(enabled)
    if _force_overview_mode == enabled:
        return

    _force_overview_mode = enabled
    if enabled:
        pause_line_animation("force_overview")
    else:
        resume_line_animation("force_overview")

    with _animated_lines_lock:
        lines = list(_animated_lines)
    for line in lines:
        if not _is_valid_qt_object(line):
            continue
        try:
            line.update()
        except Exception:
            pass


def _is_valid_qt_object(obj) -> bool:
    if obj is None:
        return False
    if _shiboken_is_valid is None:
        return True
    try:
        return bool(_shiboken_is_valid(obj))
    except Exception:
        return False


def animate_all_lines():
    global _global_dash_phase, _last_animation_tick_s

    if _is_animation_paused() or _force_overview_mode:
        return

    with _animated_lines_lock:
        lines = list(_animated_lines)

    if not lines:
        _sync_animation_timer_state()
        return

    now_s = time.perf_counter()
    if _last_animation_tick_s is None:
        _last_animation_tick_s = now_s
        return

    elapsed_s = now_s - _last_animation_tick_s
    _last_animation_tick_s = now_s
    if elapsed_s <= 0.0:
        return

    # 限制异常大的帧间隔，防止恢复后虚线相位突跳。
    if elapsed_s > 0.25:
        elapsed_s = 0.25

    _global_dash_phase += elapsed_s * _dash_units_per_second
    if _global_dash_phase >= 1000000.0:
        _global_dash_phase = _global_dash_phase % 1000000.0

    stale_lines = []
    try:
        for line in lines:
            if not _is_valid_qt_object(line):
                stale_lines.append(line)
                continue

            if not hasattr(line, "dash_offset") or not hasattr(line, "dash_pattern"):
                continue

            try:
                pattern_length = float(sum(line.dash_pattern))
            except Exception:
                continue
            if pattern_length <= 0.0:
                continue

            try:
                scene = line.scene()
            except Exception:
                scene = None
            if scene is None:
                continue

            try:
                path = line.path()
            except Exception:
                path = None
            if path is None or path.isEmpty():
                continue

            # 正向推进：沿路径起点（输出端）到终点（输入端）
            line.dash_offset = (_global_dash_phase % pattern_length)
            line.update()
    except Exception:
        pass

    if stale_lines:
        with _animated_lines_lock:
            for stale_line in stale_lines:
                _animated_lines.discard(stale_line)

    if stale_lines:
        _sync_animation_timer_state()



if TYPE_CHECKING:
    from ..workflow_parts.task_card import TaskCard


class ConnectionType(Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    RANDOM = "random"


class ConnectionLine(QGraphicsPathItem):
    def __init__(self, start_item: 'TaskCard', end_item: 'TaskCard', line_type: str, parent=None):
        super().__init__(parent)
        self.start_item = start_item
        self.end_item = end_item
        self.line_type = line_type

        self.pen = QPen()
        self.pen.setWidthF(2.0)
        self.pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        self.pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        self.pen.setStyle(Qt.PenStyle.DashLine)
        self.dash_pattern = list(_unified_dash_pattern)
        self.pen.setDashPattern(self.dash_pattern)
        self.pen.setCosmetic(False)

        self.set_line_color()
        self.setPen(self.pen)
        self.setZValue(5)
        self.setBrush(Qt.BrushStyle.NoBrush)
        # Animated dash offset updates every frame; disable item cache to avoid
        # repeated cache allocations in long-running sessions.
        self.setCacheMode(QGraphicsPathItem.CacheMode.NoCache)

        self._is_hovered = False
        self._normal_width = 2.0
        self._hover_width = 4.0
        self._original_color = None
        self.setAcceptHoverEvents(True)
        self._shape_cache = QPainterPath()
        self._shape_cache_dirty = True
        self._path_length = 0.0
        self._polyline_points = []
        self._polyline_lengths = []
        self._polyline_total_length = 0.0
        self.dash_offset = 0.0

        self.update_path()
        _register_animated_line(self)

    def itemChange(self, change, value):
        try:
            if change == QGraphicsItem.GraphicsItemChange.ItemSceneHasChanged:
                if value is None:
                    _unregister_animated_line(self)
                else:
                    _register_animated_line(self)
        except Exception:
            pass
        return super().itemChange(change, value)

    def set_line_color(self):
        color = QColor(60, 140, 210)
        if self.line_type == ConnectionType.SUCCESS.value:
            color = QColor(60, 160, 60)
        elif self.line_type == ConnectionType.FAILURE.value:
            color = QColor(210, 80, 80)
        elif self.line_type == ConnectionType.RANDOM.value or self.line_type == PORT_TYPE_RANDOM:
            color = QColor(147, 51, 234)

        self.pen.setColor(color)
        self.setPen(self.pen)

    def get_start_pos(self) -> QPointF:
        if self.start_item:
            try:
                from shiboken6 import isValid
                if not isValid(self.start_item):
                    return QPointF(0, 0)
            except ImportError:
                pass
            try:
                return self.start_item.get_output_port_scene_pos(self.line_type)
            except RuntimeError:
                return QPointF(0, 0)
        return QPointF(0, 0)

    def get_end_pos(self) -> QPointF:
        if self.end_item:
            try:
                from shiboken6 import isValid
                if not isValid(self.end_item):
                    return QPointF(0, 0)
            except ImportError:
                pass
            try:
                if self.line_type == PORT_TYPE_RANDOM:
                    return self.end_item.get_input_port_scene_pos(PORT_TYPE_SEQUENTIAL)
                return self.end_item.get_input_port_scene_pos(self.line_type)
            except RuntimeError:
                return QPointF(0, 0)
        return QPointF(0, 0)

    def _clear_polyline_cache(self):
        self._polyline_points = []
        self._polyline_lengths = []
        self._polyline_total_length = 0.0

    def _set_empty_path(self):
        self.setPath(QPainterPath())
        self._path_length = 0.0
        self._shape_cache_dirty = True
        self._clear_polyline_cache()

    def _rebuild_polyline_cache(self, path: QPainterPath):
        self._clear_polyline_cache()
        try:
            polygons = path.toSubpathPolygons()
        except Exception:
            polygons = []
        if not polygons:
            return

        points = []
        for polygon in polygons:
            try:
                polygon_points = list(polygon)
            except Exception:
                continue
            for point in polygon_points:
                current = QPointF(point)
                if points and current == points[-1]:
                    continue
                points.append(current)

        if len(points) < 2:
            return

        merged_points = [points[0]]
        cumulative_lengths = [0.0]
        total_length = 0.0

        for point in points[1:]:
            previous = merged_points[-1]
            segment_length = math.hypot(point.x() - previous.x(), point.y() - previous.y())
            if segment_length <= 1e-6:
                continue
            total_length += segment_length
            merged_points.append(point)
            cumulative_lengths.append(total_length)

        if len(merged_points) < 2 or total_length <= 1e-6:
            return

        self._polyline_points = merged_points
        self._polyline_lengths = cumulative_lengths
        self._polyline_total_length = total_length

    def _point_at_distance(self, distance: float) -> QPointF:
        if not self._polyline_points:
            return QPointF(0.0, 0.0)
        if distance <= 0.0:
            return QPointF(self._polyline_points[0])
        if distance >= self._polyline_total_length:
            return QPointF(self._polyline_points[-1])

        index = bisect_right(self._polyline_lengths, distance) - 1
        if index < 0:
            index = 0
        max_index = len(self._polyline_points) - 2
        if index > max_index:
            index = max_index

        start_len = self._polyline_lengths[index]
        end_len = self._polyline_lengths[index + 1]
        start_point = self._polyline_points[index]
        end_point = self._polyline_points[index + 1]

        span = end_len - start_len
        if span <= 1e-6:
            return QPointF(start_point)

        ratio = (distance - start_len) / span
        x = start_point.x() + (end_point.x() - start_point.x()) * ratio
        y = start_point.y() + (end_point.y() - start_point.y()) * ratio
        return QPointF(x, y)

    def _append_polyline_segment(self, output_path: QPainterPath, start_distance: float, end_distance: float):
        if end_distance <= start_distance:
            return
        if not self._polyline_points:
            return

        start_point = self._point_at_distance(start_distance)
        end_point = self._point_at_distance(end_distance)
        output_path.moveTo(start_point)

        start_index = bisect_right(self._polyline_lengths, start_distance) - 1
        end_index = bisect_right(self._polyline_lengths, end_distance) - 1
        if start_index < 0:
            start_index = 0
        if end_index < 0:
            end_index = 0
        max_index = len(self._polyline_points) - 1
        if start_index > max_index:
            start_index = max_index
        if end_index > max_index:
            end_index = max_index

        for point_index in range(start_index + 1, end_index + 1):
            vertex_distance = self._polyline_lengths[point_index]
            if start_distance < vertex_distance < end_distance:
                output_path.lineTo(self._polyline_points[point_index])

        output_path.lineTo(end_point)

    def _build_animated_stroke_path(self) -> QPainterPath:
        if self._polyline_total_length <= 0.0 or len(self._polyline_points) < 2:
            return QPainterPath()

        try:
            on_length = float(self.dash_pattern[0]) if len(self.dash_pattern) >= 1 else 0.0
            off_length = float(self.dash_pattern[1]) if len(self.dash_pattern) >= 2 else on_length
        except Exception:
            return QPainterPath()

        if on_length <= 0.0:
            return QPainterPath()
        if off_length < 0.0:
            off_length = 0.0

        cycle = on_length + off_length
        if cycle <= 0.0:
            return QPainterPath()

        phase = (-float(self.dash_offset)) % cycle
        cursor = -phase
        total = self._polyline_total_length

        dashed_path = QPainterPath()
        guard = 0
        while cursor < total and guard < 100000:
            start_distance = max(0.0, cursor)
            end_distance = min(total, cursor + on_length)
            if end_distance > start_distance:
                self._append_polyline_segment(dashed_path, start_distance, end_distance)
            cursor += cycle
            guard += 1

        return dashed_path

    def update_path(self):
        try:
            if not self.start_item or not self.end_item:
                self._set_empty_path()
                return

            try:
                from shiboken6 import isValid
                if not isValid(self.start_item) or not isValid(self.end_item):
                    self._set_empty_path()
                    return
            except ImportError:
                pass

            try:
                if not self.start_item.scene() or not self.end_item.scene():
                    self._set_empty_path()
                    return
            except RuntimeError:
                self._set_empty_path()
                return

            start_pos = self.get_start_pos()
            end_pos = self.get_end_pos()
            if start_pos == end_pos:
                self._set_empty_path()
                return

            # 使用局部坐标绘制路径，避免超大场景坐标导致精度抖动或动画失效。
            anchor_pos = QPointF(start_pos)
            local_start = QPointF(0.0, 0.0)
            local_end = end_pos - anchor_pos

            path = QPainterPath(local_start)
            dx = local_end.x() - local_start.x()
            direction = 1.0 if dx >= 0.0 else -1.0
            distance = abs(dx)
            offset = distance * 0.5
            ctrl1 = QPointF(local_start.x() + direction * offset, local_start.y())
            ctrl2 = QPointF(local_end.x() - direction * offset, local_end.y())
            path.cubicTo(ctrl1, ctrl2, local_end)

            self.prepareGeometryChange()
            self.setPos(anchor_pos)
            self.setPath(path)
            try:
                self._path_length = max(1.0, float(path.length()))
            except Exception:
                self._path_length = max(1.0, float((local_end - local_start).manhattanLength()))
            self._shape_cache_dirty = True
            self._rebuild_polyline_cache(path)
            self.update()
        except Exception:
            try:
                self._set_empty_path()
            except Exception:
                pass

    def paint(self, painter, option, widget=None):
        try:
            try:
                from shiboken6 import isValid
                if not isValid(self):
                    return
            except ImportError:
                pass

            try:
                if not self.scene():
                    return
            except RuntimeError:
                return

            path = self.path()
            if path.isEmpty():
                return

            if _overview_mode_enabled or _force_overview_mode:
                # Overview mode: simplified line rendering for large-scale zoom-out performance.
                painter.setRenderHint(painter.RenderHint.Antialiasing, True)
                try:
                    high_quality_hint = getattr(painter.RenderHint, "HighQualityAntialiasing", None)
                    if high_quality_hint is not None:
                        painter.setRenderHint(high_quality_hint, True)
                except Exception:
                    pass
                simple_pen = QPen(self.pen)
                simple_pen.setStyle(Qt.PenStyle.SolidLine)
                simple_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                simple_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                simple_pen.setCosmetic(False)
                zoom_for_width = max(0.05, _last_zoom_level)
                threshold_for_width = max(0.05, _overview_mode_zoom_threshold)
                zoom_ratio = max(0.0, min(1.0, zoom_for_width / threshold_for_width))
                # Keep line lighter near overview entry, then gradually thin with further zoom-out.
                base_scene_width = self._normal_width * (0.75 + 0.15 * zoom_ratio)
                # Prevent line from disappearing completely at extreme zoom-out.
                min_scene_width_for_device_px = 0.55 / zoom_for_width
                overview_width = max(base_scene_width, min_scene_width_for_device_px)
                simple_pen.setWidthF(overview_width)
                painter.setPen(simple_pen)
                painter.drawPath(path)
                return

            painter.setRenderHint(painter.RenderHint.Antialiasing, True)

            animated_pen = QPen(self.pen)
            animated_pen.setStyle(Qt.PenStyle.SolidLine)
            animated_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            animated_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(animated_pen)
            animated_path = self._build_animated_stroke_path()
            if animated_path.isEmpty():
                fallback_pen = QPen(self.pen)
                fallback_pen.setDashPattern(self.dash_pattern)
                fallback_pen.setDashOffset(float(self.dash_offset))
                fallback_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                fallback_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                painter.setPen(fallback_pen)
                painter.drawPath(path)
                return
            painter.drawPath(animated_path)
        except Exception:
            pass

    def shape(self):
        if not self._shape_cache_dirty:
            return self._shape_cache

        path = self.path()
        if path.isEmpty():
            self._shape_cache = path
            self._shape_cache_dirty = False
            return self._shape_cache

        stroker = QPainterPathStroker()
        stroker.setWidth(10.0)
        stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
        stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        self._shape_cache = stroker.createStroke(path)
        self._shape_cache_dirty = False
        return self._shape_cache

    def hoverEnterEvent(self, event):
        try:
            from shiboken6 import isValid
            if not isValid(self):
                return
        except ImportError:
            pass
        try:
            self._is_hovered = True
            self._original_color = self.pen.color()
            self.pen.setWidthF(self._hover_width)
            highlight_color = self._original_color.lighter(130)
            self.pen.setColor(highlight_color)
            self.setPen(self.pen)
            self.update()
            super().hoverEnterEvent(event)
        except RuntimeError:
            pass

    def hoverLeaveEvent(self, event):
        try:
            from shiboken6 import isValid
            if not isValid(self):
                return
        except ImportError:
            pass
        try:
            self._is_hovered = False
            self.pen.setWidthF(self._normal_width)
            if self._original_color:
                self.pen.setColor(self._original_color)
            self.setPen(self.pen)
            self.update()
            super().hoverLeaveEvent(event)
        except RuntimeError:
            pass

    def __del__(self):
        try:
            _unregister_animated_line(self)
        except Exception:
            pass

    def cleanup(self):
        try:
            _unregister_animated_line(self)
            self.start_item = None
            self.end_item = None
            self._set_empty_path()
        except Exception:
            pass

