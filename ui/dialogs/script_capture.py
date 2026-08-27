# -*- coding: utf-8 -*-
"""脚本编辑器工具栏：截图、取色、取坐标、选偏移、框选区域、拾取元素、查找。"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Dict, Optional

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui.dialogs.script_capture_text import apply_script_capture, peek_click_coords, peek_find_image_path
from utils.window.window_activation_utils import (
    activate_overlay_widget,
    grab_overlay_input,
    schedule_overlay_activation_boost,
    show_and_activate_overlay,
)
from utils.window.window_hider import WindowHider
from utils.window.window_overlay_utils import (
    draw_selection_overlay,
    map_native_rect_to_local,
    sync_overlay_geometry,
)

logger = logging.getLogger(__name__)

CAPTURE_BUTTONS = (
    ("image", "截图", "框选模板图。每次单独存一张；当前行已是找图时追加成多图。"),
    ("color", "取色", "可连点多个颜色，再点「完成取色」。多点写成 红,绿,蓝|偏移X,偏移Y,红,绿,蓝。"),
    ("coord", "取坐标", "点一下客户区坐标，写入点击/移动/拖拽/滚轮。"),
    ("offset", "选偏移", "从基准点拖到要点的位置，写入固定偏移。找图行会先定位图片中心。"),
    ("region", "框选区域", "框选识别范围，写入 区域=(横坐标, 纵坐标, 宽, 高)。当前行已是找图/找字/找色等就改那一行，否则插入找图。"),
    ("element", "拾取元素", "鼠标放到控件上，右键确认，写入点元素。"),
)


class ScriptCaptureBar(QWidget):
    capture_requested = Signal(str)
    find_requested = Signal()
    resources_toggled = Signal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("scriptCaptureBar")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self._buttons = []
        for kind, label, tip in CAPTURE_BUTTONS:
            button = QPushButton(label)
            button.setObjectName("scriptCaptureButton")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setToolTip(tip)
            button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
            button.clicked.connect(lambda _checked=False, name=kind: self.capture_requested.emit(name))
            row.addWidget(button)
            self._buttons.append(button)
        find_btn = QPushButton("查找")
        find_btn.setObjectName("scriptCaptureButton")
        find_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        find_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        find_btn.setToolTip("在当前脚本中查找。快捷键 Ctrl+F。")
        find_btn.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        find_btn.clicked.connect(self.find_requested.emit)
        row.addWidget(find_btn)
        self._buttons.append(find_btn)
        resource_btn = QPushButton("资源")
        resource_btn.setObjectName("scriptCaptureButton")
        resource_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        resource_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        resource_btn.setCheckable(True)
        resource_btn.setToolTip("管理这张卡导入的图片和模型。")
        resource_btn.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        resource_btn.toggled.connect(self.resources_toggled.emit)
        row.addWidget(resource_btn)
        self._resource_btn = resource_btn
        self._buttons.append(resource_btn)
        row.addStretch(1)
        layout.addLayout(row)
        hint = QLabel("写到光标处。取色可连点再完成；截图每次新文件，找图行再截会追加多图。")
        hint.setObjectName("scriptCaptureHint")
        hint.setWordWrap(True)
        hint.setToolTip("采集结果写到当前光标。取色连点后点「完成取色」。截图不覆盖旧文件。光标在找图行上再截图会追加模板。")
        layout.addWidget(hint)
        self._hint = hint
        self._idle_hint = hint.text()

    def set_resources_visible(self, visible: bool) -> None:
        button = getattr(self, "_resource_btn", None)
        if button is None:
            return
        button.blockSignals(True)
        button.setChecked(bool(visible))
        button.blockSignals(False)

    def set_busy(self, busy: bool) -> None:
        for button in self._buttons:
            button.setEnabled(not busy)
        self._hint.setText("采集中，右键或 ESC 取消。" if busy else self._idle_hint)


class ScriptCaptureController(QObject):
    """隐藏编辑器，打开现有覆盖层，再把结果写回当前行。"""

    def __init__(self, dialog, editor, bar: ScriptCaptureBar) -> None:
        super().__init__(dialog)
        self._dialog = dialog
        self._editor = editor
        self._bar = bar
        self._busy = False
        self._hider: Optional[WindowHider] = None
        self._dialog_modality = None
        self._dialog_delete_on_close = None
        self._overlay = None
        self._element_host: Optional[_ScriptElementCapture] = None
        bar.capture_requested.connect(self.start)

    def start(self, kind: str) -> None:
        if self._busy:
            return
        hwnd = None
        if kind != "element":
            hwnd = resolve_script_capture_hwnd(self._dialog)
            if not hwnd:
                QMessageBox.warning(
                    self._dialog,
                    "采集",
                    "没有可用的绑定窗口。\n\n请先在全局设置中绑定窗口。",
                )
                return
        if kind not in {"image", "color", "coord", "offset", "region", "element"}:
            return
        if kind == "element":
            from utils.window.element_picker import ElementPicker

            if not ElementPicker.is_available():
                QMessageBox.warning(self._dialog, "采集", "UIAutomation 不可用，无法拾取元素。")
                return
        self._busy = True
        self._bar.set_busy(True)
        self._hide_host_windows()
        QTimer.singleShot(200, lambda: self._launch(kind, hwnd))

    def _hide_host_windows(self) -> None:
        """先解除对话框模态再隐藏，否则覆盖层收不到框选。"""
        dialog = self._dialog
        self._dialog_modality = dialog.windowModality()
        self._dialog_delete_on_close = dialog.testAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.setModal(False)
        dialog.setWindowModality(Qt.WindowModality.NonModal)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        QApplication.processEvents()
        self._hider = WindowHider()
        self._hider.add_window(dialog, "脚本编辑器")
        main_window = _main_window_of(dialog)
        if main_window is not None and main_window is not dialog:
            self._hider.add_window(main_window, "主窗口")
        self._hider.hide_all()
        QApplication.processEvents()

    def _restore_host_windows(self) -> None:
        hider = self._hider
        self._hider = None
        if hider is not None:
            hider.restore_all()
        dialog = self._dialog
        modality = self._dialog_modality
        delete_on_close = self._dialog_delete_on_close
        self._dialog_modality = None
        self._dialog_delete_on_close = None
        if dialog is not None:
            if modality is not None:
                dialog.setWindowModality(modality)
            if delete_on_close is not None:
                dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, bool(delete_on_close))
            dialog.raise_()
            dialog.activateWindow()

    def _launch(self, kind: str, hwnd: Optional[int]) -> None:
        try:
            if kind == "image":
                self._start_image(hwnd)
            elif kind == "color":
                self._start_color(hwnd)
            elif kind == "coord":
                self._start_coord(hwnd)
            elif kind == "offset":
                self._start_offset(hwnd)
            elif kind == "region":
                self._start_region(hwnd)
            elif kind == "element":
                self._start_element()
            else:
                self._finish(error=f"未知采集类型: {kind}")
        except Exception as exc:
            logger.error("启动采集失败: %s", exc, exc_info=True)
            self._finish(error=f"启动采集失败: {exc}")

    def _start_image(self, hwnd: int) -> None:
        from ui.selectors.screenshot_tool import ScreenshotOverlay

        overlay = ScreenshotOverlay(
            target_hwnd=hwnd,
            save_dir=_images_dir_of(self._dialog),
            parent=None,
            screenshot_format=_screenshot_format(),
            card_id=getattr(self._dialog, "_card_id", None),
            workflow_id=_workflow_token_of(self._dialog),
            unique_filename=True,
        )
        overlay.screenshot_taken.connect(lambda path: self._finish(kind="image", value=path))
        overlay.screenshot_cancelled.connect(lambda: self._finish())
        self._overlay = overlay
        if not overlay.capture_and_show():
            self._finish()
            return
        QTimer.singleShot(80, overlay._grab_overlay_input)

    def _start_color(self, hwnd: int) -> None:
        from ui.selectors.color_coordinate_picker import ColorCoordinatePickerOverlay

        overlay = ColorCoordinatePickerOverlay(hwnd, parent=None)
        overlay.color_picking_finished.connect(self._on_color_finished)
        overlay.picking_closed.connect(self._on_overlay_gone)
        overlay.destroyed.connect(self._on_overlay_gone)
        self._overlay = overlay
        if not overlay.setup_target_window() or not overlay.capture_screenshot_before_show():
            self._finish(error="无法拍摄窗口截图，取色未开始。")
            return
        show_and_activate_overlay(overlay, log_prefix="脚本取色覆盖层", focus=True)
        self._arm_overlay(overlay, "脚本取色覆盖层")

    def _on_color_finished(self, color_text: object) -> None:
        value = str(color_text or "").strip()
        if not value:
            self._finish(error="没有取到颜色，请点一下再点「完成取色」。")
            return
        self._finish(kind="color", value=value)

    def _start_coord(self, hwnd: int) -> None:
        from ui.selectors.coordinate_selector import CoordinateSelectorOverlay

        overlay = CoordinateSelectorOverlay(hwnd)
        overlay.coordinate_selected.connect(lambda x, y: self._finish(kind="coord", value=(int(x), int(y))))
        overlay.selection_closed.connect(self._on_overlay_gone)
        self._overlay = overlay
        if not overlay.setup_target_window():
            self._finish(error="无法打开坐标选择。")
            return
        show_and_activate_overlay(overlay, log_prefix="脚本取坐标覆盖层", focus=True)
        self._arm_overlay(overlay, "脚本取坐标覆盖层")

    def _start_offset(self, hwnd: int) -> None:
        from ui.selectors.coordinate_selector import OffsetSelectorOverlay

        base, rect = _resolve_offset_base(self._dialog, self._editor, hwnd)
        overlay = OffsetSelectorOverlay(hwnd, base_client=base, base_rect=rect)
        overlay.offset_selected.connect(lambda dx, dy: self._finish(kind="offset", value=(int(dx), int(dy))))
        overlay.selection_closed.connect(self._on_overlay_gone)
        self._overlay = overlay
        if not overlay.setup_target_window():
            self._finish(error="无法打开偏移选择。")
            return
        show_and_activate_overlay(overlay, log_prefix="脚本选偏移覆盖层", focus=True)
        self._arm_overlay(overlay, "脚本选偏移覆盖层")

    def _start_region(self, hwnd: int) -> None:
        from ui.selectors.ocr_region_selector import OCRRegionSelectorOverlay

        overlay = OCRRegionSelectorOverlay(target_window_hwnd=hwnd)
        overlay.region_selected.connect(
            lambda x, y, width, height: self._finish(kind="region", value=(int(x), int(y), int(width), int(height)))
        )
        overlay.overlay_closed.connect(self._on_overlay_gone)
        self._overlay = overlay
        if not overlay.setup_target_window():
            self._finish(error="无法打开框选区域。")
            return
        show_and_activate_overlay(overlay, log_prefix="脚本框选区域覆盖层", focus=True)
        self._arm_overlay(overlay, "脚本框选区域覆盖层")

    def _arm_overlay(self, overlay, log_prefix: str) -> None:
        grab_overlay_input(overlay, log_prefix=log_prefix)
        schedule_overlay_activation_boost(
            overlay,
            log_prefix=log_prefix,
            intervals_ms=(50, 150, 300),
            focus=True,
        )

    def _start_element(self) -> None:
        host = _ScriptElementCapture(self._dialog)
        host.finished.connect(self._on_element_finished)
        self._element_host = host
        host.start()

    def _on_element_finished(self, name: object) -> None:
        if name is None:
            self._finish()
            return
        if not str(name).strip():
            self._finish(error="没有读到控件名称，请再试一次。")
            return
        self._finish(kind="element", value=str(name))

    def _on_overlay_gone(self, *_args) -> None:
        if self._busy:
            self._finish()

    def _apply(self, kind: str, value: Any) -> None:
        plan = apply_script_capture(
            self._editor.toPlainText(),
            self._editor.textCursor().blockNumber(),
            kind,
            value,
        )
        self._editor.apply_edit_plan(plan)
        refresh = getattr(self._dialog, "_refresh_syntax_status", None)
        if callable(refresh):
            refresh()

    def _finish(self, kind: Optional[str] = None, value: Any = None, error: Optional[str] = None) -> None:
        if not self._busy:
            return
        self._busy = False
        self._restore_host_windows()
        overlay = self._overlay
        self._overlay = None
        if overlay is not None:
            try:
                overlay._closing = True
                overlay.blockSignals(True)
                overlay.hide()
                overlay.close()
                overlay.deleteLater()
            except Exception:
                logger.debug("关闭采集覆盖层失败", exc_info=True)
        element_host = self._element_host
        self._element_host = None
        if element_host is not None:
            element_host.stop()
        if value is not None and kind:
            try:
                self._apply(kind, value)
            except Exception as exc:
                logger.error("写入采集结果失败: %s", exc, exc_info=True)
                error = error or f"写入失败: {exc}"
        self._bar.set_busy(False)
        if error:
            QMessageBox.warning(self._dialog, "采集", error)
        self._dialog.raise_()
        self._dialog.activateWindow()
        self._editor.setFocus()


class _ElementOverlay(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.highlight_rect = None
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._closing = False
        self.setMouseTracking(True)
        sync_overlay_geometry(self)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._make_click_through()

    def _make_click_through(self) -> None:
        import ctypes

        hwnd = int(self.winId())
        style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
        ctypes.windll.user32.SetWindowLongW(hwnd, -20, style | 0x00080000 | 0x00000020)

    def set_highlight(self, rect) -> None:
        self.highlight_rect = rect
        self.update()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        activate_overlay_widget(self, log_prefix="脚本元素拾取", focus=True)

    def paintEvent(self, _event) -> None:
        if not self.highlight_rect:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        left, top, width, height = self.highlight_rect
        draw_rect = map_native_rect_to_local(
            self,
            (int(left), int(top), int(left) + int(width), int(top) + int(height)),
        )
        if draw_rect.isEmpty():
            return
        draw_selection_overlay(
            painter,
            draw_rect,
            border_color=QColor(255, 0, 0),
            border_width=3,
            fill_color=QColor(255, 0, 0, 30),
        )


class _ScriptElementCapture(QObject):
    finished = Signal(object)
    highlight = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._active = False
        self._overlay: Optional[_ElementOverlay] = None
        self._thread: Optional[threading.Thread] = None
        self._emitted = False
        self.highlight.connect(self._set_highlight)

    def start(self) -> None:
        self._active = True
        overlay = _ElementOverlay()
        self._overlay = overlay
        show_and_activate_overlay(overlay, log_prefix="脚本元素拾取覆盖层", focus=True)
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._active = False
        overlay = self._overlay
        self._overlay = None
        if overlay is not None:
            try:
                overlay._closing = True
                overlay.hide()
                overlay.close()
                overlay.deleteLater()
            except Exception:
                logger.debug("关闭元素拾取覆盖层失败", exc_info=True)

    def _emit(self, name: Optional[str]) -> None:
        if self._emitted:
            return
        self._emitted = True
        self._active = False
        self.finished.emit(name)

    def _loop(self) -> None:
        import ctypes
        import time

        from utils.input.uiautomation_runtime import import_uiautomation, uiautomation_thread_context

        try:
            auto = import_uiautomation()
        except Exception as exc:
            logger.error("元素拾取初始化失败: %s", exc)
            self._emit(None)
            return

        user32 = ctypes.windll.user32
        while self._active and user32.GetAsyncKeyState(0x02) & 0x8000:
            time.sleep(0.02)

        last_rect = None
        current = None
        try:
            with uiautomation_thread_context(auto):
                while self._active:
                    if user32.GetAsyncKeyState(0x1B) & 0x8000:
                        self._emit(None)
                        return
                    if current is not None and user32.GetAsyncKeyState(0x02) & 0x8000:
                        self._emit(_element_name(current))
                        return
                    time.sleep(0.02)
                    point = ctypes.wintypes.POINT()
                    user32.GetCursorPos(ctypes.byref(point))
                    element = auto.ControlFromPoint(point.x, point.y)
                    rect = _element_rect(element)
                    if rect is None:
                        continue
                    if rect != last_rect:
                        last_rect = rect
                        current = element
                        self.highlight.emit(rect)
                    time.sleep(0.04)
        except Exception as exc:
            logger.error("元素拾取失败: %s", exc, exc_info=True)
            self._emit(None)

    def _set_highlight(self, rect) -> None:
        if self._overlay is not None:
            self._overlay.set_highlight(rect)


def _element_rect(element) -> Optional[tuple]:
    if element is None:
        return None
    rect = getattr(element, "BoundingRectangle", None)
    if not rect or rect.width() <= 0 or rect.height() <= 0:
        return None
    return (rect.left, rect.top, rect.width(), rect.height())


def _element_name(element) -> str:
    for attr in ("Name", "AutomationId", "ClassName"):
        try:
            value = str(getattr(element, attr, "") or "").strip()
        except Exception:
            value = ""
        if value:
            return value
    return ""


def _resolve_offset_base(dialog, editor, hwnd: int):
    line = editor.textCursor().block().text() if editor is not None else ""
    coords = peek_click_coords(line)
    if coords:
        return coords, None
    path = peek_find_image_path(line)
    if not path:
        return None, None
    try:
        from tasks.image_match_click import locate_image_in_window

        found, location, _reason = locate_image_in_window(
            {"image_path": path},
            hwnd,
            card_id=getattr(dialog, "_card_id", None),
        )
    except Exception:
        logger.debug("选偏移时定位图片失败", exc_info=True)
        return None, None
    if not found or not location:
        return None, None
    left, top, width, height = location[:4]
    center = (int(left + width / 2), int(top + height / 2))
    return center, (int(left), int(top), int(width), int(height))


def resolve_script_capture_hwnd(dialog) -> Optional[int]:
    main_window = _main_window_of(dialog)
    hwnd = _tab_target_hwnd(main_window)
    if hwnd and _hwnd_is_bound(main_window, hwnd):
        return int(hwnd)
    config = getattr(main_window, "config", None) if main_window is not None else None
    if config:
        from utils.window.window_binding_utils import get_active_bound_window_hwnd

        hwnd = get_active_bound_window_hwnd(config)
        if hwnd:
            return int(hwnd)
    if main_window is not None and hasattr(main_window, "validate_hwnd_or_get_first"):
        try:
            hwnd, _is_original = main_window.validate_hwnd_or_get_first(hwnd)
            if hwnd:
                return int(hwnd)
        except Exception:
            logger.debug("校验绑定窗口失败", exc_info=True)
    windows = getattr(main_window, "bound_windows", None) or []
    for item in windows:
        if not isinstance(item, dict) or not item.get("enabled", True):
            continue
        candidate = item.get("hwnd")
        if candidate:
            return int(candidate)
    return None


def _tab_target_hwnd(main_window) -> Optional[int]:
    if main_window is None:
        return None
    tab = getattr(main_window, "workflow_tab_widget", None)
    if tab is None:
        return None
    try:
        task_id = tab.get_current_task_id()
        manager = getattr(tab, "task_manager", None)
        task = manager.get_task(task_id) if manager and task_id is not None else None
        hwnd = getattr(task, "target_hwnd", None) if task is not None else None
        return int(hwnd) if hwnd else None
    except Exception:
        return None


def _hwnd_is_bound(main_window, hwnd: int) -> bool:
    checker = getattr(main_window, "is_hwnd_bound", None)
    if not callable(checker):
        return True
    try:
        return bool(checker(hwnd))
    except Exception:
        return False


def _main_window_of(dialog):
    parent = dialog.parent() if dialog is not None else None
    if parent is not None:
        return parent
    return dialog.window() if dialog is not None else None


def _images_dir_of(dialog) -> str:
    main_window = _main_window_of(dialog)
    candidate = str(getattr(main_window, "images_dir", "") or "").strip()
    if candidate:
        return candidate
    from utils.app_paths import get_images_dir

    return get_images_dir("LCA")


def _workflow_token_of(dialog) -> str:
    main_window = _main_window_of(dialog)
    tab = getattr(main_window, "workflow_tab_widget", None) if main_window is not None else None
    if tab is None:
        return ""
    try:
        if hasattr(tab, "_get_current_workflow_filepath"):
            path = str(tab._get_current_workflow_filepath() or "").strip()
            if path:
                return os.path.splitext(os.path.basename(path))[0]
    except Exception:
        logger.debug("读取工作流名称失败", exc_info=True)
    return ""


def _screenshot_format() -> str:
    try:
        from app_core.config_store import load_config

        return str(load_config().get("screenshot_format") or "bmp")
    except Exception:
        return "bmp"
