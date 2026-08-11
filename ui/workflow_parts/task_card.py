import sys
import logging
import copy
import gc
import tracemalloc
import math
import time
import weakref
import re
logger = logging.getLogger(__name__)
from typing import Optional, Dict, Any, List, Tuple # For type hints

from task_workflow.thread_window_binding import is_thread_window_limit_task_type
from .workflow_debug_utils import debug_print

try:
    from shiboken6 import isValid as _qt_is_valid
except Exception:
    def _qt_is_valid(_obj) -> bool:
        return True

HOVER_MEM_LOG_ENABLED = False
HOVER_MEM_LOG_SAMPLE = 1
HOVER_DIAG_ENABLED = False
HOVER_DIAG_SAMPLE = 10
HOVER_TRACE_ENABLED = False
HOVER_TRACE_SAMPLE = 50
HOVER_TRACE_TOP = 8
HOVER_TRACE_NFRAMES = 10
IDLE_PORT_ANIMATION_CARD_THRESHOLD = 60
CARD_ANIMATION_ZOOM_STOP_THRESHOLD = 0.50
CARD_OVERVIEW_MODE_ZOOM_THRESHOLD = 0.45
CARD_ANIMATION_VIEWPORT_MARGIN = 30.0
CARD_OVERVIEW_MIN_BORDER_DEVICE_PX = 1.2
CARD_OVERVIEW_MAX_BORDER_SCENE_WIDTH = 3.5
_hover_mem_counter = 0
_last_hover_mem_kb = None
_last_private_kb = None
_last_gdi_count = None
_last_user_count = None
_last_trace_snapshot = None


def clear_hover_diagnostics_cache():
    """Clear hover diagnostics/trace state to release tracing buffers."""
    global _hover_mem_counter, _last_hover_mem_kb, _last_private_kb, _last_gdi_count, _last_user_count
    global _last_trace_snapshot
    _hover_mem_counter = 0
    _last_hover_mem_kb = None
    _last_private_kb = None
    _last_gdi_count = None
    _last_user_count = None
    _last_trace_snapshot = None
    if tracemalloc.is_tracing():
        tracemalloc.stop()

if sys.platform.startswith("win"):
    try:
        import ctypes
        from ctypes import wintypes

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        _psapi = ctypes.WinDLL("psapi")
        _kernel32 = ctypes.WinDLL("kernel32")
        _user32 = ctypes.WinDLL("user32")
        _GetProcessMemoryInfo = _psapi.GetProcessMemoryInfo
        _GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
            wintypes.DWORD,
        ]
        _GetProcessMemoryInfo.restype = wintypes.BOOL
        _GetCurrentProcess = _kernel32.GetCurrentProcess
        _GetCurrentProcess.restype = wintypes.HANDLE

        _GetGuiResources = _user32.GetGuiResources
        _GetGuiResources.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        _GetGuiResources.restype = wintypes.DWORD

        def _get_process_mem_kb():
            counters = PROCESS_MEMORY_COUNTERS()
            if not _GetProcessMemoryInfo(
                _GetCurrentProcess(),
                ctypes.byref(counters),
                ctypes.sizeof(counters),
            ):
                return None, None
            return int(counters.WorkingSetSize / 1024), int(counters.PagefileUsage / 1024)

        def _get_gdi_count():
            return int(_GetGuiResources(_GetCurrentProcess(), 0))

        def _get_user_count():
            return int(_GetGuiResources(_GetCurrentProcess(), 1))
    except Exception:
        def _get_process_mem_kb():
            return None, None
        def _get_gdi_count():
            return None
        def _get_user_count():
            return None
else:
    def _get_process_mem_kb():
        return None, None
    def _get_gdi_count():
        return None
    def _get_user_count():
        return None

from PySide6.QtWidgets import (QApplication, QMenu,
                               QGraphicsSceneContextMenuEvent, QGraphicsSceneMouseEvent,
                               QStyleOptionGraphicsItem, QGraphicsDropShadowEffect,
                               QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QGraphicsProxyWidget,
                               QSpacerItem, QSizePolicy, QFrame, QPushButton, QCheckBox, QFileDialog, QDialog,
                               QGraphicsSceneHoverEvent, QGraphicsObject, QGraphicsItem, QGraphicsLineItem)
from PySide6.QtCore import Qt, QRectF, QPointF, QSizeF, Signal, QTimer # <-- ADD Signal & QTimer
from PySide6.QtGui import QBrush, QPen, QColor, QPainter, QFont, QPainterPath, QAction, QPolygonF, QLinearGradient, QConicalGradient, QRadialGradient # <-- ADD QAction, QPolygonF
from ui.dialogs.parameter_dialog import ParameterDialog # <<< UNCOMMENTED Import
from ui.system_parts.menu_style import apply_unified_menu_style

# Removed direct import of TASK_MODULES to break circular dependency
# from tasks import TASK_MODULES 

