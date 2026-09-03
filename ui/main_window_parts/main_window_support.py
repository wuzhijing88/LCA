import ctypes
import math
import sys

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


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

    except Exception:

        return default

def is_dark_theme() -> bool:

    """判断当前是否为深色主题"""

    try:

        from themes import get_theme_manager

        theme_manager = get_theme_manager()

        return theme_manager.is_dark_mode()

    except Exception:

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

    icon_color = QColor(get_theme_color('text', '#333333'))

    if not icon_color.isValid():

        icon_color = QColor('#333333')

    icon_color.setAlpha(245)

    return icon_color

# 系统细线图标风格：等线宽、圆角描边、统一光学校准框（参考 SF / 系统图标气质，非照抄）
_LINE_MARGIN = 0.13
_LINE_STROKE = 0.068
_LINE_RADIUS = 0.20


def _line_stroke(px: int) -> float:
    return max(1.3, px * _LINE_STROKE)


def _line_content_rect(px: int) -> QRectF:
    margin = px * _LINE_MARGIN
    return QRectF(margin, margin, px - margin * 2, px - margin * 2)


def _line_radius(rect: QRectF, ratio: float = _LINE_RADIUS) -> float:
    return min(rect.width(), rect.height()) * ratio


def _line_pen(color: QColor, px: int) -> QPen:
    return QPen(
        color,
        _line_stroke(px),
        Qt.PenStyle.SolidLine,
        Qt.PenCapStyle.RoundCap,
        Qt.PenJoinStyle.RoundJoin,
    )


def _build_modern_line_icon(size: int, draw_fn, color: "QColor | None" = None) -> QIcon:
    """系统风格细线图标：描边为主，媒体控件用实心几何。"""
    target = max(16, int(size))
    sizes = sorted({16, 18, 20, 22, 24, 26, 28, 32, target})
    icon = QIcon()
    paint_color = QColor(color) if color is not None else _get_toolbar_icon_color()
    if not paint_color.isValid():
        paint_color = _get_toolbar_icon_color()
    for px in sizes:
        pixmap = QPixmap(px, px)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(_line_pen(paint_color, px))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        draw_fn(painter, px, paint_color)
        painter.end()
        icon.addPixmap(pixmap)
    return icon


def _build_toolbar_icon(size: int, draw_fn) -> QIcon:
    """兼容旧调用：转发到细线直绘。"""
    return _build_modern_line_icon(size, lambda painter, px, _color: draw_fn(painter, px))


def create_toggle_toolbar_icon(size: int = 22) -> QIcon:
    """显示/隐藏：双 chevron。"""

    def draw(painter: QPainter, px: int, color: QColor):
        area = _line_content_rect(px)
        cy = area.center().y()
        span = area.height() * 0.34
        tip = area.width() * 0.24
        for fx in (0.30, 0.54):
            x = area.left() + area.width() * fx
            painter.drawLine(QPointF(x, cy - span), QPointF(x + tip, cy))
            painter.drawLine(QPointF(x + tip, cy), QPointF(x, cy + span))

    return _build_modern_line_icon(size, draw)


def create_save_toolbar_icon(size: int = 22) -> QIcon:
    """保存：软盘（外壳 + 顶滑片贴顶 + 底标签，细节克制）。"""

    def draw(painter: QPainter, px: int, color: QColor):
        a = _line_content_rect(px)
        r = _line_radius(a, 0.18)
        painter.drawRoundedRect(a, r, r)
        # 顶滑片：贴住上边，左右留白，像金属片凹槽
        shutter_w = a.width() * 0.42
        shutter_h = a.height() * 0.22
        shutter = QRectF(a.center().x() - shutter_w * 0.5, a.top(), shutter_w, shutter_h)
        # 只画左右和下边，上边与外壳重合不重复描边
        painter.drawLine(QPointF(shutter.left(), shutter.top()), QPointF(shutter.left(), shutter.bottom()))
        painter.drawLine(QPointF(shutter.right(), shutter.top()), QPointF(shutter.right(), shutter.bottom()))
        painter.drawLine(QPointF(shutter.left(), shutter.bottom()), QPointF(shutter.right(), shutter.bottom()))
        # 底标签：单层圆角框
        label = QRectF(
            a.left() + a.width() * 0.18,
            a.top() + a.height() * 0.48,
            a.width() * 0.64,
            a.height() * 0.36,
        )
        painter.drawRoundedRect(label, _line_radius(label, 0.22), _line_radius(label, 0.22))

    return _build_modern_line_icon(size, draw)


