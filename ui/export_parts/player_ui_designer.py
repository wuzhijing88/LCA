from __future__ import annotations

import copy
import json
import math
import os
import time
import uuid
from pathlib import Path
from typing import Callable, Dict, List, Optional

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QKeyEvent,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
    QShowEvent,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QComboBox,
    QColorDialog,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTabBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app_core.player.package import (
    PLAYER_LAYOUT_CHOICES,
    PLAYER_THEME_CHOICES,
    UI_ASSETS_DIRNAME,
    ensure_designer_ui,
    normalize_player_ui,
    resolve_player_layout,
    resolve_player_theme,
)
from themes import get_theme_manager, theme_color
from ui.system_parts.menu_style import apply_unified_menu_style
from ui.widgets.custom_widgets import CustomDropdown


GRID = 4
HANDLE = 8
SELECT_RADIUS = 6


TABS_STRIP_H = 42
# 点击标签时允许的轻微抖动；超过才算拖拽，避免点一下无法切页
TABS_CLICK_SLOP = 6
# 控件拖拽：单击只选中；按住并移出阈值后才开始拖（避免点一下就跟着跑）
DRAG_SLOP_PX = 10
DRAG_HOLD_MS = 120
# 标签页分区过矮/过窄时自动拉回可用尺寸（旧数据曾被收成仅标签条）
TABS_MIN_ZONE_H = 120
TABS_MIN_ZONE_W = 280


class _TabsPassThroughGuard(QObject):
    """标签页点击穿透期间保持鼠标穿透，直到松开，以便下方控件能拖拽。"""

    def __init__(self, tabs_item: "DesignerItem"):
        super().__init__(tabs_item)
        self._tabs = tabs_item

    def eventFilter(self, _obj, event) -> bool:
        et = event.type()
        if et in (
            QEvent.Type.MouseButtonRelease,
            QEvent.Type.MouseButtonDblClick,
            QEvent.Type.WindowDeactivate,
        ):
            self._tabs._end_tabs_pass_through()
        return False


