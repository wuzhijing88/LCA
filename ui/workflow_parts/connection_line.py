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

from .connection_routing import (
    DEFAULT_CLEARANCE,
    _reserved_path_segments,
    build_obstacle_groups,
)
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


def _connection_routing_scope(line):
    """Return the card region that can affect one route."""
    source_rect = line.start_item.sceneBoundingRect()
    target_rect = line.end_item.sceneBoundingRect()
    start_pos = line.get_start_pos()
    end_pos = line.get_end_pos()
    padding = 72.0
    long_leftward_column_change = (
        end_pos.x() <= start_pos.x()
        and abs(end_pos.y() - start_pos.y())
        >= max(source_rect.height(), target_rect.height()) * 2.0
        and target_rect.left()
        <= source_rect.left() - min(source_rect.width(), target_rect.width()) * 0.5
    )
    if long_leftward_column_change:
        padding = max(padding, max(source_rect.height(), target_rect.height()) * 3.0)
    return source_rect.united(target_rect).adjusted(-padding, -padding, padding, padding)


def update_connection_lines(
    scene,
    lines,
    *,
    reset_signatures=False,
    affected_cards=(),
) -> None:
    """使用同一场景快照按正式优先级更新一批线路。"""
    if scene is None or not _is_valid_qt_object(scene):
        return
    from .task_card import TaskCard

    affected_cards = tuple(affected_cards)

    items = scene.items()
    all_lines = [item for item in items if isinstance(item, ConnectionLine)]
    card_rects = [
        (item, item.sceneBoundingRect())
        for item in items
        if isinstance(item, TaskCard)
    ]
    obstacle_groups = build_obstacle_groups(card_rects)
    priorities = {line: line._routing_priority() for line in all_lines}
    all_lines.sort(key=priorities.__getitem__)
    context = {
        "scene": scene,
        "card_rects": card_rects,
        "obstacle_groups": obstacle_groups,
        "lines": all_lines,
        "priorities": priorities,
    }
    targets = {
        line
        for line in lines
        if line is not None and _is_valid_qt_object(line) and line.scene() is scene
    }
    changed_regions = [
        card.sceneBoundingRect().adjusted(
            -DEFAULT_CLEARANCE,
            -DEFAULT_CLEARANCE,
            DEFAULT_CLEARANCE,
            DEFAULT_CLEARANCE,
        )
        for card in affected_cards
        if card is not None and _is_valid_qt_object(card) and card.scene() is scene
    ]
    scopes = {line: _connection_routing_scope(line) for line in all_lines}
    if changed_regions:
        targets.update(
            line
            for line in all_lines
            if line._path_mode == "orthogonal"
            or line.start_item in affected_cards
            or line.end_item in affected_cards
            or any(scopes[line].intersects(region) for region in changed_regions)
        )

    # Later routes may reserve lanes around earlier routes. Propagate a changed
    # route forward through overlapping scopes so one frame always forms a
    # complete routing transaction.
    dirty_scopes = []
    for line in all_lines:
        scope = scopes[line]
        if line in targets or any(scope.intersects(dirty_scope) for dirty_scope in dirty_scopes):
            targets.add(line)
            dirty_scopes.append(scope)
    for line in all_lines:
        if line not in targets:
            continue
        if reset_signatures:
            line._route_signature = None
        line.update_path(context)


