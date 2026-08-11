import ctypes
import sys

from PySide6.QtCore import QPointF, QRect, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from .main_window_dropdown_helpers import (
    CenteredTextDelegate,
    FullBleedListWidget,
    NoWheelDoubleSpinBox,
    NoWheelSpinBox,
    RoundedPopupFrame,
)
from .main_window_dropdown_widget import CustomDropdown, QComboBox
from utils.window_coordinate_common import native_point_to_qt_global

if sys.platform.startswith("win"):

    _KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class _MEMORY_BASIC_INFORMATION(ctypes.Structure):

        _fields_ = [

            ("BaseAddress", ctypes.c_void_p),

            ("AllocationBase", ctypes.c_void_p),

            ("AllocationProtect", ctypes.wintypes.DWORD),

            ("RegionSize", ctypes.c_size_t),

            ("State", ctypes.wintypes.DWORD),

            ("Protect", ctypes.wintypes.DWORD),

            ("Type", ctypes.wintypes.DWORD),

        ]

    _KERNEL32.VirtualQuery.argtypes = [

        ctypes.c_void_p,

        ctypes.POINTER(_MEMORY_BASIC_INFORMATION),

        ctypes.c_size_t,

    ]

    _KERNEL32.VirtualQuery.restype = ctypes.c_size_t

    def _safe_get_win_msg(message_ptr):

        try:

            ptr = int(message_ptr)

        except Exception:

            return None

        if ptr <= 0:

            return None

        MEM_COMMIT = 0x1000

        PAGE_NOACCESS = 0x01

        PAGE_GUARD = 0x100

        mbi = _MEMORY_BASIC_INFORMATION()

        res = _KERNEL32.VirtualQuery(ctypes.c_void_p(ptr), ctypes.byref(mbi), ctypes.sizeof(mbi))

        if not res:

            return None

        if int(mbi.State) != MEM_COMMIT:

            return None

        if int(mbi.Protect) & (PAGE_NOACCESS | PAGE_GUARD):

            return None

        base = int(mbi.BaseAddress or 0)

        if base <= 0:

            return None

        offset = ptr - base

        if offset < 0:

            return None

        if offset + ctypes.sizeof(ctypes.wintypes.MSG) > int(mbi.RegionSize):

            return None

        return ctypes.cast(ctypes.c_void_p(ptr), ctypes.POINTER(ctypes.wintypes.MSG)).contents

else:

    def _safe_get_win_msg(message_ptr):

        return None

def get_theme_color(color_key: str, default: str = '#000000') -> str:

    """获取当前主题的颜色值"""

    try:

        from themes import get_theme_manager

        theme_manager = get_theme_manager()

        return theme_manager.get_color(color_key)

    except:

        return default

def is_dark_theme() -> bool:

    """判断当前是否为深色主题"""

    try:

        from themes import get_theme_manager

        theme_manager = get_theme_manager()

        return theme_manager.is_dark_mode()

    except:

        return False

def get_secondary_text_color() -> str:

    """获取次要文本颜色"""

    return get_theme_color('text_secondary', '#666666')

def get_disabled_text_color() -> str:

    """获取禁用文本颜色"""

    return get_theme_color('text_disabled', '#999999')

def get_success_color() -> str:

    """获取成功状态颜色"""

    return get_theme_color('success', '#4CAF50')

def get_error_color() -> str:

    """获取错误状态颜色"""

    return get_theme_color('error', '#FF5722')

def get_info_color() -> str:

    """获取信息状态颜色"""

    return get_theme_color('info', '#0078d4')

def _get_toolbar_icon_color() -> QColor:

    """获取标题栏动作图标颜色（跟随主题文本色）。"""

    icon_color = QColor(get_theme_color('text', '#1f2328'))

    if not icon_color.isValid():

        icon_color = QColor('#1f2328')

    icon_color.setAlpha(245)

    return icon_color

def _build_toolbar_icon(size: int, draw_fn) -> QIcon:

    """构建支持多尺寸缩放的透明背景图标。"""

    base = 128

    base_pixmap = QPixmap(base, base)

    base_pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(base_pixmap)

    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    draw_fn(painter, base)

    painter.end()

    icon = QIcon()

    for px in sorted(set([16, 18, 20, 22, 24, 26, 28, 32, max(16, int(size))])):

        scaled = base_pixmap.scaled(px, px, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)

        icon.addPixmap(scaled)

    return icon

