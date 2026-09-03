import logging
import copy
import math
import time
import weakref
logger = logging.getLogger(__name__)
from typing import TYPE_CHECKING, Optional, Dict, Any, List, Tuple

if TYPE_CHECKING:
    from .workflow_view import WorkflowView

from task_workflow.thread_window_binding import is_thread_window_limit_task_type
from shiboken6 import isValid as _qt_is_valid

IDLE_PORT_ANIMATION_CARD_THRESHOLD = 60
CARD_ANIMATION_ZOOM_STOP_THRESHOLD = 0.50
CARD_OVERVIEW_MODE_ZOOM_THRESHOLD = 0.45
CARD_ANIMATION_VIEWPORT_MARGIN = 30.0
CARD_OVERVIEW_MIN_BORDER_DEVICE_PX = 1.2
CARD_OVERVIEW_MAX_BORDER_SCENE_WIDTH = 3.5

from PySide6.QtWidgets import (QApplication,
                               QGraphicsSceneMouseEvent,
                               QStyleOptionGraphicsItem, QGraphicsDropShadowEffect,
                               QGraphicsSceneHoverEvent, QGraphicsObject, QGraphicsItem, QGraphicsLineItem)
from PySide6.QtCore import Qt, QRectF, QPointF, QSizeF, Signal, QTimer # <-- ADD Signal & QTimer
from PySide6.QtGui import QBrush, QPen, QColor, QPainter, QFont, QPainterPath, QConicalGradient, QRadialGradient


class SnapGuideLine(QGraphicsLineItem):
    """Snap guide line with local antialiasing for smoother dashes."""
    def paint(self, painter, option, widget=None):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        super().paint(painter, option, widget)
        painter.restore()

# --- REMOVED Signals moved outside class --- 
# delete_requested = Signal(int)
# copy_requested = Signal(int, dict) # Emit card_id and parameters
# paste_requested = Signal(QPointF) # Emit scene position for paste
# edit_settings_requested = Signal(int)
# ----------------------------------------

# Define port types - Keep for now, might be needed later
PORT_TYPE_SEQUENTIAL = 'sequential'
PORT_TYPE_SUCCESS = 'success'
PORT_TYPE_FAILURE = 'failure'
PORT_TYPE_RANDOM = 'random'
PORT_TYPES = [PORT_TYPE_SEQUENTIAL, PORT_TYPE_SUCCESS, PORT_TYPE_FAILURE, PORT_TYPE_RANDOM]