def schedule_scene_route_refresh(scene, delay_ms=0, affected_cards=None) -> None:
    """合并一次精确寻路；移动卡片时只刷新相关线路。"""
    if scene is None or not _is_valid_qt_object(scene):
        return
    if affected_cards is None:
        scene._connection_route_refresh_all = True
        scene._connection_route_refresh_cards = []
    elif not getattr(scene, "_connection_route_refresh_all", False):
        pending = list(getattr(scene, "_connection_route_refresh_cards", []))
        known = {id(card) for card in pending if card is not None and _is_valid_qt_object(card)}
        for card in affected_cards:
            if card is not None and _is_valid_qt_object(card) and id(card) not in known:
                pending.append(card)
                known.add(id(card))
        scene._connection_route_refresh_cards = pending
    timer = getattr(scene, "_connection_route_refresh_timer", None)
    if timer is None or not _is_valid_qt_object(timer):
        timer = QTimer(scene)
        timer.setSingleShot(True)

        def refresh_routes():
            if getattr(scene, "_connection_route_refreshing", False):
                return
            scene._connection_route_refreshing = True
            try:
                lines = [item for item in scene.items() if isinstance(item, ConnectionLine)]
                refresh_all = bool(getattr(scene, "_connection_route_refresh_all", False))
                cards = list(getattr(scene, "_connection_route_refresh_cards", []))
                scene._connection_route_refresh_all = False
                scene._connection_route_refresh_cards = []
                if not refresh_all:
                    affected = {
                        line
                        for card in cards
                        if card is not None and _is_valid_qt_object(card)
                        for line in getattr(card, "connections", ())
                        if line is not None and _is_valid_qt_object(line) and line.scene() is scene
                    }
                    lines = [line for line in lines if line in affected]
                update_connection_lines(
                    scene,
                    lines,
                    reset_signatures=refresh_all,
                    affected_cards=() if refresh_all else cards,
                )
            finally:
                scene._connection_route_refreshing = False

        timer.timeout.connect(refresh_routes)
        scene._connection_route_refresh_timer = timer
    timer.start(max(0, int(delay_ms)))


def _rounded_polyline(points, radius=12.0):
    """用少量正交折点生成圆角路径。"""
    simplified = []
    for point in points:
        if simplified and point == simplified[-1]:
            continue
        while len(simplified) >= 2:
            previous, corner = simplified[-2:]
            incoming, outgoing = corner - previous, point - corner
            cross = incoming.x() * outgoing.y() - incoming.y() * outgoing.x()
            if abs(cross) > 0.001 or incoming.x() * outgoing.x() + incoming.y() * outgoing.y() < 0:
                break
            simplified.pop()
        simplified.append(point)
    path = QPainterPath(simplified[0])
    for index in range(1, len(simplified) - 1):
        previous, corner, following = simplified[index - 1:index + 2]
        incoming, outgoing = previous - corner, following - corner
        length_in = math.hypot(incoming.x(), incoming.y())
        length_out = math.hypot(outgoing.x(), outgoing.y())
        corner_radius = min(radius, length_in / 2, length_out / 2)
        before = corner + incoming * (corner_radius / max(length_in, 0.001))
        after = corner + outgoing * (corner_radius / max(length_out, 0.001))
        path.lineTo(before)
        path.quadTo(corner, after)
    if len(simplified) > 1:
        path.lineTo(simplified[-1])
    return path