def create_open_toolbar_icon(size: int = 22) -> QIcon:
    """打开：连贯描边文件夹。"""

    def draw(painter: QPainter, px: int, color: QColor):
        a = _line_content_rect(px)
        r = min(a.width(), a.height()) * 0.16
        tab_w = a.width() * 0.42
        tab_h = a.height() * 0.18
        body_top = a.top() + tab_h * 0.70
        path = QPainterPath()
        path.moveTo(a.left() + r, a.top())
        path.lineTo(a.left() + tab_w - r * 0.4, a.top())
        path.quadTo(a.left() + tab_w, a.top(), a.left() + tab_w + r * 0.3, a.top() + tab_h * 0.55)
        path.lineTo(a.right() - r, body_top)
        path.quadTo(a.right(), body_top, a.right(), body_top + r)
        path.lineTo(a.right(), a.bottom() - r)
        path.quadTo(a.right(), a.bottom(), a.right() - r, a.bottom())
        path.lineTo(a.left() + r, a.bottom())
        path.quadTo(a.left(), a.bottom(), a.left(), a.bottom() - r)
        path.lineTo(a.left(), a.top() + r)
        path.quadTo(a.left(), a.top(), a.left() + r, a.top())
        painter.drawPath(path)

    return _build_modern_line_icon(size, draw)


def create_new_toolbar_icon(size: int = 22) -> QIcon:
    """新建：折角文档描边。"""

    def draw(painter: QPainter, px: int, color: QColor):
        a = _line_content_rect(px)
        # 稍收窄，更像纸张比例
        doc = QRectF(
            a.left() + a.width() * 0.10,
            a.top(),
            a.width() * 0.80,
            a.height(),
        )
        fold = min(doc.width(), doc.height()) * 0.28
        r = _line_radius(doc, 0.14)
        path = QPainterPath()
        path.moveTo(doc.left() + r, doc.top())
        path.lineTo(doc.right() - fold, doc.top())
        path.lineTo(doc.right(), doc.top() + fold)
        path.lineTo(doc.right(), doc.bottom() - r)
        path.quadTo(doc.right(), doc.bottom(), doc.right() - r, doc.bottom())
        path.lineTo(doc.left() + r, doc.bottom())
        path.quadTo(doc.left(), doc.bottom(), doc.left(), doc.bottom() - r)
        path.lineTo(doc.left(), doc.top() + r)
        path.quadTo(doc.left(), doc.top(), doc.left() + r, doc.top())
        painter.drawPath(path)
        # 折角线
        painter.drawLine(
            QPointF(doc.right() - fold, doc.top()),
            QPointF(doc.right() - fold, doc.top() + fold - r * 0.2),
        )
        painter.drawLine(
            QPointF(doc.right() - fold + r * 0.2, doc.top() + fold),
            QPointF(doc.right(), doc.top() + fold),
        )
        for fy in (0.48, 0.64):
            y = doc.top() + doc.height() * fy
            painter.drawLine(
                QPointF(doc.left() + doc.width() * 0.22, y),
                QPointF(doc.right() - doc.width() * 0.22, y),
            )

    return _build_modern_line_icon(size, draw)


def create_export_standalone_icon(size: int = 22) -> QIcon:
    """制作独立程序：托盘 + 上箭头（导出为独立应用）。"""

    def draw(painter: QPainter, px: int, color: QColor):
        a = _line_content_rect(px)
        # 底部托盘（开口方框）
        tray_top = a.top() + a.height() * 0.42
        r = min(a.width(), a.height()) * 0.16
        tray = QPainterPath()
        tray.moveTo(a.left(), tray_top)
        tray.lineTo(a.left(), a.bottom() - r)
        tray.quadTo(a.left(), a.bottom(), a.left() + r, a.bottom())
        tray.lineTo(a.right() - r, a.bottom())
        tray.quadTo(a.right(), a.bottom(), a.right(), a.bottom() - r)
        tray.lineTo(a.right(), tray_top)
        painter.drawPath(tray)
        # 上箭头
        cx = a.center().x()
        tip_y = a.top() + a.height() * 0.06
        shaft_bottom = a.top() + a.height() * 0.58
        head = a.width() * 0.22
        painter.drawLine(QPointF(cx, tip_y + head * 0.35), QPointF(cx, shaft_bottom))
        painter.drawLine(QPointF(cx - head, tip_y + head), QPointF(cx, tip_y))
        painter.drawLine(QPointF(cx + head, tip_y + head), QPointF(cx, tip_y))

    return _build_modern_line_icon(size, draw)


