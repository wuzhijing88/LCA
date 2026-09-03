# -*- coding: utf-8 -*-
"""独立程序外框/内容区：预览与运行共用，保证所见即所得。"""

from __future__ import annotations

import html
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from PySide6.QtCore import QMimeData, QPoint, QRectF, QTime, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QDrag,
    QGuiApplication,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPalette,
    QPixmap,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTabBar,
    QTextEdit,
    QTimeEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

SCRIPT_ROW_MIME = "application/x-lca-script-list-row"

from themes import theme_color

SHELL_BORDER = 1
PLAYER_SHELL_RADIUS = 8
PLAYER_PANEL_RADIUS = 4
WIN_BTN_W = 32
WIN_BTN_H = 28
WIN_BTN_GAP = 2
WIN_BTN_MARGIN = 8


class WheelScrollTabBar(QTabBar):
    """标签条铺满可用宽度；过多时隐藏左右箭头，用滚轮左右平移。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDrawBase(False)
        # 标签均分整条宽度，铺满分区
        self.setExpanding(True)
        # 仍启用内部滚动，但把 scroller 按钮藏起来，改由滚轮驱动
        self.setUsesScrollButtons(True)
        self.setElideMode(Qt.TextElideMode.ElideNone)

    def wheelEvent(self, event: QWheelEvent):
        pixel = event.pixelDelta()
        angle = event.angleDelta()
        delta = 0
        if not pixel.isNull():
            delta = pixel.x() if abs(pixel.x()) >= abs(pixel.y()) else pixel.y()
        if delta == 0 and not angle.isNull():
            delta = angle.x() if abs(angle.x()) >= abs(angle.y()) else angle.y()
        if delta == 0:
            event.accept()
            return
        left_btn, right_btn = self._scroll_tool_buttons()
        # 与常见横向列表一致：滚轮向上/向左 → 内容向左移（露出右侧）；向下/向右 → 露出左侧
        target = right_btn if delta > 0 else left_btn
        if target is not None and target.isEnabled():
            target.click()
        event.accept()

    def _scroll_tool_buttons(self) -> Tuple[Optional[QToolButton], Optional[QToolButton]]:
        buttons = [b for b in self.findChildren(QToolButton) if b.parent() is self]
        if len(buttons) < 2:
            # 兜底：不限制 parent（部分样式下按钮挂在 scroller 容器上）
            buttons = list(self.findChildren(QToolButton))
        if len(buttons) < 2:
            return None, None
        buttons.sort(key=lambda b: b.x())
        return buttons[0], buttons[-1]


def player_tabs_bar_qss(
    *,
    surface: str,
    text: str,
    border: str,
    accent: str,
    font_size: int = 12,
) -> str:
    """标签条样式：隐藏丑箭头，保留内部滚动能力。"""
    try:
        size = max(8, min(72, int(font_size)))
    except (TypeError, ValueError):
        size = 12
    return (
        "QTabBar { background: transparent; border: none; }"
        # 隐藏左右滚动箭头
        "QTabBar::scroller { width: 0px; max-width: 0px; border: none; margin: 0px; padding: 0px; }"
        "QTabBar QToolButton { width: 0px; height: 0px; max-width: 0px; max-height: 0px;"
        " border: none; margin: 0px; padding: 0px; background: transparent; }"
        f"QTabBar::tab {{ background:{surface}; color:{text}; font-size:{size}px;"
        f" border:1px solid {border}; margin-top:4px; margin-right:0px;"
        f" padding:6px 16px 6px 16px; min-width:72px; min-height:24px; }}"
        f"QTabBar::tab:selected {{ background:{accent}; color:#ffffff; font-size:{size}px;"
        f" border:1px solid {accent}; margin-top:0px; margin-right:0px;"
        f" padding:8px 18px 7px 18px; min-height:28px; font-weight:700; }}"
    )


def _theme_palette_colors(*keys: str) -> set[str]:
    """亮/暗主题色板中指定键的全部合法色值（小写 #rrggbb）。"""
    try:
        from themes.theme_manager import ThemeManager

        palettes = ThemeManager.THEME_COLORS
    except Exception:
        return set()
    out: set[str] = set()
    for mode in ("light", "dark"):
        table = palettes.get(mode) or {}
        for key in keys:
            value = str(table.get(key) or "").strip()
            if value.startswith("#") and QColor(value).isValid():
                out.add(QColor(value).name().lower())
    return out


def is_theme_linked_color(color: str, *theme_keys: str) -> bool:
    """是否为「主题默认色」：空/无效，或等于亮暗主题色板中的对应默认值。"""
    raw = str(color or "").strip()
    if not raw.startswith("#") or not QColor(raw).isValid():
        return True
    keys = theme_keys or ("canvas", "background", "card", "text", "text_secondary")
    return QColor(raw).name().lower() in _theme_palette_colors(*keys)


def resolve_player_background_color(background: dict | None) -> str:
    """纯色背景：未自定义或仍是主题默认色时跟随当前主题 canvas。"""
    bg = background if isinstance(background, dict) else {}
    custom = str(bg.get("color") or "").strip()
    live = theme_color("canvas")
    if is_theme_linked_color(custom, "canvas", "background", "card", "surface"):
        return live
    return QColor(custom).name()


def resolve_widget_color(widget: dict, key: str, theme_key: str) -> str:
    """读取控件自定义色；主题默认色/无效色则回退当前主题。"""
    custom = str((widget or {}).get(key) or "").strip()
    if is_theme_linked_color(custom, theme_key):
        return theme_color(theme_key)
    return QColor(custom).name()


def resolve_widget_font_size(widget: dict, default: int = 12) -> int:
    try:
        return max(8, min(72, int((widget or {}).get("font_size") or default)))
    except (TypeError, ValueError):
        return default


def player_panel_frame_qss(
    object_name: str,
    *,
    text: str,
    font_size: int = 12,
    outlined: bool = True,
) -> str:
    """面板外框：无自带底色；默认保留描边好辨认范围。进度条可关外框。"""
    name = str(object_name or "PlayerPanel").strip() or "PlayerPanel"
    size = max(8, min(72, int(font_size or 12)))
    if outlined:
        border = theme_color("border")
        frame = (
            f"QFrame#{name} {{ background:transparent; border:1px solid {border};"
            f" border-radius:{PLAYER_PANEL_RADIUS}px; }}"
        )
    else:
        frame = f"QFrame#{name} {{ background:transparent; border:none; }}"
    return (
        frame
        + f"QFrame#{name} QLabel {{ color:{text}; background:transparent;"
        f" border:none; font-size:{size}px; }}"
    )


def player_rich_text_qss(*, text: str, font_size: int = 12) -> str:
    """多行说明：与脚本列表/日志等面板一致——透明底 + 主题描边。"""
    size = max(8, min(72, int(font_size or 12)))
    color = str(text or theme_color("text"))
    return (
        f"color:{color}; font-size:{size}px;"
        f" background:transparent; background-color:transparent;"
        f" border:1px solid {theme_color('border')};"
        f" border-radius:{PLAYER_PANEL_RADIUS}px;"
        f" padding:6px 8px;"
    )


def apply_player_button_style(btn: QPushButton, widget: dict) -> None:
    """按钮样式：有 bg_color 用自定义底色，否则走主题。

    自定义界面是绝对几何布局：必须清掉全局 QPushButton 的 padding/min-height，
    否则运行时会比预览/设计框大一圈。
    """
    action = str(widget.get("action") or "")
    custom = str(widget.get("bg_color") or "").strip()
    bg = QColor(custom) if custom.startswith("#") else QColor()
    # 锁定几何：抵消 app 级 QSS（padding:6px 16px / min-height 等）
    size_lock = (
        " padding:0px; margin:0px; min-height:0px; min-width:0px;"
        " max-height:16777215px; max-width:16777215px;"
    )
    disabled_fg = theme_color("text_disabled")
    if custom.startswith("#") and bg.isValid():
        if bg.lightness() < 128:
            hover = bg.lighter(118)
            pressed = bg.lighter(108)
            disabled_bg = bg.lighter(112)
            fg = theme_color("accent_text")
            border = "none"
        else:
            hover = bg.darker(106)
            pressed = bg.darker(114)
            disabled_bg = bg.darker(104)
            fg = theme_color("text")
            border = f"1px solid {theme_color('border')}"
        btn.setProperty("primary", False)
        btn.setStyleSheet(
            f"QPushButton {{ background-color:{bg.name()}; color:{fg};"
            f" border:{border}; border-radius:4px;{size_lock} }}"
            f"QPushButton:hover {{ background-color:{hover.name()}; }}"
            f"QPushButton:pressed {{ background-color:{pressed.name()}; }}"
            f"QPushButton:disabled {{ background-color:{disabled_bg.name()};"
            f" color:{disabled_fg}; border:{border}; }}"
        )
        return
    # 无自定义底色：显式主题色，避免宿主全局 QSS 把禁用按钮刷成浅色块
    if action == "start":
        btn.setProperty("primary", True)
        btn.setStyleSheet(
            f"QPushButton {{ background-color:{theme_color('accent')}; color:{theme_color('accent_text')};"
            f" border:none; border-radius:4px; font-weight:600;{size_lock} }}"
            f"QPushButton:hover {{ background-color:{theme_color('accent_hover')}; }}"
            f"QPushButton:pressed {{ background-color:{theme_color('accent_pressed')}; }}"
            f"QPushButton:disabled {{ background-color:{theme_color('surface')};"
            f" color:{disabled_fg}; border:1px solid {theme_color('border')}; }}"
        )
    else:
        btn.setProperty("primary", False)
        btn.setStyleSheet(
            f"QPushButton {{ background-color:{theme_color('surface')}; color:{theme_color('text')};"
            f" border:1px solid {theme_color('border')}; border-radius:4px;{size_lock} }}"
            f"QPushButton:hover {{ background-color:{theme_color('hover')}; }}"
            f"QPushButton:pressed {{ background-color:{theme_color('pressed')}; }}"
            f"QPushButton:disabled {{ background-color:{theme_color('surface')};"
            f" color:{disabled_fg}; border:1px solid {theme_color('border')}; }}"
        )


def player_window_surface_qss() -> str:
    """运行窗本体必须透明，否则无边框 HWND 四角仍是直角色块。"""
    return (
        "QMainWindow#PlayerWindow { background: transparent; border: none; }"
        "QMainWindow#PlayerWindow QWidget#PlayerRoot { background: transparent; }"
        "QMainWindow#PlayerWindow QWidget#PlayerBody { background: transparent; }"
    )


def player_fill_qss(object_name: str, color: str) -> str:
    name = str(object_name or "PlayerBg").strip() or "PlayerBg"
    return (
        f"QLabel#{name} {{ background-color:{color}; border:none;"
        f" border-radius:{PLAYER_SHELL_RADIUS}px; }}"
    )