# --- CHANGED Inheritance from QGraphicsRectItem to QGraphicsObject --- 
class TaskCard(QGraphicsObject):
    """工作流画布中的任务卡片。"""
    VALID_EXECUTION_STATES = frozenset({"idle", "executing", "success", "failure"})
    # --- Signals moved back INSIDE the class ---
    delete_requested = Signal(int)
    copy_requested = Signal(int, dict) # Emit card_id and parameters
    edit_settings_requested = Signal(int)
    # --- ADDED Signal for jump target change ---
    jump_target_parameter_changed = Signal(str, int, int) # param_name, old_target_id, new_target_id
    # --- ADDED Signal for card click ---
    card_clicked = Signal(int) # Emit card_id
    # --- ADDED Signal for sub-workflow double click ---
    open_sub_workflow_requested = Signal(str)  # Emit workflow file path
    # -------------------------------------------
    _gradient_timer = None
    _gradient_cards = weakref.WeakSet()
    _gradient_phase = 0.0
    _gradient_interval_ms = 60
    _gradient_speed = 0.012
    _force_overview_mode = False

    @classmethod
    def _ensure_gradient_timer(cls):
        if cls._force_overview_mode:
            return
        if cls._gradient_timer is not None:
            if not cls._gradient_timer.isActive():
                cls._gradient_timer.start()
            return
        cls._gradient_timer = QTimer(QApplication.instance())
        cls._gradient_timer.setInterval(cls._gradient_interval_ms)
        cls._gradient_timer.timeout.connect(cls._tick_gradient)
        cls._gradient_timer.start()

    @classmethod
    def _stop_gradient_timer_if_idle(cls):
        try:
            if cls._gradient_cards:
                return
            if cls._gradient_timer is not None and cls._gradient_timer.isActive():
                cls._gradient_timer.stop()
        except Exception:
            pass

    @classmethod
    def get_gradient_animation_stats(cls) -> Dict[str, Any]:
        timer_active = False
        if cls._gradient_timer is not None:
            try:
                timer_active = bool(cls._gradient_timer.isActive())
            except Exception:
                timer_active = False
        try:
            registered_cards = len(cls._gradient_cards)
        except Exception:
            registered_cards = 0
        return {
            "registered_cards": int(registered_cards),
            "timer_active": bool(timer_active),
            "interval_ms": int(cls._gradient_interval_ms),
        }

    @classmethod
    def set_force_overview_mode(cls, enabled: bool):
        enabled = bool(enabled)
        if cls._force_overview_mode == enabled:
            return
        cls._force_overview_mode = enabled
        try:
            if enabled:
                if cls._gradient_timer is not None and cls._gradient_timer.isActive():
                    cls._gradient_timer.stop()
            elif cls._gradient_cards:
                cls._ensure_gradient_timer()
        except Exception:
            pass

        try:
            for card in list(cls._gradient_cards):
                try:
                    card.update()
                except RuntimeError:
                    cls._gradient_cards.discard(card)
        except Exception:
            pass

    @classmethod
    def _tick_gradient(cls):
        if cls._force_overview_mode:
            return
        if not cls._gradient_cards:
            cls._stop_gradient_timer_if_idle()
            return
        cls._gradient_phase += cls._gradient_speed
        if cls._gradient_phase >= 1.0:
            cls._gradient_phase -= 1.0
        viewport_rect_cache = {}
        scene_views_cache = {}
        visible_cards = []
        has_executing_visible_card = False
        for card in list(cls._gradient_cards):
            try:
                if not card.isVisible():
                    continue
                if not cls._is_card_in_viewport(card, viewport_rect_cache, scene_views_cache):
                    continue
                allow_zoom_animation = True
                should_animate_by_zoom = getattr(card, "_should_animate_by_zoom", None)
                if callable(should_animate_by_zoom):
                    allow_zoom_animation = bool(should_animate_by_zoom())
                if not allow_zoom_animation:
                    continue

                has_ports = True
                is_executing = getattr(card, "execution_state", "idle") != "idle"
                is_hovering = getattr(card, "hovered_port_side", None) is not None
                visible_cards.append((card, has_ports, is_executing, is_hovering))
                if is_executing:
                    has_executing_visible_card = True
            except RuntimeError:
                cls._gradient_cards.discard(card)

        for card, has_ports, is_executing, is_hovering in visible_cards:
            try:
                if is_executing or is_hovering:
                    card.update()
                    continue

                # 执行中优先保证运行卡片动画，空闲端口动画让路以减轻主线程负载
                if has_executing_visible_card:
                    continue

                allow_idle_port_animation = True
                should_animate_idle_ports = getattr(card, "_should_animate_idle_ports", None)
                if callable(should_animate_idle_ports):
                    allow_idle_port_animation = bool(should_animate_idle_ports())

                if allow_idle_port_animation and has_ports and not card.isSelected():
                    card.update()
            except RuntimeError:
                cls._gradient_cards.discard(card)
        cls._stop_gradient_timer_if_idle()

    @classmethod
    def _is_view_animatable(cls, view) -> bool:
        try:
            if view is None or not hasattr(view, "viewport"):
                return False
            if hasattr(view, "isVisible") and not view.isVisible():
                return False
            viewport = view.viewport()
            if viewport is None or not viewport.isVisible():
                return False
            viewport_rect = viewport.rect()
            return viewport_rect.width() > 0 and viewport_rect.height() > 0
        except Exception:
            return False

    @classmethod
    def _is_card_in_viewport(
        cls,
        card: "TaskCard",
        viewport_rect_cache: Dict[Any, Any],
        scene_views_cache: Optional[Dict[Any, Any]] = None,
    ) -> bool:
        try:
            scene = card.scene()
            if scene is None:
                return False

            card_rect = card.sceneBoundingRect()
            if card_rect.isEmpty():
                return False

            candidate_views = []
            preferred_view = getattr(card, "view", None)
            if preferred_view is not None:
                candidate_views.append(preferred_view)

            if scene_views_cache is not None:
                scene_views = scene_views_cache.get(scene)
                if scene_views is None:
                    scene_views = list(scene.views())
                    scene_views_cache[scene] = scene_views
            else:
                scene_views = list(scene.views())

            for scene_view in scene_views:
                if scene_view not in candidate_views:
                    candidate_views.append(scene_view)

            if not candidate_views:
                return False

            for view in candidate_views:
                if not cls._is_view_animatable(view):
                    continue

                if view not in viewport_rect_cache:
                    try:
                        visible_rect = view.mapToScene(view.viewport().rect()).boundingRect()
                        viewport_rect_cache[view] = visible_rect.adjusted(
                            -CARD_ANIMATION_VIEWPORT_MARGIN,
                            -CARD_ANIMATION_VIEWPORT_MARGIN,
                            CARD_ANIMATION_VIEWPORT_MARGIN,
                            CARD_ANIMATION_VIEWPORT_MARGIN,
                        )
                    except Exception:
                        viewport_rect_cache[view] = None

                cached_visible_rect = viewport_rect_cache.get(view)
                if cached_visible_rect is None:
                    return True

                if card_rect.intersects(cached_visible_rect):
                    return True

            return False
        except Exception:
            return False

    def _is_animation_visible(self) -> bool:
        """Check whether the current card is inside the visible viewport."""
        try:
            if not self.isVisible():
                return False
            if not hasattr(self, "scene") or self.scene() is None:
                return False
            return TaskCard._is_card_in_viewport(self, {})
        except Exception:
            return False

    def _register_gradient_animation(self):
        try:
            TaskCard._gradient_cards.add(self)
            TaskCard._ensure_gradient_timer()
        except Exception:
            pass

    def _unregister_gradient_animation(self):
        try:
            TaskCard._gradient_cards.discard(self)
            TaskCard._stop_gradient_timer_if_idle()
        except Exception:
            pass

    def _should_animate_idle_ports(self) -> bool:
        """Decide whether idle port animation should stay enabled."""
        try:
            if not self._should_animate_by_zoom():
                return False
            view = getattr(self, "view", None)
            if view is None:
                return True
            cards_map = getattr(view, "cards", None)
            if not isinstance(cards_map, dict):
                return True
            return len(cards_map) <= IDLE_PORT_ANIMATION_CARD_THRESHOLD
        except Exception:
            return False

    def _get_view_zoom_level(self) -> float:
        """Return the current view zoom level."""
        try:
            view = getattr(self, "view", None)
            if view is None:
                return 1.0
            transform = view.transform()
            return max(0.01, float(transform.m11()))
        except Exception:
            return 1.0

    def _should_animate_by_zoom(self) -> bool:
        """Disable animation when the zoom level is too low."""
        try:
            zoom_level = self._get_view_zoom_level()
            return zoom_level >= CARD_ANIMATION_ZOOM_STOP_THRESHOLD
        except Exception:
            return False

    def _is_overview_mode(self) -> bool:
        """When zoomed out enough, switch to overview mode for performance."""
        try:
            zoom_level = self._get_view_zoom_level()
            return zoom_level < CARD_OVERVIEW_MODE_ZOOM_THRESHOLD
        except Exception:
            return False

    
    def _get_theme_card_color(self):
        """返回当前主题的卡片背景色。"""
        return QColor(45, 45, 45) if self._is_dark_theme() else QColor(255, 255, 255)

    def _get_theme_title_color(self):
        """返回当前主题的标题区域颜色。"""
        return QColor(58, 58, 58) if self._is_dark_theme() else QColor(240, 240, 240)

    def _get_theme_text_color(self):
        """返回当前主题的文本颜色。"""
        return QColor(224, 224, 224) if self._is_dark_theme() else QColor(20, 20, 20)

    def _is_dark_theme(self):
        """返回当前是否为深色主题。"""
        from themes import get_theme_manager

        return bool(get_theme_manager().is_dark_mode())

    def _apply_visual_profile(self):
        """Apply a unified visual profile for card rendering."""
        is_dark = self._is_dark_theme()

        if is_dark:
            self._card_surface_top = QColor(49, 54, 64, 242)
            self._card_surface_bottom = QColor(38, 42, 50, 238)
            self._title_surface_top = QColor(61, 68, 80, 228)
            self._title_surface_bottom = QColor(52, 58, 70, 220)
            self._inner_stroke_color = QColor(255, 255, 255, 18)
            self._title_sheen_alpha = 12
            self._title_shadow_color = QColor(0, 0, 0, 95)
            self._divider_color = QColor(255, 255, 255, 22)
            idle_border = QColor(126, 142, 165, 154)

            self.default_shadow_color = QColor(0, 0, 0, 82)
            self.default_shadow_blur = 14
            self.default_shadow_offset = 3
            self.selection_shadow_color = QColor(66, 133, 244, 122)
            self.selection_shadow_blur = 20
            self.selection_shadow_offset = 5

            self.state_colors = {
                'idle': QColor(44, 49, 58),
                'executing': QColor(45, 65, 94),
                'success': QColor(41, 74, 57),
                'failure': QColor(92, 52, 61),
            }
        else:
            self._card_surface_top = QColor(255, 255, 255, 246)
            self._card_surface_bottom = QColor(246, 250, 255, 240)
            self._title_surface_top = QColor(255, 255, 255, 244)
            self._title_surface_bottom = QColor(246, 250, 255, 236)
            self._inner_stroke_color = QColor(255, 255, 255, 128)
            self._title_sheen_alpha = 28
            self._title_shadow_color = QColor(255, 255, 255, 84)
            self._divider_color = QColor(156, 174, 198, 96)
            idle_border = QColor(176, 194, 216, 194)

            self.default_shadow_color = QColor(24, 58, 112, 28)
            self.default_shadow_blur = 12
            self.default_shadow_offset = 2
            self.selection_shadow_color = QColor(0, 120, 215, 96)
            self.selection_shadow_blur = 18
            self.selection_shadow_offset = 4

            self.state_colors = {
                'idle': QColor(249, 252, 255),
                'executing': QColor(225, 239, 255),
                'success': QColor(223, 246, 235),
                'failure': QColor(255, 232, 236),
            }

        self.state_accent_colors = {
            'idle': QColor(92, 150, 255),
            'executing': QColor(53, 149, 255),
            'success': QColor(46, 181, 117),
            'failure': QColor(235, 96, 116),
        }

        self.state_border_pens = {
            'idle': QPen(idle_border, 1.2),
            'executing': QPen(QColor(53, 149, 255), 2.1),
            'success': QPen(QColor(45, 178, 114), 2.1),
            'failure': QPen(QColor(233, 92, 112), 2.1),
        }
    def _should_enable_shadow_on_init(self) -> bool:
        """Decide whether shadow creation should be delayed on init."""
        try:
            view = getattr(self, "view", None)
            if view is None:
                return True
            cards = getattr(view, "cards", None)
            threshold_getter = getattr(view, "_get_card_shadow_disable_threshold", None)
            if not isinstance(cards, dict) or not callable(threshold_getter):
                return True
            threshold = int(threshold_getter())
            return len(cards) < threshold
        except Exception:
            return True

    def _ensure_shadow_effect(self):
        if getattr(self, "shadow", None) is not None:
            return self.shadow
        try:
            shadow = QGraphicsDropShadowEffect()
            shadow.setBlurRadius(self.default_shadow_blur)
            shadow.setColor(QColor(self.default_shadow_color))
            shadow.setOffset(0, self.default_shadow_offset)
            shadow.setEnabled(True)
            self.shadow = shadow
            self.setGraphicsEffect(shadow)
            return shadow
        except Exception:
            self.shadow = None
            return None

    def _release_shadow_effect(self) -> None:
        shadow = getattr(self, "shadow", None)
        if shadow is None:
            return
        try:
            shadow.setEnabled(False)
        except Exception:
            pass
        try:
            self.setGraphicsEffect(None)
        except Exception:
            pass
        try:
            if hasattr(shadow, "deleteLater"):
                shadow.deleteLater()
        except Exception:
            pass
        self.shadow = None

    def _cleanup_timer_attr(self, attr_name: str, timeout_slot) -> None:
        timer = getattr(self, attr_name, None)
        if timer is None:
            setattr(self, attr_name, None)
            return
        timer.stop()
        try:
            timer.timeout.disconnect(timeout_slot)
        except (TypeError, RuntimeError):
            pass
        timer.deleteLater()
        setattr(self, attr_name, None)

    def _release_drag_check_timer(self) -> None:
        self._cleanup_timer_attr("_drag_check_timer", self._check_drag_state)

    def __init__(self, view: 'WorkflowView', x: float, y: float, task_type: str, card_id: int, task_module: Any, width: int = 200):
        if view is None or not callable(getattr(view, "_is_workflow_running", None)):
            raise TypeError("任务卡片必须绑定有效的 WorkflowView")
        if not isinstance(task_type, str) or not task_type.strip():
            raise TypeError("任务类型必须是非空字符串")
        if isinstance(card_id, bool) or not isinstance(card_id, int) or card_id < 0:
            raise TypeError("卡片 ID 必须是非负整数")
        if task_module is None or not callable(getattr(task_module, "get_params_definition", None)):
            raise TypeError(f"任务 {task_type} 缺少参数定义入口")
        self.initial_height = 60 # Simplified height
        # --- ADJUSTED super().__init__() call for QGraphicsObject --- 
        # QGraphicsObject init doesn't take rect args directly like QGraphicsRectItem
        # We might need to set a parent QGraphicsItem if needed, but for now None is okay.
        super().__init__(None) # Call QGraphicsObject's init 
        # -------------------------------------------------------------
        self.view = view
        self.task_type = task_type
        self._width = self._align_size_to_grid(width) # Store width for boundingRect
        self._height = self._align_size_to_grid(self.initial_height) # Store height for boundingRect
        self.setPos(x, y) 
        self._last_group_pos = self.pos()

        self.card_id = card_id
        self.sequence_id: Optional[int] = None # <<< ADDED: Dynamic sequence ID, initially None
        self.display_id = card_id # Initialize display_id (maybe remove later?)
        self.custom_name: Optional[str] = None # 用户自定义的备注名称
        self.title = f"{task_type} (ID: {self.card_id})" # Use card_id directly
        self.task_module = task_module # Keep reference
        self.parameters: Dict[str, Any] = {} 
        self.param_definitions: Dict[str, Dict[str, Any]] = {} 
        self.connections = [] # Keep connections list
        
        # --- ADDED: Flag for restricted output ports ---
        self.restricted_outputs = self._calculate_restricted_outputs()
        # --- ADDED: Flag for cards with no input ports ---
        self.no_input_ports = self._calculate_no_input_ports()
        # --------------------------------------------
        
        # Basic Item Flags (QGraphicsObject inherits QGraphicsItem flags)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges) # Needed for connections
        # self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemClipsChildrenToShape, True) # Might not be needed or available
        self.setAcceptHoverEvents(True)

        self.setCacheMode(QGraphicsItem.CacheMode.NoCache)

        # Drag-related throttling.
        self._last_connection_update_time = 0.0
        self._connection_update_interval = 0.033
        self._last_snap_guide_update_time = 0.0
        self._snap_guide_update_interval = 0.04

        self.border_radius = 9
        self.card_color = self._get_theme_card_color()
        self.title_area_color = self._get_theme_title_color()
        self.title_color = self._get_theme_text_color()
        self.port_radius = 4.8
        self.port_border_width = 1.2
        self.port_idle_color = QColor(180, 180, 180) 
        self.port_hit_radius = 12.0 # Keep hit radius large
        self.text_padding = 8 # Padding around the content area
        self.param_padding = 5 # Internal padding within the content layout
        self.default_pen = QPen(Qt.PenStyle.NoPen)
        self.title_font = QFont("Segoe UI", 10)
        self.title_font.setBold(True) 
        self.param_font = QFont("Segoe UI", 8) 
        self.port_colors = {
            PORT_TYPE_SEQUENTIAL: QColor(66, 133, 244),
            PORT_TYPE_SUCCESS: QColor(52, 168, 83),
            PORT_TYPE_FAILURE: QColor(234, 67, 53),
            PORT_TYPE_RANDOM: QColor(123, 97, 255)
        }
        self.port_hover_color_boost = 40 # How much brighter/lighter on hover

        # Unified visual profile (colors, borders, shadows)
        self.shadow = None
        self.execution_state = 'idle'
        self._apply_visual_profile()
        self._cached_bg_color = self.state_colors.get('idle', self.card_color)
        self._cached_border_pen = self.state_border_pens.get('idle', self.default_pen)

        self._shadow_rendering_enabled = self._should_enable_shadow_on_init()
        if self._shadow_rendering_enabled:
            self._ensure_shadow_effect()
        # --- ADDED: Store current border pen for flash --- 
        self._current_border_pen = self.default_pen # Start with default
        self._original_border_pen_before_flash = self.default_pen
        # --- MODIFIED: Timer for continuous toggle, not single shot ---
        self._is_flashing = False # Flag for persistent flashing
        self.flash_toggle_timer = None  # Lazy init when flash starts
        self.flash_interval_ms = 300 # Interval for toggling flash visual state
        self.flash_border_pen = QPen(QColor(255, 165, 0), 3) # Orange, thick border for flash (next step)
        self._flash_border_on = False # Internal state for toggling appearance
        # --------------------------------------------------------

        self._drag_check_timer = None

        # --- REMOVED setBrush and setPen (QGraphicsObject doesn't have them directly) --- 
        # We draw everything in paint()
        # self.setBrush(QBrush(self.card_color))
        # self.setPen(self.default_pen)
        # -----------------------------------------------------------------------------

        # Hover state for ports
        self.hovered_port_side: Optional[str] = None
        self.hovered_port_type: Optional[str] = None
        
        # --- Load parameters --- 
        self.load_and_create_parameters() 
        # ------------------------
        
        # --- ADDED: Enable ToolTips for hover events ---
        self.setAcceptHoverEvents(True) # Ensure hover events are enabled
        self.setToolTip("") # Initialize tooltip, hoverEnterEvent will populate it
        # --- END ADDED ---

        # --- ADDED: Tooltip caching for performance optimization ---
        self._cached_tooltip = ""
        self._tooltip_needs_update = True
        self._register_gradient_animation()
        self._hover_timer = None  # 用于延迟显示工具提示
        # --- END ADDED ---


    # --- ADDED boundingRect method (Required by QGraphicsObject) --- 
    def boundingRect(self) -> QRectF:
        """Returns the bounding rectangle of the item."""
        # Use stored width/height
        return QRectF(0, 0, self._width, self._height) 
    # -------------------------------------------------------------

    def _get_size_grid_unit(self) -> float:
        """返回当前画布的尺寸对齐网格。"""
        spacing = self.view._grid_spacing
        if isinstance(spacing, bool) or not isinstance(spacing, (int, float)):
            raise TypeError("画布网格间距必须是数字")
        if not math.isfinite(spacing) or spacing <= 1.0:
            raise ValueError("画布网格间距必须是大于 1 的有限数字")
        return float(spacing)

    def _align_size_to_grid(self, value: float, minimum: float = 0.0) -> float:
        """Align size to grid spacing, using upward rounding to avoid clipping."""
        unit = self._get_size_grid_unit()
        safe_value = max(float(value), float(minimum), unit)
        return float(math.ceil(safe_value / unit) * unit)

    def set_size(self, width: float, height: float):
        width = self._align_size_to_grid(width)
        height = self._align_size_to_grid(height)
        if width == self._width and height == self._height:
            return
        self.prepareGeometryChange()
        self._width = width
        self._height = height
        self.update()
        for connection in self._validated_connections():
            connection.update_path()

    def _validated_connections(self):
        """返回严格登记且属于当前场景的连接，不修改任何状态。"""
        if not isinstance(self.connections, list):
            raise TypeError(f"卡片 {self.card_id} 的连接容器必须是列表")
        view_connections = self.view.connections
        if not isinstance(view_connections, list):
            raise TypeError("工作流连接容器必须是列表")
        card_scene = self.scene()
        validated = []
        seen = set()
        for connection in self.connections:
            marker = id(connection)
            if marker in seen or self.connections.count(connection) != 1:
                raise RuntimeError(f"卡片 {self.card_id} 重复登记同一连接")
            seen.add(marker)
            if not _qt_is_valid(connection):
                raise RuntimeError(f"卡片 {self.card_id} 登记了失效连接")
            if view_connections.count(connection) != 1:
                raise RuntimeError(f"卡片 {self.card_id} 的连接未在视图中登记一次")
            start_item = getattr(connection, "start_item", None)
            end_item = getattr(connection, "end_item", None)
            if self is not start_item and self is not end_item:
                raise RuntimeError(f"卡片 {self.card_id} 登记了不属于自己的连接")
            if connection.scene() is not card_scene:
                raise RuntimeError(f"卡片 {self.card_id} 的连接未挂载到同一场景")
            if not callable(getattr(connection, "update_path", None)):
                raise TypeError("连接对象缺少路径更新入口")
            validated.append(connection)
        return tuple(validated)

    def _other_card_for_connection(self, connection):
        if connection.start_item is self:
            other_card = connection.end_item
        elif connection.end_item is self:
            other_card = connection.start_item
        else:
            raise RuntimeError(f"连接不属于卡片 {self.card_id}")
        if other_card is self:
            return None
        if not isinstance(other_card, TaskCard):
            raise TypeError("连接另一端必须是 TaskCard")
        if other_card.scene() is not self.scene():
            raise RuntimeError("连接另一端卡片不属于当前场景")
        return other_card

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget=None):
        """Custom painting for rounded corners, title, ports, and state highlight."""
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

            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

            rect = self.boundingRect()
            path = QPainterPath()
            path.addRoundedRect(rect, self.border_radius, self.border_radius)

            painter.setPen(Qt.PenStyle.NoPen)
            state = getattr(self, "execution_state", "idle")
            zoom_level = self._get_view_zoom_level()
            overview_mode = TaskCard._force_overview_mode or zoom_level < CARD_OVERVIEW_MODE_ZOOM_THRESHOLD
            if overview_mode:
                high_quality_hint = getattr(QPainter.RenderHint, "HighQualityAntialiasing", None)
                if high_quality_hint is not None:
                    painter.setRenderHint(high_quality_hint, True)
            flat_color = QColor(self.state_colors.get(state, self.card_color))
            flat_color.setAlpha(245)
            painter.fillPath(path, QBrush(flat_color))

            # Inner stroke
            if not overview_mode:
                inner_rect = rect.adjusted(1.0, 1.0, -1.0, -1.0)
                if inner_rect.width() > 0 and inner_rect.height() > 0:
                    inner_path = QPainterPath()
                    inner_path.addRoundedRect(inner_rect, max(2.0, self.border_radius - 1.0), max(2.0, self.border_radius - 1.0))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.setPen(QPen(self._inner_stroke_color, 1.0))
                    painter.drawPath(inner_path)

            # Border state machine
            effective_border_pen = self.default_pen
            if self._is_flashing:
                effective_border_pen = self._current_border_pen
            else:
                if state == 'idle':
                    effective_border_pen = self.state_border_pens.get('idle', self.default_pen)
                else:
                    effective_border_pen = self._cached_border_pen

            if effective_border_pen != QPen(Qt.PenStyle.NoPen):
                painter.setBrush(Qt.BrushStyle.NoBrush)
                if overview_mode:
                    smooth_pen = QPen(effective_border_pen)
                    smooth_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                    smooth_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                    smooth_pen.setCosmetic(False)
                    zoom_for_width = max(0.05, zoom_level)
                    min_scene_width_for_device_px = CARD_OVERVIEW_MIN_BORDER_DEVICE_PX / zoom_for_width
                    overview_width = max(effective_border_pen.widthF() * 0.9, min_scene_width_for_device_px)
                    smooth_pen.setWidthF(min(CARD_OVERVIEW_MAX_BORDER_SCENE_WIDTH, overview_width))
                    painter.setPen(smooth_pen)
                else:
                    painter.setPen(effective_border_pen)
                painter.drawPath(path)

            # Title text: keep it inside title area so connection lines do not overlap.
            painter.setFont(self.title_font)
            if (not overview_mode) and (not self._should_hide_title()):
                # Center text in the full card content area (both horizontal and vertical).
                title_text_rect = rect.adjusted(12.0, 0.0, -12.0, 0.0)
                painter.setPen(QPen(self.title_color))
                painter.drawText(
                    title_text_rect,
                    Qt.AlignmentFlag.AlignCenter,
                    self.title,
                )

            if not overview_mode:
                phase = TaskCard._gradient_phase
                allow_idle_animation = self._should_animate_idle_ports()
                for side, port_type in self._iter_render_ports():
                    self._draw_single_port(
                        painter,
                        side,
                        port_type,
                        phase,
                        allow_idle_animation,
                    )
        except (RuntimeError, AttributeError):
            pass
        except Exception:
            pass
    # ------------------------------
    def _should_hide_title(self) -> bool:
        return False


    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        """Handle clicks for port dragging and card selection/movement."""
        if event.button() == Qt.MouseButton.LeftButton:
            port_info = self.get_port_at(event.pos())
            if port_info and port_info['side'] == 'output':
                self.view.start_drag_line(self, port_info['type'])
                event.accept()
                return

        if event.button() == Qt.MouseButton.RightButton:
            event.accept()
            return

        if event.button() == Qt.MouseButton.LeftButton:
            port_info = self.get_port_at(event.pos())
            if not (port_info and port_info['side'] == 'output'):
                self.card_clicked.emit(self.card_id)

        scene = self.scene()
        if scene:
            if not self.isSelected():
                modifiers = QApplication.keyboardModifiers()
                if not (modifiers & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)):
                    scene.clearSelection()
                self.setSelected(True)

        self._drag_start_pos = event.scenePos()
        self._drag_start_card_pos = self.pos()
        self._drag_start_card_pos_for_snap = self.pos()
        self._dragging_multi_selection = False
        self._is_dragging = True
        self._last_connection_update_time = 0.0
        self._last_snap_guide_update_time = 0.0

        timer = getattr(self, "_drag_check_timer", None)
        if timer is None:
            try:
                timer = QTimer(self)
                timer.timeout.connect(self._check_drag_state)
                self._drag_check_timer = timer
            except Exception:
                self._drag_check_timer = None
                timer = None
        if timer is not None:
            timer.start(100)

        if scene:
            selected_items = scene.selectedItems()
            selected_cards = [item for item in selected_items if isinstance(item, TaskCard) and item != self]
            if selected_cards:
                self._other_selected_cards_start_positions = {
                    card: card.pos() for card in selected_cards
                }
                for card in selected_cards:
                    card._is_dragging = True
                    card._multi_dragging_member = True
                    card._last_connection_update_time = 0.0
                self._dragging_multi_selection = True
            else:
                self._other_selected_cards_start_positions = {}

        super().mousePressEvent(event)


    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent):
        """Handle mouse move for multi-selection dragging and snap guide lines."""
        if getattr(self, '_dragging_multi_selection', False) and getattr(self, '_other_selected_cards_start_positions', None):
            delta = event.scenePos() - self._drag_start_pos

            for card, start_pos in self._other_selected_cards_start_positions.items():
                new_pos = start_pos + delta
                if card.pos() != new_pos:
                    card.setPos(new_pos)
        else:
            self._update_snap_guide_lines()

        super().mouseMoveEvent(event)
        if getattr(self, '_dragging_multi_selection', False):
            self._refresh_dragged_connections()

    def _refresh_dragged_connections(self):
        """在多选卡片完成同一帧位置更新后统一刷新受影响连线。"""
        cards = [self]
        cards.extend(getattr(self, '_other_selected_cards_start_positions', {}).keys())
        connections = []
        seen = set()
        for card in cards:
            for connection in list(getattr(card, 'connections', [])):
                marker = id(connection)
                if marker in seen:
                    continue
                seen.add(marker)
                connections.append(connection)
        for connection in connections:
            if connection.scene() is self.scene():
                connection.update_path()

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        """Handle mouse release and finalize dragging state."""
        start_pos = getattr(self, '_drag_start_card_pos', None)
        partner_starts = dict(getattr(self, '_other_selected_cards_start_positions', {}) or {})
        was_multi_dragging = getattr(self, '_dragging_multi_selection', False)
        partner_cards = list(partner_starts.keys())

        self._dragging_multi_selection = False
        self._other_selected_cards_start_positions = {}
        self._drag_start_pos = None
        self._drag_start_card_pos = None
        self._is_dragging = False
        for card in partner_cards:
            card._is_dragging = False
            card._multi_dragging_member = False

        self._release_drag_check_timer()
        self._clear_snap_guide_lines()

        super().mouseReleaseEvent(event)

        if start_pos is not None and not was_multi_dragging:
            self._apply_grid_snap()
            self._apply_snap_alignment()

        self._drag_start_card_pos_for_snap = None

        moved_cards = []
        if start_pos is not None and self.pos() != start_pos:
            moved_cards.append(self)
        for card, partner_start in partner_starts.items():
            if card.pos() != partner_start:
                moved_cards.append(card)
        if moved_cards:
            notify = getattr(self.view, "_notify_cards_moved", None)
            if callable(notify):
                notify(moved_cards)


    def _cancel_drag_state(self):
        """取消拖拽状态并清理辅助线，用于异常中断场景。"""
        other_cards = getattr(self, '_other_selected_cards_start_positions', None)
        if other_cards:
            for card in list(other_cards.keys()):
                card._is_dragging = False
                card._multi_dragging_member = False
        self._dragging_multi_selection = False
        self._other_selected_cards_start_positions = {}
        self._drag_start_pos = None
        self._drag_start_card_pos = None
        self._drag_start_card_pos_for_snap = None  # 清理吸附用的起始位置
        self._is_dragging = False
        self._clear_snap_guide_lines()
        # 停止拖拽检测定时器
        self._release_drag_check_timer()


    def mouseDoubleClickEvent(self, event: QGraphicsSceneMouseEvent):
        """Handle double-clicks, including opening sub-workflow cards."""
        if event.button() == Qt.MouseButton.LeftButton:
            if self._is_workflow_running():
                event.accept()
                return

            if self.task_type == "子工作流":
                workflow_file = self.parameters.get('workflow_file')
                if workflow_file:
                    self.open_sub_workflow_requested.emit(workflow_file)
                    event.accept()
                    return

            self.edit_settings_requested.emit(self.card_id)
            event.accept()
            return

        super().mouseDoubleClickEvent(event)

    def _check_drag_state(self):
        """Poll the drag state and clear it after mouse release."""
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        if not (QApplication.mouseButtons() & Qt.MouseButton.LeftButton):
            self._cancel_drag_state()

    def focusOutEvent(self, event):
        """Clear drag state when the card loses focus."""
        self._cancel_drag_state()
        super().focusOutEvent(event)


    def _update_snap_guide_lines(self):
        """Update snap guide lines for connected cards."""
        if not self.view or not self.view.is_card_snap_enabled():
            self._clear_snap_guide_lines()
            return

        if not getattr(self, '_is_dragging', False):
            return

        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        if not (QApplication.mouseButtons() & Qt.MouseButton.LeftButton):
            self._cancel_drag_state()
            return

        now = time.perf_counter()
        if now - self._last_snap_guide_update_time < self._snap_guide_update_interval:
            return
        self._last_snap_guide_update_time = now

        if not self.scene():
            return

        self._clear_snap_guide_lines()

        snap_threshold = 50
        current_pos = self.pos()
        current_rect = self.boundingRect()
        current_center_x = current_pos.x() + current_rect.width() / 2
        current_center_y = current_pos.y() + current_rect.height() / 2

        if not hasattr(self, '_snap_guide_lines'):
            self._snap_guide_lines = []

        for connection in self._validated_connections():
            other_card = self._other_card_for_connection(connection)
            if other_card is None:
                continue

            other_pos = other_card.pos()
            other_rect = other_card.boundingRect()
            other_center_x = other_pos.x() + other_rect.width() / 2
            other_center_y = other_pos.y() + other_rect.height() / 2

            y_diff = abs(current_center_y - other_center_y)
            x_diff = abs(current_center_x - other_center_x)

            guide_pen = QPen(QColor(0, 120, 215, 180), 1.0, Qt.PenStyle.DashLine)
            guide_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            guide_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            guide_pen.setDashPattern([4, 3])
            guide_pen.setCosmetic(True)

            curr_top_left = (current_pos.x(), current_pos.y())
            curr_top_right = (current_pos.x() + current_rect.width(), current_pos.y())
            curr_bottom_left = (current_pos.x(), current_pos.y() + current_rect.height())
            curr_bottom_right = (current_pos.x() + current_rect.width(), current_pos.y() + current_rect.height())

            other_top_left = (other_pos.x(), other_pos.y())
            other_top_right = (other_pos.x() + other_rect.width(), other_pos.y())
            other_bottom_left = (other_pos.x(), other_pos.y() + other_rect.height())
            other_bottom_right = (other_pos.x() + other_rect.width(), other_pos.y() + other_rect.height())

            if y_diff < snap_threshold:
                if current_center_x < other_center_x:
                    line1 = SnapGuideLine()
                    line1.setPen(guide_pen)
                    line1.setLine(curr_top_right[0], curr_top_right[1], other_top_left[0], other_top_left[1])
                    self.scene().addItem(line1)
                    self._snap_guide_lines.append(line1)

                    line2 = SnapGuideLine()
                    line2.setPen(guide_pen)
                    line2.setLine(curr_bottom_right[0], curr_bottom_right[1], other_bottom_left[0], other_bottom_left[1])
                    self.scene().addItem(line2)
                    self._snap_guide_lines.append(line2)
                else:
                    line1 = SnapGuideLine()
                    line1.setPen(guide_pen)
                    line1.setLine(other_top_right[0], other_top_right[1], curr_top_left[0], curr_top_left[1])
                    self.scene().addItem(line1)
                    self._snap_guide_lines.append(line1)

                    line2 = SnapGuideLine()
                    line2.setPen(guide_pen)
                    line2.setLine(other_bottom_right[0], other_bottom_right[1], curr_bottom_left[0], curr_bottom_left[1])
                    self.scene().addItem(line2)
                    self._snap_guide_lines.append(line2)

            if x_diff < snap_threshold:
                if current_center_y < other_center_y:
                    line1 = SnapGuideLine()
                    line1.setPen(guide_pen)
                    line1.setLine(curr_bottom_left[0], curr_bottom_left[1], other_top_left[0], other_top_left[1])
                    self.scene().addItem(line1)
                    self._snap_guide_lines.append(line1)

                    line2 = SnapGuideLine()
                    line2.setPen(guide_pen)
                    line2.setLine(curr_bottom_right[0], curr_bottom_right[1], other_top_right[0], other_top_right[1])
                    self.scene().addItem(line2)
                    self._snap_guide_lines.append(line2)
                else:
                    line1 = SnapGuideLine()
                    line1.setPen(guide_pen)
                    line1.setLine(other_bottom_left[0], other_bottom_left[1], curr_top_left[0], curr_top_left[1])
                    self.scene().addItem(line1)
                    self._snap_guide_lines.append(line1)

                    line2 = SnapGuideLine()
                    line2.setPen(guide_pen)
                    line2.setLine(other_bottom_right[0], other_bottom_right[1], curr_top_right[0], curr_top_right[1])
                    self.scene().addItem(line2)
                    self._snap_guide_lines.append(line2)


    def _clear_snap_guide_lines(self):
        """Clear all active snap guide lines."""
        if hasattr(self, '_snap_guide_lines'):
            for line in self._snap_guide_lines:
                if line.scene():
                    line.scene().removeItem(line)
            self._snap_guide_lines.clear()


    def get_port_pos(self, side: str, port_type: str = PORT_TYPE_SEQUENTIAL) -> QPointF:
        rect = self.boundingRect()
        center_y = rect.center().y()

        port_inset = self.port_radius + 2
        spacing = 15
        if port_type == PORT_TYPE_SUCCESS:
            final_y = center_y - spacing
        elif port_type == PORT_TYPE_FAILURE:
            final_y = center_y + spacing
        else:
            final_y = center_y

        x = rect.left() + port_inset if side == 'left' else rect.right() - port_inset
        return QPointF(x, final_y)

    def _iter_render_ports(self) -> List[Tuple[str, str]]:
        ports: List[Tuple[str, str]] = []
        for side in ("left", "right"):
            if side == "left" and self.no_input_ports:
                continue

            for port_type in PORT_TYPES:
                if side == "right" and self.restricted_outputs == "random_only":
                    if port_type != PORT_TYPE_RANDOM:
                        continue
                elif side == "right" and self.restricted_outputs and port_type != PORT_TYPE_SEQUENTIAL:
                    continue
                elif port_type == PORT_TYPE_RANDOM and side == "left":
                    continue
                elif port_type == PORT_TYPE_RANDOM and self.restricted_outputs != "random_only":
                    continue

                ports.append((side, port_type))

        return ports

    def _is_port_hovered(self, side: str, port_type: str) -> bool:
        target_side = "input" if side == "left" else "output"
        return self.hovered_port_side == target_side and self.hovered_port_type == port_type

    def _draw_single_port(self, painter: QPainter, side: str, port_type: str, phase: float, allow_idle_animation: bool):
        base_color = self.port_colors.get(port_type, QColor(140, 140, 140))
        is_hovered = self._is_port_hovered(side, port_type)
        can_idle_animate = allow_idle_animation and (not is_hovered) and (not self.isSelected())
        show_animation = is_hovered or can_idle_animate
        is_input_port = side == "left"

        side_phase = phase + (0.18 if side == "right" else 0.72)
        pulse = 0.5 + 0.5 * math.sin(side_phase * math.tau)

        color = QColor(base_color)
        if not is_hovered:
            color = QColor(
                int(color.red() * 0.85 + self.card_color.red() * 0.15),
                int(color.green() * 0.85 + self.card_color.green() * 0.15),
                int(color.blue() * 0.85 + self.card_color.blue() * 0.15),
            )

        radius = self.port_radius + (0.95 if is_hovered else (0.22 * pulse if show_animation else 0.0))
        center = self.get_port_pos(side, port_type)
        rect = QRectF(center.x() - radius, center.y() - radius, radius * 2.0, radius * 2.0)

        if show_animation:
            halo_radius = radius + (1.4 + 0.6 * pulse)
            halo = QRadialGradient(center, halo_radius)
            halo_head = QColor(color.lighter(150))
            halo_head.setAlpha(120 if is_hovered else int(70 + 35 * pulse))
            halo_tail = QColor(color)
            halo_tail.setAlpha(0)
            halo.setColorAt(0.0, halo_head)
            halo.setColorAt(1.0, halo_tail)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(halo))
            painter.drawEllipse(
                QRectF(
                    center.x() - halo_radius,
                    center.y() - halo_radius,
                    halo_radius * 2.0,
                    halo_radius * 2.0,
                )
            )

        shell_color = QColor(color.lighter(118))
        shell_color.setAlpha(228 if is_hovered else 190)
        shell_width = self.port_border_width + (0.34 if is_hovered else 0.14)
        shell_pen = QPen(shell_color, shell_width)
        shell_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

        if is_input_port:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(shell_pen)
            painter.drawEllipse(rect)

            inner_ring = rect.adjusted(1.0, 1.0, -1.0, -1.0)
            inner_color = QColor(color.lighter(142))
            inner_color.setAlpha(92 if is_hovered else 58)
            painter.setPen(QPen(inner_color, 0.9))
            painter.drawEllipse(inner_ring)
        else:
            core_inner = QColor(color.lighter(138 if is_hovered else 126))
            core_inner.setAlpha(235 if is_hovered else 205)
            core_outer = QColor(color.darker(118 if is_hovered else 126))
            core_outer.setAlpha(220 if is_hovered else 185)

            core_grad = QRadialGradient(center, radius)
            core_grad.setColorAt(0.0, core_inner)
            core_grad.setColorAt(0.72, core_outer)
            edge_color = QColor(core_outer)
            edge_color.setAlpha(150 if is_hovered else 120)
            core_grad.setColorAt(1.0, edge_color)

            painter.setBrush(QBrush(core_grad))
            painter.setPen(shell_pen)
            painter.drawEllipse(rect)

        if show_animation:
            sweep_angle = ((phase * 360.0) + 20.0) % 360.0
            conical = QConicalGradient(center, sweep_angle)
            head = QColor(color.lighter(180))
            head.setAlpha(245 if is_hovered else 210)
            mid = QColor(color.lighter(140))
            mid.setAlpha(205 if is_hovered else 165)
            tail = QColor(color)
            tail.setAlpha(0)
            conical.setColorAt(0.0, head)
            conical.setColorAt(0.18, mid)
            conical.setColorAt(0.34, tail)
            conical.setColorAt(1.0, head)

            sweep_pen = QPen(QBrush(conical), self.port_border_width + (0.9 if is_hovered else 0.62))
            sweep_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            sweep_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(sweep_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(rect.adjusted(-0.35, -0.35, 0.35, 0.35))

    def shape(self) -> QPainterPath:
        """Define the precise shape for collision detection and painting."""
        path = QPainterPath()
        # Use the bounding rectangle which already includes potential padding
        path.addRoundedRect(self.boundingRect(), self.border_radius, self.border_radius)
        return path

    def itemChange(self, change, value):
        """Override to update connections when the card moves."""
        if change == QGraphicsItem.GraphicsItemChange.ItemSceneHasChanged:
            if value is None:
                self._unregister_gradient_animation()
                self._release_drag_check_timer()
                self.stop_flash()
            else:
                self._register_gradient_animation()

        # Handle selection change for shadow effect
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedChange:
            selected = value
            self.update_selection_effect(selected)

        result = super().itemChange(change, value)

        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            if getattr(self, '_multi_dragging_member', False) or getattr(self, '_dragging_multi_selection', False):
                return result

            for connection in self._validated_connections():
                connection.update_path()

        return result

    def _apply_snap_alignment(self):
        """Apply snap alignment against connected cards."""
        if not self.view or not self.view.is_card_snap_enabled():
            return

        max_snap_distance = 50
        current_pos = self.pos()
        current_rect = self.boundingRect()
        current_center_x = current_pos.x() + current_rect.width() / 2
        current_center_y = current_pos.y() + current_rect.height() / 2

        best_snap_x = None
        best_snap_y = None
        min_x_move = max_snap_distance + 1
        min_y_move = max_snap_distance + 1

        for connection in self._validated_connections():
            other_card = self._other_card_for_connection(connection)
            if other_card is None:
                continue

            other_pos = other_card.pos()
            other_rect = other_card.boundingRect()
            other_center_x = other_pos.x() + other_rect.width() / 2
            other_center_y = other_pos.y() + other_rect.height() / 2

            y_diff = abs(current_center_y - other_center_y)
            x_diff = abs(current_center_x - other_center_x)

            if y_diff < max_snap_distance:
                aligned_y = other_pos.y() + (other_rect.height() - current_rect.height()) / 2
                move_distance = abs(current_pos.y() - aligned_y)
                if move_distance < max_snap_distance and move_distance < min_y_move:
                    min_y_move = move_distance
                    best_snap_y = aligned_y

            if x_diff < max_snap_distance:
                aligned_x = other_pos.x() + (other_rect.width() - current_rect.width()) / 2
                move_distance = abs(current_pos.x() - aligned_x)
                if move_distance < max_snap_distance and move_distance < min_x_move:
                    min_x_move = move_distance
                    best_snap_x = aligned_x

        final_pos = self.pos()
        new_x = best_snap_x if best_snap_x is not None else final_pos.x()
        new_y = best_snap_y if best_snap_y is not None else final_pos.y()

        if best_snap_x is None and best_snap_y is None:
            return

        self.setPos(new_x, new_y)

        for connection in self._validated_connections():
            connection.update_path()

    def _apply_grid_snap(self):
        """Apply grid snapping to the current card position."""
        if not self.view:
            return
        if not self.view.is_grid_enabled():
            return

        grid_spacing = self.view._grid_spacing
        current_pos = self.pos()
        snapped_x = round(current_pos.x() / grid_spacing) * grid_spacing
        snapped_y = round(current_pos.y() / grid_spacing) * grid_spacing

        if snapped_x != current_pos.x() or snapped_y != current_pos.y():
            self.setPos(snapped_x, snapped_y)

            for connection in self._validated_connections():
                connection.update_path()

    def _calculate_restricted_outputs(self) -> bool:
        """Calculate whether output ports should be restricted."""
        if self.task_type == "随机跳转":
            return 'random_only'

        base_restricted_types = [
            "延迟",
            "模拟键盘操作",
            "线程起点",
            "附加条件",
            "线程窗口限制",
        ]
        if self.task_type in base_restricted_types:
            return True

        if self.task_type in {"条件控制", "自定义脚本"}:
            return False

        always_branch_types = [
            "OCR文字识别",
            "点阵字库OCR",
            "字库识别",
            "OCR区域识别",
            "图片点击",
            "查找图片并点击",
            "找图点击",
            "找图功能",
        ]
        if self.task_type in always_branch_types:
            return False

        return False

    def _calculate_no_input_ports(self) -> bool:
        """Calculate whether all input ports should be hidden."""
        if is_thread_window_limit_task_type(self.task_type):
            return True
        no_input_types = ["附加条件"]
        return self.task_type in no_input_types

    def update_port_restrictions(self):
        """重新计算端口能力；状态冲突时拒绝修改，不自动删除连线。"""
        old_restricted = self.restricted_outputs
        new_restricted = self._calculate_restricted_outputs()

        allowed_outputs = (
            {PORT_TYPE_RANDOM}
            if new_restricted == "random_only"
            else {PORT_TYPE_SEQUENTIAL}
            if new_restricted
            else {PORT_TYPE_SEQUENTIAL, PORT_TYPE_SUCCESS, PORT_TYPE_FAILURE}
        )
        for connection in self.connections:
            if not _qt_is_valid(connection):
                raise RuntimeError(f"卡片 {self.card_id} 登记了失效连接")
            if connection.start_item is self and connection.line_type not in allowed_outputs:
                raise RuntimeError(
                    f"卡片 {self.card_id} 的 {connection.line_type} 连线与当前端口能力冲突"
                )

        self.restricted_outputs = new_restricted
        if old_restricted != new_restricted:
            self.update()
        for connection in self.connections:
            if connection.scene() is not self.scene():
                raise RuntimeError(f"卡片 {self.card_id} 的连接未挂载到当前场景")
            connection.update_path()
        return old_restricted != new_restricted
    def set_shadow_rendering_enabled(self, enabled: bool) -> None:
        """Enable/disable card shadow rendering for large workflows."""
        self._shadow_rendering_enabled = bool(enabled)
        if not self._shadow_rendering_enabled:
            self._release_shadow_effect()
            return
        self._ensure_shadow_effect()
        self.update_selection_effect(self.isSelected())

    def update_selection_effect(self, selected: bool):
        """Updates the shadow effect based on selection state."""
        if not getattr(self, "_shadow_rendering_enabled", True):
            self._release_shadow_effect()
            return
        shadow = self._ensure_shadow_effect()
        if shadow is None:
            return
        if selected:
            shadow.setColor(self.selection_shadow_color)
            shadow.setBlurRadius(self.selection_shadow_blur)
            shadow.setOffset(0, self.selection_shadow_offset)
        else:
            shadow.setColor(self.default_shadow_color)
            shadow.setBlurRadius(self.default_shadow_blur)
            shadow.setOffset(0, self.default_shadow_offset)
        shadow.setEnabled(True) # Ensure it's enabled/updated

    def set_display_id(self, sequence_id: Optional[int]): # Keep this uncommented
        """Sets the display ID shown on the card title."""
        self.sequence_id = sequence_id # Store the logical sequence ID
        if sequence_id is not None:
            self.display_id = sequence_id # Use sequence ID for display if available
        else:
            self.display_id = self.card_id # Fallback to original card ID
        
        # Update the title text immediately
        # --- MODIFIED: Change title format to support custom names ---
        if hasattr(self, 'task_type') and self.task_type:
            if self.custom_name:
                self.title = f"{self.custom_name} (ID: {self.card_id})"
            else:
                self.title = f"{self.task_type} (ID: {self.card_id})" # Use card_id directly
        else:
            # Fallback title if task_type isn't set yet (shouldn't happen in normal flow)
            self.title = f"Task (ID: {self.card_id})"
        # --- END MODIFICATION ---

        self.update() # Request a repaint to show the new title

    def set_custom_name(self, custom_name: Optional[str]):
        """设置卡片的自定义备注名称"""
        self.custom_name = custom_name
        # 更新标题显示
        if custom_name:
            self.title = f"{custom_name} (ID: {self.card_id})"
        else:
            self.title = f"{self.task_type} (ID: {self.card_id})"
        self.update() # 重新绘制卡片

    def get_port_at(self, pos: QPointF) -> Optional[Dict[str, Any]]:
        """Checks if a point (in item coordinates) hits a port using an enlarged hit radius."""
        hit_radius_sq = self.port_hit_radius ** 2

        # --- SPECIAL HANDLING: random_only cards only have random output port ---
        if self.restricted_outputs == 'random_only':
            # Check input port (sequential only)
            if not self.no_input_ports:
                in_center = self.get_port_pos('left', PORT_TYPE_SEQUENTIAL)
                delta_in = pos - in_center
                if delta_in.x()**2 + delta_in.y()**2 <= hit_radius_sq:
                    return {'side': 'input', 'type': PORT_TYPE_SEQUENTIAL}
            # Check output port (random only)
            out_center = self.get_port_pos('right', PORT_TYPE_RANDOM)
            delta_out = pos - out_center
            if delta_out.x()**2 + delta_out.y()**2 <= hit_radius_sq:
                return {'side': 'output', 'type': PORT_TYPE_RANDOM}
            return None
        # ---------------------------------------------------------------

        for port_type in PORT_TYPES:
            # --- ADDED: Skip input ports for cards with no_input_ports flag ---
            if not self.no_input_ports:
                in_center = self.get_port_pos('left', port_type)
                delta_in = pos - in_center
                if delta_in.x()**2 + delta_in.y()**2 <= hit_radius_sq:
                    return {'side': 'input', 'type': port_type}
            # -----------------------------------------------------------
            out_center = self.get_port_pos('right', port_type)
            delta_out = pos - out_center
            if delta_out.x()**2 + delta_out.y()**2 <= hit_radius_sq:
                # --- ADDED: Check for restricted output ports ---
                # 普通限制：只允许点击 sequential 端口
                if self.restricted_outputs and port_type != PORT_TYPE_SEQUENTIAL:
                    pass # Ignore click on restricted success/failure output ports
                else:
                    return {'side': 'output', 'type': port_type}
                # -----------------------------------------------
        return None

    def set_execution_state(self, state: str):
        """应用卡片执行状态；状态无效或 Qt 对象失效时直接报错。"""
        if not isinstance(state, str):
            raise TypeError("卡片执行状态必须是字符串")
        if state not in self.VALID_EXECUTION_STATES:
            raise ValueError(f"无效的卡片执行状态: {state}")
        if not _qt_is_valid(self):
            raise RuntimeError(f"卡片 {self.card_id} 的 Qt 对象已失效")
        if self.execution_state == state:
            return False

        self.execution_state = state
        self._cached_bg_color = self.state_colors[state]
        self._cached_border_pen = self.state_border_pens[state]
        if self._is_flashing:
            self._original_border_pen_before_flash = self._cached_border_pen
            if not self._flash_border_on:
                self._current_border_pen = self._cached_border_pen
        self.update()
        return True

    def open_parameter_panel(self):
        """请求主窗口为当前卡片显示参数面板。"""
        if self._is_workflow_running():
            return False

        self.edit_settings_requested.emit(self.card_id)
        return True

    def get_input_port_scene_pos(self, port_type: str = PORT_TYPE_SEQUENTIAL) -> QPointF:
        """Gets the scene coordinates of the specified input port type (left side)."""
        return self.mapToScene(self.get_port_pos('left', port_type))
    def get_output_port_scene_pos(self, port_type: str = PORT_TYPE_SEQUENTIAL) -> QPointF:
        """Gets the scene coordinates of the specified output port type (right side)."""
        return self.mapToScene(self.get_port_pos('right', port_type))

    def hoverMoveEvent(self, event: QGraphicsSceneHoverEvent):
        """Handle mouse hovering over the card to highlight ports."""
        pos = event.pos()
        hovered_port_info = self.get_port_at(pos)
        new_hovered_side = None
        new_hovered_type = None
        if hovered_port_info:
            new_hovered_side = hovered_port_info.get('side')
            new_hovered_type = hovered_port_info.get('type')
        if new_hovered_side != self.hovered_port_side or new_hovered_type != self.hovered_port_type:
            self.hovered_port_side = new_hovered_side
            self.hovered_port_type = new_hovered_type
            self.update() 
    def hoverLeaveEvent(self, event: QGraphicsSceneHoverEvent):
        """Handle mouse leaving the card area."""
        if getattr(self, "_is_dragging", False):
            self._cancel_drag_state()
        if self.hovered_port_side is not None or self.hovered_port_type is not None:
            self.hovered_port_side = None
            self.hovered_port_type = None
            self.update()

        # --- ADDED: Call super for other potential hover leave handling ---
        super().hoverLeaveEvent(event)

        # --- ADDED: Clear tooltip when mouse leaves the card ---
        self.setToolTip("")

        # 绔嬪嵆闅愯棌QToolTip
        from ui.widgets.custom_tooltip import get_tooltip_manager
        get_tooltip_manager().hide()
        # --- END ADDED ---

    def load_and_create_parameters(self):
        """加载当前字典格式的参数定义并填入默认值。"""
        param_definitions = self.task_module.get_params_definition()
        if not isinstance(param_definitions, dict):
            raise TypeError(f"任务 {self.task_type} 的参数定义必须是字典")
        for name, definition in param_definitions.items():
            if not isinstance(name, str) or not name:
                raise TypeError(f"任务 {self.task_type} 的参数名必须是非空字符串")
            if not isinstance(definition, dict):
                raise TypeError(f"任务 {self.task_type} 的参数定义 {name} 必须是字典")
        self.param_definitions = copy.deepcopy(param_definitions)

        for name, param_def in self.param_definitions.items():
            if param_def.get('type') == 'separator':
                continue
            if name not in self.parameters:
                self.parameters[name] = copy.deepcopy(param_def.get('default'))

    def copy_card(self):
        """请求复制当前卡片。"""
        if self._is_workflow_running():
            return False

        self.copy_requested.emit(self.card_id, copy.deepcopy(self.parameters))
        return True

    def _is_workflow_running(self) -> bool:
        """从所属工作流读取唯一运行状态。"""
        if self.view is None or not callable(getattr(self.view, "_is_workflow_running", None)):
            raise RuntimeError(f"卡片 {self.card_id} 未绑定工作流运行状态入口")
        state = self.view._is_workflow_running()
        if not isinstance(state, bool):
            raise TypeError("工作流运行状态必须是布尔值")
        return state

    # --- ADDED: Helper method to format tooltip values ---
    def _normalize_operation_mode_for_tooltip(self, value: Any) -> str:
        """校验并返回当前格式的鼠标操作模式。"""
        valid_modes = {
            "坐标点击",
            "找图功能",
            "文字点击",
            "找色功能",
            "元素点击",
            "鼠标滚轮",
            "鼠标拖拽",
            "鼠标移动",
        }
        if not isinstance(value, str) or value not in valid_modes:
            raise ValueError(f"无效的鼠标操作模式: {value!r}")
        return value

    def _format_tooltip_value(self, value: Any) -> str:
        if value is None:
            return "None"
        if isinstance(value, bool):
            return "是" if value else "否"

        # 转换为字符串
        str_value = str(value)

        # 特殊处理多行文本（如路径点坐标）
        if isinstance(value, str) and '\n' in str_value:
            lines = str_value.strip().split('\n')

            # 如果是路径点坐标格式（每行都是 x,y 格式）
            if len(lines) > 3 and all(',' in line.strip() for line in lines[:3] if line.strip()):
                # 显示前3个点和总数
                preview_lines = lines[:3]
                total_count = len([line for line in lines if line.strip()])
                preview_text = '\n    '.join(preview_lines)
                return f"{preview_text}\n    ... (共{total_count}个坐标点)"

            # 其他多行文本，限制显示行数
            elif len(lines) > 5:
                preview_lines = lines[:5]
                preview_text = '\n    '.join(preview_lines)
                return f"{preview_text}\n    ... (共{len(lines)}行)"
            else:
                # 少于5行，直接显示，但添加缩进
                return '\n    '.join(lines)

        # 单行文本，限制长度
        elif isinstance(value, str) and len(str_value) > 50:
            return f"{str_value[:47]}..."

        # For other types (int, float, etc.), use standard string conversion
        return str_value
    # --- END ADDED ---

    def hoverEnterEvent(self, event: QGraphicsSceneHoverEvent) -> None:
        """Formats and sets the tooltip when the mouse enters the card."""
        # 拖动画布/鼠标按下期间不显示参数提示，避免误触发
        if getattr(self, 'view', None) and hasattr(self.view, 'is_card_tooltip_suppressed'):
            if self.view.is_card_tooltip_suppressed():
                self.setToolTip("")
                from ui.widgets.custom_tooltip import get_tooltip_manager
                get_tooltip_manager().hide()
                super().hoverEnterEvent(event)
                return

        # 优化：使用缓存的工具提示，避免每次重新计算
        if not hasattr(self, '_cached_tooltip') or self._tooltip_needs_update:
            self._cached_tooltip = self._generate_tooltip_text()
            self._tooltip_needs_update = False

        # 先调用父类方法
        super().hoverEnterEvent(event)

        # 立即设置工具提示，不等待Qt的默认延迟
        self.setToolTip(self._cached_tooltip)

        # 使用QToolTip立即显示工具提示
        from ui.widgets.custom_tooltip import get_tooltip_manager
        if self._cached_tooltip and hasattr(self, 'scene') and self.scene():
            # 获取鼠标在屏幕上的位置
            scene_pos = event.scenePos()
            if self.scene().views():
                view = self.scene().views()[0]
                view_pos = view.mapFromScene(scene_pos)
                global_pos = view.mapToGlobal(view_pos)
                # 立即显示工具提示
                get_tooltip_manager().show_text(self._cached_tooltip, global_pos)

    def _tooltip_condition_matches(self, condition) -> bool:
        conditions = condition if isinstance(condition, list) else [condition]
        if not conditions:
            raise ValueError("参数显示条件列表不能为空")

        for item in conditions:
            if not isinstance(item, dict) or set(("param", "value")).difference(item):
                raise TypeError("参数显示条件必须包含 param 和 value")
            parameter_name = item["param"]
            if not isinstance(parameter_name, str) or not parameter_name:
                raise TypeError("参数显示条件的 param 必须是非空字符串")

            current_value = self.parameters.get(parameter_name)
            expected_value = item["value"]
            if parameter_name == "operation_mode":
                current_value = self._normalize_operation_mode_for_tooltip(current_value)
                if isinstance(expected_value, list):
                    expected_value = [
                        self._normalize_operation_mode_for_tooltip(value)
                        for value in expected_value
                    ]
                else:
                    expected_value = self._normalize_operation_mode_for_tooltip(expected_value)

            matches = (
                current_value in expected_value
                if isinstance(expected_value, list)
                else current_value == expected_value
            )
            if not matches:
                return False
        return True

    def _generate_tooltip_text(self) -> str:
        """生成当前参数格式的卡片工具提示。"""
        if not isinstance(self.parameters, dict):
            raise TypeError("卡片参数必须是字典")
        if not self.parameters:
            return "详细参数:\n  (无参数)"
        if not isinstance(self.param_definitions, dict) or not self.param_definitions:
            raise RuntimeError("卡片参数定义缺失")

        param_lines = ["详细参数:"]
        visible_params = []
        for name, param_def in self.param_definitions.items():
            if not isinstance(param_def, dict):
                raise TypeError(f"卡片参数定义 {name} 必须是字典")
            param_type = param_def.get('type')
            if param_type in {'separator', 'hidden'}:
                continue
            if 'condition' in param_def and not self._tooltip_condition_matches(param_def['condition']):
                continue
            visible_params.append((name, param_def))

        for name, param_def in visible_params:
            label = param_def.get('label', name)
            if not isinstance(label, str):
                raise TypeError(f"卡片参数 {name} 的 label 必须是字符串")
            raw_value = self.parameters.get(name)
            if name == "operation_mode":
                raw_value = self._normalize_operation_mode_for_tooltip(raw_value)
            formatted_value = self._format_tooltip_value(raw_value)
            param_lines.append(f"  {label}: {formatted_value}")

        return "\n".join(param_lines)

    def _ensure_flash_timer(self):
        existing_timer = getattr(self, "flash_toggle_timer", None)
        if existing_timer is not None:
            existing_timer.isActive()
            return existing_timer

        timer = QTimer(self)
        timer.timeout.connect(self._toggle_flash_border)
        self.flash_toggle_timer = timer
        return timer

    def flash(self):
        """启动卡片关系闪烁。"""
        if self._is_flashing:
            return False

        timer = self._ensure_flash_timer()
        timer.start(self.flash_interval_ms)
        self._original_border_pen_before_flash = self.state_border_pens[self.execution_state]
        self._flash_border_on = True
        self._current_border_pen = self.flash_border_pen
        self._is_flashing = True
        if self._is_animation_visible():
            self.update()
        return True

    def stop_flash(self):
        """停止卡片关系闪烁并恢复当前执行状态边框。"""
        if not self._is_flashing:
            return False

        timer = self.flash_toggle_timer
        if timer is None:
            raise RuntimeError(f"卡片 {self.card_id} 缺少关系闪烁定时器")
        timer.stop()
        self._is_flashing = False
        self._flash_border_on = False
        self._original_border_pen_before_flash = self.state_border_pens[self.execution_state]
        self._current_border_pen = self._original_border_pen_before_flash
        self.update()
        return True

    def _toggle_flash_border(self):
        """切换卡片关系闪烁边框。"""
        if not self._is_flashing:
            if self.flash_toggle_timer is not None:
                self.flash_toggle_timer.stop()
            return False
        if not self._is_animation_visible():
            return False

        self._flash_border_on = not self._flash_border_on
        self._current_border_pen = (
            self.flash_border_pen
            if self._flash_border_on
            else self._original_border_pen_before_flash
        )
        self.update()
        return True

    def refresh_theme(self):
        """刷新依赖主题的卡片颜色和缓存样式。"""
        self.card_color = self._get_theme_card_color()
        self.title_area_color = self._get_theme_title_color()
        self.title_color = self._get_theme_text_color()

        self._apply_visual_profile()
        self._cached_bg_color = self.state_colors[self.execution_state]
        self._cached_border_pen = self.state_border_pens[self.execution_state]

        self.update_selection_effect(self.isSelected())
        self.update()

