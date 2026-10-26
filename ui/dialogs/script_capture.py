# -*- coding: utf-8 -*-
"""脚本编辑器工具栏：截图、取色、取坐标、选偏移、框选区域、拾取元素、查找。"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Dict, Optional

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
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
from themes import get_theme_manager, theme_color
from ui.panels.background_jobs import PanelBackgroundJobs
from ui.panels.managed_resources import PanelResources, own_background_thread, release_background_thread
from functools import partial

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
    ("coord", "取坐标", "点一下客户区坐标，写入点击/移动/拖拽/滚轮。拖拽先取起点再取终点；点选 x1/y1 或 x2/y2 可重取对应端点。"),
    ("offset", "选偏移", "从基准点拖到要点的位置，写入固定偏移。找图行会先定位图片中心。"),
    ("region", "框选区域", "框选识别范围，写入 区域.设置；已在检测/找图行上则改该行区域。"),
    ("element", "拾取元素", "鼠标放到控件上，右键确认，写入点元素。"),
)


class ScriptCaptureBar(QWidget):
    capture_requested = Signal(str)
    find_requested = Signal()
    resources_toggled = Signal(bool)
    environment_requested = Signal()

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
        self._plugin_mode = False
        self._busy = False
        for kind, label, tip in CAPTURE_BUTTONS:
            button = QPushButton(label)
            button.setObjectName("scriptCaptureButton")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setToolTip(tip)
            button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
            button.setProperty("capture_kind", kind)
            button.clicked.connect(self._request_capture)
            row.addWidget(button)
            self._buttons.append(button)
            if kind == "image":
                self._image_btn = button
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
        environment_btn = QPushButton("环境设置")
        environment_btn.setObjectName("scriptCaptureButton")
        environment_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        environment_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        environment_btn.setToolTip("选择运行环境，设置 Python 解释器、依赖和软件源。")
        environment_btn.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        environment_btn.clicked.connect(self.environment_requested.emit)
        row.addWidget(environment_btn)
        self._environment_btn = environment_btn
        self._buttons.append(environment_btn)
        row.addStretch(1)
        layout.addLayout(row)
        hint = QLabel("写到光标处。取色可连点再完成；截图每次新文件，找图行再截会追加多图。")
        hint.setObjectName("scriptCaptureHint")
        hint.setWordWrap(True)
        hint.setToolTip("采集结果写到当前光标。取色连点后点「完成取色」。截图不覆盖旧文件。光标在找图行上再截图会追加模板。")
        layout.addWidget(hint)
        self._hint = hint
        self._idle_hint = hint.text()
        self._ordinary_hint = hint.text()

    def set_resources_visible(self, visible: bool) -> None:
        button = self._resource_btn
        button.blockSignals(True)
        button.setChecked(bool(visible))
        button.blockSignals(False)

    def _request_capture(self):
        self.capture_requested.emit(self.sender().property("capture_kind"))

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        for button in self._buttons:
            button.setEnabled(not busy)
        if self._plugin_mode:
            self._resource_btn.setEnabled(False)
            self._image_btn.setEnabled(False)
        self._hint.setText("采集中，右键或 ESC 取消。" if busy else self._idle_hint)

    def set_plugin_mode(self, enabled: bool) -> None:
        self._plugin_mode = enabled
        self._idle_hint = "插件只包含逻辑：资源请用 参数.声明 的文件类型，由工作流传入。" if enabled else self._ordinary_hint
        self.set_busy(self._busy)


class ScriptCaptureController(QObject):
    """隐藏编辑器，打开现有覆盖层，再把结果写回当前行。"""

    def __init__(self, dialog, editor, bar: ScriptCaptureBar) -> None:
        super().__init__(dialog)
        import weakref
        self._dialog_ref = weakref.ref(dialog)
        self._editor_ref = weakref.ref(editor)
        self._bar_ref = weakref.ref(bar)
        self._busy = False
        self._hider: Optional[WindowHider] = None
        self._dialog_modality = None
        self._dialog_delete_on_close = None
        self._overlay = None
        self._element_host: Optional[_ScriptElementCapture] = None
        self._escape_watcher = None
        self._jobs = PanelBackgroundJobs(self)
        self._resources = PanelResources()
        self.destroyed.connect(self._resources.close)
        self._pending_capture: Optional[tuple[str, Optional[int]]] = None
        self._active_capture_kind: Optional[str] = None
        self._launch_timer = QTimer(self)
        self._launch_timer.setSingleShot(True)
        self._launch_timer.setInterval(200)
        self._launch_timer.timeout.connect(self._launch_pending)
        bar.capture_requested.connect(self.start)
        dialog.finished.connect(self._on_dialog_finished)
        dialog.installEventFilter(self)

    @property
    def _dialog(self):
        return self._dialog_ref()

    @property
    def _editor(self):
        return self._editor_ref()

    @property
    def _bar(self):
        return self._bar_ref()

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.DeferredDelete and obj is self.parent():
            self._finish(restore_editor=False)
            obj.removeEventFilter(self)
        return super().eventFilter(obj, event)

    def _on_dialog_finished(self, _result: int) -> None:
        self._dialog.removeEventFilter(self)
        self._finish(restore_editor=False)

    def _launch_pending(self) -> None:
        pending = self._pending_capture
        self._pending_capture = None
        if self._busy and pending is not None:
            self._launch(*pending)

    def start(self, kind: str) -> None:
        if self._busy:
            return
        self._dialog.installEventFilter(self)
        hwnd = None
        if kind != "element":
            try:
                hwnd = resolve_script_capture_hwnd(self._dialog)
            except Exception as exc:
                QMessageBox.warning(self._dialog, "采集", f"读取绑定窗口失败：{exc}")
                return
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
            from importlib.util import find_spec

            if find_spec("uiautomation") is None:
                QMessageBox.warning(self._dialog, "采集", "UIAutomation 不可用，无法拾取元素。")
                return
        self._busy = True
        self._bar.set_busy(True)
        self._active_capture_kind = kind
        self._pending_capture = (kind, hwnd)
        try:
            if kind == "element":
                self._start_escape_watcher()
            self._hide_host_windows()
            if not self._busy:
                return
            self._launch_timer.start()
        except Exception as exc:
            logger.error("准备采集失败: %s", exc, exc_info=True)
            self._finish(error=f"准备采集失败: {exc}")

    def _start_escape_watcher(self) -> None:
        from .script_element_pick import EscapeKeyWatcher

        watcher = EscapeKeyWatcher(self)
        self._escape_watcher = watcher
        watcher.escape_pressed.connect(
            self._cancel_element_pick_from_keyboard,
            Qt.ConnectionType.QueuedConnection,
        )
        self._resources.bind_cleanup("element_escape_hook", self._stop_escape_watcher)
        try:
            watcher.start()
        except Exception:
            self._stop_escape_watcher()
            raise

    def _cancel_element_pick_from_keyboard(self) -> None:
        if self._busy and self._active_capture_kind == "element":
            self._finish()

    def _stop_escape_watcher(self) -> None:
        watcher = self._escape_watcher
        if watcher is None:
            self._resources.forget_cleanup("element_escape_hook")
            return
        try:
            try:
                watcher.escape_pressed.disconnect(self._cancel_element_pick_from_keyboard)
            except RuntimeError:
                pass
            watcher.stop()
        except Exception:
            # 保留 watcher 和清理登记，父对象销毁时仍可重试卸钩。
            raise
        else:
            self._escape_watcher = None
            self._resources.forget_cleanup("element_escape_hook")
            watcher.deleteLater()

    def _hide_host_windows(self) -> None:
        """先登记完整恢复清单，再处理可能触发重入的 Qt 事件。"""
        dialog = self._dialog
        self._dialog_modality = dialog.windowModality()
        self._dialog_delete_on_close = dialog.testAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._hider = WindowHider()
        self._resources.bind_cleanup("restore_windows", partial(_restore_capture_windows, self._hider))
        self._hider.add_window(dialog, "脚本编辑器")
        main_window = _main_window_of(dialog)
        if main_window is not None and main_window is not dialog:
            self._hider.add_window(main_window, "主窗口")

        dialog.setModal(False)
        dialog.setWindowModality(Qt.WindowModality.NonModal)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        QApplication.processEvents()
        if not self._busy:
            return
        self._hider.hide_all()
        QApplication.processEvents()
        if not self._busy:
            return

    def _restore_host_windows(self) -> None:
        self._resources.forget_cleanup("restore_windows")
        hider, self._hider = self._hider, None
        restore_error = None
        try:
            if hider is not None:
                hider.restore_all()
        except Exception as error:
            restore_error = error
            logger.error("恢复脚本采集窗口失败，继续恢复编辑器：%s", error, exc_info=True)
        finally:
            if hider is not None:
                try:
                    for info in tuple(hider._windows.values()):
                        widget = info["widget"]
                        try:
                            should_show = bool(info.get("hidden_by_us") or info.get("was_visible"))
                            if should_show and not widget.property("parameterDisposed") and not widget.isVisible():
                                widget.show()
                        except RuntimeError:
                            continue
                finally:
                    hider.clear()

        dialog = self._dialog
        modality = self._dialog_modality
        delete_on_close = self._dialog_delete_on_close
        self._dialog_modality = None
        self._dialog_delete_on_close = None
        if dialog is not None:
            try:
                if modality is not None:
                    dialog.setWindowModality(modality)
                if delete_on_close is not None:
                    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, bool(delete_on_close))
                dialog.show()
                dialog.raise_()
                dialog.activateWindow()
            except RuntimeError:
                logger.debug("恢复脚本编辑器时窗口已销毁")
        if restore_error is not None:
            raise RuntimeError(f"脚本编辑器窗口恢复时发生错误：{restore_error}") from restore_error

    def _launch(self, kind: str, hwnd: Optional[int]) -> None:
        if not self._busy:
            return
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
        self._overlay = self._resources.own_widget(overlay)
        if not overlay.capture_and_show():
            self._finish()
            return
        QTimer.singleShot(80, overlay, overlay._grab_overlay_input)

    def _start_color(self, hwnd: int) -> None:
        from ui.selectors.color_coordinate_picker import ColorCoordinatePickerOverlay

        overlay = ColorCoordinatePickerOverlay(hwnd, parent=None)
        overlay.color_picking_finished.connect(self._on_color_finished)
        overlay.picking_closed.connect(self._on_overlay_gone)
        overlay.destroyed.connect(self._on_overlay_gone)
        self._overlay = self._resources.own_widget(overlay)
        if not overlay.window_info or not overlay.capture_screenshot_before_show():
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
        self._overlay = self._resources.own_widget(overlay)
        if not overlay.setup_target_window():
            self._finish(error="无法打开坐标选择。")
            return
        show_and_activate_overlay(overlay, log_prefix="脚本取坐标覆盖层", focus=True)
        self._arm_overlay(overlay, "脚本取坐标覆盖层")

    def _start_offset(self, hwnd: int) -> None:
        line = self._editor.textCursor().block().text()
        card_id = getattr(self._dialog, "_card_id", None)
        for name, directory in _task_resource_dirs_of(self._dialog).items():
            setattr(self, name, directory)
        self._jobs.submit("offset", partial(_resolve_offset_base, line, hwnd, card_id),
                          partial(self._show_offset_overlay, hwnd),
                          lambda error: self._finish(error=str(error)))

    def _show_offset_overlay(self, hwnd, result):
        if not self._busy:
            return
        from ui.selectors.coordinate_selector import OffsetSelectorOverlay

        base, rect = result
        overlay = OffsetSelectorOverlay(hwnd, base_client=base, base_rect=rect)
        overlay.offset_selected.connect(lambda dx, dy: self._finish(kind="offset", value=(int(dx), int(dy))))
        overlay.selection_closed.connect(self._on_overlay_gone)
        self._overlay = self._resources.own_widget(overlay)
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
        self._overlay = self._resources.own_widget(overlay)
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
        host.failed.connect(self._on_element_failed)
        self._element_host = host
        host.start()

    def _on_element_failed(self, message: str) -> None:
        if self.sender() is self._element_host:
            self._finish(error=message)

    def _on_element_finished(self, name: object) -> None:
        if self.sender() is not self._element_host:
            return
        if name is None:
            self._finish()
            return
        if not name:
            self._finish(error="没有读到控件名称，请再试一次。")
            return
        self._finish(kind="element", value=name)

    def _on_overlay_gone(self, *_args) -> None:
        if self._busy:
            self._finish()

    def _apply(self, kind: str, value: Any) -> None:
        cursor = self._editor.textCursor()
        plan = apply_script_capture(
            self._editor.toPlainText(),
            cursor.blockNumber(),
            kind,
            value,
            column=cursor.positionInBlock(),
        )
        self._editor.apply_edit_plan(plan)
        if "selection" in plan:
            self._editor.select_line_span(*plan["selection"])
        refresh = getattr(self._dialog, "_refresh_syntax_status", None)
        if callable(refresh):
            refresh()

    def _finish(
        self, kind: Optional[str] = None, value: Any = None, error: Optional[str] = None,
        *, restore_editor: bool = True,
    ) -> None:
        self._jobs.cancel_all()
        self._launch_timer.stop()
        self._pending_capture = None
        self._active_capture_kind = None
        if not self._busy:
            try:
                self._stop_escape_watcher()
            except Exception:
                logger.exception("卸载脚本元素拾取 Esc 监听失败")
            return
        self._busy = False
        cleanup_errors = []
        try:
            self._stop_escape_watcher()
        except Exception as exc:
            cleanup_errors.append(exc)
            logger.error("卸载脚本元素拾取 Esc 监听失败：%s", exc, exc_info=True)

        overlay, self._overlay = self._overlay, None
        if overlay is not None:
            try:
                overlay.blockSignals(True)
                overlay.hide()
                overlay.close()
                overlay.deleteLater()
            except Exception as exc:
                cleanup_errors.append(exc)
                logger.error("关闭脚本采集覆盖层失败：%s", exc, exc_info=True)

        element_host, self._element_host = self._element_host, None
        if element_host is not None:
            try:
                try:
                    element_host.finished.disconnect(self._on_element_finished)
                except RuntimeError:
                    pass
                try:
                    element_host.failed.disconnect(self._on_element_failed)
                except RuntimeError:
                    pass
                element_host.stop()
            except Exception as exc:
                cleanup_errors.append(exc)
                logger.error("停止脚本元素拾取失败：%s", exc, exc_info=True)
            finally:
                element_host.deleteLater()

        try:
            self._restore_host_windows()
        except Exception as exc:
            cleanup_errors.append(exc)
            logger.error("恢复脚本编辑器窗口失败：%s", exc, exc_info=True)
        finally:
            try:
                self._bar.set_busy(False)
            except RuntimeError:
                pass

        if not restore_editor:
            try:
                self._dialog.hide()
            except RuntimeError:
                pass
            return
        if value is not None and kind:
            try:
                self._apply(kind, value)
            except Exception as exc:
                logger.error("写入采集结果失败: %s", exc, exc_info=True)
                error = error or f"写入失败: {exc}"
        if cleanup_errors:
            error = error or f"采集已取消，但资源清理失败：{cleanup_errors[0]}"
        if error:
            QMessageBox.warning(self._dialog, "采集", error)
        try:
            self._dialog.show()
            self._dialog.raise_()
            self._dialog.activateWindow()
            self._editor.setFocus()
        except RuntimeError:
            logger.debug("脚本编辑器已销毁，跳过焦点恢复")


def _restore_capture_windows(hider):
    try:
        hider.restore_all()
    finally:
        hider.clear()


class _ElementOverlay(QWidget):
    def __init__(self) -> None:
        super().__init__()
        try:
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
            manager = get_theme_manager()
            import weakref
            owner = weakref.ref(self)
            def callback(theme):
                overlay = owner()
                if overlay is not None:
                    overlay._on_theme_changed(theme)
            manager.register_theme_change_callback(callback)
            self.destroyed.connect(lambda _obj=None: manager.unregister_theme_change_callback(callback))
        except Exception:
            self.deleteLater()
            raise

    def _on_theme_changed(self, _theme=None) -> None:
        self.update()

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
            border_color=QColor(theme_color("picker_crosshair_inner")),
            border_width=3,
            fill_color=self._highlight_fill(),
        )

    @staticmethod
    def _highlight_fill() -> QColor:
        color = QColor(theme_color("picker_crosshair_inner"))
        color.setAlpha(30)
        return color


class _ScriptElementCapture(QObject):
    finished = Signal(object)
    highlight = Signal(object)
    failed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._active = False
        self._overlay: Optional[_ElementOverlay] = None
        self._thread: Optional[threading.Thread] = None
        self._emitted = False
        self._completion_lock = threading.Lock()
        self._cancel = threading.Event()
        self._confirm = threading.Event()
        self._cancel_timer = QTimer(self)
        self._cancel_timer.setInterval(20)
        self._cancel_timer.timeout.connect(self._poll_escape)
        self._resources = PanelResources()
        self._resources.bind_cleanup("element_cancel_timer", self._cancel_timer.stop)
        self._resources.bind_cleanup("element_cancel", self._cancel.set)
        self.destroyed.connect(self._resources.close)
        self.highlight.connect(self._set_highlight)

    def start(self) -> None:
        if self._thread is not None or self._emitted or self._cancel.is_set():
            raise ValueError("元素采集会话已经启动或结束")
        self._active = True
        try:
            overlay = _ElementOverlay()
            self._resources.own_widget(overlay)
            self._overlay = overlay
            overlay.installEventFilter(self)
            show_and_activate_overlay(overlay, log_prefix="脚本元素拾取覆盖层", focus=True)
            if not self._active or self._cancel.is_set():
                return
            self._cancel_timer.start()
            self._thread = threading.Thread(target=self._run_loop, name="lca-script-element-capture", daemon=True)
            own_background_thread(self._thread, self._cancel)
            self._thread.start()
        except Exception:
            if self._thread is not None:
                release_background_thread(self._thread)
            self.stop()
            self._resources.close_tools()
            raise

    def _run_loop(self):
        try:
            self._loop()
        finally:
            release_background_thread(threading.current_thread())

    def stop(self) -> None:
        with self._completion_lock:
            self._active = False
            self._cancel.set()
            self._emitted = True
        self.blockSignals(True)
        self._cancel_timer.stop()
        self._thread = None
        overlay = self._overlay
        self._overlay = None
        if overlay is not None:
            try:
                overlay.removeEventFilter(self)
                overlay.hide()
                overlay.close()
                overlay.deleteLater()
            except Exception:
                logger.debug("关闭元素拾取覆盖层失败", exc_info=True)

    def _emit(self, name: Optional[str]) -> None:
        with self._completion_lock:
            if self._emitted or self._cancel.is_set():
                return
            self._emitted = True
            self._active = False
            self._cancel.set()
        self.finished.emit(name)

    def _fail(self, message: str) -> None:
        with self._completion_lock:
            if self._emitted or self._cancel.is_set():
                return
            self._emitted = True
            self._active = False
            self._cancel.set()
        self.failed.emit(message)

    def eventFilter(self, watched, event):
        if watched is self._overlay:
            if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
                self._emit(None)
                return True
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.RightButton:
                self._confirm.set()
                return True
            if event.type() == QEvent.Type.Close and not getattr(watched, '_closing', False):
                self._emit(None)
        return super().eventFilter(watched, event)

    def _poll_escape(self):
        from .script_element_pick import escape_pressed
        if self._active and escape_pressed():
            self._emit(None)

    def _loop(self) -> None:
        from .script_element_pick import pick_element
        try:
            info = pick_element(self._confirm, self._cancel, self._publish_highlight)
            if info is None:
                self._emit(None)
                return
            selector = {name: value.strip() for name, value in (
                ("名称", info.name), ("自动化ID", info.automation_id), ("类名", info.class_name),
            )}
            if not any(selector.values()):
                raise ValueError("没有读到控件名称、自动化ID或类名")
            self._emit(selector)
        except Exception as error:
            logger.error("元素拾取失败: %s", error, exc_info=True)
            self._fail(f"元素拾取失败：{error}")

    def _publish_highlight(self, rect):
        if not self._cancel.is_set():
            self.highlight.emit(rect)

    def _set_highlight(self, rect) -> None:
        if self._overlay is not None:
            self._overlay.set_highlight(rect)


def _resolve_offset_base(line, hwnd, card_id, cancelled, progress):
    if cancelled.is_set():
        return None, None
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
            card_id=card_id,
        )
    except Exception as exc:
        raise ValueError(f"无法定位偏移基准图片：{exc}") from exc
    if not found or not location:
        raise ValueError("没有找到偏移基准图片，无法选偏移")
    left, top, width, height = location[:4]
    center = (int(left + width / 2), int(top + height / 2))
    return center, (int(left), int(top), int(width), int(height))


def resolve_script_capture_hwnd(dialog) -> Optional[int]:
    from utils.window.window_binding_utils import resolve_live_target_hwnd

    main_window = _main_window_of(dialog)
    return resolve_live_target_hwnd(main_window)


def _main_window_of(dialog):
    parent = dialog.parent() if dialog is not None else None
    if parent is not None:
        return parent
    return dialog.window() if dialog is not None else None


def _task_resource_dirs_of(dialog) -> dict:
    main_window = _main_window_of(dialog)
    if main_window is not None and hasattr(main_window, "_current_task_resource_dirs"):
        dirs = dict(main_window._current_task_resource_dirs())
    else:
        from task_workflow.resource_context import resource_dirs_from_mapping

        task = _current_capture_task(dialog)
        dirs = resource_dirs_from_mapping(task) if task is not None else {
            key: str(getattr(main_window, key, "") or "").strip()
            for key in ("images_dir", "sounds_dir", "dicts_dir", "yolo_dir", "replays_dir", "plugins_dir")
        }
        if task is None and not any(dirs.values()):
            return {}
    for key in ("images_dir", "sounds_dir"):
        if not str(dirs.get(key) or "").strip():
            raise ValueError("当前任务的图片或音频资源目录未绑定")
    return dirs


def _current_capture_task(dialog):
    main_window = _main_window_of(dialog)
    tab = getattr(main_window, "workflow_tab_widget", None)
    if tab is None:
        return None
    task_id = tab.get_current_task_id()
    if task_id is None:
        return None
    task = tab.task_manager.get_task(task_id)
    if task is None:
        raise ValueError("当前任务不存在")
    return task


def _sounds_dir_of(dialog) -> str:
    task = _current_capture_task(dialog)
    owner = task if task is not None else _main_window_of(dialog)
    directory = str(getattr(owner, "sounds_dir", "") or "").strip()
    if not directory:
        raise ValueError("音频资源目录未绑定")
    return directory


def _images_dir_of(dialog) -> str:
    task = _current_capture_task(dialog)
    owner = task if task is not None else _main_window_of(dialog)
    directory = str(getattr(owner, "images_dir", "") or "").strip()
    if not directory:
        raise ValueError("图片资源目录未绑定")
    return directory


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
    from app_core.config_store import load_config

    return str(load_config()["screenshot_format"])