def create_hourglass_icon(size: int = 22) -> QIcon:
    """定时：圆形时钟（无外框）。"""

    def draw(painter: QPainter, px: int, color: QColor):
        a = _line_content_rect(px)
        cx = a.center().x()
        cy = a.center().y()
        radius = min(a.width(), a.height()) * 0.46
        painter.drawEllipse(QPointF(cx, cy), radius, radius)
        painter.drawLine(QPointF(cx, cy), QPointF(cx, cy - radius * 0.55))
        painter.drawLine(
            QPointF(cx, cy),
            QPointF(cx + radius * 0.42, cy + radius * 0.08),
        )

    return _build_modern_line_icon(size, draw)


def create_monitor_toolbar_icon(size: int = 22) -> QIcon:
    """中控/调试：显示器。"""

    def draw(painter: QPainter, px: int, color: QColor):
        a = _line_content_rect(px)
        screen = QRectF(a.left(), a.top(), a.width(), a.height() * 0.68)
        painter.drawRoundedRect(screen, _line_radius(screen, 0.18), _line_radius(screen, 0.18))
        # 底座：短颈 + 横托
        neck_y = screen.bottom()
        base_y = a.bottom() - a.height() * 0.04
        painter.drawLine(QPointF(a.center().x(), neck_y), QPointF(a.center().x(), base_y - a.height() * 0.02))
        painter.drawLine(
            QPointF(a.left() + a.width() * 0.30, base_y),
            QPointF(a.right() - a.width() * 0.30, base_y),
        )

    return _build_modern_line_icon(size, draw)


def create_copy_toolbar_icon(size: int = 22) -> QIcon:
    """复制：重叠卡片描边。"""

    def draw(painter: QPainter, px: int, color: QColor):
        a = _line_content_rect(px)
        offset = a.width() * 0.18
        back = QRectF(a.left() + offset, a.top(), a.width() - offset, a.height() - offset)
        front = QRectF(a.left(), a.top() + offset, a.width() - offset, a.height() - offset)
        painter.drawRoundedRect(back, _line_radius(back, 0.18), _line_radius(back, 0.18))
        painter.drawRoundedRect(front, _line_radius(front, 0.18), _line_radius(front, 0.18))

    return _build_modern_line_icon(size, draw)


def create_settings_toolbar_icon(size: int = 22) -> QIcon:
    """全局设置：齿轮描边。"""

    def draw(painter: QPainter, px: int, color: QColor):
        a = _line_content_rect(px)
        cx = a.center().x()
        cy = a.center().y()
        outer = min(a.width(), a.height()) * 0.48
        root = outer * 0.70
        hole = outer * 0.30
        teeth = 6
        step = 2 * math.pi / teeth
        tip = step * 0.18
        path = QPainterPath()
        first = True
        for i in range(teeth):
            base = -math.pi / 2 + i * step
            # 齿根 → 齿顶 → 齿顶 → 齿根 → 沿齿根走到下一齿
            segments = (
                (base - tip * 1.6, root),
                (base - tip, outer),
                (base + tip, outer),
                (base + tip * 1.6, root),
                (base + step - tip * 1.6, root),
            )
            for ang, radius in segments:
                x = cx + math.cos(ang) * radius
                y = cy + math.sin(ang) * radius
                if first:
                    path.moveTo(x, y)
                    first = False
                else:
                    path.lineTo(x, y)
        path.closeSubpath()
        painter.drawPath(path)
        painter.drawEllipse(QPointF(cx, cy), hole, hole)

    return _build_modern_line_icon(size, draw)


def create_window_topmost_icon(size: int = 16) -> QIcon:
    """置顶：顶栏 + 上箭头。"""

    def draw(painter: QPainter, px: int, color: QColor):
        a = _line_content_rect(px)
        bar_y = a.top() + a.height() * 0.18
        painter.drawLine(
            QPointF(a.left() + a.width() * 0.12, bar_y),
            QPointF(a.right() - a.width() * 0.12, bar_y),
        )
        cx = a.center().x()
        tip_y = a.top() + a.height() * 0.30
        base_y = a.bottom() - a.height() * 0.12
        head = a.width() * 0.22
        painter.drawLine(QPointF(cx, tip_y + head * 0.35), QPointF(cx, base_y))
        painter.drawLine(QPointF(cx - head, tip_y + head), QPointF(cx, tip_y))
        painter.drawLine(QPointF(cx + head, tip_y + head), QPointF(cx, tip_y))

    return _build_modern_line_icon(size, draw)