def _self_loop_path(line_type, card_rect, start_pos, end_pos):
    """为同一卡片的不同端口分配固定、互不重合的环路。"""
    side, offset = {
        "success": ("top", 38.0),
        "sequential": ("top", 18.0),
        "random": ("top", 18.0),
        "failure": ("bottom", 18.0),
    }[line_type]
    lane_y = card_rect.top() - offset if side == "top" else card_rect.bottom() + offset
    right_x = card_rect.right() + offset
    left_x = card_rect.left() - offset
    scene_points = [
        start_pos,
        QPointF(right_x, start_pos.y()),
        QPointF(right_x, lane_y),
        QPointF(left_x, lane_y),
        QPointF(left_x, end_pos.y()),
        end_pos,
    ]
    return _rounded_polyline([point - start_pos for point in scene_points]), lane_y


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
    # 连线本体需要较宽的命中区方便选择，但端点必须让给卡片端口，
    # 否则已有连线会位于卡片之上并截获再次拖线的鼠标按下事件。
    _ENDPOINT_HIT_CLEARANCE = 13.0

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
        self._path_revision = 0

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
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        label = {"sequential": "顺序", "success": "成功分支", "failure": "失败分支", "random": "随机分支"}[line_type]
        self.setToolTip(f"卡片 {start_item.card_id} → 卡片 {end_item.card_id} · {label}")
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
                schedule_scene_route_refresh(value)
        elif change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            self.setZValue(7 if bool(value) else 5)
            self.update()
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

    def _routing_priority(self):
        start_pos = self.get_start_pos()
        end_pos = self.get_end_pos()
        distance = abs(end_pos.x() - start_pos.x()) + abs(end_pos.y() - start_pos.y())
        return distance, self.start_item.card_id, self.end_item.card_id, self.line_type

    def _set_path(self, path: QPainterPath) -> None:
        self.setPath(path)
        self._shape_cache_dirty = True
        self._path_revision += 1

    def clear_path(self) -> None:
        self._set_path(QPainterPath())

    def update_path(self, route_context=None) -> None:
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
        direct = QPainterPath(QPointF(0, 0))
        control_x = local_end.x() * 0.5
        direct.cubicTo(QPointF(control_x, 0), QPointF(control_x, local_end.y()), local_end)

        if self.start_item is self.end_item:
            loop_signature = (
                "self-loop", self.line_type,
                start_pos.x(), start_pos.y(), end_pos.x(), end_pos.y(),
            )
            if getattr(self, "_route_signature", None) == loop_signature and not self.path().isEmpty():
                return
            self._route_signature = loop_signature
            self.setPos(anchor_pos)
            loop_path, loop_lane_y = _self_loop_path(
                self.line_type,
                self.start_item.sceneBoundingRect(),
                start_pos,
                end_pos,
            )
            self._set_path(loop_path)
            self._path_mode = "orthogonal"
            self._exact_preview_lane_y = loop_lane_y
            self.update()
            return

        path = QPainterPath(QPointF(0.0, 0.0))
        scene = self.start_item.scene()
        from .task_card import TaskCard
        source_rect = self.start_item.sceneBoundingRect()
        target_rect = self.end_item.sceneBoundingRect()
        routing_scope = _connection_routing_scope(self)
        if route_context is not None and route_context.get("scene") is scene:
            card_rects = route_context["card_rects"]
            obstacle_groups = route_context["obstacle_groups"]
            routed_lines = [line for line in route_context["lines"] if line is not self]
            priority = route_context["priorities"][self]
            priority_of = route_context["priorities"].__getitem__
        else:
            items = scene.items()
            card_rects = [
                (item, item.sceneBoundingRect())
                for item in items
                if isinstance(item, TaskCard)
            ]
            obstacle_groups = build_obstacle_groups(card_rects)
            routed_lines = [item for item in items if isinstance(item, ConnectionLine) and item is not self]
            priority = self._routing_priority()
            routed_lines.sort(key=lambda line: line._routing_priority())
            priority_of = lambda line: line._routing_priority()
        nearby = []
        for members, group_bounds in obstacle_groups:
            contains_endpoint = any(
                card in (self.start_item, self.end_item)
                for card, _rect in members
            )
            group_is_nearby = group_bounds.adjusted(
                -DEFAULT_CLEARANCE,
                -DEFAULT_CLEARANCE,
                DEFAULT_CLEARANCE,
                DEFAULT_CLEARANCE,
            ).intersects(routing_scope)
            if not contains_endpoint and not group_is_nearby:
                continue
            if contains_endpoint:
                nearby.extend(members)
            else:
                nearby.append((None, group_bounds))
        cards = [card for card, _rect in nearby]
        obstacles = [rect for _card, rect in nearby]
        reserved_routes = []
        for line in routed_lines:
            if priority_of(line) >= priority or line.path().isEmpty():
                continue
            reserved_path = line.mapToScene(line.path())
            reserved_routes.append((line, reserved_path))
        reserved_paths = [path for _line, path in reserved_routes]
        reserved_signature = tuple(
            (id(line), line._path_revision)
            for line, _path in reserved_routes
        )
        signature = (start_pos.x(), start_pos.y(), end_pos.x(), end_pos.y(),
                     tuple(sorted((r.x(), r.y(), r.width(), r.height()) for r in obstacles)),
                     reserved_signature)
        if getattr(self, "_route_signature", None) == signature and not self.path().isEmpty():
            return
        self._route_signature = signature
        stroke = QPainterPathStroker()
        stroke.setWidth(8)
        direct_area = stroke.createStroke(direct)
        # 真正向后或穿过卡片时才强制折线路由。普通线路交叉允许保留局部曲线，
        # 避免为了绕开一个交点而沿整组卡片外框走远路。
        # 开放曲线不能直接做面积相交检测，否则 Qt 会隐式闭合成额外障碍区域。
        long_overlap = False
        direct_y = start_pos.y()
        direct_is_horizontal = abs(end_pos.y() - direct_y) <= 0.01
        for reserved_line, reserved_path in reserved_routes:
            if not direct_is_horizontal:
                continue
            direct_left, direct_right = sorted((start_pos.x(), end_pos.x()))
            if reserved_line.start_item is self.start_item:
                direct_left += 42.0
            if reserved_line.end_item is self.end_item:
                direct_right -= 42.0
            if direct_right - direct_left <= 28.0:
                continue
            for orientation, fixed, lower, upper in _reserved_path_segments(reserved_path):
                if orientation != 0 or abs(fixed - direct_y) > 7.5:
                    continue
                overlap_length = min(direct_right, upper) - max(direct_left, lower)
                if overlap_length > 28.0:
                    long_overlap = True
                    break
            if long_overlap:
                break
        grouped_barriers = [
            group_bounds
            for members, group_bounds in obstacle_groups
            if len(members) > 1
            and not any(
                card in (self.start_item, self.end_item)
                for card, _rect in members
            )
            and not group_bounds.intersects(source_rect)
            and not group_bounds.intersects(target_rect)
        ]
        # 曲线只在真实绘制范围会碰到卡片或完整的紧密卡片组时才改走正交
        # 路径。单张卡片的额外净距属于视觉偏好，不能把安全斜线强制成折线。
        needs_route = local_end.x() <= 0 or long_overlap or any(
            direct_area.intersects(rect.translated(-anchor_pos))
            for card, rect in card_rects
            if card not in (self.start_item, self.end_item)
        ) or any(
            direct_area.intersects(rect.translated(-anchor_pos))
            for rect in grouped_barriers
        )
        points = None
        if needs_route:
            from .connection_routing import safe_orthogonal_route
            points = safe_orthogonal_route(
                start_pos,
                end_pos,
                source_rect,
                target_rect,
                obstacles,
                [rect for _card, rect in card_rects],
                reserved_paths=reserved_paths,
            )
        if points:
            scene_points = [QPointF(point) for point in points]
            horizontal_segments = [
                (abs(following.x() - previous.x()), previous.y())
                for previous, following in zip(scene_points, scene_points[1:])
                if abs(previous.y() - following.y()) <= 0.001
            ]
            self._exact_preview_lane_y = (
                max(horizontal_segments, default=(0.0, None))[1]
            )
            points = [point - anchor_pos for point in points]
            path = _rounded_polyline(points)
            self._path_mode = "orthogonal"
        elif not needs_route:
            path = direct
            self._path_mode = "direct"
            self._exact_preview_lane_y = None
        else:
            # 几何上暂时没有安全通道时保持线路为空，不能用穿卡曲线掩盖失败。
            # 卡片继续移动到可解位置后，同一套路由事务会自动恢复线路。
            path = QPainterPath(QPointF(0.0, 0.0))
            self._path_mode = "blocked"
            self._exact_preview_lane_y = None
        if self.pos() == anchor_pos and self.path() == path:
            return
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
        if self.isSelected():
            halo = QPen(draw_pen.color())
            halo_color = halo.color()
            halo_color.setAlpha(72)
            halo.setColor(halo_color)
            halo.setWidthF(max(8.0, draw_pen.widthF() + 5.0))
            halo.setStyle(Qt.PenStyle.SolidLine)
            halo.setCapStyle(Qt.PenCapStyle.RoundCap)
            halo.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(halo)
            painter.drawPath(path)
            draw_pen.setWidthF(max(3.2, draw_pen.widthF()))
            draw_pen.setColor(draw_pen.color().lighter(125))
        painter.setPen(draw_pen)
        painter.drawPath(path)

    def boundingRect(self):
        # 场景粗筛范围必须覆盖扩大的命中区，否则线旁的点击仍会漏掉。
        return self.path().boundingRect().adjusted(-8, -8, 8, 8)

    def shape(self):
        if not self._shape_cache_dirty:
            return self._shape_cache
        path = self.path()
        if path.isEmpty():
            self._shape_cache = QPainterPath()
        else:
            stroker = QPainterPathStroker()
            stroker.setWidth(16.0)
            stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
            stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            hit_shape = stroker.createStroke(path)
            endpoint_clearance = QPainterPath()
            radius = self._ENDPOINT_HIT_CLEARANCE
            endpoint_clearance.addEllipse(path.pointAtPercent(0.0), radius, radius)
            endpoint_clearance.addEllipse(path.pointAtPercent(1.0), radius, radius)
            self._shape_cache = hit_shape.subtracted(endpoint_clearance)
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
