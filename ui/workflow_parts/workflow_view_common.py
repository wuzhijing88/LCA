from typing import Optional, Any, Dict, List # Import Dict for type hinting

from .workflow_debug_utils import debug_print
from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QApplication, QPushButton, QVBoxLayout, QWidget, QGraphicsLineItem, QMenu, QInputDialog, QMessageBox, QDialog, QFileDialog, QGraphicsEllipseItem, QComboBox, QFrame, QGraphicsItem # Removed QResizeEvent, QShowEvent
from PySide6.QtCore import Qt, QRectF, QPointF, Signal, QLineF, QTimer # <<< ADDED QTimer
from PySide6.QtGui import QPainter, QWheelEvent, QColor, QBrush, QMouseEvent, QPen, QAction, QTransform, QResizeEvent, QShowEvent, QCursor, QPixmapCache # <<< ADDED QResizeEvent, QShowEvent HERE
import os
# Import json module
import json
import logging # <-- Import logging
import collections # <-- Added for BFS traversal
import copy # Added for deep copy
import re # <<< ADDED: Import re for regex parsing
from datetime import datetime # <<< ADDED: Import datetime for metadata
import os # <<< ADDED: Import os for file operations
import time # <<< ADDED: Import time for undo timestamp
import math

from task_workflow.thread_window_binding import (
    is_thread_window_limit_task_type,
    is_valid_thread_window_limit_connection,
)
from utils.thread_start_utils import is_thread_start_task_type

logger = logging.getLogger(__name__) # <<< ADDED: Define module-level logger


# ===== 自定义 SpinBox 类，禁用滚轮修改数值 =====
from PySide6.QtWidgets import QSpinBox, QDoubleSpinBox


class NoWheelSpinBox(QSpinBox):
    """禁用滚轮事件的 QSpinBox"""
    def wheelEvent(self, event):
        event.ignore()


class NoWheelDoubleSpinBox(QDoubleSpinBox):
    """禁用滚轮事件的 QDoubleSpinBox"""
    def wheelEvent(self, event):
        event.ignore()
# ================================================

class TempConnectionLine(QGraphicsLineItem):
    """Temporary drag line with local antialiasing to reduce jagged edges."""
    def paint(self, painter, option, widget=None):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        super().paint(painter, option, widget)
        painter.restore()

# --- MOVED TaskCard import earlier for Signal definition ---
from ..workflow_parts.task_card import TaskCard, PORT_TYPES # Import TaskCard and PORT_TYPES
# ----------------------------------------------------------
from ..workflow_parts.connection_line import ConnectionLine, ConnectionType # Import ConnectionLine and ConnectionType
from ..system_parts.menu_style import apply_unified_menu_style
# Removed direct import of TASK_MODULES
# from tasks import TASK_MODULES 
# Import the new dialog
from ..dialogs.select_task_dialog import SelectTaskDialog

# Define padding for fitInView
FIT_VIEW_PADDING = 50
# Define snapping distance for connection lines
SNAP_DISTANCE = 15