def create_window_minimize_icon(size: int = 16) -> QIcon:
    """最小化：中位横线。"""

    def draw(painter: QPainter, px: int, color: QColor):
        a = _line_content_rect(px)
        y = a.center().y()
        inset = a.width() * 0.14
        painter.drawLine(QPointF(a.left() + inset, y), QPointF(a.right() - inset, y))

    return _build_modern_line_icon(size, draw)


def create_window_maximize_icon(size: int = 16) -> QIcon:
    """最大化：单层圆角方框。"""

    def draw(painter: QPainter, px: int, color: QColor):
        a = _line_content_rect(px)
        box = a.adjusted(
            a.width() * 0.08,
            a.height() * 0.08,
            -a.width() * 0.08,
            -a.height() * 0.08,
        )
        painter.drawRoundedRect(box, _line_radius(box, 0.16), _line_radius(box, 0.16))

    return _build_modern_line_icon(size, draw)


def create_window_restore_icon(size: int = 16) -> QIcon:
    """还原：重叠双框。"""

    def draw(painter: QPainter, px: int, color: QColor):
        a = _line_content_rect(px)
        inset = min(a.width(), a.height()) * 0.10
        offset = min(a.width(), a.height()) * 0.22
        back = QRectF(
            a.left() + inset + offset * 0.35,
            a.top() + inset,
            a.width() - inset * 2 - offset,
            a.height() - inset * 2 - offset,
        )
        front = QRectF(
            a.left() + inset,
            a.top() + inset + offset,
            a.width() - inset * 2 - offset,
            a.height() - inset * 2 - offset,
        )
        painter.drawRoundedRect(back, _line_radius(back, 0.16), _line_radius(back, 0.16))
        painter.drawRoundedRect(front, _line_radius(front, 0.16), _line_radius(front, 0.16))

    return _build_modern_line_icon(size, draw)


def create_window_close_icon(size: int = 16, color: "QColor | None" = None) -> QIcon:
    """关闭：交叉线。"""

    def draw(painter: QPainter, px: int, color: QColor):
        a = _line_content_rect(px)
        inset = a.width() * 0.18
        painter.drawLine(
            QPointF(a.left() + inset, a.top() + inset),
            QPointF(a.right() - inset, a.bottom() - inset),
        )
        painter.drawLine(
            QPointF(a.right() - inset, a.top() + inset),
            QPointF(a.left() + inset, a.bottom() - inset),
        )

    return _build_modern_line_icon(size, draw, color=color)


def create_media_control_icon(control: str, size: int = 22) -> QIcon:
    """运行/停止/暂停：实心圆角几何（与系统媒体控件一致）。"""
    kind = (control or "play").strip().lower()

    def draw(painter: QPainter, px: int, color: QColor):
        a = _line_content_rect(px)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(color))
        if kind == "stop":
            inset = a.width() * 0.14
            stop = a.adjusted(inset, inset, -inset, -inset)
            painter.drawRoundedRect(stop, _line_radius(stop, 0.22), _line_radius(stop, 0.22))
            return
        if kind == "pause":
            bar_w = a.width() * 0.22
            gap = a.width() * 0.16
            top = a.top() + a.height() * 0.12
            h = a.height() * 0.76
            left = a.center().x() - gap * 0.5 - bar_w
            r = bar_w * 0.35
            painter.drawRoundedRect(QRectF(left, top, bar_w, h), r, r)
            painter.drawRoundedRect(QRectF(left + bar_w + gap, top, bar_w, h), r, r)
            return
        # play：圆角实心三角
        path = QPainterPath()
        x0 = a.left() + a.width() * 0.30
        x1 = a.right() - a.width() * 0.16
        y0 = a.top() + a.height() * 0.16
        y1 = a.bottom() - a.height() * 0.16
        cy = a.center().y()
        path.moveTo(x0, y0)
        path.lineTo(x0, y1)
        path.lineTo(x1, cy)
        path.closeSubpath()
        painter.drawPath(path)

    return _build_modern_line_icon(size, draw)

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