# Forward declare WorkflowView for type hinting
class WorkflowView: pass 


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
# ------------------------------------------------------------------
    """Represents a task step (SIMPLIFIED)."""
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

                has_ports = not getattr(card, "ports_disabled", False)
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
        """Return the themed card background color."""
        try:
            from themes import get_theme_manager
            theme_manager = get_theme_manager()
            if theme_manager.is_dark_mode():
                return QColor(45, 45, 45)  # #2d2d2d
            else:
                return QColor(255, 255, 255)  # #ffffff
        except:
            return QColor(255, 255, 255)  # 默认白色

    def _get_theme_title_color(self):
        """Return the themed title area color."""
        try:
            from themes import get_theme_manager
            theme_manager = get_theme_manager()
            if theme_manager.is_dark_mode():
                return QColor(58, 58, 58)  # #3a3a3a
            else:
                return QColor(240, 240, 240)  # #f0f0f0
        except:
            return QColor(240, 240, 240)  # 默认浅灰

    def _get_theme_text_color(self):
        """获取主题文本颜色"""
        try:
            from themes import get_theme_manager
            theme_manager = get_theme_manager()
            if theme_manager.is_dark_mode():
                return QColor(224, 224, 224)  # #e0e0e0
            else:
                return QColor(20, 20, 20)  # #141414
        except:
                return QColor(20, 20, 20)  # 默认深色

    def _is_dark_theme(self):
        """Return whether dark theme is active."""
        try:
            from themes import get_theme_manager
            theme_manager = get_theme_manager()
            return theme_manager.is_dark_mode()
        except:
            return False  # fallback

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

    def _cleanup_timer_attr(self, attr_name: str) -> None:
        timer = getattr(self, attr_name, None)
        if timer is None:
            try:
                setattr(self, attr_name, None)
            except Exception:
                pass
            return
        try:
            timer.stop()
        except Exception:
            pass
        try:
            timer.timeout.disconnect()
        except Exception:
            pass
        try:
            if hasattr(timer, "deleteLater"):
                timer.deleteLater()
        except Exception:
            pass
        try:
            setattr(self, attr_name, None)
        except Exception:
            pass

    def _release_drag_check_timer(self) -> None:
        self._cleanup_timer_attr("_drag_check_timer")

    def __init__(self, view: 'WorkflowView', x: float, y: float, task_type: str, card_id: int, task_module: Any, width: int = 200):
        debug_print(f"--- [DEBUG] TaskCard __init__ START (Inherits QGraphicsObject) - ID: {card_id}, Type: '{task_type}' ---") # Updated log
        self.initial_height = 60 # Simplified height
        # --- ADJUSTED super().__init__() call for QGraphicsObject --- 
        # QGraphicsObject init doesn't take rect args directly like QGraphicsRectItem
        # We might need to set a parent QGraphicsItem if needed, but for now None is okay.
        super().__init__(None) # Call QGraphicsObject's init 
        # -------------------------------------------------------------
        self.view = view
        self.task_type = task_type
        self.is_container_card = False
        self.container_id: Optional[int] = None
        self.ports_disabled = False
        self._container_padding = 20
        self._container_min_size = (240, 140)
        self._width = self._align_size_to_grid(width) # Store width for boundingRect
        self._height = self._align_size_to_grid(self.initial_height) # Store height for boundingRect
        if self.is_container_card:
            self._width = self._align_size_to_grid(max(self._width, self._container_min_size[0]))
            self._height = self._align_size_to_grid(max(self._height, self._container_min_size[1]))
            self.setZValue(-1)
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

        # --- ADDED: selection flash related state ---
        self._is_selection_flashing = False  # Selection flash marker
        self.selection_flash_timer = None  # Lazy init when selection flash starts
        self.selection_flash_interval_ms = 300  # Same interval as next-step flashing
        self.selection_flash_border_pen = QPen(QColor(0, 120, 255), 3)  # Blue border for selection flash
        self._selection_flash_border_on = False  # Selection flash toggle state
        # --- END ADDED ---

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

        debug_print(f"--- [DEBUG] TaskCard __init__ END (Inherits QGraphicsObject) - ID: {card_id} ---") # Updated log

    # --- ADDED boundingRect method (Required by QGraphicsObject) --- 
    def boundingRect(self) -> QRectF:
        """Returns the bounding rectangle of the item."""
        # Use stored width/height
        return QRectF(0, 0, self._width, self._height) 
    # -------------------------------------------------------------

    def _get_size_grid_unit(self) -> float:
        """Get grid spacing for size alignment."""
        try:
            spacing = float(getattr(self.view, "_grid_spacing", 20))
            return spacing if spacing > 1.0 else 20.0
        except Exception:
            return 20.0

    def _align_size_to_grid(self, value: float, minimum: float = 0.0) -> float:
        """Align size to grid spacing, using upward rounding to avoid clipping."""
        unit = self._get_size_grid_unit()
        safe_value = max(float(value), float(minimum), unit)
        return float(math.ceil(safe_value / unit) * unit)

    def set_size(self, width: float, height: float):
        min_width = self._container_min_size[0] if getattr(self, "is_container_card", False) else 0.0
        min_height = self._container_min_size[1] if getattr(self, "is_container_card", False) else 0.0
        width = self._align_size_to_grid(width, min_width)
        height = self._align_size_to_grid(height, min_height)
        if width == self._width and height == self._height:
            return
        self.prepareGeometryChange()
        self._width = width
        self._height = height
        self.update()
        # Ensure connection endpoints refresh when size changes (ports move).
        for conn in self.connections[:]:
            try:
                try:
                    from shiboken6 import isValid
                    if not isValid(conn):
                        try:
                            self.connections.remove(conn)
                        except ValueError:
                            pass
                        continue
                except ImportError:
                    pass
                if conn and hasattr(conn, 'scene'):
                    try:
                        if conn.scene():
                            conn.update_path()
                    except RuntimeError:
                        pass
            except RuntimeError:
                try:
                    self.connections.remove(conn)
                except ValueError:
                    pass
            except Exception:
                pass

    def set_ports_disabled(self, disabled: bool):
        if self.ports_disabled == disabled:
            return
        self.ports_disabled = disabled
        self.update_port_restrictions()
        self.update()

    def set_container_id(self, container_id: Optional[int]):
        self.container_id = container_id
        self.set_ports_disabled(container_id is not None)

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
            elif self._is_selection_flashing and self._selection_flash_border_on:
                effective_border_pen = self.selection_flash_border_pen
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

            if (not overview_mode) and (not self.ports_disabled):
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
        if not getattr(self, "is_container_card", False):
            return False
        view = getattr(self, "view", None)
        if not view:
            return False
        try:
            return bool(view._get_container_children(self.card_id))
        except Exception:
            return False


    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        """Handle clicks for port dragging and card selection/movement."""
        debug_print(f"--- [DEBUG] TaskCard {self.card_id} ({self.task_type}): mousePressEvent START - Button: {event.button()} ---")

        if event.button() == Qt.MouseButton.LeftButton:
            port_info = self.get_port_at(event.pos())
            if port_info and port_info['side'] == 'output':
                debug_print(f"  [DRAG_DEBUG] Detected click on output port: {port_info['type']} for card {self.card_id}")
                debug_print(f"开始拖动: 从{self.title}的{port_info['type']}输出端口")
                self.view.start_drag_line(self, port_info['type'])
                event.accept()
                return

        if event.button() == Qt.MouseButton.RightButton:
            debug_print("  [DEBUG] TaskCard: Right mouse button pressed, accepting event for context menu.")
            event.accept()
            return

        if event.button() == Qt.MouseButton.LeftButton:
            port_info = self.get_port_at(event.pos())
            if not (port_info and port_info['side'] == 'output'):
                debug_print(f"  [CLICK_DEBUG] Emitting card_clicked for ID: {self.card_id}")
                self.card_clicked.emit(self.card_id)

        debug_print("Handling standard card selection/dragging.")
        scene = self.scene()
        if scene:
            if self.isSelected():
                debug_print(f"  [SELECTION] Card {self.card_id} already selected, keeping multi-selection for drag")
            else:
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
                    card._last_connection_update_time = 0.0
                self._dragging_multi_selection = True
                debug_print(f"  [MULTI_DRAG] Starting multi-selection drag with {len(selected_cards) + 1} cards")
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

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        """Handle mouse release and finalize dragging state."""
        start_pos = getattr(self, '_drag_start_card_pos', None)
        was_actually_dragged = start_pos is not None and self.pos() != start_pos

        was_multi_dragging = getattr(self, '_dragging_multi_selection', False)
        moved_cards = None
        partner_cards = []
        other_cards = getattr(self, '_other_selected_cards_start_positions', None)
        if was_multi_dragging and other_cards:
            partner_cards = list(other_cards.keys())
        if was_actually_dragged:
            moved_cards = [self]
            if partner_cards:
                moved_cards.extend(partner_cards)
        self._dragging_multi_selection = False
        self._other_selected_cards_start_positions = {}
        self._drag_start_pos = None
        self._drag_start_card_pos = None
        self._is_dragging = False
        for card in partner_cards:
            card._is_dragging = False

        self._release_drag_check_timer()
        self._clear_snap_guide_lines()

        super().mouseReleaseEvent(event)

        if was_actually_dragged and not was_multi_dragging:
            self._apply_grid_snap()
            self._apply_snap_alignment()

        self._drag_start_card_pos_for_snap = None
        if moved_cards and getattr(self, "view", None):
            self.view.handle_cards_dropped(moved_cards)


    def _cancel_drag_state(self):
        """取消拖拽状态并清理辅助线，用于异常中断场景。"""
        other_cards = getattr(self, '_other_selected_cards_start_positions', None)
        if other_cards:
            for card in list(other_cards.keys()):
                card._is_dragging = False
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
                    debug_print(f"[双击] 打开子工作流: {workflow_file}")
                    self.open_sub_workflow_requested.emit(workflow_file)
                    event.accept()
                    return
                debug_print("[双击] 子工作流未设置文件，打开参数面板")

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

        for conn in self.connections[:]:
            try:
                if not _qt_is_valid(conn):
                    try:
                        self.connections.remove(conn)
                    except ValueError:
                        pass
                    continue

                if not hasattr(conn, 'start_item') or not hasattr(conn, 'end_item'):
                    continue
                if not conn.start_item or not conn.end_item:
                    continue

                other_card = None
                if conn.start_item == self and conn.end_item:
                    other_card = conn.end_item
                elif conn.end_item == self and conn.start_item:
                    other_card = conn.start_item

                if not other_card:
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
            except RuntimeError:
                try:
                    self.connections.remove(conn)
                except ValueError:
                    pass
            except Exception:
                pass


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
        if getattr(self, "is_container_card", False):
            edge_padding = max(10.0, rect.height() * 0.12)
            top_y = rect.top() + port_inset + edge_padding
            bottom_y = rect.bottom() - port_inset - edge_padding
            if port_type == PORT_TYPE_SUCCESS:
                final_y = top_y
            elif port_type == PORT_TYPE_FAILURE:
                final_y = bottom_y
            else:
                final_y = center_y
        else:
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
        if self.ports_disabled:
            return ports

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
        # debug_print(f"--- [ITEM_CHANGE_ENTRY] Card ID: {self.card_id}, Change: {change}, Value: {value} ---") # <-- Add this line # <<< MODIFIED: Commented out
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            if getattr(self, "is_container_card", False) and getattr(self, "view", None):
                last_pos = getattr(self, "_last_group_pos", self.pos())
                delta = self.pos() - last_pos
                if delta.x() or delta.y():
                    self.view.move_container_children(self, delta)
                self._last_group_pos = self.pos()
        if change == QGraphicsItem.GraphicsItemChange.ItemSceneHasChanged:
            if value is None:
                self._unregister_gradient_animation()
                self._release_drag_check_timer()
                self.stop_flash()
                self.stop_selection_flash()
            else:
                self._register_gradient_animation()

        # 性能优化：拖拽时禁用场景矩形动态扩展，避免缩小时卡顿；
        # 场景矩形会在移动完成后统一调整。
        pass

        # Handle selection change for shadow effect
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedChange:
            selected = value
            self.update_selection_effect(selected)

        result = super().itemChange(change, value)

        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            if getattr(self, '_is_dragging', False):
                now = time.perf_counter()
                if now - self._last_connection_update_time < self._connection_update_interval:
                    return result
                self._last_connection_update_time = now

            for conn in self.connections[:]:
                try:
                    if not _qt_is_valid(conn):
                        try:
                            self.connections.remove(conn)
                        except ValueError:
                            pass
                        continue

                    if conn and hasattr(conn, 'scene'):
                        try:
                            if conn.scene():
                                conn.update_path()
                        except RuntimeError:
                            pass
                except RuntimeError:
                    try:
                        self.connections.remove(conn)
                    except ValueError:
                        pass
                except Exception:
                    pass

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

        for conn in self.connections[:]:
            try:
                if not _qt_is_valid(conn):
                    try:
                        self.connections.remove(conn)
                    except ValueError:
                        pass
                    continue

                if not hasattr(conn, 'start_item') or not hasattr(conn, 'end_item'):
                    continue
                if not conn.start_item or not conn.end_item:
                    continue

                other_card = None
                if conn.start_item == self and conn.end_item:
                    other_card = conn.end_item
                elif conn.end_item == self and conn.start_item:
                    other_card = conn.start_item

                if not other_card:
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
            except (RuntimeError, AttributeError):
                continue

        final_pos = self.pos()
        new_x = best_snap_x if best_snap_x is not None else final_pos.x()
        new_y = best_snap_y if best_snap_y is not None else final_pos.y()

        if best_snap_x is None and best_snap_y is None:
            return

        self.setPos(new_x, new_y)

        for conn in self.connections[:]:
            try:
                if not _qt_is_valid(conn):
                    try:
                        self.connections.remove(conn)
                    except ValueError:
                        pass
                    continue

                if conn and hasattr(conn, 'scene'):
                    try:
                        if conn.scene():
                            conn.update_path()
                    except RuntimeError:
                        pass
            except (RuntimeError, AttributeError):
                pass

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

            for conn in self.connections[:]:
                try:
                    if not _qt_is_valid(conn):
                        try:
                            self.connections.remove(conn)
                        except ValueError:
                            pass
                        continue
                except Exception:
                    pass

                if conn and hasattr(conn, 'scene'):
                    try:
                        if conn.scene():
                            conn.update_path()
                    except RuntimeError:
                        pass

    def _calculate_restricted_outputs(self) -> bool:
        """Calculate whether output ports should be restricted."""
        if getattr(self, "ports_disabled", False):
            return True
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

        if self.task_type == "条件控制":
            return False

        always_branch_types = [
            "OCR文字识别",
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
        if getattr(self, "ports_disabled", False):
            return True
        if is_thread_window_limit_task_type(self.task_type):
            return True
        no_input_types = ["附加条件"]
        return self.task_type in no_input_types

    def update_port_restrictions(self):
        """Recompute port restrictions and refresh affected connections."""
        old_restricted = self.restricted_outputs
        new_restricted = self._calculate_restricted_outputs()

        if old_restricted != new_restricted:
            debug_print(f"[PORT_UPDATE] Card {self.card_id} port restrictions changed: {old_restricted} -> {new_restricted}")
            self.restricted_outputs = new_restricted

            if new_restricted and not old_restricted:
                self._cleanup_invalid_connections(['success', 'failure'])
            elif not new_restricted and old_restricted:
                pass

            self.update()

            for conn in self.connections[:]:
                try:
                    if not _qt_is_valid(conn):
                        try:
                            self.connections.remove(conn)
                        except ValueError:
                            pass
                        continue
                    if conn and hasattr(conn, 'scene') and hasattr(conn, 'update_path'):
                        try:
                            if conn.scene():
                                conn.update_path()
                        except RuntimeError:
                            pass
                except RuntimeError:
                    try:
                        self.connections.remove(conn)
                    except ValueError:
                        pass
                except Exception:
                    pass

    def _cleanup_invalid_connections(self, invalid_port_types: list):
        """Remove invalid connections for restricted output modes."""
        connections_to_remove = []

        for conn in self.connections[:]:
            if hasattr(conn, 'line_type') and conn.line_type in invalid_port_types:
                if hasattr(conn, 'start_item') and conn.start_item == self:
                    connections_to_remove.append(conn)
                    debug_print(f"[PORT_CLEANUP] Marking connection for removal: {self.card_id} -> {conn.end_item.card_id if hasattr(conn, 'end_item') and conn.end_item else 'None'} ({conn.line_type})")

        if connections_to_remove and self.view:
            for conn in connections_to_remove:
                if hasattr(self.view, 'remove_connection'):
                    self.view.remove_connection(conn)
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
        if self.ports_disabled:
            return None
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
        """Sets the execution state and triggers a repaint."""
        try:
            if state in self.state_colors:
                # 性能优化：如果状态未变化，直接跳过刷新
                if self.execution_state == state:
                    return

                self.execution_state = state
                self._cached_bg_color = self.state_colors.get(state, self.card_color)
                self._cached_border_pen = self.state_border_pens.get(state, self.default_pen)
                self.update()
            else:
                debug_print(f"Warning: tried to set invalid state {state!r} for card {self.card_id}")
        except RuntimeError as e:
            debug_print(f"  [STATE] Card {self.card_id} already deleted when setting state: {e}")
        except Exception as e:
            debug_print(f"  [STATE] Error setting execution state for Card {self.card_id}: {e}")

    def open_parameter_dialog(self):
        """Open the parameter panel for this card."""
        logger.debug("TaskCard.open_parameter_dialog() called. Card ID: %s", self.card_id)

        if self._is_workflow_running():
            logger.warning("工作流正在执行中，无法进行参数设置操作")
            return

        logger.debug("发送参数编辑请求信号: %s", self.card_id)
        self.edit_settings_requested.emit(self.card_id)

    def add_connection(self, connection): # Keep connection logic
        try:
            if connection and connection not in self.connections:
                self.connections.append(connection)
        except (RuntimeError, TypeError):
            pass

    def remove_connection(self, connection): # Keep connection logic
        try:
            if connection in self.connections:
                self.connections.remove(connection)
        except (ValueError, RuntimeError, TypeError):
            pass

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
        """Loads parameter definitions and initializes the parameters dictionary."""
        debug_print(f"--- [DEBUG] TaskCard {self.card_id}: load_and_create_parameters START ---") # DEBUG
        
        if not self.task_module or not hasattr(self.task_module, 'get_params_definition'):
            debug_print(f"    [DEBUG] TaskCard {self.card_id}: Task module missing or no get_params_definition.") # DEBUG
            debug_print(f"    警告: 任务类型 '{self.task_type}' 的模块无效或缺少 get_params_definition。Module: {self.task_module}")
            self.param_definitions = {} 
            debug_print(f"--- [DEBUG] TaskCard {self.card_id}: load_and_create_parameters END (Module Invalid/Missing Def) ---") # DEBUG
            return

        try:
            debug_print(f"    [DEBUG] TaskCard {self.card_id}: Calling {self.task_type}.get_params_definition()...") # DEBUG
            self.param_definitions = self.task_module.get_params_definition()
            debug_print(f"    [DEBUG] TaskCard {self.card_id}: Received param_definitions type: {type(self.param_definitions)}") # DEBUG
        except Exception as e:
             debug_print(f"    [调试] TaskCard {self.card_id}：调用 get_params_definition 出错：{e}") # DEBUG
             self.param_definitions = {}
             debug_print(f"--- [DEBUG] TaskCard {self.card_id}: load_and_create_parameters END (Exception in get_params_definition) ---") # DEBUG
             return
             
        if isinstance(self.param_definitions, list):
            debug_print(f"    [DEBUG] TaskCard {self.card_id}: Converting list of param definitions to dict...") # DEBUG
            try:
                definitions_dict = {item['name']: item for item in self.param_definitions if isinstance(item, dict) and 'name' in item}
                self.param_definitions = definitions_dict
                debug_print(f"    [DEBUG] TaskCard {self.card_id}: Conversion successful. New type: {type(self.param_definitions)}") # DEBUG
            except (TypeError, KeyError) as e:
                debug_print(f"    [调试] TaskCard {self.card_id}：列表转字典出错：{e}。列表格式无效。") # DEBUG
                self.param_definitions = {} 
        elif not isinstance(self.param_definitions, dict):
             debug_print(f"    [调试] TaskCard {self.card_id}：get_params_definition 返回了未预期类型：{type(self.param_definitions)}") # DEBUG
             self.param_definitions = {} 

        self._append_result_variable_params()

        debug_print(f"  [DEBUG] TaskCard {self.card_id}: Initializing parameters with defaults...")
        for name, param_def in self.param_definitions.items():
            if param_def.get('type') == 'separator':
                continue
            if name not in self.parameters:
                default_value = copy.deepcopy(param_def.get('default'))
                self.parameters[name] = default_value
                debug_print(f"    [DEBUG] Set default parameter {name} = {default_value}")
            else:
                debug_print(f"    [DEBUG] Preserve existing parameter {name} = {self.parameters[name]}")

        self._seed_result_variable_defaults()
        is_loading_workflow = bool(getattr(getattr(self, "view", None), "_loading_workflow", False))
        if not is_loading_workflow:
            self._normalize_result_variable_name_for_card_id()
            self.register_result_variable_placeholders()

        debug_print(f"卡片 {self.card_id} ('{self.task_type}') 参数定义已加载，初始参数: {self.parameters}")
        debug_print(f"--- [DEBUG] TaskCard {self.card_id}: load_and_create_parameters END (Success) ---") # DEBUG

    def _get_default_result_variable_name(self) -> str:
        return f"卡片{self.card_id}结果"

    @staticmethod
    def _is_default_result_variable_name(name: str) -> bool:
        text = str(name or "").strip()
        if not text:
            return False
        if re.fullmatch(r"卡片\d+结果", text):
            return True
        return bool(re.fullmatch(r"card_\d+_result", text, flags=re.IGNORECASE))

    def _append_result_variable_params(self):
        if not isinstance(self.param_definitions, dict):
            return
        if "save_result_variable_name" in self.param_definitions:
            return

        extra_params = {
            "---save_result_variable---": {
                "type": "separator",
                "label": "变量保存",
            },
            "save_result_variable_name": {
                "label": "保存变量名",
                "type": "text",
                "default": self._get_default_result_variable_name(),
                "tooltip": "填写变量名后，将把本卡片的执行结果保存到变量池",
            },
        }

        for name, definition in extra_params.items():
            if name not in self.param_definitions:
                self.param_definitions[name] = definition

    def _seed_result_variable_defaults(self) -> None:
        key = "save_result_variable_name"
        current_name = str(self.parameters.get(key, "") or "").strip()
        if current_name:
            self.parameters.pop("_save_result_variable_seeded", None)
            return
        self.parameters[key] = self._get_default_result_variable_name()
        self.parameters.pop("_save_result_variable_seeded", None)

    def _normalize_result_variable_name_for_card_id(self) -> None:
        """仅同步自动生成的默认结果变量名，不覆盖用户自定义名称。"""
        try:
            name_key = "save_result_variable_name"
            current_name = str(self.parameters.get(name_key, "") or "").strip()
            if not current_name:
                return
            new_name = f"卡片{self.card_id}结果"

            if current_name == new_name:
                return

            # 仅同步默认命名，保留用户自定义变量名
            if not self._is_default_result_variable_name(current_name):
                return

            old_name = current_name

            self.parameters[name_key] = new_name

            if old_name:
                self._cleanup_stale_result_variables(old_name)

            logger.info(
                f"[结果变量强制同步] 卡片{self.card_id}: save_result_variable_name "
                f"{old_name or '<空>'} -> {new_name}"
            )
        except Exception as exc:
            logger.debug(f"[结果变量强制同步] 卡片{self.card_id} 自动同步失败: {exc}")

    def _cleanup_stale_result_variables(self, old_prefix: str) -> None:
        """清理同一卡片旧前缀的结果变量，避免变量池残留混淆。"""
        old_prefix = str(old_prefix or "").strip()
        if not old_prefix:
            return

        try:
            from task_workflow.workflow_context import get_workflow_context
            context = get_workflow_context()
            if hasattr(context, "snapshot_variable_state"):
                state = context.snapshot_variable_state()
                global_vars = dict((state or {}).get("global_vars", {}) or {})
                var_sources = dict((state or {}).get("var_sources", {}) or {})
            else:
                global_vars = dict(getattr(context, "global_vars", {}) or {})
                var_sources = dict(getattr(context, "var_sources", {}) or {})

            to_remove = []
            for var_name in global_vars.keys():
                name = str(var_name or "").strip()
                if not (name == old_prefix or name.startswith(f"{old_prefix}.")):
                    continue

                owner = var_sources.get(name)
                try:
                    owner_int = int(owner)
                except (TypeError, ValueError):
                    owner_int = None

                if owner_int == self.card_id:
                    to_remove.append(name)

            for name in to_remove:
                try:
                    context.remove_global_var(name)
                except Exception:
                    pass

            if to_remove:
                logger.info(
                    f"[结果变量迁移] 卡片{self.card_id}: 已清理旧前缀变量 {len(to_remove)} 个"
                )
        except Exception:
            pass

    def _get_result_variable_suffixes(self) -> list:
        suffixes = [
            "状态",
            "动作",
            "下一步ID",
            "任务类型",
            "卡片ID",
            "时间戳",
            "参数",
        ]
        params = self.parameters or {}

        if self.task_type in ("OCR文字识别", "字库识别"):
            target_text = str(params.get("target_text", "") or "").strip()
            target_groups = str(params.get("target_text_groups", "") or "").strip()
            suffixes.extend([
                "全部文字",
                "全部文字数量",
            ])
            if target_text or target_groups:
                suffixes.extend([
                    "目标文字",
                    "目标坐标X",
                    "目标坐标Y",
                    "目标范围X1",
                    "目标范围Y1",
                    "目标范围X2",
                    "目标范围Y2",
                ])
        elif self.task_type == "YOLO目标检测":
            suffixes.extend([
                "目标数量",
                "目标坐标X",
                "目标坐标Y",
                "目标范围X1",
                "目标范围Y1",
                "目标范围X2",
                "目标范围Y2",
            ])
        elif self.task_type in ("图片点击", "查找图片并点击"):
            suffixes.extend([
                "AI输出内容",
                "最新问题",
                "AI错误",
                "目标坐标X",
                "目标坐标Y",
                "目标范围X1",
                "目标范围Y1",
                "目标范围X2",
                "目标范围Y2",
            ])
        elif self.task_type == "模拟鼠标操作":
            operation_mode = str(params.get("operation_mode", "") or "").strip()
            if operation_mode in {"找色功能", "找色点击"}:
                suffixes.extend([
                    "目标坐标X",
                    "目标坐标Y",
                    "颜色列表",
                ])

        return suffixes

    def register_result_variable_placeholders(self) -> None:
        try:
            prefix = str(self.parameters.get("save_result_variable_name", "") or "").strip()
            if not prefix:
                return
            suffixes = self._get_result_variable_suffixes()
            names = [f"{prefix}.{suffix}" for suffix in suffixes]
            from task_workflow.workflow_context import get_workflow_context
            context = get_workflow_context()
            context.register_card_result_placeholders(self.card_id, names)
        except Exception:
            pass

    def contextMenuEvent(self, event: QGraphicsSceneContextMenuEvent):
        """Creates and shows the right-click context menu."""
        # 检查工作流是否正在运行
        is_running = self._is_workflow_running()
        menu = apply_unified_menu_style(QMenu(), frameless=True)
        menu.setObjectName("task_card_menu")
        
        copy_action = QAction("复制卡片", menu)
        copy_action.triggered.connect(self.copy_card) # Connects to method
        copy_action.setEnabled(not is_running)
        if is_running:
            copy_action.setToolTip("工作流运行期间无法复制卡片")
        menu.addAction(copy_action)

        menu.addSeparator()
        
        settings_action = QAction("参数设置", menu)
        settings_action.triggered.connect(self.open_parameter_dialog) # Connects to method
        settings_action.setEnabled(not is_running)
        if is_running:
            settings_action.setToolTip("工作流运行期间无法修改参数")
        menu.addAction(settings_action)

        menu.addSeparator()

        delete_action = QAction("删除卡片", menu)
        delete_action.triggered.connect(
            lambda: (debug_print(f"--- [CONTEXT_MENU_DEBUG] Delete Action triggered for Card {self.card_id}. Emitting delete_requested... ---"), self.delete_requested.emit(self.card_id))
        )
        delete_action.setEnabled(not is_running)
        if is_running:
            delete_action.setToolTip("工作流运行期间无法删除卡片")
        menu.addAction(delete_action)

        debug_print(f"  [CONTEXT_DEBUG] Context menu created for card {self.card_id} at scene pos {event.scenePos()}")
        # Show the menu at the event position
        # --- CHANGED: Execute using mapToGlobal for correct screen positioning --- 
        selected_action = menu.exec(event.screenPos())
        # -----------------------------------------------------------------------
        
        # Handle selected action (optional, can be handled by WorkflowView via signals)
        if selected_action:
            debug_print(f"  [CONTEXT_DEBUG] Selected action: {selected_action.text()}")
            # Example: emit signal based on action
            if selected_action.text() == "编辑设置":
                self.edit_settings_requested.emit(self.card_id)
            elif selected_action.text() == "删除卡片":
                self.delete_requested.emit(self.card_id)
            elif selected_action.text() == "复制卡片":
                self.copy_card() # Call the method WorkflowView expects
                
        debug_print("--- [DEBUG] TaskCard contextMenuEvent END ---")
        
    # --- ADDED: Method to emit copy request ---
    def copy_card(self):
        """Emits the signal that this card should be copied."""
        # 检查是否正在运行，如果是则阻止复制
        if self._is_workflow_running():
            logger.warning("工作流正在执行中，无法进行复制卡片操作")
            return

        debug_print(f"--- [DEBUG] TaskCard {self.card_id}: copy_card() method called, emitting copy_requested signal. ---")
        self.copy_requested.emit(self.card_id, copy.deepcopy(self.parameters))
        
    def _is_workflow_running(self) -> bool:
        """检查工作流是否正在运行 - 检查运行按钮的文本状态"""
        try:
            # 直接调用view的方法，保持一致性
            if self.view and hasattr(self.view, '_is_workflow_running'):
                return self.view._is_workflow_running()
        except Exception as e:
            import logging
            logging.error(f"TaskCard检查任务运行状态时发生错误: {e}")

        # 默认允许操作
        return False

    # --- ADDED: Helper method to format tooltip values ---
    def _normalize_operation_mode_for_tooltip(self, value: Any) -> str:
        """归一化操作模式，兼容历史值，避免tooltip条件判断丢参数。"""
        legacy_mode_by_index = [
            "找图功能",
            "坐标点击",
            "文字点击",
            "找色功能",
            "元素点击",
            "鼠标滚轮",
            "鼠标拖拽",
            "鼠标移动",
        ]
        alias_map = {
            "图片点击": "找图功能",
            "找图点击": "找图功能",
            "找色点击": "找色功能",
        }

        mode = ""
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            idx = int(value)
            if 0 <= idx < len(legacy_mode_by_index):
                mode = legacy_mode_by_index[idx]
            else:
                mode = str(value).strip()
        else:
            mode = str(value or "").strip()
            if mode.isdigit():
                idx = int(mode)
                if 0 <= idx < len(legacy_mode_by_index):
                    mode = legacy_mode_by_index[idx]

        mode = alias_map.get(mode, mode)
        if mode:
            return mode

        task_type_candidates = [
            str(getattr(self, "task_type", "") or "").strip(),
            str((self.parameters or {}).get("task_type", "") or "").strip(),
        ]
        if any(t in {"图片点击", "查找图片并点击", "找图点击", "找图功能"} for t in task_type_candidates if t):
            return "找图功能"
        return ""

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

    def _log_hover_memory(self):
        global _hover_mem_counter, _last_hover_mem_kb, _last_private_kb, _last_gdi_count, _last_user_count
        global _last_trace_snapshot
        if not (HOVER_MEM_LOG_ENABLED or HOVER_DIAG_ENABLED or HOVER_TRACE_ENABLED):
            return
        _hover_mem_counter += 1
        self._hover_count = getattr(self, "_hover_count", 0) + 1

        mem_sample_hit = HOVER_MEM_LOG_ENABLED and (
            HOVER_MEM_LOG_SAMPLE <= 1 or _hover_mem_counter % HOVER_MEM_LOG_SAMPLE == 0
        )
        if mem_sample_hit:
            ws_kb, private_kb = _get_process_mem_kb()
            gdi_count = _get_gdi_count()
            user_count = _get_user_count()
            delta_ws = None if _last_hover_mem_kb is None or ws_kb is None else ws_kb - _last_hover_mem_kb
            delta_private = None if _last_private_kb is None or private_kb is None else private_kb - _last_private_kb
            delta_gdi = None if _last_gdi_count is None or gdi_count is None else gdi_count - _last_gdi_count
            delta_user = None if _last_user_count is None or user_count is None else user_count - _last_user_count
            if ws_kb is not None:
                _last_hover_mem_kb = ws_kb
            if private_kb is not None:
                _last_private_kb = private_kb
            if gdi_count is not None:
                _last_gdi_count = gdi_count
            if user_count is not None:
                _last_user_count = user_count
            logger.info(
                "[HOVER_MEM] card_id=%s type=%s hover=%s ws_kb=%s delta_ws=%s private_kb=%s delta_private=%s gdi=%s delta_gdi=%s user=%s delta_user=%s",
                self.card_id,
                self.task_type,
                self._hover_count,
                ws_kb,
                delta_ws,
                private_kb,
                delta_private,
                gdi_count,
                delta_gdi,
                user_count,
                delta_user,
            )

        diag_sample_hit = HOVER_DIAG_ENABLED and (
            HOVER_DIAG_SAMPLE <= 1 or _hover_mem_counter % HOVER_DIAG_SAMPLE == 0
        )
        if diag_sample_hit:
            widget_count = None
            top_level_count = None
            if QApplication.instance():
                widget_count = len(QApplication.allWidgets())
                top_level_count = len(QApplication.topLevelWidgets())
            scene_items = None
            try:
                if self.scene():
                    scene_items = len(self.scene().items())
            except Exception:
                scene_items = None
            alloc_blocks = None
            try:
                alloc_blocks = sys.getallocatedblocks()
            except AttributeError:
                alloc_blocks = None
            logger.info(
                "[HOVER_DIAG] hover=%s widgets=%s top=%s scene_items=%s gc=%s alloc_blocks=%s",
                self._hover_count,
                widget_count,
                top_level_count,
                scene_items,
                gc.get_count(),
                alloc_blocks,
            )

        trace_sample_hit = HOVER_TRACE_ENABLED and (
            HOVER_TRACE_SAMPLE <= 1 or _hover_mem_counter % HOVER_TRACE_SAMPLE == 0
        )
        if trace_sample_hit:
            try:
                if not tracemalloc.is_tracing():
                    tracemalloc.start(HOVER_TRACE_NFRAMES)
                snapshot = tracemalloc.take_snapshot()
                if _last_trace_snapshot is None:
                    stats = snapshot.statistics("lineno")
                    kind = "top"
                else:
                    stats = snapshot.compare_to(_last_trace_snapshot, "lineno")
                    kind = "delta"
                stats = stats[:HOVER_TRACE_TOP]
                parts = []
                for stat in stats:
                    frame = stat.traceback[0]
                    size_kb = stat.size / 1024
                    parts.append(f"{frame.filename}:{frame.lineno} {size_kb:.1f}KB {stat.count}")
                logger.info(
                    "[HOVER_TRACE] hover=%s kind=%s top=%s",
                    self._hover_count,
                    kind,
                    " | ".join(parts),
                )
                _last_trace_snapshot = snapshot
            except Exception as exc:
                logger.warning("[HOVER_TRACE] hover=%s error=%s", self._hover_count, exc)

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

        self._log_hover_memory()

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

    def _generate_tooltip_text(self) -> str:
        """生成工具提示文本（优化版本）"""
        # 快速检查：如果没有参数，直接返回简单文本
        if not hasattr(self, 'parameters') or not self.parameters:
            return "详细参数:\n  (无参数)"

        param_lines = ["详细参数:"]

        # 优化：如果没有参数定义，直接显示原始参数
        if not hasattr(self, 'param_definitions') or not self.param_definitions:
            param_lines.append("  (参数定义缺失，显示原始键值)")
            # 限制显示的参数数量，避免工具提示过长
            count = 0
            for key, value in self.parameters.items():
                if count >= 10:  # 最多显示10个参数
                    param_lines.append("  ...")
                    break
                param_lines.append(f"    {key}: {repr(value)}")
                count += 1
            return "\n".join(param_lines)

        # 优化：预先计算需要显示的参数，避免重复检查
        visible_params = []
        for name, param_def in self.param_definitions.items():
            # 快速跳过不需要的参数类型
            param_type = param_def.get('type')
            if param_type == 'separator':
                continue

            # 跳过所有隐藏参数
            if param_type == 'hidden':
                continue

            # 检查条件显示（优化：只在有条件时才检查）
            if 'condition' in param_def:
                condition_def = param_def['condition']

                # 处理多条件和单条件
                condition_met = True
                try:
                    if isinstance(condition_def, list):
                        # 多条件：所有条件都必须满足（AND逻辑）
                        for single_condition in condition_def:
                            if isinstance(single_condition, dict):
                                controlling_param_name = single_condition.get('param')
                                expected_value = single_condition.get('value')
                                current_value = self.parameters.get(controlling_param_name)
                                if controlling_param_name == 'operation_mode':
                                    current_value = self._normalize_operation_mode_for_tooltip(current_value)
                                    if isinstance(expected_value, list):
                                        expected_value = [self._normalize_operation_mode_for_tooltip(v) for v in expected_value]
                                    else:
                                        expected_value = self._normalize_operation_mode_for_tooltip(expected_value)

                                if isinstance(expected_value, list):
                                    if current_value not in expected_value:
                                        condition_met = False
                                        break
                                else:
                                    if current_value != expected_value:
                                        condition_met = False
                                        break
                    else:
                        # 单条件
                        if isinstance(condition_def, dict):
                            controlling_param_name = condition_def.get('param')
                            expected_value = condition_def.get('value')
                            current_value = self.parameters.get(controlling_param_name)
                            if controlling_param_name == 'operation_mode':
                                current_value = self._normalize_operation_mode_for_tooltip(current_value)
                                if isinstance(expected_value, list):
                                    expected_value = [self._normalize_operation_mode_for_tooltip(v) for v in expected_value]
                                else:
                                    expected_value = self._normalize_operation_mode_for_tooltip(expected_value)

                            # 检查条件是否满足
                            if isinstance(expected_value, list):
                                condition_met = current_value in expected_value
                            else:
                                condition_met = current_value == expected_value
                except Exception as e:
                    # 如果条件检查出错，默认显示参数
                    debug_print(f"TaskCard条件检查出错: {e}")
                    condition_met = True

                if not condition_met:
                    continue

            # 添加到可见参数列表
            visible_params.append((name, param_def))

        # 生成工具提示文本
        for name, param_def in visible_params:
            label = param_def.get('label', name)
            raw_value = self.parameters.get(name)
            if name == "operation_mode":
                raw_value = self._normalize_operation_mode_for_tooltip(raw_value)
            formatted_value = self._format_tooltip_value(raw_value)
            param_lines.append(f"  {label}: {formatted_value}")

        return "\n".join(param_lines)
        
    # hoverLeaveEvent is modified above to clear the tooltip
    # --- END ADDED --- 

    def _ensure_flash_timer(self):
        existing_timer = getattr(self, "flash_toggle_timer", None)
        if existing_timer is not None:
            try:
                existing_timer.isActive()
                return existing_timer
            except RuntimeError:
                self.flash_toggle_timer = None
        try:
            timer = QTimer(self)
            timer.timeout.connect(self._toggle_flash_border)
            self.flash_toggle_timer = timer
            return timer
        except Exception:
            self.flash_toggle_timer = None
            return None

    def _ensure_selection_flash_timer(self):
        existing_timer = getattr(self, "selection_flash_timer", None)
        if existing_timer is not None:
            try:
                existing_timer.isActive()
                return existing_timer
            except RuntimeError:
                self.selection_flash_timer = None
        try:
            timer = QTimer(self)
            timer.timeout.connect(self._toggle_selection_flash_border)
            self.selection_flash_timer = timer
            return timer
        except Exception:
            self.selection_flash_timer = None
            return None

    # --- ADDED Flash methods --- 
    def flash(self, duration_ms: int = 500):
        """ Starts persistently flashing the card border. """
        if self._is_flashing: # Already flashing
            return
        debug_print(f"  [FLASH_DEBUG] Starting flash for Card {self.card_id}")
        self._is_flashing = True
        # Store the non-flashing border based on current execution state
        self._original_border_pen_before_flash = self.state_border_pens.get(self.execution_state, self.default_pen)
        self._flash_border_on = True # Start with flash border visible
        # 橙色闪烁用于显示连线关系
        self._current_border_pen = self.flash_border_pen
        timer = self._ensure_flash_timer()
        if timer is not None:
            timer.start(self.flash_interval_ms) # Start repeating timer
        if self._is_animation_visible():
            self.update() # Trigger repaint

    def stop_flash(self):
        """ Stops the persistent flashing and restores the border. """
        try:
            if not self._is_flashing: # Not flashing
                return
            debug_print(f"  [FLASH_DEBUG] Stopping flash for Card {self.card_id}")

            # BUG FIX: 原子化操作 - 先设置标志，立即阻止回调执行
            self._is_flashing = False

            # 【性能优化】只停止定时器，不断开信号连接
            # 信号连接只在__init__中建立一次，断开后会导致后续flash()失效
            timer = getattr(self, "flash_toggle_timer", None)
            if timer is not None:
                try:
                    timer.stop()
                    debug_print(f"  [FLASH_DEBUG] Timer stopped for Card {self.card_id}")
                except RuntimeError as e:
                    debug_print(f"  [FLASH_DEBUG] Timer already deleted: {e}")

            self._current_border_pen = self._original_border_pen_before_flash
            self.update() # Trigger repaint
        except RuntimeError as e:
            # Qt对象已被删除，静默忽略
            debug_print(f"  [FLASH_DEBUG] Card {self.card_id} already deleted when stopping flash: {e}")
        except Exception as e:
            debug_print(f"  [FLASH_DEBUG] Error stopping flash for Card {self.card_id}: {e}")
        finally:
            self._cleanup_timer_attr("flash_toggle_timer")

    def _toggle_flash_border(self):
        """ Called by the timer to toggle the visual state of the flash. """
        try:
            # BUG FIX: 增强安全检查，防止在停止过程中执行回调
            if not self._is_flashing: # Safety check
                # 只停止定时器，不断开信号
                self._cleanup_timer_attr("flash_toggle_timer")
                return

            # 检查对象是否仍然有效
            if not hasattr(self, 'card_id'):
                debug_print(f"  [FLASH_DEBUG] Card object invalid in toggle callback")
                return

            if not self._is_animation_visible():
                return

            self._flash_border_on = not self._flash_border_on
            if self._flash_border_on:
                # 橙色闪烁用于显示连线关系
                self._current_border_pen = self.flash_border_pen
            else:
                # Show the original border during the "off" cycle of the flash
                self._current_border_pen = self._original_border_pen_before_flash
            self.update()
        except RuntimeError as e:
            # Qt对象已被删除，停止定时器（不断开信号）
            debug_print(f"  [FLASH_DEBUG] Card already deleted in toggle callback: {e}")
            self._cleanup_timer_attr("flash_toggle_timer")
        except Exception as e:
            debug_print(f"  [FLASH_DEBUG] Error in toggle flash: {e}")
            # 发生错误时也尝试停止定时器
            self._cleanup_timer_attr("flash_toggle_timer")
    # --- END Flash methods ---

    # --- ADDED: 选中闪烁方法 ---
    def start_selection_flash(self):
        """启动选中状态的蓝色闪烁效果"""
        if self._is_selection_flashing:
            return  # 已经在闪烁
        debug_print(f"  [SELECTION_FLASH_DEBUG] Starting selection flash for Card {self.card_id}")
        self._is_selection_flashing = True
        self._selection_flash_border_on = True  # 开始时显示蓝色边框
        timer = self._ensure_selection_flash_timer()
        if timer is not None:
            timer.start(self.selection_flash_interval_ms)
        if self._is_animation_visible():
            self.update()

    def stop_selection_flash(self):
        """停止选中状态的蓝色闪烁效果"""
        try:
            if not self._is_selection_flashing:
                return
            debug_print(f"  [SELECTION_FLASH_DEBUG] Stopping selection flash for Card {self.card_id}")
            self._is_selection_flashing = False
            self._selection_flash_border_on = False
            timer = getattr(self, "selection_flash_timer", None)
            if timer is not None:
                try:
                    timer.stop()
                except RuntimeError:
                    pass
            self.update()
        except RuntimeError as e:
            debug_print(f"  [SELECTION_FLASH_DEBUG] Card already deleted when stopping selection flash: {e}")
        except Exception as e:
            debug_print(f"  [SELECTION_FLASH_DEBUG] Error stopping selection flash: {e}")
        finally:
            self._cleanup_timer_attr("selection_flash_timer")

    def _toggle_selection_flash_border(self):
        """选中闪烁定时器回调 - 切换蓝色边框显示状态"""
        try:
            if not self._is_selection_flashing:
                self._cleanup_timer_attr("selection_flash_timer")
                return

            if not hasattr(self, 'card_id'):
                return

            if not self._is_animation_visible():
                return

            self._selection_flash_border_on = not self._selection_flash_border_on
            self.update()
        except RuntimeError as e:
            debug_print(f"  [SELECTION_FLASH_DEBUG] Card already deleted in toggle callback: {e}")
            self._cleanup_timer_attr("selection_flash_timer")
        except Exception as e:
            debug_print(f"  [SELECTION_FLASH_DEBUG] Error in toggle selection flash: {e}")
            self._cleanup_timer_attr("selection_flash_timer")
    # --- END 选中闪烁方法 ---

    def refresh_theme(self):
        """Refresh theme-dependent colors and cached styles."""
        try:
            self.card_color = self._get_theme_card_color()
            self.title_area_color = self._get_theme_title_color()
            self.title_color = self._get_theme_text_color()

            self._apply_visual_profile()
            self._cached_bg_color = self.state_colors.get(self.execution_state, self.card_color)
            self._cached_border_pen = self.state_border_pens.get(self.execution_state, self.default_pen)

            self.update_selection_effect(self.isSelected())
            self.update()
        except Exception as e:
            debug_print(f"  [THEME_REFRESH] Error refreshing theme for Card {self.card_id}: {e}")