def apply_player_rounded_window(window) -> None:
    window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    window.setAutoFillBackground(False)
    extra = player_window_surface_qss()
    current = str(window.styleSheet() or "").strip()
    if extra not in current:
        window.setStyleSheet((current + "\n" + extra).strip() if current else extra)


def player_shell_qss(*, dark: bool) -> str:
    if dark:
        return f"""
QWidget#PlayerRoot {{
    background: #2d2d2d;
    border: {SHELL_BORDER}px solid #3e3e3e;
    border-radius: {PLAYER_SHELL_RADIUS}px;
}}
QWidget#PlayerBody {{ background: transparent; }}
"""
    return f"""
QWidget#PlayerRoot {{
    background: #ffffff;
    border: {SHELL_BORDER}px solid #d0d0d0;
    border-radius: {PLAYER_SHELL_RADIUS}px;
}}
QWidget#PlayerBody {{ background: transparent; }}
"""


def _win_button_qss(*, dark: bool, close_btn: bool = False) -> str:
    if dark:
        normal = "#c0c0c0"
        hover_bg = "rgba(255,255,255,0.14)"
        hover_fg = "#ffffff"
    else:
        normal = "#666666"
        hover_bg = "rgba(0,0,0,0.08)"
        hover_fg = "#222222"
    if close_btn:
        return (
            f"QPushButton {{ background: transparent; border: none; color: {normal};"
            f" font-family: 'Segoe UI','Arial'; font-size: 14px; padding: 0; margin: 0;"
            f" border-radius: 4px; }}"
            f"QPushButton:hover {{ background: #e81123; color: #ffffff; }}"
            f"QPushButton:pressed {{ background: #c50f1f; color: #ffffff; }}"
        )
    return (
        f"QPushButton {{ background: transparent; border: none; color: {normal};"
        f" font-family: 'Segoe UI','Arial'; font-size: 14px; padding: 0; margin: 0;"
        f" border-radius: 4px; }}"
        f"QPushButton:hover {{ background: {hover_bg}; color: {hover_fg}; }}"
        f"QPushButton:pressed {{ background: {hover_bg}; color: {hover_fg}; }}"
    )


class PlayerWindowControls(QWidget):
    """叠在设计区右上角内侧：最小化 | 关闭，横排对齐。"""

    minimize_clicked = Signal()
    close_clicked = Signal()

    def __init__(self, parent=None, *, show_minimize: bool = True, dark: bool = False):
        super().__init__(parent)
        self.setObjectName("PlayerWinControls")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("QWidget#PlayerWinControls { background: transparent; border: none; }")
        self._show_minimize = bool(show_minimize)
        self._dark = bool(dark)

        x = 0
        self._min_btn = None
        if self._show_minimize:
            self._min_btn = QPushButton("−", self)
            self._min_btn.setObjectName("PlayerWinButton")
            self._min_btn.setToolTip("最小化")
            self._min_btn.setCursor(Qt.CursorShape.ArrowCursor)
            self._min_btn.setFixedSize(WIN_BTN_W, WIN_BTN_H)
            self._min_btn.setStyleSheet(_win_button_qss(dark=self._dark, close_btn=False))
            self._min_btn.move(x, 0)
            self._min_btn.clicked.connect(self.minimize_clicked.emit)
            x += WIN_BTN_W + WIN_BTN_GAP

        self._close_btn = QPushButton("×", self)
        self._close_btn.setObjectName("PlayerCloseButton")
        self._close_btn.setToolTip("关闭")
        self._close_btn.setCursor(Qt.CursorShape.ArrowCursor)
        self._close_btn.setFixedSize(WIN_BTN_W, WIN_BTN_H)
        self._close_btn.setStyleSheet(_win_button_qss(dark=self._dark, close_btn=True))
        self._close_btn.move(x, 0)
        self._close_btn.clicked.connect(self.close_clicked.emit)
        x += WIN_BTN_W

        self.setFixedSize(x, WIN_BTN_H)

    def reposition(self, host: QWidget) -> None:
        """贴到 host 右上角内侧，避开圆角裁切。"""
        host_w = max(1, host.width())
        x = max(WIN_BTN_MARGIN, host_w - self.width() - WIN_BTN_MARGIN)
        y = WIN_BTN_MARGIN
        self.setGeometry(x, y, self.width(), self.height())
        self.raise_()


def install_window_controls(
    host: QWidget,
    *,
    show_minimize: bool = True,
    on_minimize: Optional[Callable[[], None]] = None,
    on_close: Optional[Callable[[], None]] = None,
    dark: Optional[bool] = None,
) -> PlayerWindowControls:
    if dark is None:
        try:
            from themes import get_theme_manager

            dark = get_theme_manager().is_dark_mode()
        except Exception:
            dark = False
    controls = PlayerWindowControls(host, show_minimize=show_minimize, dark=bool(dark))
    if on_minimize is not None:
        controls.minimize_clicked.connect(on_minimize)
    if on_close is not None:
        controls.close_clicked.connect(on_close)
    controls.reposition(host)
    controls.show()
    controls.raise_()
    # 布局完成后再贴一次，避免 host 尚未拿到最终宽度时跑偏
    from PySide6.QtCore import QTimer

    QTimer.singleShot(0, lambda h=host, c=controls: c.reposition(h) if c is not None else None)
    return controls


def window_outer_size(body_w: int, body_h: int) -> tuple[int, int]:
    """窗口客户区 = 设计尺寸（不再额外加标题栏高度）。"""
    return int(body_w), int(body_h)


def background_image_geometry(
    background: dict,
    body_w: int,
    body_h: int,
) -> Optional[Tuple[int, int, int, int]]:
    """背景图区域。w/h 未设时铺满，兼容旧包。无图片返回 None。"""
    bg = background if isinstance(background, dict) else {}
    if str(bg.get("mode") or "color") != "image":
        return None
    if not str(bg.get("image") or "").strip():
        return None
    width = max(1, int(body_w or 1))
    height = max(1, int(body_h or 1))
    x = int(bg.get("x") or 0)
    y = int(bg.get("y") or 0)
    w = int(bg.get("w") or 0)
    h = int(bg.get("h") or 0)
    if w <= 0 or h <= 0:
        return (0, 0, width, height)
    return (x, y, w, h)


class PlayerShellFill(QLabel):
    """铺满运行区的底色/背景图：按外壳半径裁切，避免运行窗四角被直角色块盖住。"""

    def paintEvent(self, event):
        painter = QPainter(self)
        if not painter.isActive():
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        path = QPainterPath()
        box = QRectF(self.rect())
        if box.width() > 1 and box.height() > 1:
            box = box.adjusted(0.5, 0.5, -0.5, -0.5)
        path.addRoundedRect(box, float(PLAYER_SHELL_RADIUS), float(PLAYER_SHELL_RADIUS))
        painter.setClipPath(path)
        pix = self.pixmap()
        if pix is not None and not pix.isNull():
            painter.drawPixmap(self.rect(), pix)
            return
        color = self.palette().color(QPalette.ColorRole.Window)
        if color.alpha() <= 0:
            color = QColor(theme_color("canvas"))
        painter.fillPath(path, color)


def apply_player_background_geometry(body: QWidget, image_label: Optional[QLabel], background: dict) -> None:
    if body is None:
        return
    fill = body.findChild(QLabel, "PlayerBgFill")
    if fill is not None:
        fill.setGeometry(0, 0, body.width(), body.height())
        fill.lower()
    if image_label is None:
        return
    geo = background_image_geometry(background, body.width(), body.height())
    if geo is None:
        image_label.setGeometry(0, 0, body.width(), body.height())
    else:
        image_label.setGeometry(*geo)
    image_label.lower()
    if fill is not None:
        fill.lower()


def paint_player_background(
    body: QWidget,
    background: dict,
    *,
    load_pixmap: Callable[[str], QPixmap],
) -> QLabel:
    bg = background if isinstance(background, dict) else {}
    color = resolve_player_background_color(bg)
    image = str(bg.get("image") or "")
    fill = PlayerShellFill(body)
    fill.setObjectName("PlayerBgFill")
    fill.setGeometry(0, 0, max(1, body.width()), max(1, body.height()))
    fill.setStyleSheet(player_fill_qss("PlayerBgFill", color))
    fill.setAutoFillBackground(False)
    pal = fill.palette()
    pal.setColor(QPalette.ColorRole.Window, QColor(color))
    fill.setPalette(pal)
    fill.lower()

    geo = background_image_geometry(bg, body.width(), body.height())
    if geo is None:
        # 纯色模式：对象名改为 PlayerBg 时必须同步改 stylesheet，否则颜色选择器失效看起来像白色
        fill.setObjectName("PlayerBg")
        fill.setStyleSheet(player_fill_qss("PlayerBg", color))
        return fill

    label = PlayerShellFill(body)
    label.setObjectName("PlayerBg")
    label.setGeometry(*geo)
    label.setScaledContents(True)
    pix = load_pixmap(image)
    if not pix.isNull():
        label.setPixmap(pix)
        label.setStyleSheet("QLabel#PlayerBg { background:transparent; border:none; }")
    else:
        label.setStyleSheet(player_fill_qss("PlayerBg", color))
        pal = label.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor(color))
        label.setPalette(pal)
    apply_player_background_geometry(body, label, bg)
    return label


def _qt_text_align(align: str) -> Qt.AlignmentFlag:
    key = str(align or "left").lower()
    if key == "center":
        return Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
    if key == "right":
        return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop
    return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop


def widget_center_in_rect(
    x: int, y: int, w: int, h: int, rx: int, ry: int, rw: int, rh: int
) -> bool:
    """控件中心点是否落在矩形内（用于判断是否在标签页分区内）。"""
    if rw <= 0 or rh <= 0 or w <= 0 or h <= 0:
        return False
    cx = float(x) + float(w) * 0.5
    cy = float(y) + float(h) * 0.5
    return float(rx) <= cx < float(rx + rw) and float(ry) <= cy < float(ry + rh)


def apply_player_page_visibility(
    page_nodes: List[Dict[str, Any]],
    active_page: str,
    *,
    known_pages: Optional[List[str]] = None,
) -> None:
    """按当前标签页显隐控件。

    - 分区外 / page 为空：始终显示
    - 分区内且 page 有值：仅 active_page 匹配时显示
    - 无有效 active_page / 无已知页面：全部显示
    """
    active = str(active_page or "")
    known = {str(p) for p in (known_pages or []) if str(p or "")}
    if not active or not known:
        for entry in page_nodes or []:
            for node in entry.get("nodes") or []:
                if node is None:
                    continue
                try:
                    node.setVisible(True)
                except RuntimeError:
                    pass
        return
    for entry in page_nodes or []:
        page = str(entry.get("page") or "")
        in_zone = bool(entry.get("in_zone", True))
        if (not in_zone) or (not page) or (page not in known):
            show = True
        else:
            show = page == active
        for node in entry.get("nodes") or []:
            if node is None:
                continue
            try:
                node.setVisible(show)
            except RuntimeError:
                pass