class _SelectionChrome(QWidget):
    """盖在子控件之上的选中框：淡色流动虚线。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DesignerSelectionChrome")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self._dash_offset = 0.0
        self._paused = False
        self._emphasis = False
        self._anim = QTimer(self)
        self._anim.setInterval(50)
        self._anim.timeout.connect(self._tick)

    def set_emphasis(self, on: bool):
        self._emphasis = bool(on)
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._paused and not self._anim.isActive():
            self._anim.start()

    def hideEvent(self, event):
        self._anim.stop()
        super().hideEvent(event)

    def pause(self):
        self._paused = True
        self._anim.stop()

    def resume(self):
        self._paused = False
        if self.isVisible() and not self._anim.isActive():
            self._anim.start()

    def _tick(self):
        # 周期 = dash+gap，偏移循环形成「蚂蚁线」流动
        self._dash_offset = (self._dash_offset + 0.8) % 10.0
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        accent = _theme_qcolor("accent")
        # 淡色虚线：主题色提亮并半透明；标签页强调时更粗更亮
        soft = QColor(accent)
        if self._emphasis:
            soft = soft.lighter(120)
            soft.setAlpha(220)
            fill = QColor(accent)
            fill.setAlpha(28)
            painter.fillRect(self.rect().adjusted(1, 1, -1, -1), fill)
            pen = QPen(soft, 2.4, Qt.PenStyle.CustomDashLine)
            pen.setDashPattern([7, 4])
        else:
            soft = soft.lighter(145)
            soft.setAlpha(150)
            pen = QPen(soft, 1.4, Qt.PenStyle.CustomDashLine)
            pen.setDashPattern([6, 4])
        pen.setDashOffset(self._dash_offset)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(
            self.rect().adjusted(1, 1, -2, -2),
            SELECT_RADIUS,
            SELECT_RADIUS,
        )
        # 缩放点：同色淡圆点，不画粗描边
        hx = self.width() - HANDLE - 1
        hy = self.height() - HANDLE - 1
        dot = QColor(soft)
        dot.setAlpha(230 if self._emphasis else 200)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(dot)
        size = HANDLE + (2 if self._emphasis else 0)
        painter.drawEllipse(hx - (1 if self._emphasis else 0), hy - (1 if self._emphasis else 0), size, size)
        painter.end()


def _snap(value: int) -> int:
    return int(round(value / GRID) * GRID)


def _tc(key: str) -> str:
    return theme_color(key)


def _select_combo_data(combo: CustomDropdown, value: str, default: str = "") -> None:
    target = str(value or default or "").strip()
    index = combo.findData(target)
    if index < 0 and default:
        index = combo.findData(default)
    if index >= 0:
        combo.setCurrentIndex(index)


def _combo_data_value(combo: CustomDropdown, default: str = "") -> str:
    data = combo.currentData()
    text = str(data if data is not None else "").strip()
    return text or default


def _theme_qcolor(key: str) -> QColor:
    return QColor(_tc(key))


def _default_button_bg(action: str) -> str:
    return _tc("accent") if str(action or "") == "start" else _tc("surface")


def _panel_bg_color(data: dict, *, default_key: str = "card") -> str:
    """面板底色：自定义优先，否则主题色。"""
    custom = str((data or {}).get("bg_color") or "").strip()
    if custom.startswith("#"):
        color = QColor(custom)
        if color.isValid():
            return color.name()
    return _tc(default_key)


def _panel_tabs_bg_color(data: dict) -> str:
    """标签页未选中底色，默认 surface。"""
    return _panel_bg_color(data, default_key="surface")


def _panel_text_color(data: dict) -> str:
    """面板/标签文字色：自定义优先，否则主题 text。"""
    custom = str((data or {}).get("color") or "").strip()
    if custom.startswith("#"):
        color = QColor(custom)
        if color.isValid():
            return color.name()
    return _tc("text")


def _panel_font_size(data: dict) -> int:
    try:
        size = int((data or {}).get("font_size") or 12)
    except (TypeError, ValueError):
        size = 12
    return max(8, min(72, size))


def _polish_widget(widget: QWidget):
    style = widget.style()
    if style is None:
        return
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def designer_panel_item_qss(bg: str, border: str, fg: str, size: int) -> str:
    """设计器面板代理：无底色、保留描边，好辨认范围。"""
    from ui.player.player_chrome import PLAYER_PANEL_RADIUS

    _ = bg  # 底色统一透明，签名保留兼容
    edge = border or _tc("border")
    return (
        f"#DesignerItem {{ background:transparent; border:1px solid {edge};"
        f" color:{fg}; font-size:{size}px; border-radius:{PLAYER_PANEL_RADIUS}px; }}"
    )


def _rounded_rect_path(rect, radius: int) -> QPainterPath:
    path = QPainterPath()
    box = QRectF(rect)
    if box.width() > 1 and box.height() > 1:
        box = box.adjusted(0.5, 0.5, -0.5, -0.5)
    path.addRoundedRect(box, float(radius), float(radius))
    return path


def _apply_button_chrome(btn: QPushButton, data: dict) -> None:
    """与运行/预览共用同一套按钮样式，保证画布尺寸一致。"""
    from ui.player.player_chrome import apply_player_button_style

    apply_player_button_style(btn, data)
    _polish_widget(btn)


def _fill_panel(widget: QWidget, color_key: str):
    """只用 palette 上色并清空局部 stylesheet，避免挡住子按钮的全局主题。"""
    color = QColor(_tc(color_key))
    pal = widget.palette()
    pal.setColor(QPalette.ColorRole.Window, color)
    pal.setColor(QPalette.ColorRole.Base, color)
    widget.setAutoFillBackground(True)
    widget.setPalette(pal)
    widget.setStyleSheet("")


def _make_sep(orientation: str = "h") -> QFrame:
    line = QFrame()
    line.setObjectName("DesignerSep")
    if orientation == "v":
        line.setFixedWidth(1)
        line.setFrameShape(QFrame.Shape.VLine)
    else:
        line.setFixedHeight(1)
        line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Plain)
    return line


class DesignerItem(QWidget):
    """画布上的可拖拽控件代理。"""

    selected = Signal(str)
    changed = Signal(str)
    interaction_began = Signal(str)
    page_activated = Signal(str)

    def __init__(self, widget_data: dict, parent=None):
        super().__init__(parent)
        self.data = dict(widget_data)
        self._drag_offset: Optional[QPoint] = None
        self._press_global: Optional[QPoint] = None
        self._press_mono: float = 0.0
        self._drag_armed = False
        self._resizing = False
        self._selected = False
        self._geometry_dirty = False
        self._caption = ""
        self._proxy_btn: Optional[QPushButton] = None
        self._proxy_tabs = None
        self._sel_chrome: Optional[_SelectionChrome] = None
        self._cached_pix: Optional[QPixmap] = None
        self._cached_pix_key = ""
        self._pass_guard: Optional[_TabsPassThroughGuard] = None
        self.setObjectName("DesignerItem")
        # 仅按住左键时才需要 move；开启 tracking 会在未按下时也进 mouseMove，易误触
        self.setMouseTracking(False)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._apply_geometry()
        self._refresh_look()

    @property
    def widget_id(self) -> str:
        return str(self.data.get("id") or "")

    def set_selected(self, selected: bool):
        self._selected = selected
        self._sync_selection_chrome()
        self.update()

    def _ensure_sel_chrome(self) -> _SelectionChrome:
        if self._sel_chrome is None:
            self._sel_chrome = _SelectionChrome(self)
        return self._sel_chrome

    def _sync_selection_chrome(self):
        if self._selected:
            chrome = self._ensure_sel_chrome()
            chrome.set_emphasis(str(self.data.get("type") or "") == "tabs")
            chrome.setGeometry(0, 0, max(1, self.width()), max(1, self.height()))
            chrome.show()
            chrome.raise_()
            if not (self._drag_offset is not None or self._resizing):
                chrome.update()
        elif self._sel_chrome is not None:
            self._sel_chrome.hide()

    def _image_path_key(self) -> str:
        return str(self.data.get("_local_path") or self.data.get("path") or "")

    def _cached_pixmap(self) -> QPixmap:
        key = self._image_path_key()
        if key != self._cached_pix_key:
            self._cached_pix_key = key
            if key and os.path.isfile(key):
                self._cached_pix = QPixmap(key)
            else:
                self._cached_pix = QPixmap()
        return self._cached_pix if self._cached_pix is not None else QPixmap()

    def apply_data(self, data: dict):
        old_key = self._image_path_key()
        self.data = dict(data)
        if self._image_path_key() != old_key:
            self._cached_pix = None
            self._cached_pix_key = ""
        self._apply_geometry()
        self._refresh_look()
        self.update()

    def export_data(self) -> dict:
        geo = self.geometry()
        payload = dict(self.data)
        payload.update(
            {
                "x": geo.x(),
                "y": geo.y(),
                "w": geo.width(),
                "h": geo.height(),
                "z": int(self.data.get("z") or 0),
            }
        )
        return payload

    def _apply_geometry(self):
        self.setGeometry(
            int(self.data.get("x", 0)),
            int(self.data.get("y", 0)),
            max(8, int(self.data.get("w", 100))),
            max(8, int(self.data.get("h", 28))),
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._proxy_btn is not None:
            self._proxy_btn.setGeometry(0, 0, self.width(), self.height())
        if self._proxy_tabs is not None:
            self._proxy_tabs.setGeometry(0, 0, self.width(), self._tabs_strip_height())
        self._sync_selection_chrome()

    def _ensure_proxy_btn(self) -> QPushButton:
        if self._proxy_btn is None:
            btn = QPushButton(self)
            btn.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setCursor(Qt.CursorShape.ArrowCursor)
            self._proxy_btn = btn
        return self._proxy_btn

    def _clear_proxy_btn(self):
        if self._proxy_btn is not None:
            self._proxy_btn.deleteLater()
            self._proxy_btn = None

    def _ensure_proxy_tabs(self) -> QTabBar:
        if self._proxy_tabs is None:
            from ui.player.player_chrome import WheelScrollTabBar

            bar = WheelScrollTabBar(self)
            bar.setObjectName("DesignerTabsProxy")
            bar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            # 标签条自己接收点击（比外层命中检测可靠）
            bar.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
            bar.currentChanged.connect(self._on_proxy_tab_changed)
            self._proxy_tabs = bar
            self._syncing_tabs_bar = False
        return self._proxy_tabs

    def _clear_proxy_tabs(self):
        if self._proxy_tabs is not None:
            self._proxy_tabs.deleteLater()
            self._proxy_tabs = None

    def _tabs_strip_height(self) -> int:
        return min(max(28, TABS_STRIP_H), max(28, self.height()))

    def _on_proxy_tab_changed(self, index: int):
        if getattr(self, "_syncing_tabs_bar", False):
            return
        pages = [p for p in (self.data.get("pages") or []) if isinstance(p, dict)]
        if index < 0 or index >= len(pages):
            return
        page_id = str(pages[index].get("id") or "")
        if not page_id:
            return
        self.selected.emit(self.widget_id)
        self.page_activated.emit(page_id)

    def _sync_proxy_tabs(self):
        bar = self._ensure_proxy_tabs()
        pages = [p for p in (self.data.get("pages") or []) if isinstance(p, dict)]
        titles = [str(p.get("title") or p.get("id") or f"页{i+1}") for i, p in enumerate(pages)]
        self._syncing_tabs_bar = True
        bar.blockSignals(True)
        try:
            while bar.count() > len(titles):
                bar.removeTab(bar.count() - 1)
            for i, title in enumerate(titles):
                if i < bar.count():
                    bar.setTabText(i, title)
                else:
                    bar.addTab(title)
            parent = self.parentWidget()
            edit_page = str(getattr(parent, "_edit_page", "") or "") if parent is not None else ""
            active = 0
            for i, page in enumerate(pages):
                if str(page.get("id") or "") == edit_page:
                    active = i
                    break
            if bar.count() > 0:
                bar.setCurrentIndex(active)
        finally:
            bar.blockSignals(False)
            self._syncing_tabs_bar = False
        strip_h = self._tabs_strip_height()
        bar.setGeometry(0, 0, max(1, self.width()), strip_h)
        from ui.player.player_chrome import player_tabs_bar_qss

        bar.setStyleSheet(
            player_tabs_bar_qss(
                surface=_tc("surface"),
                text=_panel_text_color(self.data),
                border=_tc("border"),
                accent=_tc("accent"),
                font_size=_panel_font_size(self.data),
            )
        )
        bar.show()
        # 标签条抬到最前，保证能点到；选中框透明盖在上面不挡鼠标
        bar.raise_()
        self._sync_selection_chrome()

    def _page_allows_visible(self) -> bool:
        parent = self.parentWidget()
        if parent is None:
            return True
        edit_page = str(getattr(parent, "_edit_page", "") or "")
        kind = str(self.data.get("type") or "")
        page = str(self.data.get("page") or "")
        if kind in ("tabs", "_background"):
            return True
        # 标签分区外：始终显示（不受所属页影响）
        if hasattr(parent, "item_in_tabs_zone") and not parent.item_in_tabs_zone(self):
            return True
        # 分区内：空所属页 = 全部页；有所属页则仅匹配时显示
        if not edit_page or not page:
            return True
        return page == edit_page

    def _refresh_look(self):
        kind = str(self.data.get("type") or "")
        text = str(self.data.get("text") or kind)
        accent = _tc("accent")
        card = _tc("card")
        text_c = _tc("text")
        text_sec = _tc("text_secondary")
        border = _tc("border")
        surface = _tc("surface")
        if kind == "button":
            self._clear_proxy_tabs()
            action = str(self.data.get("action") or "")
            text = str(self.data.get("text") or action)
            btn = self._ensure_proxy_btn()
            btn.setText(text)
            btn.setGeometry(0, 0, max(1, self.width()), max(1, self.height()))
            _apply_button_chrome(btn, self.data)
            btn.show()
            # 仅作用于本控件，避免无选择器样式表覆盖子 QPushButton 的全局主题
            self.setStyleSheet("#DesignerItem { background:transparent; border:none; }")
            self._sync_selection_chrome()
        elif kind == "tabs":
            self._clear_proxy_btn()
            pages = self.data.get("pages") or []
            titles = [str(p.get("title") or p.get("id") or "") for p in pages if isinstance(p, dict)]
            text = " | ".join([t for t in titles if t]) or "标签页"
            # 控件本体全透明：不遮挡下方其它控件，仅顶部标签条可见
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self.setAutoFillBackground(False)
            self.setStyleSheet("#DesignerItem { background: transparent; border: none; }")
            self._sync_proxy_tabs()
            self._sync_selection_chrome()
        else:
            self._clear_proxy_btn()
            self._clear_proxy_tabs()
            if kind == "link":
                color = str(self.data.get("color") or accent)
                size = int(self.data.get("font_size") or 12)
                self.setStyleSheet(
                    f"#DesignerItem {{ background:transparent; color:{color};"
                    f" font-size:{size}px; text-decoration:underline; border:none; }}"
                )
            elif kind == "log":
                # Match runtime PlayerLogFrame toolbar (title + 清空/复制/目录).
                text = "运行日志  清空  复制  目录"
                panel_fg = _panel_text_color(self.data)
                size = _panel_font_size(self.data)
                self.setStyleSheet(designer_panel_item_qss("", "", panel_fg, size))
            elif kind == "script_list":
                title = str(self.data.get("title") or "脚本")
                items = self.data.get("items") or []
                names = []
                for entry in items:
                    if not isinstance(entry, dict):
                        continue
                    name = str(entry.get("title") or "")
                    if not name:
                        continue
                    try:
                        loops = max(1, int(entry.get("loops") or 1))
                    except (TypeError, ValueError):
                        loops = 1
                    mark = "☑" if entry.get("checked", True) else "☐"
                    names.append(f"{mark} {name}  ×{loops}")
                try:
                    group = max(1, int(self.data.get("group_loops") or 1))
                except (TypeError, ValueError):
                    group = 1
                text = title + ("\n" + "\n".join(names[:5]) if names else "")
                text += f"\n整组 ×{group}"
                panel_fg = _panel_text_color(self.data)
                size = _panel_font_size(self.data)
                self.setStyleSheet(designer_panel_item_qss("", "", panel_fg, size))
            elif kind == "progress":
                text = "待命"
                panel_fg = _panel_text_color(self.data)
                size = _panel_font_size(self.data)
                self.setStyleSheet(
                    f"#DesignerItem {{ background:transparent; border:none;"
                    f" color:{panel_fg}; font-size:{size}px; }}"
                )
            elif kind == "schedule":
                title = str(self.data.get("title") or "定时")
                alarms = self.data.get("alarms") or []
                lines = []
                for alarm in alarms[:4]:
                    if not isinstance(alarm, dict):
                        continue
                    mark = "☑" if alarm.get("enabled") else "☐"
                    hour = int(alarm.get("hour") or 0)
                    minute = int(alarm.get("minute") or 0)
                    lines.append(f"{mark} {hour:02d}:{minute:02d}")
                text = title + ("\n" + "\n".join(lines) if lines else "\n未启用")
                panel_fg = _panel_text_color(self.data)
                size = _panel_font_size(self.data)
                self.setStyleSheet(designer_panel_item_qss("", "", panel_fg, size))
            elif kind == "rich_text":
                text = str(self.data.get("text") or "说明文字")
                color = str(self.data.get("color") or text_c)
                size = int(self.data.get("font_size") or 12)
                self.setStyleSheet(
                    f"#DesignerItem {{ background:transparent; color:{color};"
                    f" font-size:{size}px; border:none; }}"
                )
            elif kind == "status":
                text = "状态：就绪"
                color = str(self.data.get("color") or text_c)
                size = int(self.data.get("font_size") or 12)
                self.setStyleSheet(
                    f"#DesignerItem {{ background:transparent; color:{color};"
                    f" font-size:{size}px; border:none; }}"
                )
            elif kind in ("image", "_background"):
                text = "背景图" if kind == "_background" else "图片"
                if kind == "_background":
                    self.setStyleSheet("#DesignerItem { background:transparent; border:none; }")
                else:
                    self.setStyleSheet(
                        f"#DesignerItem {{ background:{surface}; border:1px dashed {border}; color:{text_sec}; }}"
                    )
            else:
                color = str(self.data.get("color") or text_c)
                size = int(self.data.get("font_size") or 12)
                self.setStyleSheet(
                    f"#DesignerItem {{ background:transparent; color:{color};"
                    f" font-size:{size}px; border:none; }}"
                )
        self._caption = text
        # 背景图层在纯色模式下由画布强制隐藏，避免 _refresh_look 又把它显示出来
        if str(self.data.get("type") or "") == "_background" and not getattr(self, "_layer_active", True):
            self.setVisible(False)
        else:
            # 必须叠加页过滤，否则刷新外观会把其它页控件重新显示出来
            self.setVisible(bool(self.data.get("visible", True)) and self._page_allows_visible())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        kind = str(self.data.get("type") or "")
        if kind == "button":
            # 按钮外观由内嵌 QPushButton 渲染，这里只画选中框
            pass
        elif kind in ("image", "_background"):
            if kind == "_background":
                parent = self.parentWidget()
                shell = getattr(parent, "shell_path", None)
                if callable(shell):
                    clip = shell()
                    clip.translate(-self.x(), -self.y())
                    painter.setClipPath(clip)
            pix = self._cached_pixmap()
            if not pix.isNull():
                painter.drawPixmap(self.rect(), pix)
            else:
                painter.fillRect(self.rect(), _theme_qcolor("surface"))
                painter.setPen(_theme_qcolor("text_secondary"))
                painter.drawText(
                    self.rect(),
                    Qt.AlignmentFlag.AlignCenter,
                    "背景图" if kind == "_background" else "图片",
                )
        elif kind == "log":
            from ui.player.player_chrome import PLAYER_PANEL_RADIUS

            path = _rounded_rect_path(self.rect(), PLAYER_PANEL_RADIUS)
            painter.setPen(QPen(_theme_qcolor("border")))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
            size = _panel_font_size(self.data)
            fg = QColor(_panel_text_color(self.data))
            border = _theme_qcolor("border")
            font = painter.font()
            font.setPixelSize(max(8, size))
            painter.setFont(font)
            painter.setPen(fg)
            content = self.rect().adjusted(8, 6, -8, -6)
            painter.drawText(
                content,
                Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
                "运行日志",
            )
            # Preview-only chrome: same toolbar chips as runtime QToolButtons.
            metrics = painter.fontMetrics()
            btn_h = max(18, metrics.height() + 4)
            pad_x = 6
            gap = 4
            x = float(content.x() + content.width())
            for label in ("目录", "复制", "清空"):
                bw = float(metrics.horizontalAdvance(label) + pad_x * 2)
                x -= bw
                btn = QRectF(x, float(content.y()), bw, float(btn_h))
                painter.setPen(QPen(border))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(btn, 3.0, 3.0)
                painter.setPen(fg)
                painter.drawText(btn, int(Qt.AlignmentFlag.AlignCenter), label)
                x -= gap
        elif kind == "tabs":
            # 顶部标签由 QTabBar 渲染；下方透明分区仅在选中时画虚线提示
            if self._selected:
                accent = _theme_qcolor("accent")
                zone = QColor(accent)
                zone.setAlpha(22)
                strip_h = self._tabs_strip_height()
                painter.fillRect(0, strip_h, self.width(), max(0, self.height() - strip_h), zone)
                pen = QPen(accent, 1.2, Qt.PenStyle.DashLine)
                accent_line = QColor(accent)
                accent_line.setAlpha(160)
                pen.setColor(accent_line)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
                painter.drawLine(0, strip_h, self.width(), strip_h)
        elif kind == "progress":
            # 整个代理区域就是轨道，字画在中间
            from ui.player.player_chrome import PLAYER_PANEL_RADIUS

            size = _panel_font_size(self.data)
            fg = _panel_text_color(self.data)
            radius = float(max(2, min(PLAYER_PANEL_RADIUS, max(2, self.height() // 2))))
            track = _rounded_rect_path(self.rect(), int(radius))
            painter.setPen(QPen(_theme_qcolor("border")))
            painter.setBrush(QColor(_tc("canvas")))
            painter.drawPath(track)
            font = painter.font()
            font.setPixelSize(max(8, size))
            painter.setFont(font)
            painter.setPen(QColor(fg))
            painter.drawText(
                self.rect(),
                int(Qt.AlignmentFlag.AlignCenter),
                self._caption or "待命",
            )
        elif kind in ("script_list", "schedule", "rich_text"):
            if kind in ("script_list", "schedule"):
                from ui.player.player_chrome import PLAYER_PANEL_RADIUS

                path = _rounded_rect_path(self.rect(), PLAYER_PANEL_RADIUS)
                painter.setPen(QPen(_theme_qcolor("border")))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(path)
                size = _panel_font_size(self.data)
                fg = _panel_text_color(self.data)
            else:
                size = int(self.data.get("font_size") or 12)
                fg = str(self.data.get("color") or _tc("text"))
            font = painter.font()
            font.setPixelSize(max(8, size))
            painter.setFont(font)
            painter.setPen(QColor(fg))
            flags = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap
            painter.drawText(self.rect().adjusted(6, 4, -6, -4), int(flags), self._caption)
        elif kind == "link":
            size = int(self.data.get("font_size") or 12)
            font = painter.font()
            font.setPixelSize(max(8, size))
            font.setUnderline(True)
            painter.setFont(font)
            link_color = QColor(str(self.data.get("color") or _tc("accent")))
            if not link_color.isValid():
                link_color = _theme_qcolor("accent")
            painter.setPen(link_color)
            align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            painter.drawText(self.rect().adjusted(2, 0, -2, 0), int(align), self._caption)
        else:
            size = int(self.data.get("font_size") or 12)
            font = painter.font()
            font.setPixelSize(max(8, size))
            painter.setFont(font)
            painter.setPen(QColor(str(self.data.get("color") or _tc("text"))))
            align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            painter.drawText(self.rect().adjusted(2, 0, -2, 0), int(align), self._caption)

        # 选中框由上层 _SelectionChrome 绘制，避免被子 QPushButton 挡住
        painter.end()

    def _tabs_in_strip(self, local: QPoint) -> bool:
        return local.y() <= self._tabs_strip_height()

    def _tabs_in_handle(self, local: QPoint) -> bool:
        return local.x() >= self.width() - HANDLE and local.y() >= self.height() - HANDLE

    def _end_tabs_pass_through(self) -> None:
        if self._pass_guard is not None:
            app = QApplication.instance()
            if app is not None:
                app.removeEventFilter(self._pass_guard)
            self._pass_guard.deleteLater()
            self._pass_guard = None
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        if self._proxy_tabs is not None:
            self._proxy_tabs.raise_()
        if self._sel_chrome is not None and self._selected:
            self._sel_chrome.raise_()

    def _begin_tabs_pass_through(self) -> None:
        """按下穿透后保持穿透直到松开，否则拖动事件仍会被标签页吃掉。"""
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        if self._pass_guard is None:
            app = QApplication.instance()
            if app is not None:
                self._pass_guard = _TabsPassThroughGuard(self)
                app.installEventFilter(self._pass_guard)

    def _forward_click_through_tabs(self, event: QMouseEvent) -> bool:
        """分区内容点击穿透到下方控件；命中则转发并返回 True。"""
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        try:
            below = QApplication.widgetAt(event.globalPosition().toPoint())
        finally:
            # 先恢复，便于下面按需重新开启「拖拽期穿透」
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        target = below
        while target is not None and not isinstance(target, DesignerItem):
            parent = target.parentWidget()
            if parent is None or parent is self.parentWidget():
                break
            target = parent
        if isinstance(target, DesignerItem) and target is not self:
            mapped = target.mapFromGlobal(event.globalPosition().toPoint())
            forwarded = QMouseEvent(
                event.type(),
                QPointF(mapped),
                event.globalPosition(),
                event.button(),
                event.buttons(),
                event.modifiers(),
            )
            # 先置顶目标再转发，并保持标签页穿透直到松开
            target.raise_()
            self._begin_tabs_pass_through()
            QApplication.sendEvent(target, forwarded)
            return True
        return False

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        local = event.position().toPoint()
        kind = str(self.data.get("type") or "")
        if kind == "tabs":
            # 顶部标签条由子 QTabBar 直接接收，不会进到这里
            # 内容区：无论是否选中，优先点到下方控件，避免「点控件却切页/拖分区」
            if not self._tabs_in_strip(local) and not self._tabs_in_handle(local):
                if self._forward_click_through_tabs(event):
                    event.accept()
                    return
                # 点到空白：未选中则取消选中；已选中才进入拖分区
                if not self._selected:
                    parent = self.parentWidget()
                    if parent is not None and hasattr(parent, "select"):
                        parent.select("")
                    event.accept()
                    return
            elif self._tabs_in_strip(local):
                # 极少情况：事件落到父级而非 QTabBar，仍尝试穿透
                if self._forward_click_through_tabs(event):
                    event.accept()
                    return
                event.accept()
                return
        self.selected.emit(self.widget_id)
        self._press_global = event.globalPosition().toPoint()
        self._press_mono = time.monotonic()
        self._drag_armed = False
        self._drag_offset = None
        self._resizing = False
        if local.x() >= self.width() - HANDLE and local.y() >= self.height() - HANDLE:
            # 缩放柄：按下即可调大小（仍要按住拖）
            self.interaction_began.emit(self.widget_id)
            self._resizing = True
            if self._sel_chrome is not None:
                self._sel_chrome.pause()
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        if self._resizing:
            local = event.position().toPoint()
            w = max(24, _snap(local.x()))
            h = max(20, _snap(local.y()))
            if w == int(self.data.get("w") or 0) and h == int(self.data.get("h") or 0):
                event.accept()
                return
            self.resize(w, h)
            self.data["w"] = w
            self.data["h"] = h
            self._geometry_dirty = True
            event.accept()
            return
        if self._press_global is None:
            return
        delta = event.globalPosition().toPoint() - self._press_global
        dist = math.hypot(float(delta.x()), float(delta.y()))
        if not self._drag_armed:
            held_ms = (time.monotonic() - self._press_mono) * 1000.0
            # 单击抖动不拖；需按住一小会并移出阈值才进入拖拽
            if held_ms < DRAG_HOLD_MS or dist < DRAG_SLOP_PX:
                event.accept()
                return
            self._drag_armed = True
            self._drag_offset = event.globalPosition().toPoint() - self.pos()
            self.interaction_began.emit(self.widget_id)
            if self._sel_chrome is not None:
                self._sel_chrome.pause()
        if self._drag_offset is None:
            event.accept()
            return
        parent = self.parentWidget()
        if parent is None:
            return
        top_left = event.globalPosition().toPoint() - self._drag_offset
        x = _snap(max(0, min(parent.width() - self.width(), top_left.x())))
        y = _snap(max(0, min(parent.height() - self.height(), top_left.y())))
        if x == int(self.data.get("x") or 0) and y == int(self.data.get("y") or 0):
            event.accept()
            return
        self.move(x, y)
        self.data["x"] = x
        self.data["y"] = y
        self._geometry_dirty = True
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent):
        was_dirty = self._geometry_dirty
        self._drag_offset = None
        self._press_global = None
        self._press_mono = 0.0
        self._drag_armed = False
        self._resizing = False
        self._geometry_dirty = False
        if self._sel_chrome is not None and self._selected:
            self._sel_chrome.resume()
            self._sync_selection_chrome()
        # 仅真正拖过/缩放过才写回；纯单击不触发 changed
        if was_dirty:
            self.changed.emit(self.widget_id)
        event.accept()


class DesignerCanvas(QWidget):
    selection_changed = Signal(str)
    widgets_changed = Signal()
    interaction_began = Signal()
    page_activated = Signal(str)
    BG_ITEM_ID = "__bg__"

    def __init__(self, parent=None):
        super().__init__(parent)
        from ui.player.player_chrome import PLAYER_SHELL_RADIUS

        self.CORNER_RADIUS = PLAYER_SHELL_RADIUS
        self._items: Dict[str, DesignerItem] = {}
        self._selected_id = ""
        self._edit_page = ""
        self._bg = {"mode": "color", "color": _tc("canvas"), "image": "", "_local_path": "", "x": 0, "y": 0, "w": 0, "h": 0}
        self._bg_item: Optional[DesignerItem] = None
        self.setObjectName("DesignerCanvas")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setStyleSheet("#DesignerCanvas { background: transparent; border: none; }")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip("选中控件后用方向键微调位置，按住 Shift 一次移动 10 像素")
        self.setFixedSize(460, 360)

    def shell_path(self) -> QPainterPath:
        return _rounded_rect_path(self.rect(), self.CORNER_RADIUS)

    def tab_pages(self) -> List[dict]:
        for item in self._items.values():
            if item.data.get("type") == "tabs":
                pages = item.data.get("pages") or []
                return [dict(p) for p in pages if isinstance(p, dict)]
        return []

    def tabs_item(self) -> Optional["DesignerItem"]:
        for item in self._items.values():
            if item.data.get("type") == "tabs":
                return item
        return None

    def item_in_tabs_zone(self, item: "DesignerItem") -> bool:
        """控件中心是否落在标签页分区矩形内。"""
        tabs = self.tabs_item()
        if tabs is None or item is None or item is tabs:
            return False
        zone = tabs.geometry()
        if zone.width() <= 0 or zone.height() <= 0:
            return False
        return zone.contains(item.geometry().center())

    def set_edit_page(self, page_id: str):
        self._edit_page = str(page_id or "")
        self.apply_page_filter()
        self._sync_tabs_proxies()

    def apply_page_filter(self):
        """编辑态：仅标签分区内按「所属页」显隐；分区外始终显示。"""
        edit_page = str(self._edit_page or "")
        for item in self._items.values():
            kind = str(item.data.get("type") or "")
            page = str(item.data.get("page") or "")
            base_visible = bool(item.data.get("visible", True))
            if kind == "_background":
                continue
            if kind == "tabs":
                item.setVisible(base_visible)
                continue
            if not self.item_in_tabs_zone(item):
                item.setVisible(base_visible)
                continue
            if not page or not edit_page or page == edit_page:
                item.setVisible(base_visible)
            else:
                item.setVisible(False)

    def _sync_tabs_proxies(self):
        for item in self._items.values():
            if item.data.get("type") == "tabs" and item._proxy_tabs is not None:
                item._sync_proxy_tabs()

    def assign_unpaged_widgets_to(self, page_id: str, *, skip_global_types: bool = False):
        """把「标签分区内」尚未归属的控件归到指定页。分区外不改。"""
        target = str(page_id or "")
        if not target:
            return
        global_types = {"log", "status"} if skip_global_types else set()
        for item in self._items.values():
            kind = str(item.data.get("type") or "")
            if kind in ("tabs", "_background") or kind in global_types:
                continue
            if not self.item_in_tabs_zone(item):
                continue
            if str(item.data.get("page") or ""):
                continue
            data = item.export_data()
            data["page"] = target
            item.apply_data(data)
        self.apply_page_filter()
        self.widgets_changed.emit()

    def clear_page_outside_tabs_zone(self):
        """分区外控件清空所属页（它们本就不参与切页，避免侧栏显示误导）。"""
        changed = False
        for item in self._items.values():
            kind = str(item.data.get("type") or "")
            if kind in ("tabs", "_background"):
                continue
            if self.item_in_tabs_zone(item):
                continue
            if not str(item.data.get("page") or ""):
                continue
            data = item.export_data()
            data["page"] = ""
            item.apply_data(data)
            changed = True
        if changed:
            self.apply_page_filter()
            self.widgets_changed.emit()

    def set_background(self, background: dict):
        payload = dict(background or {})
        mode = str(payload.get("mode") or "color").strip().lower()
        payload["mode"] = "image" if mode == "image" else "color"
        self._bg = payload
        self._sync_bg_item()
        self.update()

    def background_payload(self) -> dict:
        payload = dict(self._bg)
        mode = str(payload.get("mode") or "color").strip().lower()
        payload["mode"] = "image" if mode == "image" else "color"
        if (
            payload["mode"] == "image"
            and self._bg_item is not None
            and self._bg_item.isVisible()
        ):
            geo = self._bg_item.geometry()
            payload["x"] = geo.x()
            payload["y"] = geo.y()
            payload["w"] = geo.width()
            payload["h"] = geo.height()
        return payload

    def fill_background_image(self):
        self._bg["x"] = 0
        self._bg["y"] = 0
        self._bg["w"] = self.width()
        self._bg["h"] = self.height()
        if self._bg_item is not None and getattr(self._bg_item, "_layer_active", False):
            data = self._bg_item.export_data()
            data.update({"x": 0, "y": 0, "w": self.width(), "h": self.height()})
            self._bg_item.apply_data(data)
        else:
            self._sync_bg_item()
        self.widgets_changed.emit()

    def _sync_bg_geometry_from_item(self):
        if self._bg_item is None or not getattr(self._bg_item, "_layer_active", False):
            return
        geo = self._bg_item.geometry()
        self._bg["x"] = geo.x()
        self._bg["y"] = geo.y()
        self._bg["w"] = geo.width()
        self._bg["h"] = geo.height()

    def _on_bg_item_changed(self, _wid: str):
        self._sync_bg_geometry_from_item()
        self.widgets_changed.emit()

    def _hide_bg_item(self):
        if self._bg_item is None:
            return
        self._bg_item._layer_active = False
        self._bg_item.set_selected(False)
        self._bg_item.hide()
        if self._selected_id == self.BG_ITEM_ID:
            self.select("")

    def _sync_bg_item(self):
        mode = str(self._bg.get("mode") or "color").strip().lower()
        if mode != "image":
            self._hide_bg_item()
            return
        local = str(self._bg.get("_local_path") or "")
        image = str(self._bg.get("image") or "")
        path = local if local and os.path.isfile(local) else (image if os.path.isfile(image) else "")
        if not path:
            self._hide_bg_item()
            return
        x = int(self._bg.get("x") or 0)
        y = int(self._bg.get("y") or 0)
        w = int(self._bg.get("w") or 0)
        h = int(self._bg.get("h") or 0)
        if w <= 0 or h <= 0:
            x, y = 0, 0
            w, h = max(8, self.width()), max(8, self.height())
        data = {
            "id": self.BG_ITEM_ID,
            "type": "_background",
            "path": image,
            "_local_path": local or path,
            "x": x,
            "y": y,
            "w": w,
            "h": h,
            "z": -10000,
            "visible": True,
        }
        if self._bg_item is None:
            item = DesignerItem(data, self)
            item.selected.connect(self.select)
            item.changed.connect(self._on_bg_item_changed)
            item.interaction_began.connect(lambda _wid: self.interaction_began.emit())
            self._bg_item = item
        else:
            self._bg_item.apply_data(data)
        self._bg_item._layer_active = True
        self._bg_item.show()
        self._bg_item.lower()

    def clear_items(self):
        for item in list(self._items.values()):
            item.deleteLater()
        self._items.clear()
        if self._selected_id != self.BG_ITEM_ID:
            self._selected_id = ""

    def load_widgets(self, widgets: List[dict]):
        self.clear_items()
        ordered = sorted(
            list(widgets or []),
            key=lambda d: (int(d.get("z") or 0), str(d.get("id") or "")),
        )
        for data in ordered:
            # 分组框已移除：旧数据加载时直接丢弃
            if str((data or {}).get("type") or "") == "group":
                continue
            payload = dict(data or {})
            if str(payload.get("type") or "") == "tabs":
                # 旧版曾把标签页收成「仅标签条」矮条，分区失效且看起来很窄
                payload = self._repair_tabs_geometry(payload)
            self.add_item(payload, select=False, reapply=False)
        self.reapply_z_order()
        self.apply_page_filter()
        self.widgets_changed.emit()

    def _repair_tabs_geometry(self, data: dict) -> dict:
        payload = dict(data or {})
        x = int(payload.get("x") or 0)
        y = int(payload.get("y") or 0)
        w = max(8, int(payload.get("w") or 0))
        h = max(8, int(payload.get("h") or 0))
        need_w = w < TABS_MIN_ZONE_W
        need_h = h < TABS_MIN_ZONE_H
        if not need_w and not need_h:
            return payload
        if need_w:
            w = max(TABS_MIN_ZONE_W, max(8, self.width() - max(0, x) - 16))
        if need_h:
            h = max(TABS_MIN_ZONE_H, max(8, self.height() - max(0, y) - 16))
        payload["w"] = w
        payload["h"] = h
        return payload

    def next_z(self, *, bottom: bool = False) -> int:
        if not self._items:
            return 0 if bottom else 10
        zs = [int(item.data.get("z") or 0) for item in self._items.values()]
        return (min(zs) - 1) if bottom else (max(zs) + 1)

    def add_item(self, data: dict, *, select: bool = True, reapply: bool = True) -> DesignerItem:
        payload = dict(data)
        if "z" not in payload:
            kind = str(payload.get("type") or "")
            payload["z"] = self.next_z(bottom=(kind == "image"))
        item = DesignerItem(payload, self)
        item.selected.connect(self.select)
        item.changed.connect(lambda _wid: self.widgets_changed.emit())
        item.interaction_began.connect(lambda _wid: self.interaction_began.emit())
        item.page_activated.connect(self._on_item_page_activated)
        item.show()
        self._items[item.widget_id] = item
        if reapply:
            self.reapply_z_order()
        self.apply_page_filter()
        if select:
            self.select(item.widget_id)
        else:
            self.widgets_changed.emit()
        return item

    def _on_item_page_activated(self, page_id: str):
        self.set_edit_page(str(page_id or ""))
        self.page_activated.emit(str(page_id or ""))

    def reapply_z_order(self):
        if self._bg_item is not None:
            self._bg_item.lower()
        ordered = sorted(
            self._items.values(),
            key=lambda item: (int(item.data.get("z") or 0), item.widget_id),
        )
        # 普通控件 → 标签页分区；选中的非标签页再置于标签页之上，否则分区内无法拖拽。
        # 顶部标签条是子 QTabBar，内容区点击仍走穿透，不靠把整个标签页盖在选中项上。
        tabs_items = [item for item in ordered if item.data.get("type") == "tabs"]
        other_items = [item for item in ordered if item.data.get("type") != "tabs"]
        for item in other_items:
            item.raise_()
        for item in tabs_items:
            item.raise_()
        if self._selected_id == self.BG_ITEM_ID and self._bg_item is not None:
            self._bg_item.raise_()
        elif self._selected_id and self._selected_id in self._items:
            selected = self._items[self._selected_id]
            # 选中项置顶（含非标签页），保证按下后的移动/释放事件仍落在该控件上
            selected.raise_()
            if selected.data.get("type") == "tabs" and selected._proxy_tabs is not None:
                selected._proxy_tabs.raise_()

    def select(self, widget_id: str):
        self._selected_id = widget_id or ""
        for wid, item in self._items.items():
            item.set_selected(wid == self._selected_id)
        if self._bg_item is not None:
            self._bg_item.set_selected(self._selected_id == self.BG_ITEM_ID)
        self.reapply_z_order()
        self.selection_changed.emit(self._selected_id)
        if self._selected_id:
            self.setFocus(Qt.FocusReason.OtherFocusReason)

    def selected_item(self) -> Optional[DesignerItem]:
        if self._selected_id == self.BG_ITEM_ID:
            return self._bg_item
        return self._items.get(self._selected_id)

    def send_selected_to_back(self):
        item = self.selected_item()
        if item is None or item.widget_id == self.BG_ITEM_ID:
            return
        item.data["z"] = self.next_z(bottom=True)
        self.reapply_z_order()
        self.widgets_changed.emit()

    def bring_selected_to_front(self):
        item = self.selected_item()
        if item is None or item.widget_id == self.BG_ITEM_ID:
            return
        item.data["z"] = self.next_z(bottom=False)
        self.reapply_z_order()
        self.widgets_changed.emit()

    def remove_selected(self):
        item = self.selected_item()
        if item is None:
            return
        if item.widget_id == self.BG_ITEM_ID:
            return
        wid = item.widget_id
        item.deleteLater()
        self._items.pop(wid, None)
        self._selected_id = ""
        self.selection_changed.emit("")
        self.reapply_z_order()
        self.widgets_changed.emit()

    def export_widgets(self) -> List[dict]:
        ordered = sorted(
            self._items.values(),
            key=lambda item: (int(item.data.get("z") or 0), item.widget_id),
        )
        result = []
        for item in ordered:
            payload = item.export_data()
            payload["z"] = int(item.data.get("z") or 0)
            result.append(payload)
        return result

    def nudge_selected(self, dx: int, dy: int) -> bool:
        """按像素微调选中控件，不吸附网格。碰到画布边缘则停住。"""
        item = self.selected_item()
        if item is None:
            return False
        old_x = int(item.data.get("x") or 0)
        old_y = int(item.data.get("y") or 0)
        x = max(0, min(self.width() - item.width(), old_x + int(dx)))
        y = max(0, min(self.height() - item.height(), old_y + int(dy)))
        if x == old_x and y == old_y:
            return False
        item.move(x, y)
        item.data["x"] = x
        item.data["y"] = y
        item._sync_selection_chrome()
        if item.widget_id == self.BG_ITEM_ID:
            self._sync_bg_geometry_from_item()
        self.widgets_changed.emit()
        return True

    def keyPressEvent(self, event: QKeyEvent):
        dialog = self.window()
        if dialog is not None and hasattr(dialog, "_try_nudge_from_key"):
            if dialog._try_nudge_from_key(event, focus_widget=self):
                event.accept()
                return
        super().keyPressEvent(event)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.select("")
        super().mousePressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        path = self.shell_path()
        fallback_bg = _tc("canvas")
        painter.fillPath(path, QColor(str(self._bg.get("color") or fallback_bg)))
        painter.setClipPath(path)
        grid = _theme_qcolor("accent")
        grid.setAlpha(36)
        painter.setPen(QPen(grid, 1, Qt.PenStyle.DotLine))
        for x in range(0, self.width(), GRID * 4):
            painter.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), GRID * 4):
            painter.drawLine(0, y, self.width(), y)
        painter.setClipping(False)
        painter.setPen(QPen(_theme_qcolor("border"), 1))
        painter.drawPath(path)
        painter.end()


class PlayerUiDesignerDialog(QDialog):
    """按键精灵式运行界面设计器。"""

    def __init__(
        self,
        parent=None,
        *,
        app_name: str = "",
        ui: Optional[dict] = None,
        asset_map: Optional[Dict[str, str]] = None,
        live_run_context: Optional[Callable[[], dict]] = None,
        script_catalog: Optional[Callable[[], list]] = None,
    ):
        super().__init__(parent)
        self.setObjectName("PlayerUiDesigner")
        self.setWindowTitle("运行界面设计器")
        self.setAutoFillBackground(False)
        self._app_name = app_name or "独立程序"
        self._asset_map: Dict[str, str] = dict(asset_map or {})  # rel -> abs
        self._live_run_context = live_run_context
        self._script_catalog = script_catalog
        self._live_player = None
        self._result_ui: Optional[dict] = None
        self._result_assets: Dict[str, str] = {}
        self._syncing_props = True
        self._undoing = False
        self._nudge_active = False
        self._undo_stack: List[dict] = []
        self._redo_stack: List[dict] = []
        self._last_undo_key = ""
        self._max_undo = 40

        seed = ensure_designer_ui(ui, app_name=self._app_name)
        # 打开时互斥同步：新工作流进第一个列表，剔除项从所有列表移除
        if callable(self._script_catalog):
            try:
                from ui.export_parts.export_scripts import apply_catalog_to_ui_exclusive

                seed = apply_catalog_to_ui_exclusive(seed, list(self._script_catalog() or []))
            except Exception:
                pass
        # 把已有相对路径映射回本地预览
        for widget in seed.get("widgets") or []:
            if widget.get("type") == "image":
                rel = str(widget.get("path") or "")
                if rel in self._asset_map:
                    widget["_local_path"] = self._asset_map[rel]
        bg = seed.get("background") or {}
        rel_bg = str(bg.get("image") or "")
        if rel_bg in self._asset_map:
            bg = dict(bg)
            bg["_local_path"] = self._asset_map[rel_bg]
            seed["background"] = bg

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 顶部紧凑工具条
        self._toolbar = QFrame(self)
        self._toolbar.setObjectName("DesignerToolbar")
        self._toolbar.setFixedHeight(44)
        tb = QHBoxLayout(self._toolbar)
        tb.setContentsMargins(10, 6, 10, 6)
        tb.setSpacing(6)

        # 用 QPushButton+菜单，避免裸 QToolButton 吃不到全局 QPushButton 主题样式
        add_btn = QPushButton("添加控件", self._toolbar)
        add_menu = QMenu(add_btn)
        for label, handler in (
            ("文本标签", self._add_label),
            ("多行说明", self._add_rich_text),
            ("标签页", self._add_tabs),
            ("脚本列表", self._add_script_list),
            ("链接", self._add_link),
            ("装饰图片", self._add_image),
            ("状态文字", self._add_status),
            ("运行日志", self._add_log),
            ("开始按钮", lambda: self._add_button("start")),
            ("暂停按钮", lambda: self._add_button("pause")),
            ("停止按钮", lambda: self._add_button("stop")),
            ("绑定窗口按钮", lambda: self._add_button("bind")),
            ("设置按钮", lambda: self._add_button("settings")),
            ("进度条", self._add_progress),
            ("定时执行", self._add_schedule),
        ):
            act = QAction(label, self)
            act.triggered.connect(handler)
            add_menu.addAction(act)
        apply_unified_menu_style(add_menu, frameless=True)
        add_menu.aboutToShow.connect(lambda: apply_unified_menu_style(add_menu, frameless=True))
        self._add_menu = add_menu
        add_btn.setMenu(add_menu)
        tb.addWidget(add_btn)

        for text, slot in (
            ("置底", self._send_to_back),
            ("置顶", self._bring_to_front),
            ("删除", self._delete_selected),
        ):
            b = QPushButton(text)
            b.clicked.connect(slot)
            tb.addWidget(b)

        self._undo_btn = QPushButton("撤回")
        self._undo_btn.setToolTip("撤回 (Ctrl+Z)")
        self._undo_btn.clicked.connect(self._undo)
        self._redo_btn = QPushButton("恢复")
        self._redo_btn.setToolTip("恢复 (Ctrl+Y)")
        self._redo_btn.clicked.connect(self._redo)
        tb.addWidget(self._undo_btn)
        tb.addWidget(self._redo_btn)

        tb.addStretch(1)
        run_btn = QPushButton("运行")
        run_btn.setProperty("primary", True)
        run_btn.setToolTip("用当前画布打开真实运行窗，可绑定窗口并执行当前工作流")
        run_btn.clicked.connect(self._run_live)
        tb.addWidget(run_btn)
        root.addWidget(self._toolbar)
        self._toolbar_sep = _make_sep("h")
        root.addWidget(self._toolbar_sep)

        body_split = QSplitter(Qt.Orientation.Horizontal)
        body_split.setHandleWidth(1)
        body_split.setChildrenCollapsible(False)

        # 中：灰色工作区 + 画布居中
        scroll = QScrollArea()
        scroll.setObjectName("DesignerWorkspace")
        scroll.setWidgetResizable(False)
        scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.canvas = DesignerCanvas()
        scroll.setWidget(self.canvas)
        body_split.addWidget(scroll)

        # 右：精简属性（窄栏可滚动，避免背景图模式控件增多时裁切）
        right = QFrame()
        right.setObjectName("DesignerSide")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(12, 10, 12, 10)
        right_layout.setSpacing(6)

        def _side_title(text: str) -> QLabel:
            lab = QLabel(text)
            lab.setObjectName("SideTitle")
            return lab

        right_layout.addWidget(_side_title("窗口"))
        size_row = QHBoxLayout()
        size_row.setSpacing(6)
        self._width_spin = QSpinBox()
        self._width_spin.setRange(240, 1920)
        self._width_spin.setPrefix("宽 ")
        self._height_spin = QSpinBox()
        self._height_spin.setRange(160, 1200)
        self._height_spin.setPrefix("高 ")
        self._width_spin.setValue(int(seed["window"]["width"]))
        self._height_spin.setValue(int(seed["window"]["height"]))
        self._width_spin.valueChanged.connect(self._on_window_size)
        self._height_spin.valueChanged.connect(self._on_window_size)
        size_row.addWidget(self._width_spin, 1)
        size_row.addWidget(self._height_spin, 1)
        right_layout.addLayout(size_row)

        edit_page_row = QHBoxLayout()
        edit_page_row.setSpacing(6)
        edit_page_lab = QLabel("编辑页")
        edit_page_lab.setObjectName("PropFieldLabel")
        self._edit_page = CustomDropdown(self)
        self._edit_page.setToolTip(
            "进入某一页进行编辑：画布只显示该页控件；新添加的控件会自动放进当前页。"
            "也可直接点击画布上的标签切换。"
        )
        self._edit_page.currentIndexChanged.connect(self._on_edit_page_changed)
        edit_page_row.addWidget(edit_page_lab)
        edit_page_row.addWidget(self._edit_page, 1)
        right_layout.addLayout(edit_page_row)
        self._edit_page_hint = QLabel(
            "只有标签页框内的控件随切换显隐；框外始终显示。框内用「所属页」决定在哪一页。"
        )
        self._edit_page_hint.setObjectName("PropFieldHint")
        self._edit_page_hint.setWordWrap(True)
        self._edit_page_hint.setStyleSheet("color: palette(mid); font-size: 11px;")
        right_layout.addWidget(self._edit_page_hint)

        self._title_edit = QLineEdit(str(seed.get("title") or self._app_name))
        self._title_edit.setPlaceholderText("窗口标题")
        right_layout.addWidget(self._title_edit)

        self._layout_combo = CustomDropdown(self)
        self._theme_combo = CustomDropdown(self)
        for value, label in PLAYER_LAYOUT_CHOICES:
            self._layout_combo.addItem(label, value)
        for value, label in PLAYER_THEME_CHOICES:
            self._theme_combo.addItem(label, value)
        _select_combo_data(self._layout_combo, resolve_player_layout(seed), "mini")
        _select_combo_data(self._theme_combo, resolve_player_theme(seed), "auto")
        self._layout_combo.setToolTip("普通窗口、始终置顶，或启动后藏到托盘（点托盘图标可再打开）。")
        self._theme_combo.setToolTip("独立程序启动时的界面主题。设计器画布仍跟随编辑器主题。")
        self._layout_combo.currentIndexChanged.connect(self._on_shell_choice_changed)
        self._theme_combo.currentIndexChanged.connect(self._on_shell_choice_changed)
        right_layout.addWidget(self._layout_combo)
        right_layout.addWidget(self._theme_combo)

        right_layout.addWidget(_side_title("背景"))
        self._bg_mode = CustomDropdown(self)
        self._bg_mode.addItem("纯色", "color")
        self._bg_mode.addItem("图片", "image")
        right_layout.addWidget(self._bg_mode)
        color_row = QHBoxLayout()
        color_row.setSpacing(6)
        self._bg_color = QLineEdit(str(seed["background"].get("color") or _tc("canvas")))
        color_btn = QPushButton("取色")
        color_btn.clicked.connect(self._pick_bg_color)
        color_row.addWidget(self._bg_color, 1)
        color_row.addWidget(color_btn)
        right_layout.addLayout(color_row)
        img_row = QHBoxLayout()
        img_row.setSpacing(6)
        self._bg_image = QLineEdit(str(seed["background"].get("image") or ""))
        self._bg_image.setReadOnly(True)
        self._bg_image.setPlaceholderText("背景图（可选）")
        img_btn = QPushButton("浏览…")
        img_btn.clicked.connect(self._pick_bg_image)
        self._bg_clear_btn = QPushButton("清除")
        self._bg_clear_btn.setToolTip("移除背景图（也可选中背景图后按 Delete）")
        self._bg_clear_btn.clicked.connect(self._clear_bg_image)
        img_row.addWidget(self._bg_image, 1)
        img_row.addWidget(img_btn)
        img_row.addWidget(self._bg_clear_btn)
        right_layout.addLayout(img_row)
        self._bg_fill_btn = QPushButton("铺满窗口")
        self._bg_fill_btn.setToolTip("把背景图重新铺满整个窗口")
        self._bg_fill_btn.clicked.connect(self._fill_bg_image)
        right_layout.addWidget(self._bg_fill_btn)
        self._bg_hint = QLabel("选中背景图后可拖动、缩放；Delete 或「清除」可去掉背景图")
        self._bg_hint.setObjectName("PropFieldLabel")
        self._bg_hint.setWordWrap(True)
        right_layout.addWidget(self._bg_hint)
        self._bg_mode.currentIndexChanged.connect(self._on_bg_mode_changed)
        self._bg_color.editingFinished.connect(self._on_bg_color_edited)
        mode = str(seed["background"].get("mode") or "color")
        self._bg_mode.setCurrentIndex(0 if mode != "image" else 1)

        right_layout.addWidget(_side_title("选中控件"))
        self._prop_type = QLabel("未选中")
        self._prop_type.setObjectName("PropTypeLabel")
        right_layout.addWidget(self._prop_type)
        self._prop_text = QLineEdit()
        self._prop_text.setPlaceholderText("文字")
        self._prop_text_multi = QTextEdit()
        self._prop_text_multi.setPlaceholderText("多行说明文字")
        self._prop_text_multi.setFixedHeight(88)
        self._prop_text_multi.hide()
        self._prop_url = QLineEdit()
        self._prop_url.setPlaceholderText("链接 URL")
        right_layout.addWidget(self._prop_text)
        right_layout.addWidget(self._prop_text_multi)
        right_layout.addWidget(self._prop_url)

        page_row = QHBoxLayout()
        page_row.setSpacing(6)
        page_lab = QLabel("所属页")
        page_lab.setObjectName("PropFieldLabel")
        self._prop_page = CustomDropdown(self)
        self._prop_page.setToolTip(
            "切换标签时只显示所属页匹配的控件；选「全部页」则每一页都显示。"
        )
        self._prop_page.currentIndexChanged.connect(self._on_prop_page_changed)
        page_row.addWidget(page_lab)
        page_row.addWidget(self._prop_page, 1)
        right_layout.addLayout(page_row)

        align_row = QHBoxLayout()
        align_row.setSpacing(6)
        align_lab = QLabel("对齐")
        align_lab.setObjectName("PropFieldLabel")
        self._prop_align = CustomDropdown(self)
        self._prop_align.addItems(["左对齐", "居中", "右对齐"])
        self._prop_align.setToolTip("多行说明的水平对齐")
        self._prop_align.currentIndexChanged.connect(self._apply_props_to_item)
        align_row.addWidget(align_lab)
        align_row.addWidget(self._prop_align, 1)
        right_layout.addLayout(align_row)

        font_row = QHBoxLayout()
        font_row.setSpacing(6)
        font_lab = QLabel("字号")
        font_lab.setObjectName("PropFieldLabel")
        self._prop_font = CustomDropdown(self)
        self._prop_font.addItems([str(n) for n in (8, 9, 10, 11, 12, 14, 16, 18, 20, 22, 24, 28, 32, 36, 48, 72)])
        self._prop_font.setCurrentText("12")
        self._prop_font.setToolTip("从列表选择字号")
        font_row.addWidget(font_lab)
        font_row.addWidget(self._prop_font, 1)
        right_layout.addLayout(font_row)

        self._tabs_editor = QFrame()
        self._tabs_editor.setObjectName("TabsEditor")
        tabs_layout = QVBoxLayout(self._tabs_editor)
        tabs_layout.setContentsMargins(0, 4, 0, 0)
        tabs_layout.setSpacing(4)
        tabs_layout.addWidget(QLabel("标签页（可多个）"))
        self._tabs_list = QListWidget()
        self._tabs_list.setFixedHeight(140)
        self._tabs_list.setToolTip("选中一项后可在下方改名称；点「添加页」可自定义多个页面")
        self._tabs_list.currentItemChanged.connect(self._on_tabs_list_current)
        self._tabs_list.itemDoubleClicked.connect(self._on_tabs_list_double_clicked)
        tabs_layout.addWidget(self._tabs_list)
        name_lab = QLabel("页面名称")
        name_lab.setObjectName("PropFieldLabel")
        tabs_layout.addWidget(name_lab)
        self._tabs_title = QLineEdit()
        self._tabs_title.setPlaceholderText("输入名称后回车或失焦生效")
        self._tabs_title.setToolTip("修改当前选中标签页的显示名称")
        self._tabs_title.editingFinished.connect(self._apply_tabs_editor)
        tabs_layout.addWidget(self._tabs_title)
        tabs_btns = QHBoxLayout()
        tabs_add = QPushButton("添加页")
        tabs_del = QPushButton("删除页")
        tabs_add.setToolTip("新增一个自定义标签页")
        tabs_del.setToolTip("删除当前选中的标签页（至少保留一页）")
        tabs_add.clicked.connect(self._add_tab_page)
        tabs_del.clicked.connect(self._remove_tab_page)
        tabs_btns.addWidget(tabs_add)
        tabs_btns.addWidget(tabs_del)
        tabs_layout.addLayout(tabs_btns)
        self._tabs_editor.hide()
        right_layout.addWidget(self._tabs_editor)

        self._script_editor = QFrame()
        self._script_editor.setObjectName("ScriptEditor")
        script_layout = QVBoxLayout(self._script_editor)
        script_layout.setContentsMargins(0, 4, 0, 0)
        script_layout.setSpacing(4)
        script_hint = QLabel(
            "工作区工作流可分配到多个脚本列表，但每个工作流只能属于一个列表。"
            "勾选为默认启用；可改显示名与顺序。"
        )
        script_hint.setObjectName("PropFieldHint")
        script_hint.setWordWrap(True)
        script_hint.setStyleSheet("color: palette(mid); font-size: 11px;")
        script_hint.setToolTip("拖拽或上移/下移调整顺序。从下方「可分配」加入；移除后可分到其它列表。")
        script_layout.addWidget(script_hint)
        self._script_list = QListWidget()
        self._script_list.setObjectName("DesignerScriptList")
        self._script_list.setFixedHeight(100)
        self._script_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._script_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._script_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._script_list.setToolTip("当前列表中的工作流")
        self._script_list.itemChanged.connect(self._on_script_item_changed)
        self._script_list.currentItemChanged.connect(self._on_script_list_current)
        self._script_list.model().rowsMoved.connect(self._on_script_rows_moved)
        script_layout.addWidget(self._script_list)
        self._script_title = QLineEdit()
        self._script_title.setPlaceholderText("自定义显示名称")
        self._script_title.setToolTip("仅改列表显示名，不影响导出的脚本文件")
        self._script_title.editingFinished.connect(self._apply_script_editor)
        script_layout.addWidget(self._script_title)
        script_btns = QHBoxLayout()
        script_btns.setSpacing(6)
        script_up = QPushButton("上移")
        script_down = QPushButton("下移")
        script_remove = QPushButton("移出列表")
        script_up.setToolTip("将选中脚本上移（执行更靠前）")
        script_down.setToolTip("将选中脚本下移（执行更靠后）")
        script_remove.setToolTip("移出当前列表，回到可分配池")
        script_up.clicked.connect(lambda: self._move_script_row(-1))
        script_down.clicked.connect(lambda: self._move_script_row(1))
        script_remove.clicked.connect(self._remove_script_from_current_list)
        script_btns.addWidget(script_up, 1)
        script_btns.addWidget(script_down, 1)
        script_btns.addWidget(script_remove, 1)
        script_layout.addLayout(script_btns)
        pool_lab = QLabel("可分配工作流")
        pool_lab.setObjectName("PropFieldLabel")
        script_layout.addWidget(pool_lab)
        self._script_pool = QListWidget()
        self._script_pool.setObjectName("DesignerScriptPool")
        self._script_pool.setFixedHeight(72)
        self._script_pool.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._script_pool.setToolTip("尚未放入任何脚本列表的工作流")
        script_layout.addWidget(self._script_pool)
        pool_add = QPushButton("加入当前列表")
        pool_add.clicked.connect(self._assign_pool_to_current_list)
        script_layout.addWidget(pool_add)
        self._script_editor.hide()
        right_layout.addWidget(self._script_editor)

        color_row2 = QHBoxLayout()
        color_row2.setSpacing(6)
        self._prop_color_lab = QLabel("颜色")
        self._prop_color_lab.setObjectName("PropFieldLabel")
        self._prop_color_swatch = QFrame()
        self._prop_color_swatch.setObjectName("PropColorSwatch")
        self._prop_color_swatch.setFixedSize(28, 28)
        self._prop_color_swatch.setToolTip("当前颜色")
        self._prop_color = QLineEdit(_tc("text"))
        self._prop_color.setPlaceholderText("颜色")
        self._prop_color.setToolTip("也可手动输入 #RRGGBB")
        self._prop_color_btn = QPushButton("取色")
        self._prop_color_btn.setToolTip("打开取色板")
        self._prop_color_btn.clicked.connect(self._pick_prop_color)
        color_row2.addWidget(self._prop_color_lab)
        color_row2.addWidget(self._prop_color_swatch)
        color_row2.addWidget(self._prop_color, 1)
        color_row2.addWidget(self._prop_color_btn)
        right_layout.addLayout(color_row2)
        self._refresh_prop_color_swatch()

        # 脚本列表 / 日志：底色用上面「底色」，这里单独设文字色
        self._prop_fg_wrap = QWidget()
        fg_row = QHBoxLayout(self._prop_fg_wrap)
        fg_row.setContentsMargins(0, 0, 0, 0)
        fg_row.setSpacing(6)
        self._prop_fg_lab = QLabel("文字")
        self._prop_fg_lab.setObjectName("PropFieldLabel")
        self._prop_fg_swatch = QFrame()
        self._prop_fg_swatch.setObjectName("PropFgColorSwatch")
        self._prop_fg_swatch.setFixedSize(28, 28)
        self._prop_fg_swatch.setToolTip("框内文字颜色")
        self._prop_fg = QLineEdit(_tc("text"))
        self._prop_fg.setPlaceholderText("文字颜色")
        self._prop_fg.setToolTip("标题与列表/日志正文的文字颜色，#RRGGBB")
        self._prop_fg_btn = QPushButton("取色")
        self._prop_fg_btn.setToolTip("选择文字颜色")
        self._prop_fg_btn.clicked.connect(self._pick_prop_fg_color)
        fg_row.addWidget(self._prop_fg_lab)
        fg_row.addWidget(self._prop_fg_swatch)
        fg_row.addWidget(self._prop_fg, 1)
        fg_row.addWidget(self._prop_fg_btn)
        self._prop_fg_wrap.hide()
        right_layout.addWidget(self._prop_fg_wrap)
        self._refresh_prop_fg_swatch()

        geo_row1 = QHBoxLayout()
        geo_row2 = QHBoxLayout()
        self._prop_x = QSpinBox()
        self._prop_y = QSpinBox()
        self._prop_w = QSpinBox()
        self._prop_h = QSpinBox()
        self._prop_x.setPrefix("X ")
        self._prop_y.setPrefix("Y ")
        self._prop_w.setPrefix("W ")
        self._prop_h.setPrefix("H ")
        for spin in (self._prop_x, self._prop_y, self._prop_w, self._prop_h):
            spin.setRange(0, 4000)
        self._prop_x.setToolTip("水平位置。选中控件后也可用 ← → 微调，Shift 加速")
        self._prop_y.setToolTip("垂直位置。选中控件后也可用 ↑ ↓ 微调，Shift 加速")
        geo_row1.addWidget(self._prop_x, 1)
        geo_row1.addWidget(self._prop_y, 1)
        geo_row2.addWidget(self._prop_w, 1)
        geo_row2.addWidget(self._prop_h, 1)
        right_layout.addLayout(geo_row1)
        right_layout.addLayout(geo_row2)
        self._prop_visible = QCheckBox("显示")
        self._prop_visible.setChecked(True)
        right_layout.addWidget(self._prop_visible)

        self._prop_text.editingFinished.connect(self._apply_props_to_item)
        self._prop_text_multi.textChanged.connect(self._on_prop_text_multi_changed)
        self._prop_url.editingFinished.connect(self._apply_props_to_item)
        self._prop_visible.toggled.connect(self._apply_props_to_item)
        self._prop_font.currentTextChanged.connect(self._on_prop_font_changed)
        self._prop_font.currentIndexChanged.connect(self._on_prop_font_changed)
        self._prop_color.editingFinished.connect(self._on_prop_color_edited)
        self._prop_color.textChanged.connect(self._refresh_prop_color_swatch)
        self._prop_fg.editingFinished.connect(self._on_prop_fg_edited)
        self._prop_fg.textChanged.connect(self._refresh_prop_fg_swatch)
        for spin in (self._prop_x, self._prop_y, self._prop_w, self._prop_h):
            spin.valueChanged.connect(self._apply_geo_to_item)

        right_layout.addWidget(_side_title("运行"))
        self._auto_start = QCheckBox("打开后自动执行")
        self._auto_start.setChecked(bool(seed.get("auto_start")))
        self._exit_on_finish = QCheckBox("结束后退出")
        self._exit_on_finish.setChecked(bool(seed.get("exit_on_finish")))
        right_layout.addWidget(self._auto_start)
        right_layout.addWidget(self._exit_on_finish)
        right_layout.addStretch(1)

        side_scroll = QScrollArea()
        side_scroll.setObjectName("DesignerSideScroll")
        side_scroll.setWidgetResizable(True)
        side_scroll.setFrameShape(QFrame.Shape.NoFrame)
        side_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # 原先 276 偏窄，长说明/三按钮会被裁切；可拖分割条再加宽
        side_scroll.setMinimumWidth(300)
        side_scroll.setMaximumWidth(440)
        right.setMinimumWidth(280)
        side_scroll.setWidget(right)
        body_split.addWidget(side_scroll)
        body_split.setStretchFactor(0, 1)
        body_split.setStretchFactor(1, 0)
        body_split.setSizes([780, 320])
        root.addWidget(body_split, 1)

        self._footer_sep = _make_sep("h")
        root.addWidget(self._footer_sep)
        self._footer = QFrame(self)
        self._footer.setObjectName("DesignerFooter")
        foot = QHBoxLayout(self._footer)
        foot.setContentsMargins(12, 8, 12, 8)
        foot.addStretch(1)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        self._ok_btn = QPushButton("完成")
        self._ok_btn.setProperty("primary", True)
        self._ok_btn.setDefault(True)
        self._ok_btn.clicked.connect(self._accept)
        foot.addWidget(cancel_btn)
        foot.addWidget(self._ok_btn)
        root.addWidget(self._footer)

        self._side_panel = right
        self._side_scroll = side_scroll
        self._workspace = scroll

        self.canvas.selection_changed.connect(self._on_selection)
        self.canvas.widgets_changed.connect(self._on_canvas_widgets_changed)
        self.canvas.interaction_began.connect(self._checkpoint)
        self.canvas.page_activated.connect(self._on_canvas_page_activated)
        self.canvas.setFixedSize(self._width_spin.value(), self._height_spin.value())
        self.canvas.set_background(seed.get("background") or {})
        self.canvas.load_widgets(list(seed.get("widgets") or []))
        self._syncing_props = False
        self._refresh_bg_controls()
        self._migrate_unpaged_widgets_if_needed()
        self._refresh_page_combos()
        self._on_selection("")
        self._install_edit_shortcuts()
        self._update_undo_actions()
        self._apply_shell_theme()
        try:
            get_theme_manager().register_theme_change_callback(self._apply_shell_theme)
        except Exception:
            pass
        self.resize(1140, 880)
        self.setMinimumSize(980, 760)

    def _install_edit_shortcuts(self):
        undo_sc = QShortcut(QKeySequence.StandardKey.Undo, self)
        undo_sc.setContext(Qt.ShortcutContext.WindowShortcut)
        undo_sc.activated.connect(self._undo)
        redo_sc = QShortcut(QKeySequence.StandardKey.Redo, self)
        redo_sc.setContext(Qt.ShortcutContext.WindowShortcut)
        redo_sc.activated.connect(self._redo)
        # Windows 习惯：Ctrl+Y 也恢复
        redo_y = QShortcut(QKeySequence("Ctrl+Y"), self)
        redo_y.setContext(Qt.ShortcutContext.WindowShortcut)
        redo_y.activated.connect(self._redo)
        del_sc = QShortcut(QKeySequence.StandardKey.Delete, self)
        del_sc.setContext(Qt.ShortcutContext.WindowShortcut)
        del_sc.activated.connect(self._delete_selected)

    def _capture_snapshot(self) -> dict:
        widgets = []
        for raw in self.canvas.export_widgets():
            widgets.append(copy.deepcopy(raw))
        return {
            "widgets": widgets,
            "background": copy.deepcopy(self.canvas.background_payload()),
            "width": int(self._width_spin.value()),
            "height": int(self._height_spin.value()),
            "title": self._title_edit.text(),
            "bg_mode": int(self._bg_mode.currentIndex()),
            "bg_color": self._bg_color.text(),
            "bg_image": self._bg_image.text(),
            "auto_start": bool(self._auto_start.isChecked()),
            "exit_on_finish": bool(self._exit_on_finish.isChecked()),
            "layout": _combo_data_value(self._layout_combo, "mini"),
            "theme": _combo_data_value(self._theme_combo, "auto"),
            "selected": str(self.canvas._selected_id or ""),
            "asset_map": dict(self._asset_map),
        }

    def _snapshot_key(self, snap: dict) -> str:
        payload = dict(snap)
        payload.pop("asset_map", None)
        try:
            return json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        except Exception:
            return str(id(snap))

    def _focus_blocks_nudge(self, widget=None) -> bool:
        """输入框、数字框、下拉、列表里方向键应留给编辑，不要挪控件。"""
        current = widget if widget is not None else QApplication.focusWidget()
        if current is None:
            return False
        blocking = (
            QLineEdit,
            QTextEdit,
            QAbstractSpinBox,
            QComboBox,
            QAbstractItemView,
            QTabBar,
            CustomDropdown,
        )
        while current is not None and current is not self:
            if isinstance(current, blocking):
                return True
            current = current.parentWidget()
        return False

    def _try_nudge_from_key(self, event, *, focus_widget=None) -> bool:
        key = event.key()
        if key not in (
            Qt.Key.Key_Left,
            Qt.Key.Key_Right,
            Qt.Key.Key_Up,
            Qt.Key.Key_Down,
        ):
            return False
        if self._focus_blocks_nudge(focus_widget):
            return False
        if self.canvas.selected_item() is None:
            return False
        step = 10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
        dx, dy = 0, 0
        if key == Qt.Key.Key_Left:
            dx = -step
        elif key == Qt.Key.Key_Right:
            dx = step
        elif key == Qt.Key.Key_Up:
            dy = -step
        else:
            dy = step
        if not self._nudge_active:
            self._checkpoint()
            self._nudge_active = True
        self.canvas.nudge_selected(dx, dy)
        self._sync_selected_geo()
        return True

    def _checkpoint(self):
        self._nudge_active = False
        if self._undoing or self._syncing_props:
            return
        snap = self._capture_snapshot()
        key = self._snapshot_key(snap)
        if key == self._last_undo_key:
            return
        self._undo_stack.append(snap)
        if len(self._undo_stack) > self._max_undo:
            self._undo_stack.pop(0)
        self._last_undo_key = key
        self._redo_stack.clear()
        self._update_undo_actions()

    def _restore_snapshot(self, snap: dict):
        self._undoing = True
        self._syncing_props = True
        try:
            self._asset_map = dict(snap.get("asset_map") or {})
            self._width_spin.setValue(int(snap.get("width") or 460))
            self._height_spin.setValue(int(snap.get("height") or 360))
            self.canvas.setFixedSize(self._width_spin.value(), self._height_spin.value())
            self._title_edit.setText(str(snap.get("title") or self._app_name))
            self._bg_mode.setCurrentIndex(int(snap.get("bg_mode") or 0))
            self._bg_color.setText(str(snap.get("bg_color") or _tc("canvas")))
            self._bg_image.setText(str(snap.get("bg_image") or ""))
            self._auto_start.setChecked(bool(snap.get("auto_start")))
            self._exit_on_finish.setChecked(bool(snap.get("exit_on_finish")))
            _select_combo_data(self._layout_combo, str(snap.get("layout") or "mini"), "mini")
            _select_combo_data(self._theme_combo, str(snap.get("theme") or "auto"), "auto")
            bg = copy.deepcopy(snap.get("background") or {})
            rel = str(bg.get("image") or "")
            if rel and rel in self._asset_map:
                bg["_local_path"] = self._asset_map[rel]
            self.canvas.set_background(bg)
            widgets = copy.deepcopy(snap.get("widgets") or [])
            for widget in widgets:
                if widget.get("type") == "image":
                    path = str(widget.get("path") or "")
                    if path in self._asset_map:
                        widget["_local_path"] = self._asset_map[path]
            self.canvas.load_widgets(widgets)
            selected = str(snap.get("selected") or "")
            if selected:
                self.canvas.select(selected)
            else:
                self.canvas.select("")
            self._last_undo_key = self._snapshot_key(snap)
        finally:
            self._syncing_props = False
            self._theme_tokens = self._current_theme_tokens()
            # 恢复快照时只刷外壳，避免把设计色再次强制成主题色
            self._refresh_chrome_theme()
            self._undoing = False
            self._refresh_bg_controls()
            self._refresh_page_combos(preserve=True)
            self._on_selection(str(snap.get("selected") or ""))
            self._update_undo_actions()

    def _undo(self):
        if not self._undo_stack:
            return
        current = self._capture_snapshot()
        prev = self._undo_stack.pop()
        self._redo_stack.append(current)
        self._restore_snapshot(prev)

    def _redo(self):
        if not self._redo_stack:
            return
        current = self._capture_snapshot()
        nxt = self._redo_stack.pop()
        self._undo_stack.append(current)
        self._restore_snapshot(nxt)

    def _update_undo_actions(self):
        if hasattr(self, "_undo_btn"):
            self._undo_btn.setEnabled(bool(self._undo_stack) and not self._undoing)
        if hasattr(self, "_redo_btn"):
            self._redo_btn.setEnabled(bool(self._redo_stack) and not self._undoing)

    def _current_theme_tokens(self) -> Dict[str, str]:
        return {
            "canvas": _tc("canvas"),
            "surface": _tc("surface"),
            "card": _tc("card"),
            "text": _tc("text"),
            "text_secondary": _tc("text_secondary"),
            "accent": _tc("accent"),
            "border": _tc("border"),
            "success": _tc("success"),
        }

    def _force_design_colors_to_theme(self):
        """主题切换时：仅把「仍等于旧主题默认色」的项跟到新主题，保留用户自定义色。"""
        if not hasattr(self, "canvas"):
            return
        tokens = self._current_theme_tokens()
        old = getattr(self, "_theme_tokens", None) or tokens
        old_text = str(old.get("text") or "").lower()
        old_accent = str(old.get("accent") or "").lower()
        old_canvas = str(old.get("canvas") or "").lower()
        was_syncing = self._syncing_props
        was_undoing = self._undoing
        self._syncing_props = True
        self._undoing = True
        try:
            bg = dict(self.canvas._bg or {})
            mode = str(bg.get("mode") or "color")
            current_bg = str(bg.get("color") or "").lower()
            # 纯色背景且仍是旧默认画布色 → 跟随新主题
            if mode != "image" and current_bg in ("", old_canvas):
                self._bg_color.setText(tokens["canvas"])
                bg["color"] = tokens["canvas"]
                bg["mode"] = "color"
                idx = self._bg_mode.findData("color")
                if idx >= 0:
                    self._bg_mode.setCurrentIndex(idx)
                self.canvas.set_background(bg)

            for item in list(self.canvas._items.values()):
                data = item.export_data()
                kind = str(data.get("type") or "")
                current = str(data.get("color") or "").lower()
                if kind in ("label", "status", "script_list", "progress", "schedule", "log", "tabs"):
                    if current in ("", old_text):
                        data["color"] = tokens["text"]
                        item.apply_data(data)
                elif kind == "link":
                    if current in ("", old_accent):
                        data["color"] = tokens["accent"]
                        item.apply_data(data)

            selected = self.canvas.selected_item()
            if selected is not None:
                kind = str(selected.data.get("type") or "")
                data = selected.export_data()
                if kind == "button":
                    custom_bg = str(data.get("bg_color") or "").strip()
                    self._prop_color.setText(
                        custom_bg or _default_button_bg(str(data.get("action") or ""))
                    )
                elif kind in ("script_list", "progress", "schedule", "log", "tabs"):
                    self._prop_color.setText(str(data.get("color") or tokens["text"]))
                    self._prop_fg.setText(str(data.get("color") or tokens["text"]))
                elif kind == "link":
                    self._prop_color.setText(str(data.get("color") or tokens["accent"]))
                elif kind in ("label", "status"):
                    self._prop_color.setText(str(data.get("color") or tokens["text"]))
            self._refresh_prop_color_swatch()
            self._refresh_prop_fg_swatch()
            self._theme_tokens = tokens
        finally:
            self._syncing_props = was_syncing
            self._undoing = was_undoing

    def _refresh_chrome_theme(self):
        """刷新设计器外壳/控件样式与画布绘制，不改设计数据。"""
        surface = _tc("surface")
        card = _tc("card")
        border = _tc("border")
        text = _tc("text")
        text_sec = _tc("text_secondary")

        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor(surface))
        pal.setColor(QPalette.ColorRole.WindowText, QColor(text))
        pal.setColor(QPalette.ColorRole.Base, QColor(card))
        pal.setColor(QPalette.ColorRole.Text, QColor(text))
        pal.setColor(QPalette.ColorRole.Button, QColor(surface))
        pal.setColor(QPalette.ColorRole.ButtonText, QColor(text))
        self.setPalette(pal)
        # 不要铺满直角底，否则会盖住系统/DWM 圆角
        self.setAutoFillBackground(False)
        self.setStyleSheet(
            "#PlayerUiDesigner { background: transparent; }"
            f"#DesignerCanvas {{ background: transparent; border: none; }}"
        )

        if hasattr(self, "_toolbar"):
            _fill_panel(self._toolbar, "card")
        if hasattr(self, "_footer"):
            _fill_panel(self._footer, "card")
        if hasattr(self, "_side_panel"):
            _fill_panel(self._side_panel, "card")
        if hasattr(self, "_side_scroll"):
            _fill_panel(self._side_scroll, "card")
            side_viewport = self._side_scroll.viewport()
            if side_viewport is not None:
                _fill_panel(side_viewport, "card")
        if hasattr(self, "_workspace"):
            _fill_panel(self._workspace, "canvas")
            viewport = self._workspace.viewport()
            if viewport is not None:
                _fill_panel(viewport, "canvas")

        for sep in (getattr(self, "_toolbar_sep", None), getattr(self, "_footer_sep", None)):
            if sep is None:
                continue
            sep.setStyleSheet(
                f"QFrame#DesignerSep {{ background:{border}; border:none; color:{border}; }}"
            )

        for title in self.findChildren(QLabel, "SideTitle"):
            title.setStyleSheet(
                f"QLabel#SideTitle {{ color:{text_sec}; font-size:11px; font-weight:600;"
                f" margin-top:6px; background:transparent; border:none; }}"
            )
        for lab in self.findChildren(QLabel, "PropFieldLabel"):
            lab.setStyleSheet(
                f"QLabel#PropFieldLabel {{ color:{text_sec}; background:transparent; border:none; min-width:28px; }}"
            )
        if hasattr(self, "_prop_type"):
            self._prop_type.setStyleSheet(
                f"QLabel#PropTypeLabel {{ color:{text}; background:transparent; border:none; }}"
            )
        self._refresh_prop_color_swatch()
        if hasattr(self, "_ok_btn"):
            self._ok_btn.setProperty("primary", True)

        for btn in self.findChildren(QPushButton):
            btn.setStyleSheet("")
            _polish_widget(btn)

        for combo in self.findChildren(CustomDropdown):
            _polish_widget(combo)
            apply_theme = getattr(combo, "_apply_popup_theme", None)
            if callable(apply_theme):
                apply_theme()
            display = getattr(combo, "display_button", None)
            if display is not None:
                _polish_widget(display)

        for widget in self.findChildren(QLineEdit):
            _polish_widget(widget)
        for widget in self.findChildren(QSpinBox):
            _polish_widget(widget)
        for widget in self.findChildren(QCheckBox):
            _polish_widget(widget)
        for widget in self.findChildren(QTextEdit):
            _polish_widget(widget)

        if hasattr(self, "_add_menu") and self._add_menu is not None:
            apply_unified_menu_style(self._add_menu, frameless=True)

        self._update_undo_actions()

        if hasattr(self, "canvas"):
            for item in self.canvas._items.values():
                item._refresh_look()
                item.update()
            self.canvas.update()

    def _apply_shell_theme(self, *_args):
        """主题变更时智能同步默认色；首次打开只刷外壳，不覆盖用户已设颜色。"""
        tokens = self._current_theme_tokens()
        old = getattr(self, "_theme_tokens", None)
        theme_changed = (not self._undoing) and old is not None and old != tokens
        if theme_changed:
            self._force_design_colors_to_theme()
        elif old is None:
            self._theme_tokens = tokens
        self._refresh_chrome_theme()
        # 宿主编辑器切主题时全局 QSS 会半刷新调试窗（底浅钮深）；整窗重建才能一致。
        if theme_changed:
            self._schedule_live_player_refresh()

    def _schedule_live_player_refresh(self):
        """合并到下一事件循环，避免主题回调里同步关窗/重建。"""
        if getattr(self, "_live_refresh_pending", False):
            return
        if self._live_player is None or not callable(self._live_run_context):
            return
        self._live_refresh_pending = True

        def _refresh():
            self._live_refresh_pending = False
            if self._live_player is None or not callable(self._live_run_context):
                return
            self._run_live()

        QTimer.singleShot(0, _refresh)

    def showEvent(self, event: QShowEvent):
        super().showEvent(event)
        from themes.rounded_popup import apply_native_window_corners

        apply_native_window_corners(self)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def hideEvent(self, event):
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        super().hideEvent(event)

    def closeEvent(self, event):
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self._close_live_player()
        try:
            get_theme_manager().unregister_theme_change_callback(self._apply_shell_theme)
        except Exception:
            pass
        super().closeEvent(event)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress and isinstance(obj, QWidget):
            if obj is self or self.isAncestorOf(obj):
                if self._try_nudge_from_key(event, focus_widget=obj):
                    return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event: QKeyEvent):
        if self._try_nudge_from_key(event, focus_widget=QApplication.focusWidget() or self):
            event.accept()
            return
        super().keyPressEvent(event)

    @property
    def result_ui(self) -> Optional[dict]:
        return self._result_ui

    @property
    def result_asset_map(self) -> Dict[str, str]:
        return dict(self._result_assets)

    def _stage_asset(self, source_path: str) -> str:
        source = Path(source_path)
        rel = f"{UI_ASSETS_DIRNAME}/{uuid.uuid4().hex[:8]}_{source.name}"
        self._asset_map[rel] = str(source.resolve())
        return rel

    def _on_shell_choice_changed(self, *_args):
        if self._syncing_props or self._undoing:
            return
        self._checkpoint()
        # Theme/layout change should refresh an already-open debug player.
        if self._live_player is not None and callable(self._live_run_context):
            self._run_live()

    def _on_window_size(self):
        if not self._undoing and not self._syncing_props:
            self._checkpoint()
        old_w, old_h = self.canvas.width(), self.canvas.height()
        new_w, new_h = self._width_spin.value(), self._height_spin.value()
        self.canvas.setFixedSize(new_w, new_h)
        bg = self.canvas.background_payload()
        was_fill = (
            int(bg.get("x") or 0) == 0
            and int(bg.get("y") or 0) == 0
            and int(bg.get("w") or 0) in (0, old_w)
            and int(bg.get("h") or 0) in (0, old_h)
        )
        if str(bg.get("mode") or "") == "image" and was_fill:
            self.canvas.fill_background_image()
        else:
            self.canvas._sync_bg_item()

    def _pick_bg_color(self):
        color = QColorDialog.getColor(QColor(self._bg_color.text()), self, "背景颜色")
        if color.isValid():
            self._checkpoint()
            self._bg_color.setText(color.name())
            if self._bg_mode.currentIndex() != 0:
                self._bg_mode.setCurrentIndex(0)
            else:
                self._apply_background_to_canvas()

    def _prop_font_size(self) -> int:
        try:
            value = int(str(self._prop_font.currentText() or "").strip())
        except (TypeError, ValueError):
            value = 12
        return max(8, min(72, value))

    def _set_prop_font_size(self, size: int):
        value = max(8, min(72, int(size or 12)))
        text = str(value)
        idx = self._prop_font.findText(text)
        if idx >= 0:
            self._prop_font.setCurrentIndex(idx)
            return
        # 不在预设列表时选最接近的项（与背景下拉同为不可编辑列表）
        sizes = []
        for i in range(self._prop_font.count()):
            try:
                sizes.append((abs(int(self._prop_font.itemText(i)) - value), i))
            except (TypeError, ValueError):
                continue
        if sizes:
            sizes.sort()
            self._prop_font.setCurrentIndex(sizes[0][1])

    def _on_prop_font_changed(self, *_args):
        if getattr(self, "_syncing_props", True):
            return
        self._checkpoint()
        self._apply_props_to_item()

    def _pick_prop_color(self):
        item = self.canvas.selected_item()
        kind = str((item.data if item else {}).get("type") or "")
        if kind == "button":
            title = "底色"
            fallback = _default_button_bg(
                str((item.data if item else {}).get("action") or "")
            )
        else:
            title = "文字颜色"
            fallback = _tc("accent") if kind == "link" else _tc("text")
        current = QColor(self._prop_color.text().strip() or fallback)
        color = QColorDialog.getColor(current, self, title)
        if not color.isValid():
            return
        self._checkpoint()
        self._prop_color.setText(color.name())
        self._refresh_prop_color_swatch()
        self._apply_props_to_item()

    def _pick_prop_fg_color(self):
        current = QColor(self._prop_fg.text().strip() or _tc("text"))
        color = QColorDialog.getColor(current, self, "文字颜色")
        if not color.isValid():
            return
        self._checkpoint()
        self._prop_fg.setText(color.name())
        self._refresh_prop_fg_swatch()
        self._apply_props_to_item()

    def _on_prop_color_edited(self):
        if getattr(self, "_syncing_props", True):
            return
        self._checkpoint()
        self._refresh_prop_color_swatch()
        self._apply_props_to_item()

    def _on_prop_fg_edited(self):
        if getattr(self, "_syncing_props", True):
            return
        self._checkpoint()
        self._refresh_prop_fg_swatch()
        self._apply_props_to_item()

    def _refresh_prop_color_swatch(self, *_args):
        if not hasattr(self, "_prop_color_swatch"):
            return
        raw = self._prop_color.text().strip() if hasattr(self, "_prop_color") else ""
        color = QColor(raw) if raw else QColor(_tc("text"))
        if not color.isValid():
            color = QColor(_tc("text"))
        border = _tc("border")
        self._prop_color_swatch.setStyleSheet(
            f"QFrame#PropColorSwatch {{ background:{color.name()}; border:1px solid {border};"
            f" border-radius:4px; }}"
        )

    def _refresh_prop_fg_swatch(self, *_args):
        if not hasattr(self, "_prop_fg_swatch"):
            return
        raw = self._prop_fg.text().strip() if hasattr(self, "_prop_fg") else ""
        color = QColor(raw) if raw else QColor(_tc("text"))
        if not color.isValid():
            color = QColor(_tc("text"))
        border = _tc("border")
        self._prop_fg_swatch.setStyleSheet(
            f"QFrame#PropFgColorSwatch {{ background:{color.name()}; border:1px solid {border};"
            f" border-radius:4px; }}"
        )

    def _pick_bg_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择背景图", "", "图片 (*.png *.jpg *.jpeg *.bmp *.webp);;所有文件 (*.*)"
        )
        if not path:
            return
        self._checkpoint()
        rel = self._stage_asset(path)
        self._bg_image.setText(rel)
        self._bg_mode.setCurrentIndex(1)
        bg = {
            "mode": "image",
            "color": self._bg_color.text().strip() or _tc("canvas"),
            "image": rel,
            "_local_path": path,
            "x": 0,
            "y": 0,
            "w": self.canvas.width(),
            "h": self.canvas.height(),
        }
        self.canvas.set_background(bg)
        self.canvas.select(DesignerCanvas.BG_ITEM_ID)
        self._refresh_bg_controls()

    def _on_bg_mode_changed(self, *_args):
        if self._undoing or self._syncing_props:
            self._apply_background_to_canvas()
            return
        self._checkpoint()
        self._apply_background_to_canvas()

    def _on_bg_color_edited(self):
        if self._undoing or self._syncing_props:
            self._apply_background_to_canvas()
            return
        self._checkpoint()
        self._apply_background_to_canvas()

    def _bg_mode_value(self) -> str:
        data = self._bg_mode.currentData()
        if data == "image" or str(data or "").strip().lower() == "image":
            return "image"
        text = str(self._bg_mode.currentText() or "").strip()
        if text in ("图片", "image", "Image"):
            return "image"
        return "color"

    def _refresh_bg_controls(self):
        is_image = self._bg_mode_value() == "image"
        has_image = bool(self._bg_image.text().strip())
        if hasattr(self, "_bg_fill_btn"):
            self._bg_fill_btn.setEnabled(is_image and has_image)
        if hasattr(self, "_bg_clear_btn"):
            self._bg_clear_btn.setEnabled(has_image)
        if hasattr(self, "_bg_hint"):
            self._bg_hint.setVisible(is_image or has_image)
        if hasattr(self, "_bg_image"):
            self._bg_image.setEnabled(is_image)
        if hasattr(self, "_bg_color"):
            self._bg_color.setEnabled(True)

    def _clear_bg_image(self):
        """移除背景图，切回纯色背景。"""
        color = self._bg_color.text().strip() or _tc("canvas")
        if not color.startswith("#"):
            color = _tc("canvas")
        already_clear = (
            self._bg_mode_value() != "image"
            and not self._bg_image.text().strip()
            and str((self.canvas.background_payload() or {}).get("mode") or "") != "image"
        )
        if already_clear:
            self.canvas.select("")
            self._refresh_bg_controls()
            return
        if not self._undoing and not self._syncing_props:
            self._checkpoint()
        self._syncing_props = True
        try:
            self._bg_image.clear()
            idx = self._bg_mode.findData("color")
            if idx >= 0:
                self._bg_mode.setCurrentIndex(idx)
            else:
                self._bg_mode.setCurrentIndex(0)
        finally:
            self._syncing_props = False
        self.canvas.set_background(
            {
                "mode": "color",
                "color": color,
                "image": "",
                "_local_path": "",
                "x": 0,
                "y": 0,
                "w": 0,
                "h": 0,
            }
        )
        self.canvas.select("")
        self._refresh_bg_controls()
        self.canvas.update()

    def _fill_bg_image(self):
        if self._bg_mode_value() != "image":
            return
        self._checkpoint()
        self.canvas.fill_background_image()
        self.canvas.select(DesignerCanvas.BG_ITEM_ID)

    def _apply_background_to_canvas(self):
        mode = self._bg_mode_value()
        prev = self.canvas.background_payload()
        color = self._bg_color.text().strip() or _tc("canvas")
        if not color.startswith("#"):
            color = _tc("canvas")
        # 切回纯色时同时清掉图片路径，避免“删不掉”的残留
        if mode != "image":
            if self._bg_image.text().strip():
                self._bg_image.clear()
            image_rel = ""
        else:
            image_rel = self._bg_image.text().strip()
        bg = {
            "mode": mode if image_rel or mode == "color" else "color",
            "color": color,
            "image": image_rel,
            "_local_path": self._asset_map.get(image_rel, "") if image_rel else "",
            "x": int(prev.get("x") or 0) if image_rel else 0,
            "y": int(prev.get("y") or 0) if image_rel else 0,
            "w": int(prev.get("w") or 0) if image_rel else 0,
            "h": int(prev.get("h") or 0) if image_rel else 0,
        }
        if mode == "image" and not image_rel:
            bg["mode"] = "color"
        self.canvas.set_background(bg)
        self._refresh_bg_controls()
        self.canvas.update()

    def _has_action(self, action: str) -> bool:
        return any(
            w.data.get("type") == "button" and w.data.get("action") == action
            for w in self.canvas._items.values()
        )

    def _has_type(self, kind: str) -> bool:
        return any(w.data.get("type") == kind for w in self.canvas._items.values())

    def _add_button(self, action: str):
        labels = {
            "start": "开始",
            "pause": "暂停",
            "stop": "停止",
            "bind": "绑定窗口",
            "settings": "设置",
        }
        widths = {"start": 120, "pause": 120, "stop": 120, "bind": 100, "settings": 90}
        if self._has_action(action):
            QMessageBox.information(self, "提示", f"「{labels.get(action, action)}」按钮已存在")
            return
        self._checkpoint()
        self.canvas.add_item(
            {
                "id": f"btn_{action}_{uuid.uuid4().hex[:6]}",
                "type": "button",
                "action": action,
                "text": labels[action],
                "x": 40,
                "y": 40,
                "w": widths.get(action, 120),
                "h": 36,
                "page": self._default_page_for_new_item(),
                "visible": True,
            }
        )

    def _current_edit_page_id(self) -> str:
        data = self._edit_page.currentData()
        return str(data or "")

    def _default_page_for_new_item(self) -> str:
        """新控件默认归属当前编辑页；无标签页时为空（全局）。"""
        if self.canvas.tabs_item() is None:
            return ""
        return self._current_edit_page_id()

    def _on_canvas_widgets_changed(self):
        self._sync_selected_geo()
        # 拖出分区后所属页不再生效，清掉以免外面跟着切页
        self.canvas.clear_page_outside_tabs_zone()
        self.canvas.apply_page_filter()

    def _selected_item_page_id(self) -> str:
        item = self.canvas.selected_item()
        if item is None:
            return ""
        kind = str(item.data.get("type") or "")
        if kind in ("tabs", "_background"):
            return ""
        return str(item.data.get("page") or "")

    def _refresh_page_combos(self, *, preserve: bool = False):
        pages = self.canvas.tab_pages()
        edit_current = self._current_edit_page_id() if preserve else ""
        # 所属页以下拉框为准不可靠：优先用选中控件真实 page
        prop_current = self._selected_item_page_id()
        if preserve and not prop_current and self.canvas.selected_item() is None:
            prop_current = str(self._prop_page.currentData() or "")
        self._syncing_props = True
        try:
            self._edit_page.blockSignals(True)
            self._prop_page.blockSignals(True)
            self._edit_page.clear()
            self._prop_page.clear()
            self._edit_page.addItem("全部页（始终显示）", "")
            self._prop_page.addItem("全部页（始终显示）", "")
            for page in pages:
                page_id = str(page.get("id") or "")
                title = str(page.get("title") or page_id)
                self._edit_page.addItem(title, page_id)
                self._prop_page.addItem(title, page_id)
            if pages:
                valid_ids = {str(p.get("id") or "") for p in pages}
                first_id = str(pages[0].get("id") or "")
                if preserve and (edit_current == "" or edit_current in valid_ids):
                    # 保留「全部页」预览或当前页
                    target = edit_current
                elif edit_current in valid_ids:
                    target = edit_current
                else:
                    # 打开设计器时默认进入第一页，否则停在「全部页」会看起来像切页无效
                    target = first_id
                idx = self._edit_page.findData(target)
                self._edit_page.setCurrentIndex(max(0, idx))
                self.canvas.set_edit_page(str(self._edit_page.currentData() or ""))
            else:
                self._edit_page.setCurrentIndex(0)
                self.canvas.set_edit_page("")
            prop_idx = self._prop_page.findData(prop_current)
            self._prop_page.setCurrentIndex(max(0, prop_idx))
            self._refresh_edit_page_hint()
        finally:
            self._edit_page.blockSignals(False)
            self._prop_page.blockSignals(False)
            self._syncing_props = False

    def _refresh_edit_page_hint(self):
        pages = self.canvas.tab_pages()
        if not pages:
            self._edit_page_hint.setText(
                "未添加标签页时控件全局显示。添加「标签页」后：框内控件按所属页切换，框外始终显示。"
            )
            return
        page_id = self._current_edit_page_id()
        if not page_id:
            self._edit_page_hint.setText(
                "当前：全部页预览。框内控件按所属页切换；框外控件始终显示。"
            )
            return
        title = page_id
        for page in pages:
            if str(page.get("id") or "") == page_id:
                title = str(page.get("title") or page_id)
                break
        self._edit_page_hint.setText(
            f"正在编辑「{title}」：框内只显示此页（或全部页）的控件；框外不受影响。"
        )

    def _on_edit_page_changed(self, *_args):
        if self._syncing_props:
            return
        self.canvas.set_edit_page(self._current_edit_page_id())
        self._refresh_edit_page_hint()

    def _on_canvas_page_activated(self, page_id: str):
        """画布标签条点击 → 同步侧栏「编辑页」与标签页列表选中项。"""
        if self._syncing_props:
            return
        target = str(page_id or "")
        idx = self._edit_page.findData(target)
        if idx < 0:
            return
        self._syncing_props = True
        try:
            self._edit_page.setCurrentIndex(idx)
            # 侧栏页列表必须跟着标签条走，否则再次点选标签页控件时会跳回旧页
            self._tabs_list.blockSignals(True)
            try:
                for row in range(self._tabs_list.count()):
                    item = self._tabs_list.item(row)
                    data = item.data(Qt.ItemDataRole.UserRole) or {}
                    if str(data.get("id") or "") == target:
                        self._tabs_list.setCurrentRow(row)
                        self._tabs_title.setText(str(data.get("title") or ""))
                        break
            finally:
                self._tabs_list.blockSignals(False)
        finally:
            self._syncing_props = False
        self.canvas.set_edit_page(target)
        self._refresh_edit_page_hint()

    def _migrate_unpaged_widgets_if_needed(self):
        """修复页归属：分区外清 page；分区内无效 page 清空；分区内全无归属则归到第一页。"""
        pages = self.canvas.tab_pages()
        if not pages:
            return
        valid = {str(p.get("id") or "") for p in pages if p.get("id")}
        self.canvas.clear_page_outside_tabs_zone()
        for item in list(self.canvas._items.values()):
            kind = str(item.data.get("type") or "")
            if kind in ("tabs", "_background"):
                continue
            if not self.canvas.item_in_tabs_zone(item):
                continue
            page = str(item.data.get("page") or "")
            if page and page not in valid:
                data = item.export_data()
                data["page"] = ""
                item.apply_data(data)
        has_paged_in_zone = any(
            str(item.data.get("page") or "") in valid
            for item in self.canvas._items.values()
            if item.data.get("type") not in ("tabs", "_background")
            and self.canvas.item_in_tabs_zone(item)
        )
        if has_paged_in_zone:
            self.canvas.apply_page_filter()
            return
        first = str(pages[0].get("id") or "")
        if first:
            self.canvas.assign_unpaged_widgets_to(first, skip_global_types=False)

    def _on_prop_page_changed(self, *_args):
        if self._syncing_props or self._undoing:
            return
        item = self.canvas.selected_item()
        if item is None or item.data.get("type") in ("tabs", "_background"):
            return
        self._checkpoint()
        data = item.export_data()
        data["page"] = str(self._prop_page.currentData() or "")
        item.apply_data(data)
        self.canvas.apply_page_filter()

    def _on_prop_text_multi_changed(self):
        if self._syncing_props or self._undoing:
            return
        # 输入过程中不写历史，失焦式保存靠 apply；这里直接同步预览
        item = self.canvas.selected_item()
        if item is None or item.data.get("type") != "rich_text":
            return
        data = item.export_data()
        data["text"] = self._prop_text_multi.toPlainText()
        item.apply_data(data)
        self.canvas.apply_page_filter()

    def _align_index(self, align: str) -> int:
        return {"left": 0, "center": 1, "right": 2}.get(str(align or "left"), 0)

    def _align_value(self) -> str:
        return ("left", "center", "right")[max(0, min(2, self._prop_align.currentIndex()))]

    def _fill_tabs_editor(self, pages: list):
        # 以当前编辑页为准，不要沿用侧栏列表里过期的选中项（否则会跳回旧页）
        keep_id = self._current_edit_page_id()
        self._tabs_list.blockSignals(True)
        try:
            self._tabs_list.clear()
            select_row = 0
            for index, page in enumerate(pages or []):
                if not isinstance(page, dict):
                    continue
                item = QListWidgetItem(str(page.get("title") or page.get("id") or "页"))
                item.setData(Qt.ItemDataRole.UserRole, dict(page))
                self._tabs_list.addItem(item)
                if str(page.get("id") or "") == keep_id:
                    select_row = index
            if self._tabs_list.count() > 0:
                self._tabs_list.setCurrentRow(select_row)
                cur = self._tabs_list.currentItem()
                if cur is not None:
                    data = cur.data(Qt.ItemDataRole.UserRole) or {}
                    self._tabs_title.setText(str(data.get("title") or ""))
        finally:
            self._tabs_list.blockSignals(False)

    def _on_tabs_list_current(self, current: Optional[QListWidgetItem], _previous):
        if self._syncing_props:
            return
        if current is None:
            self._tabs_title.setText("")
            return
        data = current.data(Qt.ItemDataRole.UserRole) or {}
        self._syncing_props = True
        try:
            self._tabs_title.setText(str(data.get("title") or ""))
            page_id = str(data.get("id") or "")
            if page_id:
                idx = self._edit_page.findData(page_id)
                if idx >= 0:
                    self._edit_page.setCurrentIndex(idx)
        finally:
            self._syncing_props = False
        page_id = str(data.get("id") or "")
        if page_id:
            self.canvas.set_edit_page(page_id)
            self._refresh_edit_page_hint()

    def _on_tabs_list_double_clicked(self, _item: QListWidgetItem):
        self._tabs_title.setFocus()
        self._tabs_title.selectAll()

    def _collect_tabs_pages(self) -> list:
        pages = []
        for i in range(self._tabs_list.count()):
            item = self._tabs_list.item(i)
            data = dict(item.data(Qt.ItemDataRole.UserRole) or {})
            page_id = str(data.get("id") or f"page_{i + 1}")
            title = str(data.get("title") or f"页{i + 1}")
            pages.append({"id": page_id, "title": title})
        return pages

    def _apply_tabs_editor(self):
        if self._syncing_props or self._undoing:
            return
        item = self.canvas.selected_item()
        if item is None or item.data.get("type") != "tabs":
            return
        current = self._tabs_list.currentItem()
        if current is not None:
            data = dict(current.data(Qt.ItemDataRole.UserRole) or {})
            new_title = self._tabs_title.text().strip() or data.get("title") or "页"
            data["title"] = new_title
            current.setData(Qt.ItemDataRole.UserRole, data)
            current.setText(str(data["title"]))
        new_pages = self._collect_tabs_pages()
        old_pages = [
            {"id": str(p.get("id") or ""), "title": str(p.get("title") or "")}
            for p in (item.data.get("pages") or [])
            if isinstance(p, dict)
        ]
        if new_pages == old_pages:
            return
        self._checkpoint()
        payload = item.export_data()
        payload["pages"] = new_pages
        item.apply_data(payload)
        self._refresh_page_combos(preserve=True)
        # 画布标签条立即显示新名称
        if item._proxy_tabs is not None:
            item._sync_proxy_tabs()

    def _add_tab_page(self):
        item = self.canvas.selected_item()
        if item is None or item.data.get("type") != "tabs":
            return
        index = self._tabs_list.count() + 1
        page_id = f"page_{uuid.uuid4().hex[:6]}"
        title = f"页面{index}"
        list_item = QListWidgetItem(title)
        list_item.setData(Qt.ItemDataRole.UserRole, {"id": page_id, "title": title})
        self._tabs_list.blockSignals(True)
        self._tabs_list.addItem(list_item)
        self._tabs_list.setCurrentItem(list_item)
        self._tabs_list.blockSignals(False)
        self._tabs_title.setText(title)
        self._apply_tabs_editor()
        self.canvas.set_edit_page(page_id)
        self._refresh_page_combos(preserve=True)
        self._refresh_edit_page_hint()
        self._tabs_title.setFocus()
        self._tabs_title.selectAll()

    def _remove_tab_page(self):
        item = self.canvas.selected_item()
        if item is None or item.data.get("type") != "tabs":
            return
        if self._tabs_list.count() <= 1:
            QMessageBox.information(self, "提示", "至少保留一个标签页")
            return
        row = self._tabs_list.currentRow()
        if row < 0:
            return
        self._tabs_list.takeItem(row)
        self._apply_tabs_editor()
        cur = self._tabs_list.currentItem()
        if cur is not None:
            page_id = str((cur.data(Qt.ItemDataRole.UserRole) or {}).get("id") or "")
            if page_id:
                self.canvas.set_edit_page(page_id)
                self._refresh_page_combos(preserve=True)
                self._refresh_edit_page_hint()

    def _designer_ui_snapshot(self) -> dict:
        widgets = []
        for raw in self.canvas.export_widgets():
            widgets.append(dict(raw))
        return {"widgets": widgets}

    def _fill_script_pool(self):
        if not hasattr(self, "_script_pool"):
            return
        self._script_pool.clear()
        catalog = []
        if callable(self._script_catalog):
            try:
                catalog = list(self._script_catalog() or [])
            except Exception:
                catalog = []
        from ui.export_parts.export_scripts import unassigned_catalog_items

        for entry in unassigned_catalog_items(catalog, self._designer_ui_snapshot()):
            sid = str(entry.get("id") or "").strip()
            if not sid:
                continue
            item = QListWidgetItem(str(entry.get("title") or sid))
            item.setData(Qt.ItemDataRole.UserRole, dict(entry))
            self._script_pool.addItem(item)

    def _fill_script_editor(self, items: list):
        self._script_list.blockSignals(True)
        self._script_list.clear()
        for entry in items or []:
            if not isinstance(entry, dict):
                continue
            list_item = QListWidgetItem(str(entry.get("title") or entry.get("id") or "脚本"))
            list_item.setFlags(
                list_item.flags()
                | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsDragEnabled
            )
            list_item.setCheckState(
                Qt.CheckState.Checked if entry.get("checked", True) else Qt.CheckState.Unchecked
            )
            list_item.setData(Qt.ItemDataRole.UserRole, dict(entry))
            self._script_list.addItem(list_item)
        self._script_list.blockSignals(False)
        if self._script_list.count() > 0:
            self._script_list.setCurrentRow(0)
        self._fill_script_pool()

    def _on_script_list_current(self, current: Optional[QListWidgetItem], _previous):
        if current is None:
            self._script_title.setText("")
            return
        data = current.data(Qt.ItemDataRole.UserRole) or {}
        self._script_title.setText(str(data.get("title") or ""))

    def _on_script_item_changed(self, _item: QListWidgetItem):
        self._apply_script_editor()

    def _on_script_rows_moved(self, *_args):
        if self._syncing_props or self._undoing:
            return
        self._apply_script_editor()

    def _move_script_row(self, delta: int):
        if self._syncing_props or self._undoing:
            return
        row = self._script_list.currentRow()
        if row < 0:
            return
        target = row + int(delta)
        if target < 0 or target >= self._script_list.count():
            return
        self._checkpoint()
        self._script_list.blockSignals(True)
        item = self._script_list.takeItem(row)
        self._script_list.insertItem(target, item)
        self._script_list.setCurrentRow(target)
        self._script_list.blockSignals(False)
        self._apply_script_editor()

    def _collect_script_items(self) -> list:
        items = []
        for i in range(self._script_list.count()):
            item = self._script_list.item(i)
            data = dict(item.data(Qt.ItemDataRole.UserRole) or {})
            item_id = str(data.get("id") or f"script_{i + 1}")
            title = str(data.get("title") or f"脚本{i + 1}")
            entry = dict(data)
            entry["id"] = item_id
            entry["title"] = title
            entry["checked"] = item.checkState() == Qt.CheckState.Checked
            items.append(entry)
        return items

    def _apply_script_editor(self):
        if self._syncing_props or self._undoing:
            return
        item = self.canvas.selected_item()
        if item is None or item.data.get("type") != "script_list":
            return
        current = self._script_list.currentItem()
        if current is not None:
            data = dict(current.data(Qt.ItemDataRole.UserRole) or {})
            data["title"] = self._script_title.text().strip() or data.get("title") or "脚本"
            data["checked"] = current.checkState() == Qt.CheckState.Checked
            current.setData(Qt.ItemDataRole.UserRole, data)
            current.setText(str(data["title"]))
        self._checkpoint()
        payload = item.export_data()
        payload["items"] = self._collect_script_items()
        # 区标题沿用 text 属性
        payload["title"] = self._prop_text.text().strip() or payload.get("title") or "脚本"
        item.apply_data(payload)
        self.canvas.apply_page_filter()

    def _sync_script_list_from_catalog(self, *, quiet: bool = True):
        """按导出目录互斥刷新脚本列表。"""
        if not callable(self._script_catalog):
            if not quiet:
                QMessageBox.information(self, "提示", "当前没有可同步的导出脚本。")
            return
        try:
            catalog = list(self._script_catalog() or [])
        except Exception as exc:
            if not quiet:
                QMessageBox.warning(self, "同步失败", str(exc))
            return
        if not catalog:
            if not quiet:
                QMessageBox.information(self, "提示", "工作区没有可打包的工作流。")
            return
        from ui.export_parts.export_scripts import apply_catalog_to_ui_exclusive

        self._checkpoint()
        synced = apply_catalog_to_ui_exclusive(self._designer_ui_snapshot(), catalog)
        by_id = {
            str(w.get("id") or ""): w
            for w in (synced.get("widgets") or [])
            if isinstance(w, dict) and str(w.get("type") or "") == "script_list"
        }
        for item in self.canvas._items.values():
            if item.data.get("type") != "script_list":
                continue
            data = by_id.get(str(item.widget_id or ""))
            if data is None:
                continue
            item.apply_data(data)
        selected = self.canvas.selected_item()
        if selected is not None and selected.data.get("type") == "script_list":
            self._fill_script_editor(list(selected.data.get("items") or []))
        else:
            self._fill_script_pool()
        self.canvas.apply_page_filter()

    def _assign_pool_to_current_list(self):
        if self._syncing_props or self._undoing:
            return
        item = self.canvas.selected_item()
        if item is None or item.data.get("type") != "script_list":
            return
        selected = list(self._script_pool.selectedItems())
        if not selected:
            return
        from ui.export_parts.export_scripts import sync_script_list_items

        self._checkpoint()
        payload = item.export_data()
        existing = list(payload.get("items") or [])
        stub = [dict(pool.data(Qt.ItemDataRole.UserRole) or {}) for pool in selected]
        payload["items"] = existing + sync_script_list_items([], stub)
        item.apply_data(payload)
        self._fill_script_editor(list(payload.get("items") or []))
        self.canvas.apply_page_filter()

    def _remove_script_from_current_list(self):
        if self._syncing_props or self._undoing:
            return
        item = self.canvas.selected_item()
        if item is None or item.data.get("type") != "script_list":
            return
        row = self._script_list.currentRow()
        if row < 0:
            return
        self._checkpoint()
        self._script_list.blockSignals(True)
        self._script_list.takeItem(row)
        self._script_list.blockSignals(False)
        self._apply_script_editor()
        self._fill_script_pool()

    def _add_label(self):
        self._checkpoint()
        self.canvas.add_item(
            {
                "id": f"label_{uuid.uuid4().hex[:6]}",
                "type": "label",
                "text": "文本标签",
                "x": 40,
                "y": 40,
                "w": 160,
                "h": 28,
                "font_size": 12,
                "color": _tc("text"),
                "page": self._default_page_for_new_item(),
                "visible": True,
            }
        )

    def _add_rich_text(self):
        self._checkpoint()
        self.canvas.add_item(
            {
                "id": f"rich_{uuid.uuid4().hex[:6]}",
                "type": "rich_text",
                "text": "在这里填写说明文字",
                "x": 40,
                "y": 40,
                "w": 240,
                "h": 80,
                "font_size": 12,
                "color": _tc("text"),
                "align": "left",
                "page": self._default_page_for_new_item(),
                "visible": True,
            }
        )

    def _add_tabs(self):
        if self._has_type("tabs"):
            QMessageBox.information(self, "提示", "标签页控件已存在（全局唯一）")
            return
        self._checkpoint()
        # 分区要罩住内容区：顶部是标签条，下方透明区决定哪些控件随页切换
        zone_w = max(TABS_MIN_ZONE_W, self.canvas.width() - 40)
        zone_h = max(TABS_MIN_ZONE_H, self.canvas.height() - 24)
        self.canvas.add_item(
            {
                "id": f"tabs_{uuid.uuid4().hex[:6]}",
                "type": "tabs",
                "x": 20,
                "y": 8,
                "w": zone_w,
                "h": zone_h,
                "pages": [
                    {"id": "page_1", "title": "页面1"},
                    {"id": "page_2", "title": "页面2"},
                ],
                "page": "",
                "z": 1,
                "visible": True,
            }
        )
        # 已有控件若未归属页面，全部归到第一页，否则切换标签看不出变化
        self.canvas.assign_unpaged_widgets_to("page_1")
        self._refresh_page_combos(preserve=False)
        idx = self._edit_page.findData("page_1")
        if idx >= 0:
            self._edit_page.setCurrentIndex(idx)
        self.canvas.set_edit_page("page_1")

    def _add_script_list(self):
        from ui.export_parts.export_scripts import sync_script_list_items

        catalog = []
        if callable(self._script_catalog):
            try:
                catalog = list(self._script_catalog() or [])
            except Exception:
                catalog = []
        if not catalog:
            QMessageBox.information(
                self,
                "提示",
                "当前没有可映射的导出脚本。请先在导出流程中选择工作区工作流。",
            )
            return
        existing_lists = [
            it for it in self.canvas._items.values() if it.data.get("type") == "script_list"
        ]
        if not existing_lists:
            items = sync_script_list_items([], catalog)
            title = "脚本"
        else:
            # 额外列表默认空，从可分配池手动加入（避免重复占用）
            items = []
            title = f"脚本{len(existing_lists) + 1}"
        self._checkpoint()
        offset = 20 * len(existing_lists)
        self.canvas.add_item(
            {
                "id": f"scripts_{uuid.uuid4().hex[:6]}",
                "type": "script_list",
                "title": title,
                "x": 40 + offset,
                "y": 50 + offset,
                "w": 220,
                "h": 160,
                "items": items,
                "group_loops": 1,
                "order_mode": "fixed",
                "page": self._default_page_for_new_item(),
                "visible": True,
            }
        )

    def _add_link(self):
        self._checkpoint()
        self.canvas.add_item(
            {
                "id": f"link_{uuid.uuid4().hex[:6]}",
                "type": "link",
                "text": "打开链接",
                "url": "https://",
                "x": 40,
                "y": 40,
                "w": 140,
                "h": 24,
                "font_size": 12,
                "color": _tc("accent"),
                "page": self._default_page_for_new_item(),
                "visible": True,
            }
        )

    def _add_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择图片", "", "图片 (*.png *.jpg *.jpeg *.bmp *.webp);;所有文件 (*.*)"
        )
        if not path:
            return
        self._checkpoint()
        rel = self._stage_asset(path)
        # 装饰图默认铺满画布并置于底层，避免挡住按钮
        self.canvas.add_item(
            {
                "id": f"image_{uuid.uuid4().hex[:6]}",
                "type": "image",
                "path": rel,
                "_local_path": path,
                "x": 0,
                "y": 0,
                "w": self.canvas.width(),
                "h": self.canvas.height(),
                "z": self.canvas.next_z(bottom=True),
                "page": self._default_page_for_new_item(),
                "visible": True,
            }
        )

    def _send_to_back(self):
        item = self.canvas.selected_item()
        if item is None:
            QMessageBox.information(self, "提示", "请先选中一个控件")
            return
        if item.widget_id == DesignerCanvas.BG_ITEM_ID:
            return
        self._checkpoint()
        self.canvas.send_selected_to_back()

    def _bring_to_front(self):
        item = self.canvas.selected_item()
        if item is None:
            QMessageBox.information(self, "提示", "请先选中一个控件")
            return
        if item.widget_id == DesignerCanvas.BG_ITEM_ID:
            return
        self._checkpoint()
        self.canvas.bring_selected_to_front()

    def _close_live_player(self):
        window = self._live_player
        self._live_player = None
        if window is None:
            return
        try:
            from ui.export_parts.player_dev_run import cancel_dev_player_theme_restore

            cancel_dev_player_theme_restore(window)
        except Exception:
            pass
        try:
            window.destroyed.disconnect(self._on_live_player_destroyed)
        except (RuntimeError, TypeError):
            pass
        try:
            window.close()
        except RuntimeError:
            pass

    def _on_live_player_destroyed(self, *_args):
        self._live_player = None

    def _run_live(self):
        if not callable(self._live_run_context):
            QMessageBox.information(self, "无法运行", "当前没有可执行的工作流。")
            return
        self._apply_props_to_item()
        # 运行前再修一次页归属，避免「全是全部页」导致运行窗切页无变化
        self._migrate_unpaged_widgets_if_needed()
        ui = self._build_ui_payload()
        widgets = ui.get("widgets") or []
        actions = {
            widget.get("action")
            for widget in widgets
            if widget.get("type") == "button" and widget.get("visible", True)
        }
        if "start" not in actions:
            QMessageBox.warning(self, "无法运行", "至少需要一个可见的「开始」按钮。")
            return
        try:
            context = dict(self._live_run_context() or {})
            workflow_data = context.get("workflow_data") or {}
        except Exception as exc:
            QMessageBox.warning(self, "无法运行", str(exc))
            return
        if not workflow_data.get("cards"):
            QMessageBox.warning(self, "无法运行", "当前工作流没有卡片")
            return
        from ui.export_parts.export_scripts import (
            scripts_dict_from_catalog,
            scripts_meta_from_catalog,
        )
        from ui.export_parts.player_dev_run import build_dev_player_package, launch_dev_player_window

        catalog = list(context.get("script_catalog") or [])
        package = build_dev_player_package(
            app_name=str(context.get("app_name") or self._app_name),
            ui=ui,
            asset_map=self._asset_map,
            workflow_data=workflow_data,
            images_dir=str(context.get("images_dir") or ""),
            sounds_dir=str(context.get("sounds_dir") or ""),
            parent_workflow_file=str(context.get("parent_workflow_file") or ""),
            required_client_width=int(context.get("required_client_width") or 0),
            required_client_height=int(context.get("required_client_height") or 0),
            scripts=scripts_dict_from_catalog(catalog),
            scripts_meta=scripts_meta_from_catalog(catalog),
            entry_script_id=str(context.get("entry_script_id") or ""),
        )
        self._close_live_player()
        window = launch_dev_player_window(
            package,
            context.get("config") or {},
            parent=self,
            initial_page=self._current_edit_page_id(),
        )
        self._live_player = window
        window.destroyed.connect(self._on_live_player_destroyed)

    def _add_status(self):
        if self._has_type("status"):
            QMessageBox.information(self, "提示", "状态文字已存在")
            return
        self._checkpoint()
        self.canvas.add_item(
            {
                "id": f"status_{uuid.uuid4().hex[:6]}",
                "type": "status",
                "x": 40,
                "y": 40,
                "w": 300,
                "h": 24,
                "font_size": 12,
                "color": _tc("text"),
                "page": self._default_page_for_new_item(),
                "visible": True,
            }
        )

    def _add_log(self):
        if self._has_type("log"):
            QMessageBox.information(self, "提示", "运行日志区已存在")
            return
        self._checkpoint()
        self.canvas.add_item(
            {
                "id": f"log_{uuid.uuid4().hex[:6]}",
                "type": "log",
                "x": 40,
                "y": 140,
                "w": 360,
                "h": 160,
                "page": self._default_page_for_new_item(),
                "visible": True,
            }
        )

    def _add_progress(self):
        if self._has_type("progress"):
            QMessageBox.information(self, "提示", "进度条已存在")
            return
        self._checkpoint()
        self.canvas.add_item(
            {
                "id": f"progress_{uuid.uuid4().hex[:6]}",
                "type": "progress",
                "title": "进度",
                "x": 40,
                "y": 40,
                "w": 280,
                "h": 28,
                "page": self._default_page_for_new_item(),
                "visible": True,
            }
        )

    def _add_schedule(self):
        if self._has_type("schedule"):
            QMessageBox.information(self, "提示", "定时执行已存在")
            return
        from app_core.player.package import normalize_schedule_alarms

        self._checkpoint()
        self.canvas.add_item(
            {
                "id": f"schedule_{uuid.uuid4().hex[:6]}",
                "type": "schedule",
                "title": "定时",
                "alarms": normalize_schedule_alarms(None),
                "x": 40,
                "y": 40,
                "w": 220,
                "h": 148,
                "page": self._default_page_for_new_item(),
                "visible": True,
            }
        )

    def _delete_selected(self):
        item = self.canvas.selected_item()
        if item is None:
            return
        # 背景图不是普通控件：删除 = 清除背景图并回到纯色
        if item.widget_id == DesignerCanvas.BG_ITEM_ID or item.data.get("type") == "_background":
            self._clear_bg_image()
            return
        self._checkpoint()
        self.canvas.remove_selected()

    def _sync_selected_geo(self):
        if self._syncing_props or self._undoing:
            return
        item = self.canvas.selected_item()
        if item is None:
            return
        data = item.export_data()
        self._syncing_props = True
        try:
            self._prop_x.setValue(int(data.get("x") or 0))
            self._prop_y.setValue(int(data.get("y") or 0))
            self._prop_w.setValue(int(data.get("w") or 0))
            self._prop_h.setValue(int(data.get("h") or 0))
        finally:
            self._syncing_props = False

    def _on_selection(self, widget_id: str):
        self._syncing_props = True
        try:
            item = self.canvas.selected_item()
            enabled = item is not None
            for w in (
                self._prop_text,
                self._prop_text_multi,
                self._prop_url,
                self._prop_visible,
                self._prop_font,
                self._prop_color,
                self._prop_color_btn,
                self._prop_color_swatch,
                self._prop_fg,
                self._prop_fg_btn,
                self._prop_fg_swatch,
                self._prop_page,
                self._prop_align,
                self._prop_x,
                self._prop_y,
                self._prop_w,
                self._prop_h,
            ):
                w.setEnabled(enabled)
            self._tabs_editor.hide()
            self._script_editor.hide()
            self._prop_fg_wrap.hide()
            self._prop_text.show()
            self._prop_text_multi.hide()
            if item is None:
                self._prop_type.setText("未选中")
                self._refresh_prop_color_swatch()
                self._refresh_prop_fg_swatch()
                return
            data = item.export_data()
            type_names = {
                "button": "按钮",
                "label": "文本",
                "rich_text": "多行说明",
                "tabs": "标签页",
                "script_list": "脚本列表",
                "progress": "进度条",
                "schedule": "定时执行",
                "link": "链接",
                "log": "日志",
                "status": "状态",
                "image": "图片",
                "_background": "背景图",
            }
            kind = str(data.get("type") or "")
            extra = f" · {data.get('action')}" if kind == "button" else ""
            self._prop_type.setText(f"{type_names.get(kind, kind)}{extra}")
            if kind in ("script_list", "progress", "schedule"):
                self._prop_text.setText(str(data.get("title") or data.get("text") or ""))
            elif kind == "rich_text":
                self._prop_text.hide()
                self._prop_text_multi.show()
                self._prop_text_multi.setPlainText(str(data.get("text") or ""))
            else:
                self._prop_text.setText(str(data.get("text") or ""))
            self._prop_url.setText(str(data.get("url") or ""))
            self._prop_visible.setChecked(bool(data.get("visible", True)))
            self._set_prop_font_size(int(data.get("font_size") or 12))
            self._prop_align.setCurrentIndex(self._align_index(str(data.get("align") or "left")))
            page_id = "" if kind == "tabs" else str(data.get("page") or "")
            page_idx = self._prop_page.findData(page_id)
            self._prop_page.setCurrentIndex(max(0, page_idx))
            self._prop_x.setValue(int(data.get("x") or 0))
            self._prop_y.setValue(int(data.get("y") or 0))
            self._prop_w.setValue(int(data.get("w") or 0))
            self._prop_h.setValue(int(data.get("h") or 0))
            style_ok = kind in (
                "label",
                "link",
                "status",
                "rich_text",
                "script_list",
                "progress",
                "schedule",
                "log",
                "tabs",
            )
            panel_kinds = ("script_list", "progress", "schedule", "log", "tabs")
            # 面板跟主题，不再单独设底色；按钮可设底色；文字/标签可设颜色
            if kind == "button":
                self._prop_color_lab.setText("底色")
                self._prop_color_swatch.setToolTip("按钮底色")
                self._prop_color.setToolTip("底色，可输入 #RRGGBB")
                self._prop_color_btn.setToolTip("选择底色")
                custom_bg = str(data.get("bg_color") or "").strip()
                self._prop_color.setText(
                    custom_bg or _default_button_bg(str(data.get("action") or ""))
                )
                self._prop_fg_wrap.hide()
            elif kind in panel_kinds:
                self._prop_color_lab.setText("颜色")
                self._prop_color_swatch.setToolTip("文字颜色")
                self._prop_color.setToolTip("面板文字颜色，可输入 #RRGGBB")
                self._prop_color_btn.setToolTip("选择文字颜色")
                self._prop_color.setText(str(data.get("color") or _tc("text")))
                self._prop_fg.setText(str(data.get("color") or _tc("text")))
                self._prop_fg_wrap.hide()
            else:
                self._prop_color_lab.setText("颜色")
                self._prop_color_swatch.setToolTip("当前文字颜色")
                self._prop_color.setToolTip("也可手动输入 #RRGGBB")
                self._prop_color_btn.setToolTip("打开取色板选择文字颜色")
                default_color = _tc("accent") if kind == "link" else _tc("text")
                self._prop_color.setText(str(data.get("color") or default_color))
                self._prop_url.setPlaceholderText("链接 URL")
                self._prop_fg_wrap.hide()
            self._refresh_prop_color_swatch()
            self._refresh_prop_fg_swatch()
            self._prop_text.setEnabled(
                kind in ("button", "label", "link", "script_list", "progress", "schedule")
            )
            self._prop_text_multi.setEnabled(kind == "rich_text")
            self._prop_url.setEnabled(kind == "link")
            self._prop_font.setEnabled(style_ok)
            self._prop_align.setEnabled(kind == "rich_text")
            color_ok = kind in ("button", "label", "link", "status", "rich_text") or kind in panel_kinds
            self._prop_color.setEnabled(color_ok)
            self._prop_color_btn.setEnabled(color_ok)
            self._prop_color_swatch.setEnabled(color_ok)
            self._prop_fg.setEnabled(False)
            self._prop_fg_btn.setEnabled(False)
            self._prop_fg_swatch.setEnabled(False)
            has_tabs = self.canvas.tabs_item() is not None
            in_zone = has_tabs and self.canvas.item_in_tabs_zone(item)
            page_ok = kind not in ("tabs", "_background") and in_zone
            self._prop_page.setEnabled(page_ok)
            if not has_tabs:
                self._prop_page.setToolTip("请先添加「标签页」控件，再设置所属页")
            elif not in_zone:
                self._prop_page.setToolTip("控件在标签页框外：始终显示，无需设置所属页")
            else:
                self._prop_page.setToolTip(
                    "框内控件：切换标签时只显示所属页匹配的；选「全部页」则每一页都显示。"
                )
            self._prop_visible.setEnabled(kind != "_background")
            if kind == "tabs":
                self._tabs_editor.show()
                self._fill_tabs_editor(list(data.get("pages") or []))
            if kind == "script_list":
                self._script_editor.show()
                self._fill_script_editor(list(data.get("items") or []))
        finally:
            self._syncing_props = False

    def _apply_props_to_item(self):
        """把右侧属性写回选中控件（不含所属页；所属页见 _on_prop_page_changed）。"""
        if self._syncing_props or self._undoing:
            return
        item = self.canvas.selected_item()
        if item is None:
            return
        data = item.export_data()
        kind = str(data.get("type") or "")
        sender = self.sender()
        if kind in ("button", "label", "link"):
            data["text"] = self._prop_text.text().strip() or data.get("text") or ""
        if kind == "script_list":
            data["title"] = self._prop_text.text().strip() or data.get("title") or "脚本"
        if kind == "progress":
            data["title"] = self._prop_text.text().strip() or data.get("title") or "进度"
        if kind == "schedule":
            data["title"] = self._prop_text.text().strip() or data.get("title") or "定时"
        if kind == "rich_text":
            data["text"] = self._prop_text_multi.toPlainText()
            data["align"] = self._align_value()
            data["font_size"] = self._prop_font_size()
            data["color"] = self._prop_color.text().strip() or _tc("text")
        if kind == "link":
            data["url"] = self._prop_url.text().strip()
        if kind in ("label", "link", "status"):
            data["font_size"] = self._prop_font_size()
            fallback = _tc("accent") if kind == "link" else _tc("text")
            raw_color = self._prop_color.text().strip() or fallback
            data["color"] = raw_color if QColor(raw_color).isValid() else fallback
        if kind in ("script_list", "progress", "schedule", "log", "tabs"):
            data["font_size"] = self._prop_font_size()
            # 面板只保留文字色；底色一律走主题（清掉旧包里的自定义底色）
            fg_raw = self._prop_color.text().strip() or _tc("text")
            data["color"] = fg_raw if QColor(fg_raw).isValid() else _tc("text")
            data["bg_color"] = ""
        if kind == "button":
            raw = self._prop_color.text().strip()
            color = QColor(raw)
            if color.isValid():
                name = color.name()
                default_bg = _default_button_bg(str(data.get("action") or ""))
                had_custom = bool(str(data.get("bg_color") or "").strip())
                if (not had_custom) and name.lower() == default_bg.lower():
                    data["bg_color"] = ""
                else:
                    data["bg_color"] = name
            else:
                data["bg_color"] = ""
        # page 只由 _on_prop_page_changed 写入，这里绝不改所属页
        if kind != "_background":
            data["visible"] = self._prop_visible.isChecked()
        # 文本/显示等由 editingFinished/toggled 触发时在此记历史（字号/颜色路径已 checkpoint）
        if sender in (self._prop_text, self._prop_url, self._prop_visible, self._prop_align):
            self._checkpoint()
        item.apply_data(data)
        self.canvas.apply_page_filter()

    def _apply_geo_to_item(self):
        if self._syncing_props or self._undoing:
            return
        item = self.canvas.selected_item()
        if item is None:
            return
        self._checkpoint()
        data = item.export_data()
        data.update(
            {
                "x": self._prop_x.value(),
                "y": self._prop_y.value(),
                "w": max(8, self._prop_w.value()),
                "h": max(8, self._prop_h.value()),
            }
        )
        item.apply_data(data)
        if item.widget_id == DesignerCanvas.BG_ITEM_ID:
            self.canvas._sync_bg_geometry_from_item()

    def _build_ui_payload(self) -> dict:
        widgets = []
        for raw in self.canvas.export_widgets():
            cleaned = dict(raw)
            cleaned.pop("_local_path", None)
            widgets.append(cleaned)
        bg_mode = self._bg_mode_value()
        bg = self.canvas.background_payload()
        color = self._bg_color.text().strip() or _tc("canvas")
        if not color.startswith("#"):
            color = _tc("canvas")
        background = {
            "mode": bg_mode,
            "color": color,
            "image": self._bg_image.text().strip() if bg_mode == "image" else "",
            "x": int(bg.get("x") or 0) if bg_mode == "image" else 0,
            "y": int(bg.get("y") or 0) if bg_mode == "image" else 0,
            "w": int(bg.get("w") or 0) if bg_mode == "image" else 0,
            "h": int(bg.get("h") or 0) if bg_mode == "image" else 0,
        }
        payload = {
            "title": self._title_edit.text().strip() or self._app_name,
            "layout": _combo_data_value(self._layout_combo, "mini"),
            "theme": _combo_data_value(self._theme_combo, "auto"),
            "auto_start": self._auto_start.isChecked(),
            "exit_on_finish": self._exit_on_finish.isChecked(),
            "show_log": any(w.get("type") == "log" and w.get("visible", True) for w in widgets),
            "window": {"width": self._width_spin.value(), "height": self._height_spin.value()},
            "background": background,
            "widgets": widgets,
        }
        if callable(self._script_catalog):
            try:
                from ui.export_parts.export_scripts import (
                    apply_catalog_to_ui_exclusive,
                    ensure_list_order,
                )

                catalog = list(self._script_catalog() or [])
                payload = apply_catalog_to_ui_exclusive(payload, catalog)
                payload = ensure_list_order(payload)
            except Exception:
                pass
        return normalize_player_ui(payload, app_name=self._app_name)

    def _accept(self):
        # 先把右侧属性（含文字/状态色）刷进画布，避免未失焦就点完成导致丢色
        self._apply_props_to_item()
        ui = self._build_ui_payload()
        from ui.export_parts.export_scripts import assert_script_lists_exclusive

        conflict = assert_script_lists_exclusive(ui)
        if conflict:
            QMessageBox.warning(self, "无法完成", conflict)
            return
        widgets = ui.get("widgets") or []
        actions = {w.get("action") for w in widgets if w.get("type") == "button" and w.get("visible", True)}
        if "start" not in actions:
            QMessageBox.warning(self, "无法完成", "至少需要一个可见的「开始」按钮。")
            return
        # 只保留仍被引用的资源
        used = set()
        bg = ui.get("background") or {}
        if bg.get("image"):
            used.add(bg["image"])
        for w in widgets:
            if w.get("type") == "image" and w.get("path"):
                used.add(w["path"])
        self._result_assets = {k: v for k, v in self._asset_map.items() if k in used}
        self._result_ui = ui
        self.accept()
