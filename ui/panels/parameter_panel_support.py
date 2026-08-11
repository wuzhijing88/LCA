"""
参数设置面板 - 吸附在主窗口右侧的小窗口
"""

import json
import logging
import os
import random
import re
import time
from functools import partial
from typing import Dict, Any, Optional, List, Set
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QCheckBox, QSpinBox, QDoubleSpinBox, QTextEdit,
    QPlainTextEdit, QPushButton, QScrollArea, QFrame, QGroupBox,
    QSlider, QProgressBar, QFileDialog, QColorDialog, QFontDialog,
    QButtonGroup, QRadioButton, QTabWidget, QSplitter, QFormLayout,
    QGridLayout, QStackedWidget, QSizePolicy, QDialog, QApplication,
    QListWidget, QListWidgetItem, QMenu, QAbstractItemView, QMessageBox,
    QTableWidget, QHeaderView, QInputDialog
)
from PySide6.QtCore import Qt, Signal, QTimer, QSize, QPoint, QRect, QObject, QEvent, Slot, QThread
from PySide6.QtGui import QFont, QPalette, QColor, QPainter, QBrush, QPainterPath, QPen
from utils.app_paths import (
    get_config_path,
    get_favorites_path,
    get_images_dir,
    normalize_workflow_image_path,
)
from utils.thread_start_utils import THREAD_START_TASK_TYPE, is_thread_start_task_type
from tasks.random_jump import get_branch_weight, set_branch_weight
from ..widgets.custom_widgets import CustomDropdown as QComboBox
from ..system_parts.menu_style import apply_unified_menu_style

# 导入截图工具
from ..selectors.screenshot_tool import QuickScreenshotButton

# 统一下拉框样式

logger = logging.getLogger(__name__)


from .support.parameter_panel_support_buttons import CloseButton, ResponsiveButton
from .support.parameter_panel_support_filters import (
    CheckboxEventFilter,
    FavoritesItemEventFilter,
    InputWidgetEventFilter,
    WheelEventFilter,
)
from .support.parameter_panel_support_media import FlowLayout, ThumbnailWidget