SCRIPT_ITEM_TITLE_ROLE = Qt.ItemDataRole.UserRole + 1
SCRIPT_ITEM_LOOPS_ROLE = Qt.ItemDataRole.UserRole + 2


def script_item_display_text(
    title: str,
    loops: int = 1,
    *,
    status: str = "",
    loop_index: int = 0,
    loop_total: int = 0,
) -> str:
    name = str(title or "").strip() or "脚本"
    times = max(1, int(loops or 1))
    extra = f"  ×{times}" if times > 1 else ""
    state = str(status or "").strip()
    if state == "running":
        if loop_total > 1:
            return f"{name}{extra}  · 执行中 {loop_index}/{loop_total}"
        return f"{name}{extra}  · 执行中"
    if state == "paused":
        return f"{name}{extra}  · 已暂停"
    if state == "waiting":
        return f"{name}{extra}"
    return f"{name}{extra}"


class OnceAwareCheckBox(QCheckBox):
    """左键只在勾选/取消间切换；右键设为半选「仅一次」。"""

    onceChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTristate(True)
        self.setToolTip("左键勾选；右键「仅一次」（本次执行，跑完清除）")

    def nextCheckState(self):
        if self.checkState() == Qt.CheckState.Checked:
            self.setCheckState(Qt.CheckState.Unchecked)
        else:
            self.setCheckState(Qt.CheckState.Checked)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.RightButton and self.isEnabled():
            self.setCheckState(Qt.CheckState.PartiallyChecked)
            self.onceChanged.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class PlayerScriptListView(QListWidget):
    """支持带 itemWidget 的行内拖拽调序（Qt InternalMove 在 setItemWidget 下不可用）。

    注意：不可 takeItem 后再 setItemWidget——takeItem 会销毁行控件导致闪退。
    拖拽时按鼠标位置实时交换行数据（控件槽位不动）。
    """

    order_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._reorder_enabled = True
        self._dragging_row = -1
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        # 不用内置 InternalMove：与 setItemWidget 不兼容
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDragEnabled(False)
        self.viewport().setAcceptDrops(True)

    def set_reorder_enabled(self, enabled: bool) -> None:
        self._reorder_enabled = bool(enabled)
        if not self._reorder_enabled:
            self._dragging_row = -1

    def reorder_enabled(self) -> bool:
        return bool(self._reorder_enabled)

    def begin_row_drag(self, row: int) -> None:
        self._dragging_row = int(row)

    def end_row_drag(self) -> None:
        self._dragging_row = -1

    def _viewport_pos(self, pos: QPoint, *, source: Optional[QWidget] = None) -> QPoint:
        if source is None:
            return self.viewport().mapFrom(self, pos)
        return self.viewport().mapFromGlobal(source.mapToGlobal(pos))

    def insert_row_for_viewport_pos(self, viewport_pos: QPoint) -> int:
        target_item = self.itemAt(viewport_pos)
        if target_item is None:
            return self.count()
        to_row = self.row(target_item)
        rect = self.visualItemRect(target_item)
        if viewport_pos.y() > rect.center().y():
            to_row += 1
        return to_row

    def _snapshot_row(self, index: int) -> Optional[dict]:
        item = self.item(index)
        if item is None:
            return None
        widget = self.itemWidget(item)
        if isinstance(widget, PlayerScriptTaskRow):
            return widget.export_state()
        sid = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
        if not sid:
            return None
        return {
            "script_id": sid,
            "title": str(item.data(SCRIPT_ITEM_TITLE_ROLE) or sid),
            "loops": int(item.data(SCRIPT_ITEM_LOOPS_ROLE) or 1),
            "check_state": int(Qt.CheckState.Checked),
            "locked": False,
        }

    def _apply_row_snapshot(self, index: int, snap: Mapping[str, Any]) -> None:
        item = self.item(index)
        if item is None:
            return
        sid = str(snap.get("script_id") or "").strip()
        title = str(snap.get("title") or sid)
        loops = int(snap.get("loops") or 1)
        item.setData(Qt.ItemDataRole.UserRole, sid)
        item.setData(SCRIPT_ITEM_TITLE_ROLE, title)
        item.setData(SCRIPT_ITEM_LOOPS_ROLE, loops)
        widget = self.itemWidget(item)
        if isinstance(widget, PlayerScriptTaskRow):
            widget.import_state(snap)

    def move_row(self, from_row: int, to_row: int) -> bool:
        """把 from_row 移到目标下标 to_row（移动前的目标位置，可等于 count 表示末尾）。"""
        count = self.count()
        if from_row < 0 or from_row >= count:
            return False
        insert_at = max(0, min(count, int(to_row)))
        if insert_at == from_row or insert_at == from_row + 1:
            return False
        snapshots: List[dict] = []
        for index in range(count):
            snap = self._snapshot_row(index)
            if snap is None:
                return False
            snapshots.append(snap)
        moving = snapshots.pop(from_row)
        if insert_at > from_row:
            insert_at -= 1
        snapshots.insert(insert_at, moving)
        for index, snap in enumerate(snapshots):
            self._apply_row_snapshot(index, snap)
        if self._dragging_row == from_row:
            self._dragging_row = insert_at
        self.setCurrentRow(insert_at)
        self.order_changed.emit()
        return True

    def reorder_drag_to(self, viewport_pos: QPoint) -> bool:
        if not self._reorder_enabled or self._dragging_row < 0:
            return False
        to_row = self.insert_row_for_viewport_pos(viewport_pos)
        return self.move_row(self._dragging_row, to_row)

    def _accept_script_drag(self, event) -> bool:
        return bool(
            self._reorder_enabled
            and event.mimeData() is not None
            and event.mimeData().hasFormat(SCRIPT_ROW_MIME)
        )

    def dropEvent(self, event):
        if not self._accept_script_drag(event):
            event.ignore()
            return
        # 行已在 dragMove 中按鼠标实时挪动，松手只收尾
        self.end_row_drag()
        event.acceptProposedAction()

    def dragEnterEvent(self, event):
        if self._accept_script_drag(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if not self._accept_script_drag(event):
            event.ignore()
            return
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        self.reorder_drag_to(self._viewport_pos(pos))
        event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        super().dragLeaveEvent(event)


class PlayerScriptTaskRow(QWidget):
    """MAA 式任务行：勾选 + 名称 + 状态 + 次数；名称区可拖拽调序。"""

    def __init__(
        self,
        script_id: str,
        title: str,
        loops: int,
        *,
        checked: bool = True,
        interactive: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        self.script_id = str(script_id or "")
        self._title = str(title or script_id or "脚本")
        self._interactive = bool(interactive)
        self._locked = False
        self._drag_start: Optional[QPoint] = None
        self.setObjectName("PlayerScriptTaskRow")
        self.setAutoFillBackground(False)
        self.setAcceptDrops(bool(interactive))
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(6)
        self._check = OnceAwareCheckBox()
        self._check.setCheckState(
            Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        )
        self._check.setEnabled(interactive)
        self._check.stateChanged.connect(self._sync_once_badge)
        self._check.onceChanged.connect(self._sync_once_badge)
        self._name = QLabel(self._title)
        self._name.setObjectName("PlayerScriptTaskName")
        self._name.setMinimumWidth(40)
        self._name.setToolTip("按住拖拽可调整执行顺序")
        self._name.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._once = QLabel("仅一次")
        self._once.setObjectName("PlayerScriptOnceBadge")
        self._once.setStyleSheet(f"color:{theme_color('warning')};")
        self._once.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._once.hide()
        self._status = QLabel("")
        self._status.setObjectName("PlayerScriptTaskStatus")
        self._status.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._status.hide()
        self._spin = QSpinBox()
        self._spin.setObjectName("PlayerScriptTaskSpin")
        self._spin.setAutoFillBackground(False)
        self._spin.setRange(1, 9999)
        self._spin.setValue(max(1, int(loops or 1)))
        self._spin.setPrefix("× ")
        self._spin.setFixedWidth(70)
        self._spin.setFixedHeight(24)
        self._spin.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._spin.setToolTip("这个工作流重复执行多少次")
        self._spin.setEnabled(interactive)
        layout.addWidget(self._check, 0)
        layout.addWidget(self._name, 1)
        layout.addWidget(self._once, 0)
        layout.addWidget(self._status, 0)
        layout.addWidget(self._spin, 0)
        self.setMinimumHeight(28)
        self._sync_once_badge()

    def _list_view(self) -> Optional[PlayerScriptListView]:
        parent = self.parent()
        while parent is not None:
            if isinstance(parent, PlayerScriptListView):
                return parent
            if isinstance(parent, QListWidget):
                return parent  # type: ignore[return-value]
            parent = parent.parent()
        return None

    def _is_drag_source_pos(self, pos: QPoint) -> bool:
        child = self.childAt(pos)
        if child is None:
            return True
        if child is self._check or self._check.isAncestorOf(child):
            return False
        if child is self._spin or self._spin.isAncestorOf(child):
            return False
        return True

    def export_state(self) -> dict:
        try:
            check_state = int(self._check.checkState().value)
        except Exception:
            check_state = int(Qt.CheckState.Checked.value)
        return {
            "script_id": str(self.script_id or ""),
            "title": str(self._title or self.script_id or ""),
            "loops": self.loops(),
            "check_state": check_state,
            "locked": bool(self._locked),
        }

    def import_state(self, snap: Mapping[str, Any]) -> None:
        sid = str(snap.get("script_id") or "").strip()
        title = str(snap.get("title") or sid)
        loops = max(1, int(snap.get("loops") or 1))
        try:
            state = Qt.CheckState(int(snap.get("check_state") or int(Qt.CheckState.Checked)))
        except (TypeError, ValueError):
            state = Qt.CheckState.Checked
        self.script_id = sid
        self._title = title
        try:
            self._check.blockSignals(True)
            self._spin.blockSignals(True)
            self._name.setText(title)
            self._spin.setValue(loops)
            self._check.setCheckState(state)
            self._sync_once_badge()
        except RuntimeError:
            return
        finally:
            try:
                self._check.blockSignals(False)
                self._spin.blockSignals(False)
            except RuntimeError:
                pass
        self.set_locked(bool(snap.get("locked")))

    def _row_index_in_list(self, list_w: QListWidget) -> int:
        for index in range(list_w.count()):
            item = list_w.item(index)
            if item is not None and list_w.itemWidget(item) is self:
                return index
        return -1

    def _forward_drag_pos(self, event) -> QPoint:
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        return pos

    def dragEnterEvent(self, event):
        list_w = self._list_view()
        if (
            isinstance(list_w, PlayerScriptListView)
            and list_w.reorder_enabled()
            and event.mimeData()
            and event.mimeData().hasFormat(SCRIPT_ROW_MIME)
        ):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        list_w = self._list_view()
        if not isinstance(list_w, PlayerScriptListView) or not list_w.reorder_enabled():
            event.ignore()
            return
        if not event.mimeData() or not event.mimeData().hasFormat(SCRIPT_ROW_MIME):
            event.ignore()
            return
        list_w.reorder_drag_to(list_w._viewport_pos(self._forward_drag_pos(event), source=self))
        event.acceptProposedAction()

    def dropEvent(self, event):
        list_w = self._list_view()
        if isinstance(list_w, PlayerScriptListView):
            list_w.end_row_drag()
            event.acceptProposedAction()
        else:
            event.ignore()

    def mousePressEvent(self, event: QMouseEvent):
        if (
            self._interactive
            and not self._locked
            and event.button() == Qt.MouseButton.LeftButton
            and self._is_drag_source_pos(event.position().toPoint())
        ):
            self._drag_start = event.position().toPoint()
        else:
            self._drag_start = None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if (
            self._drag_start is None
            or self._locked
            or not (event.buttons() & Qt.MouseButton.LeftButton)
        ):
            super().mouseMoveEvent(event)
            return
        if (event.position().toPoint() - self._drag_start).manhattanLength() < QApplication.startDragDistance():
            return
        list_w = self._list_view()
        reorder_ok = True
        if isinstance(list_w, PlayerScriptListView):
            reorder_ok = list_w.reorder_enabled()
        if list_w is None or not reorder_ok:
            self._drag_start = None
            return
        row = self._row_index_in_list(list_w)
        if row < 0:
            self._drag_start = None
            return
        mime = QMimeData()
        mime.setData(SCRIPT_ROW_MIME, str(row).encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        pixmap = self.grab()
        if not pixmap.isNull():
            drag.setPixmap(pixmap)
            drag.setHotSpot(event.position().toPoint())
        self._drag_start = None
        if isinstance(list_w, PlayerScriptListView):
            list_w.begin_row_drag(row)
        try:
            drag.exec(Qt.DropAction.MoveAction)
        finally:
            if isinstance(list_w, PlayerScriptListView):
                list_w.end_row_drag()

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._drag_start = None
        super().mouseReleaseEvent(event)

    def _sync_once_badge(self, *_args):
        try:
            if self.is_once():
                self._once.show()
            else:
                self._once.hide()
        except RuntimeError:
            return

    def is_checked(self) -> bool:
        try:
            return self._check.checkState() != Qt.CheckState.Unchecked
        except RuntimeError:
            return False

    def is_once(self) -> bool:
        try:
            return self._check.checkState() == Qt.CheckState.PartiallyChecked
        except RuntimeError:
            return False

    def clear_once(self):
        try:
            if self.is_once():
                self._check.setCheckState(Qt.CheckState.Unchecked)
                self._sync_once_badge()
        except RuntimeError:
            return

    def loops(self) -> int:
        from app_core.player.package import normalize_script_loop_count

        try:
            return normalize_script_loop_count(self._spin.value(), 1)
        except RuntimeError:
            return 1

    def set_locked(self, locked: bool):
        self._locked = bool(locked)
        try:
            self._check.setEnabled(not locked)
            self._spin.setEnabled(not locked)
        except RuntimeError:
            pass

    def set_run_state(
        self,
        state: str,
        *,
        loop_index: int = 0,
        loop_total: int = 0,
        accent: str = "",
        muted: str = "",
        warn: str = "",
    ):
        try:
            if state == "running":
                text = f"执行中 {loop_index}/{loop_total}" if loop_total > 1 else "执行中"
                self._status.setText(text)
                self._status.setStyleSheet(f"color:{accent or theme_color('accent')};")
                self._status.show()
            elif state == "paused":
                self._status.setText("已暂停")
                self._status.setStyleSheet(f"color:{warn or theme_color('warning')};")
                self._status.show()
            elif state == "waiting":
                self._status.setText("等待")
                self._status.setStyleSheet(f"color:{muted or theme_color('text_secondary')};")
                self._status.show()
            else:
                self._status.clear()
                self._status.hide()
        except RuntimeError:
            return


def iter_script_list_widgets(refs: Dict[str, Any]) -> List[Any]:
    """所有脚本列表控件（保序：list_order / 插入顺序）。"""
    mapping = refs.get("script_lists")
    if isinstance(mapping, dict) and mapping:
        order = refs.get("script_list_order") or list(mapping.keys())
        out = []
        seen = set()
        for key in order:
            wid = mapping.get(key)
            if wid is not None and id(wid) not in seen:
                out.append(wid)
                seen.add(id(wid))
        for key, wid in mapping.items():
            if wid is not None and id(wid) not in seen:
                out.append(wid)
                seen.add(id(wid))
        return out
    single = refs.get("script_list_widget")
    return [single] if single is not None else []


def clear_once_script_checks(refs: Dict[str, Any]):
    """跑完后把「仅一次」半选清回未勾选。"""
    for list_w in iter_script_list_widgets(refs):
        try:
            for index in range(list_w.count()):
                item = list_w.item(index)
                if item is None:
                    continue
                row = _script_row_from_item(list_w, item)
                if row is not None:
                    row.clear_once()
        except RuntimeError:
            continue


def schedule_alarms_from_refs(refs: Dict[str, Any]) -> List[Dict[str, Any]]:
    from app_core.player.package import normalize_schedule_alarms

    rows = refs.get("schedule_alarm_rows") or []
    raw: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        enabled = row.get("enabled")
        time_edit = row.get("time")
        hour, minute = 0, 0
        try:
            if time_edit is not None:
                t = time_edit.time()
                hour, minute = int(t.hour()), int(t.minute())
        except RuntimeError:
            continue
        checked = False
        try:
            checked = bool(enabled.isChecked()) if enabled is not None else False
        except RuntimeError:
            checked = False
        raw.append({"enabled": checked, "hour": hour, "minute": minute})
    if raw:
        return normalize_schedule_alarms(raw)
    return normalize_schedule_alarms(refs.get("schedule_alarms"))


def apply_schedule_alarms_to_refs(refs: Dict[str, Any], alarms: Optional[List[Dict[str, Any]]]):
    from app_core.player.package import normalize_schedule_alarms

    normalized = normalize_schedule_alarms(alarms)
    editor = refs.get("schedule_editor")
    if editor is not None and hasattr(editor, "set_alarms"):
        try:
            editor.set_alarms(normalized)
            refs["schedule_alarm_rows"] = editor.alarm_rows()
            refs["schedule_alarms"] = normalized
            return
        except RuntimeError:
            pass
    rows = refs.get("schedule_alarm_rows") or []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or index >= len(normalized):
            continue
        alarm = normalized[index]
        enabled = row.get("enabled")
        time_edit = row.get("time")
        try:
            if enabled is not None:
                enabled.blockSignals(True)
                enabled.setChecked(bool(alarm.get("enabled")))
                enabled.blockSignals(False)
            if time_edit is not None:
                time_edit.blockSignals(True)
                time_edit.setTime(QTime(int(alarm.get("hour") or 0), int(alarm.get("minute") or 0)))
                time_edit.blockSignals(False)
        except RuntimeError:
            continue
    refs["schedule_alarms"] = normalized


def _script_row_from_item(list_w: QListWidget, item: QListWidgetItem) -> Optional[PlayerScriptTaskRow]:
    try:
        widget = list_w.itemWidget(item)
    except RuntimeError:
        return None
    if isinstance(widget, PlayerScriptTaskRow):
        return widget
    return None


def script_loops_from_refs(refs: Dict[str, Any]) -> Dict[str, int]:
    """从脚本列表行内次数框读取。"""
    from app_core.player.package import normalize_script_loop_count

    loops: Dict[str, int] = {}
    for list_w in iter_script_list_widgets(refs):
        try:
            for index in range(list_w.count()):
                item = list_w.item(index)
                if item is None:
                    continue
                sid = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
                if not sid:
                    continue
                row = _script_row_from_item(list_w, item)
                if row is not None:
                    loops[sid] = row.loops()
                else:
                    loops[sid] = normalize_script_loop_count(
                        item.data(SCRIPT_ITEM_LOOPS_ROLE), 1
                    )
        except RuntimeError:
            continue
    return loops


def group_loops_from_refs(refs: Dict[str, Any]) -> int:
    from app_core.player.package import normalize_script_loop_count

    spin = refs.get("group_loop_spin")
    if spin is not None:
        try:
            return normalize_script_loop_count(spin.value(), 1)
        except RuntimeError:
            pass
    return normalize_script_loop_count(refs.get("group_loops"), 1)


def apply_script_loops_to_refs(
    refs: Dict[str, Any],
    *,
    loops_by_id: Optional[Mapping[str, int]] = None,
    group_loops: Optional[int] = None,
    group_loops_by_list: Optional[Mapping[str, int]] = None,
):
    """把持久化次数写回脚本列表行内 Spin。"""
    from app_core.player.package import normalize_script_loop_count

    counts = loops_by_id or {}
    if counts:
        for list_w in iter_script_list_widgets(refs):
            try:
                for index in range(list_w.count()):
                    item = list_w.item(index)
                    if item is None:
                        continue
                    sid = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
                    if not sid or sid not in counts:
                        continue
                    value = normalize_script_loop_count(counts.get(sid), 1)
                    item.setData(SCRIPT_ITEM_LOOPS_ROLE, value)
                    row = _script_row_from_item(list_w, item)
                    if row is not None:
                        row._spin.blockSignals(True)
                        row._spin.setValue(value)
                        row._spin.blockSignals(False)
            except RuntimeError:
                continue
    applied_group = False
    if isinstance(group_loops_by_list, Mapping):
        mapping = refs.get("script_lists")
        spins_by_id = refs.get("group_loop_spins_by_id")
        if isinstance(spins_by_id, Mapping) and spins_by_id:
            for list_id, value in group_loops_by_list.items():
                spin = spins_by_id.get(str(list_id))
                if spin is None:
                    continue
                try:
                    normalized = normalize_script_loop_count(value, 1)
                    spin.blockSignals(True)
                    spin.setValue(normalized)
                    spin.blockSignals(False)
                    applied_group = True
                except RuntimeError:
                    continue
        elif isinstance(mapping, Mapping) and mapping:
            spins = refs.get("group_loop_spins") or []
            order = [str(key) for key in (refs.get("script_list_order") or mapping.keys())]
            for index, list_id in enumerate(order):
                if index >= len(spins) or list_id not in group_loops_by_list:
                    continue
                try:
                    normalized = normalize_script_loop_count(group_loops_by_list[list_id], 1)
                    spin = spins[index]
                    spin.blockSignals(True)
                    spin.setValue(normalized)
                    spin.blockSignals(False)
                    applied_group = True
                except RuntimeError:
                    continue
    if group_loops is not None and not applied_group:
        value = normalize_script_loop_count(group_loops, 1)
        refs["group_loops"] = value
        spin = refs.get("group_loop_spin")
        if spin is not None:
            try:
                spin.blockSignals(True)
                spin.setValue(value)
                spin.blockSignals(False)
            except RuntimeError:
                pass


def set_progress_widget_state(
    refs: Dict[str, Any],
    *,
    text: str = "待命",
    value: int = 0,
    maximum: int = 100,
    indeterminate: bool = False,
):
    bar = refs.get("progress_bar")
    try:
        if bar is None:
            return
        # 整个控件就是轨道；状态字画在条上（% 需转义，避免被 format 吃掉）
        bar.setFormat(str(text or "待命").replace("%", "%%"))
        bar.setTextVisible(True)
        if indeterminate:
            bar.setRange(0, 0)
        else:
            top = max(1, int(maximum or 100))
            bar.setRange(0, top)
            bar.setValue(max(0, min(top, int(value or 0))))
    except RuntimeError:
        return


def apply_script_run_status(
    refs: Dict[str, Any],
    *,
    active_id: str = "",
    loop_index: int = 1,
    loop_total: int = 1,
    state: str = "idle",
    waiting_ids: Optional[List[str]] = None,
):
    """刷新脚本列表行上的执行状态。"""
    waiting = {str(item) for item in (waiting_ids or []) if item}
    active = str(active_id or "").strip()
    try:
        accent = QColor(theme_color("accent"))
        text_c = QColor(theme_color("text"))
        muted = QColor(theme_color("text_secondary"))
        warn = QColor(theme_color("warning"))
        accent_s = theme_color("accent")
        muted_s = theme_color("text_secondary")
        warn_s = theme_color("warning")
    except Exception:
        accent = QColor("#3b82f6")
        text_c = QColor("#222222")
        muted = QColor("#888888")
        warn = QColor("#d97706")
        accent_s, muted_s, warn_s = "#3b82f6", "#888888", "#d97706"
    run_bg = QColor(accent)
    run_bg.setAlpha(36)
    for list_w in iter_script_list_widgets(refs):
        try:
            for index in range(list_w.count()):
                item = list_w.item(index)
                if item is None:
                    continue
                sid = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
                row_state = "idle"
                row_index = 0
                row_total = 0
                if state in ("running", "paused") and sid and sid == active:
                    row_state = state
                    row_index = loop_index
                    row_total = loop_total
                elif state in ("running", "paused") and sid in waiting:
                    row_state = "waiting"
                row = _script_row_from_item(list_w, item)
                if row is not None:
                    row.set_run_state(
                        row_state,
                        loop_index=row_index,
                        loop_total=row_total,
                        accent=accent_s,
                        muted=muted_s,
                        warn=warn_s,
                    )
                else:
                    title = str(item.data(SCRIPT_ITEM_TITLE_ROLE) or item.text() or sid)
                    loops = int(item.data(SCRIPT_ITEM_LOOPS_ROLE) or 1)
                    item.setText(
                        script_item_display_text(
                            title,
                            loops,
                            status=row_state,
                            loop_index=row_index,
                            loop_total=row_total,
                        )
                    )
                if row_state == "running":
                    item.setBackground(run_bg)
                elif row_state == "paused":
                    item.setBackground(run_bg)
                else:
                    item.setBackground(QColor(0, 0, 0, 0))
                if row is None:
                    if row_state == "running":
                        item.setForeground(accent)
                    elif row_state == "paused":
                        item.setForeground(warn)
                    elif row_state == "waiting":
                        item.setForeground(muted)
                    else:
                        item.setForeground(text_c)
        except RuntimeError:
            continue


def _iter_script_task_rows(list_w: QListWidget) -> List["PlayerScriptTaskRow"]:
    rows: List[PlayerScriptTaskRow] = []
    if list_w is None:
        return rows
    try:
        for index in range(list_w.count()):
            item = list_w.item(index)
            if item is None:
                continue
            row = _script_row_from_item(list_w, item)
            if row is not None:
                rows.append(row)
    except RuntimeError:
        return []
    return rows


def set_all_script_checks(list_w: QListWidget, checked: bool) -> None:
    """将该列表内全部脚本勾选或取消勾选。"""
    state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
    for row in _iter_script_task_rows(list_w):
        try:
            row._check.blockSignals(True)
            row._check.setCheckState(state)
            row._check.blockSignals(False)
            row._sync_once_badge()
        except RuntimeError:
            pass


def sync_script_select_all_box(list_w: QListWidget, select_all: Optional[QCheckBox] = None) -> None:
    """按行勾选状态同步标题行全选框。

    无勾选 → 未勾选；有任意勾选（含部分/全部）→ 已勾选。
    """
    box = select_all if select_all is not None else getattr(list_w, "_select_all_box", None)
    if box is None:
        return
    rows = _iter_script_task_rows(list_w)
    try:
        box.blockSignals(True)
        if rows and any(row.is_checked() for row in rows):
            box.setCheckState(Qt.CheckState.Checked)
        else:
            box.setCheckState(Qt.CheckState.Unchecked)
        box.blockSignals(False)
    except RuntimeError:
        pass


def set_script_list_locked(refs: Dict[str, Any], locked: bool):
    """运行中锁定勾选/拖拽/次数，但保持列表可见以便显示执行状态。"""
    for list_w in iter_script_list_widgets(refs):
        try:
            if isinstance(list_w, PlayerScriptListView):
                list_w.set_reorder_enabled(not locked)
            select_all = getattr(list_w, "_select_all_box", None)
            if select_all is not None:
                select_all.setEnabled(not locked)
            for index in range(list_w.count()):
                item = list_w.item(index)
                if item is None:
                    continue
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                row = _script_row_from_item(list_w, item)
                if row is not None:
                    row.set_locked(locked)
        except RuntimeError:
            continue
    for spin in refs.get("group_loop_spins") or []:
        try:
            spin.setEnabled(not locked)
        except RuntimeError:
            pass
    spin = refs.get("group_loop_spin")
    if spin is not None:
        try:
            spin.setEnabled(not locked)
        except RuntimeError:
            pass


def selected_script_ids_from_list_widget(list_w) -> List[str]:
    ids: List[str] = []
    if list_w is None:
        return ids
    try:
        for index in range(list_w.count()):
            item = list_w.item(index)
            if item is None:
                continue
            row = _script_row_from_item(list_w, item)
            if row is not None:
                if not row.is_checked():
                    continue
                sid = row.script_id or str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
            else:
                if item.checkState() != Qt.CheckState.Checked:
                    continue
                sid = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
            if sid:
                ids.append(sid)
    except RuntimeError:
        return ids
    return ids


def selected_script_ids_by_list_from_refs(refs: Dict[str, Any]) -> Dict[str, List[str]]:
    mapping = refs.get("script_lists")
    if isinstance(mapping, dict) and mapping:
        return {
            str(key): selected_script_ids_from_list_widget(widget)
            for key, widget in mapping.items()
            if widget is not None
        }
    single = refs.get("script_list_widget")
    if single is not None:
        return {"__main__": selected_script_ids_from_list_widget(single)}
    return {}


def script_ids_in_list_widget(list_w: Any) -> List[str]:
    ids: List[str] = []
    if list_w is None:
        return ids
    try:
        for index in range(list_w.count()):
            item = list_w.item(index)
            if item is None:
                continue
            sid = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
            if sid:
                ids.append(sid)
    except RuntimeError:
        return ids
    return ids


def script_item_orders_from_refs(refs: Dict[str, Any]) -> Dict[str, List[str]]:
    mapping = refs.get("script_lists")
    if not isinstance(mapping, dict) or not mapping:
        single = refs.get("script_list_widget")
        if single is not None:
            return {"__main__": script_ids_in_list_widget(single)}
        return {}
    return {
        str(key): script_ids_in_list_widget(widget)
        for key, widget in mapping.items()
        if widget is not None
    }


def apply_script_item_order_to_list_widget(list_w: Any, ordered_ids: Sequence[str] | None) -> bool:
    """按 ordered_ids 重排列表行（交换行数据，不 takeItem，避免销毁 itemWidget）。"""
    if list_w is None or not ordered_ids:
        return False
    try:
        current = script_ids_in_list_widget(list_w)
    except RuntimeError:
        return False
    if not current:
        return False
    desired: List[str] = []
    seen = set()
    for sid in ordered_ids:
        s = str(sid or "").strip()
        if s and s in current and s not in seen:
            desired.append(s)
            seen.add(s)
    for s in current:
        if s not in seen:
            desired.append(s)
            seen.add(s)
    if desired == current:
        return False
    if isinstance(list_w, PlayerScriptListView):
        by_id = {}
        for index in range(list_w.count()):
            snap = list_w._snapshot_row(index)
            if snap and snap.get("script_id"):
                by_id[str(snap["script_id"])] = snap
        for index, sid in enumerate(desired):
            snap = by_id.get(sid)
            if snap is not None:
                list_w._apply_row_snapshot(index, snap)
        list_w.order_changed.emit()
        return True
    # 非 PlayerScriptListView：仅改 UserRole（无行控件时）
    for index, sid in enumerate(desired):
        item = list_w.item(index)
        if item is not None:
            item.setData(Qt.ItemDataRole.UserRole, sid)
    return True


def apply_script_item_orders_to_refs(
    refs: Dict[str, Any], item_orders: Mapping[str, Sequence[str]] | None
) -> None:
    if not isinstance(item_orders, Mapping):
        return
    mapping = refs.get("script_lists")
    if isinstance(mapping, dict) and mapping:
        for key, list_w in mapping.items():
            apply_script_item_order_to_list_widget(list_w, item_orders.get(str(key)))
        return
    single = refs.get("script_list_widget")
    if single is not None:
        preferred = item_orders.get("__main__")
        if preferred is None and item_orders:
            preferred = next(iter(item_orders.values()), None)
        apply_script_item_order_to_list_widget(single, preferred)


def selected_script_ids_from_refs(refs: Dict[str, Any]) -> List[str]:
    """按各列表顺序串联已勾选脚本 id（兼容单列表）。"""
    by_list = selected_script_ids_by_list_from_refs(refs)
    if by_list:
        order = refs.get("script_list_order") or list(by_list.keys())
        ids: List[str] = []
        seen: set[str] = set()
        for key in order:
            for sid in by_list.get(str(key)) or []:
                if sid not in seen:
                    ids.append(sid)
                    seen.add(sid)
        for key, values in by_list.items():
            if str(key) in {str(x) for x in order}:
                continue
            for sid in values:
                if sid not in seen:
                    ids.append(sid)
                    seen.add(sid)
        return ids
    ids = []
    for item_id, box in refs.get("script_checkboxes") or []:
        try:
            if box is not None and box.isChecked():
                ids.append(str(item_id))
        except RuntimeError:
            continue
    return ids


def populate_custom_player_body(
    body: QWidget,
    ui: dict,
    *,
    load_pixmap: Callable[[str], QPixmap],
    on_link: Optional[Callable[[str], None]] = None,
    on_start: Optional[Callable[[], None]] = None,
    on_pause: Optional[Callable[[], None]] = None,
    on_stop: Optional[Callable[[], None]] = None,
    on_bind: Optional[Callable[[], None]] = None,
    on_settings: Optional[Callable[[], None]] = None,
    on_scripts_changed: Optional[Callable[[List[str]], None]] = None,
    on_loops_changed: Optional[Callable[[], None]] = None,
    on_open_log_dir: Optional[Callable[[], None]] = None,
    on_schedule_changed: Optional[Callable[[], None]] = None,
    log_placeholder: str = "",
    interactive_buttons: bool = True,
    initial_page: str = "",
) -> Dict[str, Any]:
    """在 body 上按 ui.widgets 绝对布局创建控件。返回引用字典供运行窗持有。"""
    refs: Dict[str, Any] = {
        "bg_label": None,
        "start_button": None,
        "pause_button": None,
        "stop_button": None,
        "bind_button": None,
        "status_label": None,
        "status_dot": None,
        "log_view": None,
        "log_frame": None,
        "tabs_bar": None,
        "script_checkboxes": [],
        "script_lists": {},
        "script_list_order": [
            str(w.get("id") or "")
            for w in (ui.get("widgets") or [])
            if isinstance(w, dict) and w.get("type") == "script_list" and w.get("id")
        ]
        if not isinstance(ui.get("list_order"), list)
        else [str(x) for x in ui.get("list_order") if str(x or "").strip()],
        "group_loop_spin": None,
        "group_loop_spins": [],
        "group_loop_spins_by_id": {},
        "group_loops": 1,
        "settings_button": None,
        "progress_label": None,
        "progress_bar": None,
        "progress_frame": None,
        "schedule_alarms": [],
        "schedule_frame": None,
        "page_nodes": [],
        "active_page": "",
        "start_default_text": "开始",
        "status_text_color": theme_color("text"),
        "status_font_size": 12,
    }
    window = ui.get("window") if isinstance(ui.get("window"), dict) else {}
    body_w = int(window.get("width") or body.width() or 460)
    body_h = int(window.get("height") or body.height() or 360)
    body.setFixedSize(body_w, body_h)

    refs["bg_label"] = paint_player_background(
        body, ui.get("background") or {}, load_pixmap=load_pixmap
    )

    widgets = sorted(
        [w for w in (ui.get("widgets") or []) if isinstance(w, dict)],
        key=lambda w: (int(w.get("z") or 0), str(w.get("id") or "")),
    )
    created = []
    page_nodes: List[Dict[str, Any]] = []
    tabs_pages: List[Dict[str, str]] = []
    tabs_geo: Optional[Tuple[int, int, int, int]] = None

    for widget in widgets:
        if str(widget.get("type") or "") != "tabs":
            continue
        tx = int(widget.get("x") or 0)
        ty = int(widget.get("y") or 0)
        tw = max(8, int(widget.get("w") or 100))
        th = max(8, int(widget.get("h") or 28))
        # 旧数据曾把标签页收成仅标签条：分区过小会导致切页无效果、看起来很窄
        if tw < 280:
            tw = max(280, body_w - max(0, tx) - 16)
        if th < 120:
            th = max(120, body_h - max(0, ty) - 16)
        tabs_geo = (tx, ty, tw, th)
        for page in widget.get("pages") or []:
            if isinstance(page, dict) and str(page.get("id") or ""):
                tabs_pages.append(
                    {"id": str(page.get("id") or ""), "title": str(page.get("title") or "")}
                )
        break

    # 仅标签分区内 + 有所属页 → 随切换显隐；分区外 / 所属页为空 → 始终显示。
    known_page_ids = [str(p["id"]) for p in tabs_pages if p.get("id")]
    known_page_set = set(known_page_ids)
    default_page = known_page_ids[0] if known_page_ids else ""
    start_page = str(initial_page or "").strip()
    if start_page not in known_page_set:
        start_page = default_page

    def _in_tabs_zone(x: int, y: int, w: int, h: int) -> bool:
        if tabs_geo is None:
            return False
        return widget_center_in_rect(x, y, w, h, *tabs_geo)

    has_paged_in_zone = any(
        str(w.get("page") or "") in known_page_set
        and _in_tabs_zone(
            int(w.get("x") or 0),
            int(w.get("y") or 0),
            max(8, int(w.get("w") or 100)),
            max(8, int(w.get("h") or 28)),
        )
        for w in widgets
        if str(w.get("type") or "") != "tabs" and w.get("visible", True)
    )
    auto_page = (not has_paged_in_zone) and bool(default_page) and tabs_geo is not None

    def _track(page: str, in_zone: bool, *nodes: QWidget):
        clean = [n for n in nodes if n is not None]
        if clean:
            page_nodes.append(
                {"page": str(page or ""), "in_zone": bool(in_zone), "nodes": clean}
            )

    for widget in widgets:
        if not widget.get("visible", True):
            continue
        kind = str(widget.get("type") or "")
        geo = (
            int(widget.get("x") or 0),
            int(widget.get("y") or 0),
            max(8, int(widget.get("w") or 100)),
            max(8, int(widget.get("h") or 28)),
        )
        in_zone = False if kind == "tabs" else _in_tabs_zone(*geo)
        if kind == "tabs":
            page = ""
        else:
            page = str(widget.get("page") or "")
            if page and page not in known_page_set:
                page = ""
            # 分区外不参与分页
            if not in_zone:
                page = ""
            elif auto_page and not page:
                page = default_page
        node = None
        if kind == "button":
            action = str(widget.get("action") or "start")
            text = str(widget.get("text") or action)
            btn = QPushButton(text, body)
            btn.setGeometry(*geo)
            btn.setFixedSize(geo[2], geo[3])
            btn.setCursor(Qt.CursorShape.ArrowCursor)
            apply_player_button_style(btn, widget)
            if action == "start":
                btn.setObjectName("PlayerStartButton")
                refs["start_button"] = btn
                refs["start_default_text"] = text
                if interactive_buttons and on_start is not None:
                    btn.clicked.connect(on_start)
            elif action == "pause":
                btn.setObjectName("PlayerPauseButton")
                refs["pause_button"] = btn
                if interactive_buttons and on_pause is not None:
                    btn.clicked.connect(on_pause)
            elif action == "stop":
                btn.setObjectName("PlayerStopButton")
                refs["stop_button"] = btn
                if interactive_buttons and on_stop is not None:
                    btn.clicked.connect(on_stop)
            elif action == "bind":
                btn.setObjectName("PlayerBindButton")
                refs["bind_button"] = btn
                if interactive_buttons and on_bind is not None:
                    btn.clicked.connect(on_bind)
            elif action == "settings":
                btn.setObjectName("PlayerSettingsButton")
                refs["settings_button"] = btn
                if interactive_buttons and on_settings is not None:
                    btn.clicked.connect(on_settings)
            node = btn
            _track(page, in_zone, btn)
        elif kind == "label":
            label = QLabel(str(widget.get("text") or ""), body)
            label.setGeometry(*geo)
            label.setWordWrap(True)
            color = resolve_widget_color(widget, "color", "text")
            size = int(widget.get("font_size") or 12)
            label.setStyleSheet(
                f"color:{color}; font-size:{size}px; background:transparent; border:none;"
            )
            node = label
            _track(page, in_zone, label)
        elif kind == "rich_text":
            label = QLabel(str(widget.get("text") or ""), body)
            label.setObjectName("PlayerRichText")
            label.setGeometry(*geo)
            label.setWordWrap(True)
            label.setAlignment(_qt_text_align(str(widget.get("align") or "left")))
            color = resolve_widget_color(widget, "color", "text")
            size = resolve_widget_font_size(widget, 12)
            label.setStyleSheet(player_rich_text_qss(text=color, font_size=size))
            node = label
            _track(page, in_zone, label)
        elif kind == "tabs":
            bar = WheelScrollTabBar(body)
            bar.setObjectName("PlayerTabsBar")
            bar.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            # 仅标签条高度参与布局/点击，下方分区不生成遮挡层
            bar.setStyleSheet(
                player_tabs_bar_qss(
                    surface=theme_color("surface"),
                    text=resolve_widget_color(widget, "color", "text"),
                    border=theme_color("border"),
                    accent=theme_color("accent"),
                    font_size=resolve_widget_font_size(widget, 12),
                )
            )
            for index, page_info in enumerate(tabs_pages):
                bar.addTab(page_info["title"] or page_info["id"] or "页")
                bar.setTabData(index, page_info["id"])
            # 用修复后的分区尺寸铺标签条，避免沿用过窄/过矮的旧 geo
            zone = tabs_geo or geo
            strip_h = max(40, int(bar.sizeHint().height() or 42))
            if zone[3] > 0:
                strip_h = min(strip_h, max(40, zone[3]))
            bar.setGeometry(zone[0], zone[1], max(8, zone[2]), strip_h)
            bar.setFixedHeight(strip_h)
            refs["tabs_bar"] = bar
            node = bar
            _track("", False, bar)
        elif kind == "script_list":
            from app_core.player.package import normalize_script_loop_count

            frame = QFrame(body)
            frame.setObjectName("PlayerScriptList")
            frame.setGeometry(*geo)
            text_c = resolve_widget_color(widget, "color", "text")
            font_px = resolve_widget_font_size(widget, 12)
            border = theme_color("border")
            border_hi = theme_color("border_light")
            accent = theme_color("accent")
            accent_hover = theme_color("accent_hover")
            frame.setStyleSheet(
                player_panel_frame_qss("PlayerScriptList", text=text_c, font_size=font_px)
                + f"QFrame#PlayerScriptList QListWidget,"
                f" QFrame#PlayerScriptList QListWidget::viewport,"
                f" QFrame#PlayerScriptList QAbstractScrollArea::viewport {{"
                f" background:transparent; border:none;"
                f" color:{text_c}; font-size:{font_px}px; outline:none;"
                f" show-decoration-selected:0; }}"
                # Kill global QListWidget item margin/hover/selected chrome (causes gray offset band).
                f"QFrame#PlayerScriptList QListWidget::item,"
                f" QFrame#PlayerScriptList QListWidget::item:hover,"
                f" QFrame#PlayerScriptList QListWidget::item:selected,"
                f" QFrame#PlayerScriptList QListWidget::item:selected:active,"
                f" QFrame#PlayerScriptList QListWidget::item:selected:!active,"
                f" QFrame#PlayerScriptList QListWidget::item:focus {{"
                f" background:transparent; background-color:transparent;"
                f" color:{text_c}; border:none; margin:0px; padding:0px; outline:none; }}"
                f"QFrame#PlayerScriptList QWidget#PlayerScriptListHeader {{"
                f" background:transparent; background-color:transparent; border:none; }}"
                f"QFrame#PlayerScriptList QCheckBox {{"
                f" spacing:4px; color:{text_c}; font-size:{font_px}px;"
                f" background:transparent; background-color:transparent; border:none; padding:0; }}"
                f"QFrame#PlayerScriptList QCheckBox::indicator {{"
                f" width:16px; height:16px; border:1px solid {border}; border-radius:3px;"
                f" background:transparent; background-color:transparent; }}"
                f"QFrame#PlayerScriptList QCheckBox::indicator:hover {{ border-color:{border_hi}; }}"
                f"QFrame#PlayerScriptList QCheckBox::indicator:checked {{"
                f" background-color:{accent}; border-color:{accent};"
                f" image:url(themes/icons/check-white.svg); }}"
                f"QFrame#PlayerScriptList QCheckBox::indicator:checked:hover {{"
                f" background-color:{accent_hover}; border-color:{accent_hover}; }}"
                f"QFrame#PlayerScriptList QCheckBox::indicator:disabled {{"
                f" background:transparent; background-color:transparent; border-color:{border}; }}"
                f"QFrame#PlayerScriptList QSpinBox {{ color:{text_c}; font-size:{font_px}px;"
                f" background:transparent; border:1px solid {border}; border-radius:4px;"
                f" min-height:22px; max-height:24px; padding:0 2px; }}"
                f"QFrame#PlayerScriptList QSpinBox:focus {{ border-color:{accent}; }}"
                f"QFrame#PlayerScriptList QSpinBox::up-button,"
                f" QFrame#PlayerScriptList QSpinBox::down-button {{"
                f" width:0px; height:0px; border:none; background:transparent; }}"
                f"QFrame#PlayerScriptList QFrame#PlayerGroupLoopBar {{"
                f" background:transparent; border:none; }}"
                f"QFrame#PlayerScriptList QWidget#PlayerScriptTaskRow {{"
                f" background:transparent; border:none; }}"
            )
            layout = QVBoxLayout(frame)
            layout.setContentsMargins(8, 6, 8, 6)
            layout.setSpacing(4)
            title = str(widget.get("title") or "").strip()
            header = QWidget(frame)
            header.setObjectName("PlayerScriptListHeader")
            header.setAutoFillBackground(False)
            header_row = QHBoxLayout(header)
            header_row.setContentsMargins(0, 0, 0, 0)
            header_row.setSpacing(6)
            hint_text = ""
            if title:
                hint_text = title if not interactive_buttons else f"{title}（可拖拽调顺序）"
            hint = QLabel(hint_text, header)
            hint.setStyleSheet("background:transparent; border:none;")
            select_all = QCheckBox("全选", header)
            select_all.setObjectName("PlayerScriptSelectAll")
            # 文案在左、勾选框在右：全选 ☐
            select_all.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            select_all.setToolTip("全选 / 取消全选")
            select_all.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            select_all.setAutoFillBackground(False)
            select_all.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            select_all.setEnabled(interactive_buttons)
            header_row.addWidget(hint, 1)
            header_row.addWidget(select_all, 0, Qt.AlignmentFlag.AlignRight)
            layout.addWidget(header)
            list_w = PlayerScriptListView(frame)
            list_w.setObjectName("PlayerScriptListView")
            list_w.setAutoFillBackground(False)
            list_w.viewport().setAutoFillBackground(False)
            list_w.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
            list_w.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            list_w.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            list_w.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
            list_w.set_reorder_enabled(interactive_buttons)
            list_w._select_all_box = select_all
            list_key = str(widget.get("id") or f"script_list_{len(refs.get('script_lists') or {})}")
            if interactive_buttons:
                list_w.setToolTip("勾选要执行的脚本；右侧改次数；按住名称拖拽调整顺序")
            else:
                list_w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                select_all.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

            def _on_row_check_changed(_checked: bool = False, _list=list_w) -> None:
                sync_script_select_all_box(_list)
                if on_scripts_changed is not None:
                    on_scripts_changed(selected_script_ids_from_refs(refs))

            def _on_select_all_clicked(_checked: bool = False, _list=list_w, _box=select_all) -> None:
                rows = _iter_script_task_rows(_list)
                all_on = bool(rows) and all(row.is_checked() for row in rows)
                set_all_script_checks(_list, not all_on)
                sync_script_select_all_box(_list, _box)
                if on_scripts_changed is not None:
                    on_scripts_changed(selected_script_ids_from_refs(refs))

            for item in widget.get("items") or []:
                if not isinstance(item, dict):
                    continue
                item_id = str(item.get("id") or "").strip()
                if not item_id:
                    continue
                item_title = str(item.get("title") or item_id or "脚本")
                loops = normalize_script_loop_count(item.get("loops"), 1)
                checked = bool(item.get("checked", True))
                list_item = QListWidgetItem()
                list_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                list_item.setData(Qt.ItemDataRole.UserRole, item_id)
                list_item.setData(SCRIPT_ITEM_TITLE_ROLE, item_title)
                list_item.setData(SCRIPT_ITEM_LOOPS_ROLE, loops)
                task_row = PlayerScriptTaskRow(
                    item_id,
                    item_title,
                    loops,
                    checked=checked,
                    interactive=interactive_buttons,
                    parent=list_w,
                )
                list_item.setSizeHint(task_row.sizeHint())
                list_w.addItem(list_item)
                list_w.setItemWidget(list_item, task_row)
                if interactive_buttons:
                    task_row._check.toggled.connect(_on_row_check_changed)
                if interactive_buttons and on_loops_changed is not None:
                    task_row._spin.valueChanged.connect(lambda *_args: on_loops_changed())
            if interactive_buttons:
                select_all.clicked.connect(_on_select_all_clicked)
            if interactive_buttons and on_scripts_changed is not None:
                list_w.order_changed.connect(
                    lambda: on_scripts_changed(selected_script_ids_from_refs(refs))
                )
            sync_script_select_all_box(list_w, select_all)
            layout.addWidget(list_w, 1)
            sep = QFrame(frame)
            sep.setObjectName("PlayerGroupLoopSep")
            sep.setFrameShape(QFrame.Shape.HLine)
            sep.setFrameShadow(QFrame.Shadow.Plain)
            sep.setFixedHeight(1)
            sep.setStyleSheet(
                f"QFrame#PlayerGroupLoopSep {{ background:{border}; border:none; max-height:1px; }}"
            )
            layout.addWidget(sep)
            group_bar = QFrame(frame)
            group_bar.setObjectName("PlayerGroupLoopBar")
            group_bar.setFrameShape(QFrame.Shape.NoFrame)
            group_bar.setAutoFillBackground(False)
            group_row = QHBoxLayout(group_bar)
            group_row.setContentsMargins(2, 6, 2, 0)
            group_row.setSpacing(6)
            group_lab = QLabel("整组循环")
            group_spin = QSpinBox(group_bar)
            group_spin.setObjectName("PlayerGroupLoopSpin")
            group_spin.setAutoFillBackground(False)
            group_spin.setRange(1, 9999)
            group_spin.setValue(normalize_script_loop_count(widget.get("group_loops"), 1))
            group_spin.setPrefix("× ")
            group_spin.setFixedWidth(70)
            group_spin.setFixedHeight(24)
            group_spin.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            group_spin.setToolTip("整份勾选序列再重复多少轮")
            group_spin.setEnabled(interactive_buttons)
            group_row.addWidget(group_lab, 1)
            group_row.addWidget(group_spin, 0)
            layout.addWidget(group_bar)
            lists_map = dict(refs.get("script_lists") or {})
            lists_map[list_key] = list_w
            refs["script_lists"] = lists_map
            order = list(refs.get("script_list_order") or [])
            if list_key not in order:
                order.append(list_key)
            refs["script_list_order"] = order
            refs["script_list_widget"] = list_w  # 兼容：指向最后一个
            refs["script_checkboxes"] = list(refs.get("script_checkboxes") or [])
            refs["group_loop_spin"] = group_spin
            spins = list(refs.get("group_loop_spins") or [])
            spins.append(group_spin)
            refs["group_loop_spins"] = spins
            spins_by_id = dict(refs.get("group_loop_spins_by_id") or {})
            if list_key:
                spins_by_id[list_key] = group_spin
            refs["group_loop_spins_by_id"] = spins_by_id
            refs["group_loops"] = normalize_script_loop_count(widget.get("group_loops"), 1)

            def _on_group_changed(value: int):
                refs["group_loops"] = normalize_script_loop_count(value, 1)
                if on_loops_changed is not None:
                    on_loops_changed()

            group_spin.valueChanged.connect(_on_group_changed)
            if interactive_buttons and on_scripts_changed is not None:
                model = list_w.model()
                if model is not None:
                    model.rowsMoved.connect(
                        lambda *_args: on_scripts_changed(selected_script_ids_from_refs(refs))
                    )
            node = frame
            _track(page, in_zone, frame)
        elif kind == "progress":
            # 整个控件就是轨道，不再套外框 + 内条
            bar = QProgressBar(body)
            bar.setObjectName("PlayerProgressBar")
            bar.setGeometry(*geo)
            text_c = resolve_widget_color(widget, "color", "text")
            font_px = resolve_widget_font_size(widget, 12)
            border = theme_color("border")
            accent = theme_color("accent")
            radius = max(2, min(PLAYER_PANEL_RADIUS, max(2, geo[3] // 2)))
            bar.setStyleSheet(
                f"QProgressBar#PlayerProgressBar {{ border:1px solid {border};"
                f" border-radius:{radius}px; background:{theme_color('canvas')};"
                f" text-align:center; color:{text_c}; font-size:{font_px}px; }}"
                f"QProgressBar#PlayerProgressBar::chunk {{ background:{accent};"
                f" border-radius:{max(1, radius - 1)}px; }}"
            )
            bar.setRange(0, 100)
            bar.setValue(0)
            bar.setTextVisible(True)
            bar.setFormat("待命")
            title = str(widget.get("title") or "进度").strip()
            if title:
                bar.setToolTip(title)
            refs["progress_frame"] = bar
            refs["progress_label"] = None
            refs["progress_bar"] = bar
            node = bar
            _track(page, in_zone, bar)
        elif kind == "link":
            link = QLabel(body)
            link.setObjectName("PlayerLink")
            link.setGeometry(*geo)
            text = str(widget.get("text") or "链接")
            url = str(widget.get("url") or "").strip()
            color = str(widget.get("color") or theme_color("accent")).strip()
            if not QColor(color).isValid():
                color = theme_color("accent")
            size = int(widget.get("font_size") or 12)
            safe_text = html.escape(text)
            safe_url = html.escape(url, quote=True)
            safe_color = html.escape(color, quote=True)
            link.setTextFormat(Qt.TextFormat.RichText)
            # QLabel 富文本里 <a> 颜色不受 QSS 控制，必须写进 HTML / Palette
            link.setText(
                f'<a href="{safe_url}" style="color:{safe_color}; text-decoration:underline;">'
                f"{safe_text}</a>"
            )
            link.setOpenExternalLinks(False)
            link.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
            pal = link.palette()
            link_color = QColor(color)
            pal.setColor(QPalette.ColorRole.Link, link_color)
            pal.setColor(QPalette.ColorRole.LinkVisited, link_color)
            link.setPalette(pal)
            link.setStyleSheet(
                f"QLabel#PlayerLink {{ background:transparent; border:none;"
                f" font-size:{size}px; color:{color}; }}"
            )
            if on_link is not None:
                link.linkActivated.connect(on_link)
            node = link
            _track(page, in_zone, link)
        elif kind == "status":
            color = resolve_widget_color(widget, "color", "text")
            size = int(widget.get("font_size") or 12)
            refs["status_text_color"] = color
            refs["status_font_size"] = size
            dot = QLabel("●", body)
            dot.setObjectName("PlayerStatusDot")
            dot.setGeometry(geo[0], geo[1], max(14, size + 4), geo[3])
            label = QLabel("就绪", body)
            label.setObjectName("PlayerStatusLabel")
            label.setGeometry(
                geo[0] + max(14, size + 4) + 4,
                geo[1],
                max(40, geo[2] - max(14, size + 4) - 4),
                geo[3],
            )
            label.setStyleSheet(
                f"color:{color}; font-size:{size}px; background:transparent; border:none;"
            )
            dot.setStyleSheet(
                f"color:{theme_color('success')}; font-size:{size}px;"
                " background:transparent; border:none;"
            )
            refs["status_dot"] = dot
            refs["status_label"] = label
            node = label
            _track(page, in_zone, dot, label)
        elif kind == "log":
            frame = QFrame(body)
            frame.setObjectName("PlayerLogFrame")
            frame.setGeometry(*geo)
            text_c = resolve_widget_color(widget, "color", "text")
            font_px = resolve_widget_font_size(widget, 12)
            border = theme_color("border")
            frame.setStyleSheet(
                player_panel_frame_qss("PlayerLogFrame", text=text_c, font_size=font_px)
                + f"QFrame#PlayerLogFrame QTextEdit,"
                f" QFrame#PlayerLogFrame QTextEdit::viewport,"
                f" QFrame#PlayerLogFrame QAbstractScrollArea::viewport {{"
                f" background:transparent; color:{text_c}; border:none;"
                f" font-size:{font_px}px; }}"
                f"QFrame#PlayerLogFrame QToolButton {{ color:{text_c}; background:transparent;"
                f" border:1px solid {border}; border-radius:3px; padding:1px 6px;"
                f" font-size:{max(9, font_px - 1)}px; }}"
                f"QFrame#PlayerLogFrame QToolButton:hover {{ background:{theme_color('hover')}; }}"
            )
            log_layout = QVBoxLayout(frame)
            log_layout.setContentsMargins(8, 6, 8, 6)
            log_layout.setSpacing(4)
            head = QHBoxLayout()
            head.setContentsMargins(0, 0, 0, 0)
            head.setSpacing(4)
            title = QLabel("运行日志")
            title.setObjectName("PlayerLogTitle")
            title.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
            head.addWidget(title, 0)
            head.addStretch(1)
            view = QTextEdit()
            view.setObjectName("PlayerLogView")
            view.setAutoFillBackground(False)
            view.viewport().setAutoFillBackground(False)
            view.setReadOnly(True)
            if log_placeholder:
                view.setPlainText(log_placeholder)

            def _clear_log():
                try:
                    view.clear()
                except RuntimeError:
                    return

            def _copy_log():
                try:
                    text = view.toPlainText()
                except RuntimeError:
                    return
                clip = QGuiApplication.clipboard()
                if clip is not None:
                    clip.setText(text or "")

            if interactive_buttons:
                for text, tip, handler in (
                    ("清空", "清空日志", _clear_log),
                    ("复制", "复制全部日志到剪贴板", _copy_log),
                ):
                    btn = QToolButton(frame)
                    btn.setText(text)
                    btn.setToolTip(tip)
                    btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
                    btn.clicked.connect(handler)
                    head.addWidget(btn, 0)
                if on_open_log_dir is not None:
                    dir_btn = QToolButton(frame)
                    dir_btn.setText("目录")
                    dir_btn.setToolTip("打开 userdata 目录")
                    dir_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
                    dir_btn.clicked.connect(on_open_log_dir)
                    head.addWidget(dir_btn, 0)
            log_layout.addLayout(head)
            log_layout.addWidget(view, 1)
            refs["log_frame"] = frame
            refs["log_view"] = view
            node = frame
            _track(page, in_zone, frame)
        elif kind == "schedule":
            from app_core.player.package import normalize_schedule_alarms
            from ui.player.schedule_alarms_editor import ScheduleAlarmsEditor

            frame = QFrame(body)
            frame.setObjectName("PlayerSchedule")
            frame.setGeometry(*geo)
            text_c = resolve_widget_color(widget, "color", "text")
            font_px = resolve_widget_font_size(widget, 12)
            border = theme_color("border")
            border_hi = theme_color("border_light")
            accent = theme_color("accent")
            accent_hover = theme_color("accent_hover")
            frame.setStyleSheet(
                player_panel_frame_qss("PlayerSchedule", text=text_c, font_size=font_px)
                + f"QFrame#PlayerSchedule QFrame {{ background:transparent; border:none; }}"
                f"QFrame#PlayerSchedule QCheckBox {{"
                f" color:{text_c}; font-size:{font_px}px; background:transparent; border:none; }}"
                f"QFrame#PlayerSchedule QCheckBox::indicator {{"
                f" width:16px; height:16px; border:1px solid {border}; border-radius:3px;"
                f" background:transparent; }}"
                f"QFrame#PlayerSchedule QCheckBox::indicator:hover {{ border-color:{border_hi}; }}"
                f"QFrame#PlayerSchedule QCheckBox::indicator:checked {{"
                f" background-color:{accent}; border-color:{accent};"
                f" image:url(themes/icons/check-white.svg); }}"
                f"QFrame#PlayerSchedule QCheckBox::indicator:checked:hover {{"
                f" background-color:{accent_hover}; border-color:{accent_hover}; }}"
                f"QFrame#PlayerSchedule QTimeEdit {{ color:{text_c}; font-size:{font_px}px;"
                f" background:transparent; border:1px solid {border}; border-radius:4px;"
                f" min-height:22px; padding:0 4px; }}"
                f"QFrame#PlayerSchedule QTimeEdit:focus {{ border-color:{accent}; }}"
                f"QFrame#PlayerSchedule QTimeEdit::up-button,"
                f" QFrame#PlayerSchedule QTimeEdit::down-button {{"
                f" width:0px; height:0px; border:none; background:transparent; }}"
            )
            layout = QVBoxLayout(frame)
            layout.setContentsMargins(8, 6, 8, 6)
            layout.setSpacing(4)
            title = str(widget.get("title") or "定时").strip() or "定时"
            alarms = normalize_schedule_alarms(widget.get("alarms"))
            editor = ScheduleAlarmsEditor(
                frame,
                alarms=alarms,
                title=title if not interactive_buttons else f"{title}（到点自动开始）",
                interactive=interactive_buttons,
            )
            layout.addWidget(editor)

            def _emit_schedule():
                refs["schedule_alarms"] = editor.alarms()
                if on_schedule_changed is not None:
                    on_schedule_changed()

            if interactive_buttons:
                editor.alarms_changed.connect(_emit_schedule)
            refs["schedule_frame"] = frame
            refs["schedule_editor"] = editor
            refs["schedule_alarm_rows"] = editor.alarm_rows()
            refs["schedule_alarms"] = alarms
            node = frame
            _track(page, in_zone, frame)
        elif kind == "image":
            image = QLabel(body)
            image.setGeometry(*geo)
            image.setScaledContents(True)
            image.setStyleSheet("background:transparent; border:none;")
            pix = load_pixmap(str(widget.get("path") or ""))
            if not pix.isNull():
                image.setPixmap(pix)
            else:
                image.setStyleSheet(
                    f"background:{theme_color('surface')}; border:1px dashed {theme_color('border')};"
                    f" color:{theme_color('text_secondary')};"
                )
                image.setText("图片")
                image.setAlignment(Qt.AlignmentFlag.AlignCenter)
            node = image
            _track(page, in_zone, image)
        if node is not None:
            created.append((int(widget.get("z") or 0), node))

    refs["page_nodes"] = page_nodes
    active_page = start_page
    refs["active_page"] = active_page
    if known_page_ids:
        apply_player_page_visibility(
            page_nodes, active_page, known_pages=known_page_ids
        )

    tabs_bar = refs.get("tabs_bar")
    if tabs_bar is not None and tabs_pages:
        # 与设计器当前编辑页对齐
        for index, page_info in enumerate(tabs_pages):
            if page_info.get("id") == active_page:
                tabs_bar.blockSignals(True)
                tabs_bar.setCurrentIndex(index)
                tabs_bar.blockSignals(False)
                break

        def _on_tab_changed(index: int):
            if index < 0 or index >= len(tabs_pages):
                return
            page_id = str(tabs_bar.tabData(index) or tabs_pages[index]["id"] or "")
            refs["active_page"] = page_id
            apply_player_page_visibility(
                page_nodes, page_id, known_pages=known_page_ids
            )
            # 切页后把可见控件抬到背景之上，避免被挡住
            for entry in page_nodes:
                page = str(entry.get("page") or "")
                in_zone = bool(entry.get("in_zone", True))
                show = (not in_zone) or (not page) or (page == page_id)
                if not show:
                    continue
                for node in entry.get("nodes") or []:
                    try:
                        if node is not None and node.isVisible():
                            node.raise_()
                    except RuntimeError:
                        pass
            try:
                tabs_bar.raise_()
            except RuntimeError:
                pass

        tabs_bar.currentChanged.connect(_on_tab_changed)

    for _z, node in sorted(created, key=lambda item: item[0]):
        try:
            if node.isVisible():
                node.raise_()
        except RuntimeError:
            pass
    if tabs_bar is not None:
        try:
            tabs_bar.raise_()
        except RuntimeError:
            pass
    if refs["bg_label"] is not None:
        refs["bg_label"].lower()
    return refs