def create_hourglass_icon(size: int = 24) -> QIcon:

    """绘制现代极简定时图标（正方形时钟，透明底）。"""

    icon_color = _get_toolbar_icon_color()

    def draw_fn(painter: QPainter, base: int):

        cx = base * 0.5

        cy = base * 0.5

        clock_rect = QRect(int(base * 0.16), int(base * 0.16), int(base * 0.68), int(base * 0.68))

        ring_pen = QPen(icon_color, base * 0.075, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)

        painter.setPen(ring_pen)

        painter.setBrush(Qt.BrushStyle.NoBrush)

        corner_radius = base * 0.15

        painter.drawRoundedRect(clock_rect, corner_radius, corner_radius)

        hand_pen = QPen(icon_color, base * 0.07, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)

        painter.setPen(hand_pen)

        # 时针（约10点）

        painter.drawLine(QPointF(cx, cy), QPointF(cx - base * 0.10, cy - base * 0.08))

        # 分针（约2点）

        painter.drawLine(QPointF(cx, cy), QPointF(cx + base * 0.12, cy - base * 0.10))

    return _build_toolbar_icon(size, draw_fn)

def create_media_control_icon(control: str, size: int = 24) -> QIcon:

    """绘制标题栏启动/停止/暂停图标。"""

    icon_color = _get_toolbar_icon_color()

    kind = (control or 'play').strip().lower()

    def draw_fn(painter: QPainter, base: int):

        painter.setPen(Qt.PenStyle.NoPen)

        painter.setBrush(QBrush(icon_color))

        if kind == 'stop':

            stop_rect = QRect(int(base * 0.23), int(base * 0.23), int(base * 0.54), int(base * 0.54))

            painter.drawRoundedRect(stop_rect, base * 0.06, base * 0.06)

            return

        if kind == 'pause':

            bar_w = base * 0.17

            bar_h = base * 0.56

            top = base * 0.22

            left = base * 0.24

            gap = base * 0.18

            left_rect = QRect(int(left), int(top), int(bar_w), int(bar_h))

            right_rect = QRect(int(left + bar_w + gap), int(top), int(bar_w), int(bar_h))

            painter.drawRoundedRect(left_rect, base * 0.035, base * 0.035)

            painter.drawRoundedRect(right_rect, base * 0.035, base * 0.035)

            return

        play_path = QPainterPath()

        play_path.moveTo(base * 0.27, base * 0.20)

        play_path.lineTo(base * 0.27, base * 0.80)

        play_path.lineTo(base * 0.79, base * 0.50)

        play_path.closeSubpath()

        painter.drawPath(play_path)

    return _build_toolbar_icon(size, draw_fn)

def normalize_execution_mode(mode: str) -> str:

    """

    将新的执行模式标准化为基础的 'foreground' 或 'background' 或 'emulator' 或 'hook'

    用于兼容现有的判断逻辑

    Args:

        mode: 执行模式标识

    Returns:

        'foreground', 'background', 'emulator', 或 'hook'

    """

    if mode.startswith('foreground'):

        return 'foreground'

    elif mode.startswith('background'):

        return 'background'

    elif mode.startswith('emulator_'):

        return 'emulator'

    elif mode.startswith('hook_'):

        return 'hook'

    else:

        # 兼容旧的模式标识

        return mode

def normalize_execution_mode_setting(mode: str) -> str:

    """

    将旧的执行模式配置值转换为新的模式标识

    Args:

        mode: 执行模式标识

    Returns:

        新的执行模式标识

    """

    if mode == 'foreground':

        return 'foreground_driver'

    if mode == 'background':

        return 'background_sendmessage'

    return mode

def parse_execution_mode(mode: str) -> tuple:

    """

    将UI的execution_mode转换为operation_mode和execution_mode

    Args:

        mode: UI的执行模式标识

    Returns:

        (operation_mode, execution_mode) 元组

    """

    # 前台模式

    if mode.startswith('foreground'):

        return ('auto', 'foreground')

    # 后台模式

    elif mode.startswith('background'):

        return ('auto', 'background')

    # 默认

    else:

        return ('auto', 'background')

def format_time_display(seconds: int) -> str:

    """

    将秒数格式化为易读的时间显示格式

    Args:

        seconds: 秒数

    Returns:

        格式化后的时间字符串，例如 "1小时30分钟" 或 "45秒"

    """

    if seconds < 60:

        return f"{seconds}秒"

    elif seconds < 3600:

        minutes = seconds // 60

        remaining_seconds = seconds % 60

        if remaining_seconds == 0:

            return f"{minutes}分钟"

        return f"{minutes}分钟{remaining_seconds}秒"

    else:

        hours = seconds // 3600

        remaining_minutes = (seconds % 3600) // 60

        remaining_seconds = seconds % 60

        result = f"{hours}小时"

        if remaining_minutes > 0:

            result += f"{remaining_minutes}分钟"

        if remaining_seconds > 0:

            result += f"{remaining_seconds}秒"

        return result

