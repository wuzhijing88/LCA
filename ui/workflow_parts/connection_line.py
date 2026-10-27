"""连线图元与显示运行时。拓扑修改和轨道规划不属于绘制层。"""
from collections import Counter
from contextlib import contextmanager
from enum import Enum
from math import hypot
from time import perf_counter
import weakref

from PySide6.QtCore import QObject, QPointF, Qt, QTimer, Slot
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPainterPathStroker, QPen
from PySide6.QtWidgets import QApplication, QGraphicsItem, QGraphicsObject
from shiboken6 import isValid

from themes import get_theme_manager, theme_color
from .connection_geometry import LINE_TYPES, orthogonal_points

_animated_lines = weakref.WeakSet()
_DASH_LENGTH = 24.0
_DASH_GAP = 16.0
_DASH_PERIOD = _DASH_LENGTH + _DASH_GAP
_DASH_SPEED = 40.0
_ANIMATION_INTERVAL_MS = 16


class ConnectionType(Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    RANDOM = "random"


def painter_path_from_points(points):
    points = orthogonal_points(points)
    path = QPainterPath(QPointF(*points[0]))
    for previous, corner, following in zip(points, points[1:], points[2:]):
        first = hypot(corner[0] - previous[0], corner[1] - previous[1])
        second = hypot(following[0] - corner[0], following[1] - corner[1])
        radius = min(8.0, first / 2, second / 2)
        entry = QPointF(corner[0] + (previous[0] - corner[0]) * radius / first,
                        corner[1] + (previous[1] - corner[1]) * radius / first)
        exit_point = QPointF(corner[0] + (following[0] - corner[0]) * radius / second,
                             corner[1] + (following[1] - corner[1]) * radius / second)
        path.lineTo(entry)
        path.quadTo(QPointF(*corner), exit_point)
    path.lineTo(QPointF(*points[-1]))
    return path


class _ConnectionDisplay(QObject):
    """可见连线共用一个计时器；悬停优先于点击选中的聚焦状态。"""
    def __init__(self):
        super().__init__()
        self.mounted = weakref.WeakValueDictionary()
        self.scenes = weakref.WeakKeyDictionary()
        self.focused = weakref.WeakKeyDictionary()
        self.dirty_scenes = weakref.WeakSet()
        self.batch_depth = 0
        self.pauses = Counter()
        self.timer = None
        self.overview = False
        self.theme_registered = False
        self.last_tick = None
        self.application_ref = None
        self.stopping = False

    def attach(self, line):
        if self.stopping:
            raise RuntimeError("应用程序正在退出，无法挂载连线")
        if self.application_ref is None:
            app = QApplication.instance()
            if app is None:
                raise RuntimeError("挂载连线前必须创建应用程序")
            self.setParent(app)
            self.application_ref = weakref.ref(app)
            app.aboutToQuit.connect(self.shutdown)
            app.destroyed.connect(self.shutdown)
        self.mounted[id(line)] = line
        scene = line.scene()
        line._mounted_scene_ref = weakref.ref(scene)
        self.scenes.setdefault(scene, weakref.WeakSet()).add(line)
        if not self.theme_registered:
            get_theme_manager().register_theme_change_callback(self.theme_changed)
            self.theme_registered = True
        self.focus_changed(line.scene())

    def forget(self, identity):
        """解除 Python 登记，不访问正在销毁的 Qt 对象。"""
        line = self.mounted.pop(identity, None)
        scene = None
        if line is not None:
            line._hovered = False
            _animated_lines.discard(line)
            if line._mounted_scene_ref is not None:
                scene = line._mounted_scene_ref()
                line._mounted_scene_ref = None
                if scene in self.scenes:
                    self.scenes[scene].discard(line)
                    if not self.scenes[scene]:
                        del self.scenes[scene]
                        self.focused.pop(scene, None)
                        self.dirty_scenes.discard(scene)
        return scene

    def detach(self, identity):
        self.focus_changed(self.forget(identity))

    def stop_timer(self):
        timer, self.timer = self.timer, None
        self.last_tick = None
        if timer is not None and isValid(timer):
            timer.stop()
            timer.timeout.disconnect(self.tick)
            timer.deleteLater()

    def release_callbacks(self):
        if self.theme_registered:
            get_theme_manager().unregister_theme_change_callback(self.theme_changed)
            self.theme_registered = False
        if self.application_ref is not None:
            app = self.application_ref()
            self.application_ref = None
            if app is not None and isValid(app):
                app.aboutToQuit.disconnect(self.shutdown)
                app.destroyed.disconnect(self.shutdown)

    @Slot()
    def shutdown(self):
        """退出先停止显示运行时，后续图元销毁只解除登记。"""
        self.stopping = True
        for identity in tuple(self.mounted):
            self.forget(identity)
        _animated_lines.clear()
        self.scenes.clear()
        self.focused.clear()
        self.dirty_scenes.clear()
        self.pauses.clear()
        self.stop_timer()
        self.release_callbacks()

    def focus_changed(self, scene):
        if self.stopping:
            return
        if scene is not None and isValid(scene) and scene in self.scenes:
            self.dirty_scenes.add(scene)
        self.refresh()

    @contextmanager
    def batch(self):
        self.batch_depth += 1
        self.stop_timer()
        try:
            yield
        finally:
            self.batch_depth -= 1
            if not self.batch_depth:
                self.refresh()

    @staticmethod
    def focused_lines(lines):
        visible = [line for line in lines if line.isVisible()]
        hovered = {line for line in visible if line._hovered}
        return hovered or {line for line in visible if line.isSelected()}

    @classmethod
    def apply_focus(cls, lines):
        focused = cls.focused_lines(lines)
        for line in lines:
            opacity = 0.2 if focused and line not in focused else 1.0
            z = -0.5 if line in focused else -1.0
            if line.opacity() != opacity:
                line.setOpacity(opacity)
            if line.zValue() != z:
                line.setZValue(z)
        return focused

    def theme_changed(self, _theme):
        for line in tuple(self.mounted.values()):
            if isValid(line):
                line.set_line_color()

    @staticmethod
    def visible(line, rects, *, animated=False):
        if not isValid(line) or not line.isVisible():
            return False
        scene = line.scene()
        if scene is None or not isValid(scene):
            return False
        for view in scene.views():
            if not isValid(view) or not view.isVisible():
                continue
            if animated and abs(view.transform().m11()) < 0.45:
                continue
            viewport = view.viewport()
            if viewport is None or not isValid(viewport) or not viewport.isVisible():
                continue
            if view not in rects:
                rects[view] = view.mapToScene(viewport.rect()).boundingRect().adjusted(-30, -30, 30, 30)
            local_rect = line.mapFromScene(rects[view]).boundingRect()
            if line._shape.intersects(local_rect):
                return True
        return False

    def refresh(self):
        if self.stopping or self.batch_depth:
            return
        _animated_lines.clear()
        for scene, registered in tuple(self.scenes.items()):
            if not isValid(scene):
                continue
            if scene in self.dirty_scenes:
                self.focused[scene] = weakref.WeakSet(self.apply_focus(registered))
                self.dirty_scenes.discard(scene)
            visible_lines, animatable = set(), set()
            for view in scene.views():
                if not isValid(view) or not view.isVisible() or not view.viewport().isVisible():
                    continue
                rect = view.mapToScene(view.viewport().rect()).boundingRect().adjusted(-30, -30, 30, 30)
                flowing = abs(view.transform().m11()) >= 0.45
                for line in scene.items(rect, Qt.ItemSelectionMode.IntersectsItemBoundingRect):
                    if not isinstance(line, ConnectionLine) or line._disposed:
                        continue
                    if line._shape.intersects(line.mapFromScene(rect).boundingRect()):
                        visible_lines.add(line)
                        if flowing:
                            animatable.add(line)
            focused = self.focused.get(scene, ())
            cleared_hover = False
            for line in tuple(focused):
                if line._hovered and line not in visible_lines:
                    line._hovered = False
                    line.update()
                    cleared_hover = True
            if cleared_hover:
                focused = self.apply_focus(registered)
                self.focused[scene] = weakref.WeakSet(focused)
            _animated_lines.update(line for line in animatable if not focused or line in focused)
        running = bool(_animated_lines) and not self.pauses and not self.overview
        if running and self.timer is None:
            app = QApplication.instance()
            if app is None:
                raise RuntimeError("创建连线动画前必须创建应用程序")
            self.timer = QTimer(app)
            self.timer.setTimerType(Qt.TimerType.PreciseTimer)
            self.timer.setInterval(_ANIMATION_INTERVAL_MS)
            self.timer.timeout.connect(self.tick)
            self.last_tick = perf_counter()
            self.timer.start()
        elif not running and self.timer is not None:
            self.stop_timer()
        if not self.mounted:
            self.release_callbacks()

    @Slot()
    def tick(self):
        if self.timer is None:
            return
        rects = {}
        if any(not isValid(line) or line._disposed or not self.visible(line, rects, animated=True)
               for line in tuple(_animated_lines)):
            self.refresh()
            if self.timer is None:
                return
        now = perf_counter()
        distance = min(now - self.last_tick, 0.1) * _DASH_SPEED
        self.last_tick = now
        for line in tuple(_animated_lines):
            line._dash_offset = (line._dash_offset + distance) % _DASH_PERIOD
            line.update()


_display = _ConnectionDisplay()


def refresh_line_animation_state():
    _display.refresh()


def batch_line_display_updates():
    return _display.batch()


def clear_line_hover(scene):
    """显式取消悬停聚焦，鼠标再次移动到连线上时重新激活。"""
    for line in tuple(_display.mounted.values()):
        if isValid(line) and line.scene() is scene and line._hovered:
            line._hovered = False
            line.update()
    _display.focus_changed(scene)


def set_line_animation_paused(reason, paused):
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("连线暂停原因必须是非空字符串")
    if paused:
        _display.pauses[reason] += 1
    elif reason in _display.pauses:
        _display.pauses[reason] -= 1
        if _display.pauses[reason] == 0:
            del _display.pauses[reason]
    _display.refresh()


def pause_line_animation(reason="default"):
    set_line_animation_paused(reason, True)


def resume_line_animation(reason="default"):
    set_line_animation_paused(reason, False)


def set_force_overview_mode(enabled):
    _display.overview = bool(enabled)
    _display.refresh()


def get_line_animation_stats():
    return {"registered_lines": len(_display.mounted), "animatable_lines": len(_animated_lines),
            "paused": bool(_display.pauses), "pause_reasons": sorted(_display.pauses),
            "pause_counts": dict(_display.pauses), "timer_active": _display.timer is not None,
            "interval_ms": _ANIMATION_INTERVAL_MS}


def animate_all_lines():
    _display.tick()


class ConnectionLine(QGraphicsObject):
    """无箭头的圆角流动虚线，悬停及点击选中时淡化其他连线。"""
    def __init__(self, start_item, end_item, line_type, parent=None):
        if start_item is None or end_item is None:
            raise ValueError("连线必须有起点和终点")
        if line_type not in LINE_TYPES:
            raise ValueError("不支持的连线类型")
        super().__init__(parent)
        self.start_item, self.end_item = start_item, end_item
        self.line_type = line_type
        self._points = ()
        self._path = QPainterPath()
        self._shape = QPainterPath()
        self._dash_offset = 0.0
        self._bounds = self._path.boundingRect()
        self._hovered = False
        self._disposed = False
        self._mounted_scene_ref = None
        self.pen = QPen(QColor(theme_color("connection_" + line_type)), 2.0)
        self.pen.setDashPattern([_DASH_LENGTH / self.pen.widthF(), _DASH_GAP / self.pen.widthF()])
        self.pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        self.pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        self.setAcceptHoverEvents(True)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setZValue(-1)
        self.setCacheMode(QGraphicsItem.CacheMode.NoCache)
        identity = id(self)
        reference = weakref.ref(self)
        self.destroyed.connect(lambda: _release_destroyed_line(reference, identity))

    def itemChange(self, change, value):
        result = super().itemChange(change, value)
        if change == QGraphicsItem.GraphicsItemChange.ItemSceneHasChanged:
            if value is not None and not self._disposed:
                _display.attach(self)
            else:
                _display.detach(id(self))
        elif change == QGraphicsItem.GraphicsItemChange.ItemVisibleHasChanged:
            _display.focus_changed(self.scene())
        elif change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            _display.focus_changed(self.scene())
        return result

    def boundingRect(self):
        return self._bounds

    def shape(self):
        return self._shape

    def path(self):
        return QPainterPath(self._path)

    def route_points(self):
        return list(self._points)

    def clear_path(self):
        self.prepareGeometryChange()
        self._points = ()
        self._path = QPainterPath()
        self._shape = QPainterPath()
        self._dash_offset = 0.0
        self._bounds = self._path.boundingRect()
        self.update()

    def apply_route_points(self, points):
        if self._disposed:
            raise RuntimeError("已销毁的连线不能重新规划")
        normalized = orthogonal_points(points)
        if normalized == self._points:
            return False
        origin = normalized[0]
        path = painter_path_from_points([(x - origin[0], y - origin[1]) for x, y in normalized])
        stroker = QPainterPathStroker()
        stroker.setWidth(12.0)
        shape = stroker.createStroke(path)
        self.prepareGeometryChange()
        self._points, self._path, self._shape = normalized, path, shape
        self._bounds = shape.boundingRect().adjusted(-2, -2, 2, 2)
        self.setPos(QPointF(*origin))
        self.update()
        return True

    def get_start_pos(self):
        if self.start_item is None or not isValid(self.start_item):
            raise RuntimeError("连线起点已销毁")
        return self.start_item.get_output_port_scene_pos(self.line_type)

    def get_end_pos(self):
        if self.end_item is None or not isValid(self.end_item):
            raise RuntimeError("连线终点已销毁")
        return self.end_item.get_input_port_scene_pos("sequential" if self.line_type == "random" else self.line_type)

    def update_path(self):
        if self._disposed:
            return
        view = self.start_item.view
        if not view._loading_workflow and not view._rerouting_connections:
            view.reroute_connections((self.start_item, self.end_item))

    def set_line_color(self):
        self.pen.setColor(QColor(theme_color("connection_" + self.line_type)))
        self.update()

    def paint(self, painter, option, widget=None):
        if self._path.isEmpty():
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(self.pen)
        pen.setWidthF(2.8 if self.isSelected() else 2.6 if self._hovered else 2.0)
        # QPen 的虚线单位随线宽变化，按场景长度设置可避免悬停时节奏跳变。
        pen.setDashPattern([_DASH_LENGTH / pen.widthF(), _DASH_GAP / pen.widthF()])
        pen.setDashOffset(-self._dash_offset / pen.widthF())
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        # 交叉处保留细小的底色间隙，避免同色线路看起来像四向接点。
        gap_pen = QPen(QColor(theme_color("background")), pen.widthF() + 3.0)
        gap_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        gap_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(gap_pen)
        painter.drawPath(self._path)
        painter.setPen(pen)
        painter.drawPath(self._path)

    def hoverEnterEvent(self, event):
        self._hovered = True
        _display.focus_changed(self.scene())
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._hovered = False
        _display.focus_changed(self.scene())
        self.update()
        super().hoverLeaveEvent(event)

    def hoverMoveEvent(self, event):
        if not self._hovered:
            self._hovered = True
            _display.focus_changed(self.scene())
            self.update()
        super().hoverMoveEvent(event)

    def cleanup(self):
        if self._disposed:
            return
        self._disposed = True
        self._hovered = False
        self.setSelected(False)
        _display.detach(id(self))
        self.start_item = self.end_item = None
        self.clear_path()


def _release_destroyed_line(reference, identity):
    line = reference()
    if line is not None:
        line.start_item = line.end_item = None
        line._disposed = True
        line._hovered = False
        line._points = ()
        line._path = QPainterPath()
        line._shape = QPainterPath()
        line._dash_offset = 0.0
    _display.detach(identity)
