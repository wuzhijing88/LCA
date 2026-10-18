# -*- coding: utf-8 -*-
"""自定义脚本的独立编辑窗口，不走通用参数面板。"""

from __future__ import annotations

import logging
import re
import threading
from typing import Any, Callable, Dict, Optional

from PySide6.QtCore import QCoreApplication, QEvent, Qt, QTimer, QObject, QThread, Signal
from shiboken6 import isValid
from PySide6.QtGui import QFont, QFontMetrics, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from tasks.script_task import (
    DEFAULT_SCRIPT_SOURCE,
    SCRIPT_PLACEHOLDER,
    validate_script_source,
)
from ui.dialogs.script_capture import (
    ScriptCaptureBar,
    ScriptCaptureController,
    _task_resource_dirs_of,
    _workflow_token_of,
)
from ui.dialogs.script_code_edit import ScriptCodeEdit
from ui.dialogs.script_command_panel import ScriptCommandPanel, script_action_button_size
from ui.dialogs.script_param_bar import ScriptParamBar
from ui.dialogs.script_resource_panel import ScriptResourcePanel
from ui.dialogs.script_debug_panel import ScriptDebugPanel
from task_workflow.script_debug import ScriptDebugController
from utils.window.window_coordinate_common import (
    center_window_on_widget_screen,
    clamp_preferred_window_size,
    get_available_geometry_for_widget,
)

logger = logging.getLogger(__name__)
HELP_VISIBLE_SETTING = "script_editor/help_visible"
RESOURCE_VISIBLE_SETTING = "script_editor/resource_visible"
_ERROR_LINE_RE = re.compile(r"第\s*(\d+)\s*行")


# 已从对话框摘下、但仍在运行的调试线程。对话框关闭时若线程卡在阻塞调用里，
# 直接随对话框析构 QThread 会触发 "QThread: Destroyed while thread is still
# running" 的 qFatal。这里保留一份强引用，直到线程自己结束再丢弃，避免包装器
# 被 GC、PySide 连带删掉仍在运行的 QThread。
_ORPHAN_DEBUG_THREADS: set = set()
_ORPHAN_LOCK = threading.Lock()


def _discard_orphan_debug_thread(thread) -> None:
    # 仅从集合摘除引用：此刻线程刚发出 finished（deleteLater 尚未真正析构），
    # 但这里绝不调用可能已被销毁的包装器的方法，set.discard 只用其身份/哈希。
    with _ORPHAN_LOCK:
        _ORPHAN_DEBUG_THREADS.discard(thread)


def _drain_orphan_debug_threads() -> None:
    # 退出前必须等阻塞调用返回并完成收尾，不能超时后带着运行中的 QThread 析构。
    # 先处理仍挂在编辑器上的线程，退出信号各接收者的连接顺序不能决定是否漏收尾。
    for widget in QApplication.allWidgets():
        if isinstance(widget, ScriptEditorDialog) and isValid(widget) and getattr(widget, '_debug_thread', None) is not None:
            widget._shutdown_debug_thread()
    with _ORPHAN_LOCK:
        threads = list(_ORPHAN_DEBUG_THREADS)
    for thread in threads:
        if not isValid(thread):
            _discard_orphan_debug_thread(thread)
            continue
        try:
            thread._debug_controller.stop()
        except Exception:
            logger.exception("退出时请求脚本调试停止失败，继续等待线程收尾")
        thread.wait()
        _discard_orphan_debug_thread(thread)
        thread.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _ensure_debug_shutdown_hook():
    app = QCoreApplication.instance()
    if app is None:
        raise RuntimeError("托管脚本调试线程前必须创建应用程序")
    if not app.property("_lca_debug_orphan_exit_hook"):
        app.aboutToQuit.connect(_drain_orphan_debug_threads)
        app.setProperty("_lca_debug_orphan_exit_hook", True)


def _orphan_debug_thread(thread, controller) -> None:
    """登记一个仍在运行、已摘下的调试线程，保留强引用直到它结束。"""
    _ensure_debug_shutdown_hook()
    thread._debug_controller = controller
    with _ORPHAN_LOCK:
        _ORPHAN_DEBUG_THREADS.add(thread)
    # 线程结束时（直接的 finished 发射，早于 deleteLater 的延迟删除）摘除引用。
    thread.finished.connect(lambda t=thread: _discard_orphan_debug_thread(t))


class _DebugBridge(QObject):
    event = Signal(str, dict)


class _ScriptDebugWorker(QObject):
    finished = Signal(bool, str)

    def __init__(
        self,
        source: str,
        controller: ScriptDebugController,
        params: Optional[Dict[str, Any]] = None,
        run_context: Optional[Dict[str, Any]] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.source = source
        self.controller = controller
        self._params = dict(params or {})
        self._run_context = dict(run_context or {})
        from task_workflow.resource_context import current_package_session

        self._package_session = current_package_session()
        if "runtime_store" not in self._run_context:
            # 在调用方线程捕获上下文；调试 worker 运行在另一个线程，不能在那里
            # 再调用按线程绑定的 get_runtime_store()。
            try:
                from task_workflow.workflow_context import get_runtime_store

                self._run_context["runtime_store"] = get_runtime_store()
            except Exception as exc:
                raise RuntimeError(f"获取脚本调试运行上下文失败：{exc}") from exc

    def run(self):
        from task_workflow.runtime_store import RuntimeStore
        from task_workflow.script_sandbox import run_script
        from tasks.script_task import build_script_run_context

        ctx = self._run_context
        try:
            context = build_script_run_context(
                params=self._params,
                project_path=ctx.get("project_path"),
                source=self.source,
                counters={},
                execution_mode=ctx.get("execution_mode") or "foreground",
                target_hwnd=ctx.get("target_hwnd"),
                window_region=None,
                card_id=ctx.get("card_id"),
                images_dir=ctx.get("images_dir"),
                sounds_dir=ctx.get("sounds_dir"),
                dicts_dir=ctx.get("dicts_dir"),
                yolo_dir=ctx.get("yolo_dir"),
                replays_dir=ctx.get("replays_dir"),
                plugins_dir=ctx.get("plugins_dir"),
                debugger=self.controller,
                stop_checker=self.controller.stopped,
            )
            # 运行时存储由创建编辑器的工作流线程显式传入。调试线程不能直接调用
            # get_runtime_store()，因为该 API 按线程绑定上下文，会得到一个空的默认存储。
            # 副本中的写入不会污染正在运行的工作流状态。
            source_store = ctx.get("runtime_store")
            if source_store is None:
                # 独立编辑器没有正式运行存储时，使用明确的新空存储。
                debug_store = RuntimeStore()
            else:
                copy_for_debug = getattr(source_store, "copy_for_debug", None)
                if not callable(copy_for_debug):
                    raise RuntimeError("调试运行时存储不可用")
                debug_store = copy_for_debug()
        except Exception as exc:
            # 构建上下文阶段就失败：run_script 尚未接管调试器生命周期，这里补一次 finish。
            self.controller.finish(False, str(exc))
            self.finished.emit(False, str(exc))
            return
        # 进入 run_script 之前若已被停止（用户抢先按了停止/关闭），不再运行脚本，
        # 避免真实输入在停止之后才被发出。
        if self.controller.stopped():
            self.controller.finish(False, "已停止")
            self.finished.emit(False, "已停止")
            return
        try:
            from task_workflow.resource_context import workflow_resource_scope

            with workflow_resource_scope(
                {key: context.get(key) or "" for key in
                 ("images_dir", "sounds_dir", "dicts_dir", "yolo_dir", "replays_dir", "plugins_dir")},
                package_session=self._package_session,
            ):
                ok, detail = run_script(self.source, debug_store, logger, context=context)
        except Exception as exc:
            # run_script 的 finally 已调用 controller.finish，这里只回传 Qt 信号，不重复 finish。
            self.finished.emit(False, str(exc))
            return
        self.finished.emit(bool(ok), str(detail or ""))


def _load_help_visible() -> bool:
    try:
        from utils.instance_runtime import create_app_settings

        return bool(create_app_settings().value(HELP_VISIBLE_SETTING, True, type=bool))
    except Exception:
        return True


def _save_help_visible(visible: bool) -> None:
    try:
        from utils.instance_runtime import create_app_settings

        create_app_settings().setValue(HELP_VISIBLE_SETTING, bool(visible))
    except Exception:
        logger.debug("保存命令列表显示状态失败", exc_info=True)


def _load_resource_visible() -> bool:
    try:
        from utils.instance_runtime import create_app_settings

        return bool(create_app_settings().value(RESOURCE_VISIBLE_SETTING, True, type=bool))
    except Exception:
        return True


def _save_resource_visible(visible: bool) -> None:
    try:
        from utils.instance_runtime import create_app_settings

        create_app_settings().setValue(RESOURCE_VISIBLE_SETTING, bool(visible))
    except Exception:
        logger.debug("保存资源栏显示状态失败", exc_info=True)


def _load_debug_visible() -> bool:
    # 调试只给需要排查问题时使用，每次打开编辑器默认关闭，避免占用编辑区。
    return False


class ScriptEditorDialog(QDialog):
    """大编辑区 + 命令列表，应用前做语法检查。"""

    def __init__(
        self,
        card_id: int,
        source: str = "",
        custom_name: Optional[str] = None,
        on_applied: Optional[Callable[[str], None]] = None,
        debug_context_provider: Optional[Callable[[], dict]] = None,
        parent=None,
        environment=None,
    ):
        super().__init__(parent)
        self._card_id = card_id
        self._initial_source = source if source else DEFAULT_SCRIPT_SOURCE
        self._saved_source = self._initial_source
        self._applied_source: Optional[str] = None
        self._on_applied = on_applied
        self._debug_context_provider = debug_context_provider
        from app_core.script_environments import normalize_environment

        self._environment = normalize_environment(environment)
        self._saved_environment = dict(self._environment)
        self._find_message = ""
        self._custom_name = str(custom_name or "").strip() or None
        self._help_visible = _load_help_visible()
        self._resource_visible = _load_resource_visible()
        self._debug_visible = _load_debug_visible()
        self._syntax_ok = True
        self._syntax_text = ""
        self._leave_confirmed = False
        self._debugger = ScriptDebugController()
        self._debug_bridge = _DebugBridge(self)
        self._debug_bridge.event.connect(self._on_debug_event)
        self._debugger.set_callback(lambda event, payload: self._debug_bridge.event.emit(event, payload))
        self._debug_thread = None
        self._debug_worker = None
        self._build_ui()
        self.editor.setPlainText(self._initial_source)
        self._refresh_syntax_status()
        self._refresh_resources()
        self._register_theme_callback()

    def _on_debug_event(self, event: str, payload: dict) -> None:
        panel = getattr(self, "_debug_panel", None)
        if panel is not None:
            panel.update_event(event, payload)
            if event == "breakpoint" and payload.get("line") is not None:
                current_line = int(self.editor.textCursor().blockNumber()) + 1
                if int(payload.get("line")) == current_line:
                    panel.set_breakpoint_state(bool(payload.get("enabled")))
        line = payload.get("line") if isinstance(payload, dict) else None
        if event == "line" and line:
            # 逐行只移动执行标记并合并重绘，不抢焦点、不居中，避免高频事件刷屏。
            self.editor.set_execution_line(int(line))
        elif event == "break" and line:
            self.editor.set_execution_line(int(line))
            self.editor.goto_line(int(line))
        elif event in {"finished", "stopped"}:
            self.editor.set_execution_line(None)
        if event in {"breakpoint", "breakpoints"}:
            self.editor.refresh_line_number_area()

    def _on_editor_breakpoints_changed(self, lines) -> None:
        # 编辑器块标记是断点唯一真源；每次变化把整份行号原子推给控制器。
        self._debugger.replace_breakpoints(set(lines))
        self.editor.refresh_line_number_area()
        self._sync_debug_breakpoint_button()

    def applied_source(self) -> str:
        if self._applied_source is None:
            return self.editor.toPlainText()
        return self._applied_source

    def current_source(self) -> str:
        return self.editor.toPlainText()

    def is_dirty(self) -> bool:
        return (self.editor.toPlainText() != self._saved_source
                or self.environment_settings() != self._saved_environment)

    def environment_settings(self):
        return dict(self._environment)

    def _configure_environment(self):
        from ui.dialogs.script_environment_dialog import ScriptEnvironmentDialog

        dialog = ScriptEnvironmentDialog(self._environment, self)
        try:
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self._environment = dialog.settings()
                self._refresh_syntax_status()
        finally:
            dialog.deleteLater()

    def reload_source(self, source: str) -> None:
        text = str(source or "")
        if text == self.editor.toPlainText():
            self._saved_source = text
            return
        if self.is_dirty():
            choice = QMessageBox.question(
                self,
                "脚本已改",
                "卡片上的内容变了，但窗口里还有没应用的修改。用卡片上的覆盖这里吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if choice != QMessageBox.StandardButton.Yes:
                return
        self.editor.replace_document_text(text)
        self._initial_source = text
        self._saved_source = text
        self._refresh_syntax_status()
        self._refresh_resources()

    def _build_ui(self) -> None:
        title_name = self._custom_name or "自定义脚本"
        self.setObjectName("scriptEditorDialog")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setWindowTitle(f"{title_name}（编号 {self._card_id}）")
        self.setMinimumSize(900, 560)
        available_geometry = get_available_geometry_for_widget(self.parentWidget() or self)
        preferred_width = 1240 if self._help_visible else 920
        width, height = clamp_preferred_window_size(preferred_width, 780, available_geometry)
        self.resize(width, height)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(12)
        help_panel = self._build_help_panel()
        body.addWidget(self._build_editor_column(), 3)
        body.addWidget(help_panel, 2)
        layout.addLayout(body, 1)
        layout.addLayout(self._build_footer())
        self._apply_help_visible(self._help_visible, persist=False)
        self._bind_shortcuts()
        center_window_on_widget_screen(self, self.parentWidget())

    def _register_theme_callback(self) -> None:
        import weakref
        from themes import get_theme_manager

        manager = get_theme_manager()
        owner = weakref.ref(self)

        def changed(theme) -> None:
            dialog = owner()
            if dialog is not None:
                dialog._on_theme_changed(theme)

        manager.register_theme_change_callback(changed)
        self.destroyed.connect(lambda _=None: manager.unregister_theme_change_callback(changed))

    def _on_theme_changed(self, _theme=None) -> None:
        widgets = [self, *self.findChildren(QWidget)]
        style = self.style()
        for widget in widgets:
            style.unpolish(widget)
            style.polish(widget)
            widget.update()
        self._sync_minimum_size()
        self._set_status(self.status_label.text(), ok=self._syntax_ok)

    def _sync_minimum_size(self) -> None:
        self.layout().invalidate()
        minimum = self.layout().minimumSize()
        self.setMinimumSize(max(900, minimum.width()), max(560, minimum.height()))

    def _build_editor_column(self) -> QWidget:
        column = QWidget()
        column.setObjectName("scriptEditorColumn")
        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        capture = ScriptCaptureBar()
        layout.addWidget(capture)
        layout.addWidget(self._build_find_bar())
        editor = self._build_editor()
        debug_panel = ScriptDebugPanel(editor)
        debug_panel.start_requested.connect(self._start_debug_run)
        debug_panel.pause_requested.connect(self._debugger.pause)
        debug_panel.continue_requested.connect(self._debugger.continue_run)
        debug_panel.step_requested.connect(self._debugger.step)
        debug_panel.stop_requested.connect(self._debugger.stop)
        debug_panel.breakpoint_requested.connect(self._toggle_debug_breakpoint)
        debug_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        debug_panel.setFixedWidth(360)
        debug_panel.setVisible(False)
        editor_host = QWidget()
        editor_host.setObjectName("scriptEditorWorkspace")
        editor_layout = QGridLayout(editor_host)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(0)
        editor_layout.addWidget(editor, 0, 0)
        debug_toggle = QPushButton("调\n试\n›")
        debug_toggle.setObjectName("scriptDebugToggle")
        debug_toggle.setCheckable(True)
        debug_toggle.setToolTip("在编辑框右侧展开或收起调试工具")
        debug_toggle.setFixedWidth(28)
        debug_toggle.setMinimumHeight(72)
        debug_toggle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        debug_toggle.toggled.connect(lambda visible: self._set_debug_visible(visible))
        editor_layout.addWidget(debug_toggle, 0, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        editor_layout.addWidget(debug_panel, 0, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        debug_toggle.raise_()
        self._debug_toggle = debug_toggle
        layout.addWidget(editor_host, 1)
        param_bar = ScriptParamBar()
        param_bar.bind_editor(self.editor)
        layout.addWidget(param_bar)
        self._param_bar = param_bar
        resources = ScriptResourcePanel()
        self._bind_resource_panel(resources)
        resources.insert_requested.connect(self._insert_resource)
        resources.locate_requested.connect(self._locate_resource)
        resources.source_rewrite_requested.connect(self._rewrite_source)
        layout.addWidget(resources)
        self._capture_bar = capture
        self._resource_panel = resources
        self._debug_panel = debug_panel
        self.editor.breakpoints_changed.connect(self._on_editor_breakpoints_changed)
        self.editor.breakpoint_toggle_requested.connect(self._toggle_debug_breakpoint)
        self.editor.cursorPositionChanged.connect(self._sync_debug_breakpoint_button)
        self._capture = ScriptCaptureController(self, self.editor, capture)
        capture.find_requested.connect(self._show_find_bar)
        capture.resources_toggled.connect(self._set_resources_visible)
        capture.environment_requested.connect(self._configure_environment)
        self._resource_timer = QTimer(self)
        self._resource_timer.setSingleShot(True)
        self._resource_timer.setInterval(200)
        self._resource_timer.timeout.connect(self._refresh_resources)
        self.editor.textChanged.connect(self._resource_timer.start)
        self._apply_resources_visible(self._resource_visible, persist=False)
        self._set_debug_visible(self._debug_visible)
        return column

    def _set_debug_visible(self, visible: bool) -> None:
        self._apply_debug_visible(visible)

    def _apply_debug_visible(self, visible: bool) -> None:
        self._debug_visible = bool(visible)
        panel = getattr(self, "_debug_panel", None)
        if panel is not None:
            panel.setVisible(self._debug_visible)
        toggle = getattr(self, "_debug_toggle", None)
        if toggle is not None:
            toggle.blockSignals(True)
            toggle.setChecked(self._debug_visible)
            toggle.setText("调\n试\n‹" if self._debug_visible else "调\n试\n›")
            toggle.blockSignals(False)
        # 不持久化调试栏状态：调试结束后重新打开编辑器应保持紧凑布局。

    def _toggle_debug_breakpoint(self, line: int) -> None:
        # 断点按钮与行号区点击都走这里：切换编辑器块标记，其 breakpoints_changed
        # 会把整份断点推给控制器。
        enabled = self.editor.toggle_breakpoint(int(line))
        self._debug_panel.set_breakpoint_state(enabled)
        self.editor.refresh_line_number_area()

    def _sync_debug_breakpoint_button(self) -> None:
        panel = getattr(self, "_debug_panel", None)
        if panel is None:
            return
        line = int(self.editor.textCursor().blockNumber()) + 1
        panel.set_breakpoint_state(line in self.editor.breakpoint_lines())

    def _start_debug_run(self) -> None:
        if self._debug_thread is not None and self._debug_thread.isRunning():
            return
        source = self._normalize_editor_source()
        try:
            validate_script_source(source)
        except Exception as exc:
            self._syntax_ok = False; self._syntax_text = str(exc); self._refresh_status_bar(); self._jump_error_line(str(exc)); return
        # 先清理上次状态，再启动控制器；否则 started 事件会被 clear() 立刻覆盖，
        # 导致暂停/继续/停止按钮看起来像没有反应。
        self._debug_panel.clear()
        self._debugger.start()
        params = {"script_source": source, "script_environment": self.environment_settings()}
        run_context: Dict[str, Any] = {}
        provider = self._debug_context_provider
        if callable(provider):
            try:
                provided_context = provider()
                if not isinstance(provided_context, dict):
                    raise TypeError("脚本调试运行上下文必须是字典")
                run_context = dict(provided_context)
            except Exception as exc:
                logger.exception("获取调试运行上下文失败")
                self._debugger.stop()
                self._set_status(f"无法启动调试：{exc}", ok=False)
                return
        try:
            worker = _ScriptDebugWorker(source, self._debugger, params, run_context)
        except Exception as exc:
            logger.exception("创建脚本调试工作对象失败")
            self._debugger.stop()
            self._set_status(f"无法启动调试：{exc}", ok=False)
            return
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._debug_finished)
        worker.finished.connect(thread.quit, Qt.ConnectionType.DirectConnection)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._debug_thread_done)
        thread.finished.connect(thread.deleteLater)
        self._debug_thread, self._debug_worker = thread, worker
        self._set_status(
            self._status_text("调试运行使用运行时存储的副本：可读取上次运行的卡片结果，写入不会影响正式运行"),
            ok=True,
        )
        _ensure_debug_shutdown_hook()
        thread.start()

    def _debug_finished(self, ok: bool, detail: str) -> None:
        text = "调试完成" if ok else (f"调试失败：{detail}" if detail else "调试失败")
        self._set_status(self._status_text(text), ok=bool(ok))

    def _debug_thread_done(self) -> None:
        # 该回调是排队投递的：投递到执行之间可能又启动了更新一轮调试运行。只有当
        # 发出 finished 的线程仍是当前持有的线程时才清空引用，否则会把新一轮运行的
        # 线程引用误删，导致 _shutdown_debug_thread 变成空操作、对话框带着活线程销毁。
        if self.sender() is self._debug_thread:
            self._debug_thread = None
            self._debug_worker = None

    def _build_find_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("scriptFindBar")
        bar.setVisible(False)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        label = QLabel("查找")
        layout.addWidget(label)
        field = QLineEdit()
        field.setObjectName("scriptFindInput")
        field.setPlaceholderText("在当前脚本中查找")
        field.returnPressed.connect(lambda: self._find_in_editor(False))
        layout.addWidget(field, 1)
        case_box = QCheckBox("区分大小写")
        case_box.setObjectName("scriptFindCase")
        case_box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        layout.addWidget(case_box)
        next_btn = QPushButton("下一个")
        next_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        next_btn.clicked.connect(lambda: self._find_in_editor(False))
        layout.addWidget(next_btn)
        prev_btn = QPushButton("上一个")
        prev_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        prev_btn.clicked.connect(lambda: self._find_in_editor(True))
        layout.addWidget(prev_btn)
        close_btn = QPushButton("关闭")
        close_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        close_btn.clicked.connect(self._hide_find_bar)
        layout.addWidget(close_btn)
        self._find_bar = bar
        self._find_input = field
        self._find_case = case_box
        return bar

    def _build_editor(self) -> ScriptCodeEdit:
        editor = ScriptCodeEdit()
        editor.setPlaceholderText(SCRIPT_PLACEHOLDER)
        editor.setLineWrapMode(ScriptCodeEdit.LineWrapMode.NoWrap)
        editor.setTabChangesFocus(False)
        font = QFont("Consolas")
        if not font.exactMatch():
            font = QFont("Cascadia Mono")
        if not font.exactMatch():
            font = QFont("Courier New")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(11)
        editor.setFont(font)
        editor.setTabStopDistance(4 * QFontMetrics(font).horizontalAdvance(" "))
        editor.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._syntax_timer = QTimer(self)
        self._syntax_timer.setSingleShot(True)
        self._syntax_timer.setInterval(250)
        self._syntax_timer.timeout.connect(self._refresh_syntax_status)
        editor.textChanged.connect(self._syntax_timer.start)
        editor.cursorPositionChanged.connect(self._refresh_status_bar)
        self.editor = editor
        return editor

    def _build_help_panel(self) -> QWidget:
        panel = ScriptCommandPanel(self._insert_command)
        panel.can_insert_changed.connect(self._sync_insert_enabled)
        self._help_panel = panel
        return panel

    def _make_action_button(self, text: str, object_name: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName(object_name)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setAutoDefault(False)
        button.setDefault(False)
        button.setFixedSize(*script_action_button_size(self))
        return button

    def _build_footer(self) -> QHBoxLayout:
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(8)
        footer.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.status_label = QLabel()
        self.status_label.setObjectName("scriptEditorStatus")
        self.status_label.setWordWrap(True)
        self.status_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.status_label.mousePressEvent = self._on_status_clicked  # type: ignore[method-assign]
        footer.addWidget(self.status_label, 1)

        insert_btn = self._make_action_button("插入", "scriptActionButton")
        insert_btn.clicked.connect(self._help_panel.insert_current)
        self._insert_btn = insert_btn
        footer.addWidget(insert_btn)

        toggle = self._make_action_button("显示命令", "scriptActionButton")
        toggle.clicked.connect(self._toggle_help)
        self._help_toggle = toggle
        footer.addWidget(toggle)

        apply_btn = self._make_action_button("应用", "scriptActionButton")
        apply_btn.setProperty("primary", True)
        apply_btn.clicked.connect(self._on_apply_and_close)
        footer.addWidget(apply_btn)

        reset_btn = self._make_action_button("重置", "scriptActionButton")
        reset_btn.clicked.connect(self._on_reset)
        self._reset_btn = reset_btn
        footer.addWidget(reset_btn)

        return footer

    def _bind_shortcuts(self) -> None:
        find_shortcut = QShortcut(QKeySequence.StandardKey.Find, self)
        find_shortcut.activated.connect(self._show_find_bar)
        save_shortcut = QShortcut(QKeySequence.StandardKey.Save, self)
        save_shortcut.activated.connect(lambda: self._on_apply())
        find_next = QShortcut(QKeySequence.StandardKey.FindNext, self)
        find_next.activated.connect(lambda: self._find_in_editor(False))
        find_prev = QShortcut(QKeySequence.StandardKey.FindPrevious, self)
        find_prev.activated.connect(lambda: self._find_in_editor(True))

    def _show_find_bar(self) -> None:
        self._find_bar.setVisible(True)
        self._find_input.setFocus()
        self._find_input.selectAll()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape and self._find_bar.isVisible():
            self._hide_find_bar()
            return
        super().keyPressEvent(event)

    def _hide_find_bar(self) -> None:
        if self._find_bar.isVisible():
            self._find_bar.setVisible(False)
            self.editor.setFocus()

    def _find_in_editor(self, backward: bool) -> None:
        query = self._find_input.text()
        case = bool(getattr(self, "_find_case", None) and self._find_case.isChecked())
        if not self.editor.find_text(query, backward=backward, case_sensitive=case) and query:
            self._find_message = f"未找到：{query}"
            self._refresh_status_bar()
            QTimer.singleShot(2500, self._clear_find_message)
        else:
            self._clear_find_message()

    def _clear_find_message(self) -> None:
        if not self._find_message:
            return
        self._find_message = ""
        self._refresh_status_bar()

    def _insert_command(self, item: Dict[str, Any]) -> None:
        if not item:
            return
        self.editor.insert_command(item)
        self._refresh_syntax_status()

    def _set_resources_visible(self, visible: bool) -> None:
        self._apply_resources_visible(visible, persist=True)

    def _apply_resources_visible(self, visible: bool, persist: bool) -> None:
        self._resource_visible = bool(visible)
        self._resource_panel.setVisible(self._resource_visible)
        self._capture_bar.set_resources_visible(self._resource_visible)
        if persist:
            _save_resource_visible(self._resource_visible)

    def _bind_resource_panel(self, panel=None) -> None:
        target = panel if panel is not None else getattr(self, "_resource_panel", None)
        if target is None:
            return
        try:
            dirs = _task_resource_dirs_of(self)
        except ValueError as exc:
            target.bind()
            target.set_binding_error(str(exc))
            return
        target.set_binding_error("")
        target.bind(
            dirs.get("images_dir") or "",
            self._card_id,
            _workflow_token_of(self),
            dirs.get("sounds_dir") or "",
            dicts_dir=dirs.get("dicts_dir") or "",
            yolo_dir=dirs.get("yolo_dir") or "",
            replays_dir=dirs.get("replays_dir") or "",
            plugins_dir=dirs.get("plugins_dir") or "",
        )

    def _refresh_resources(self) -> None:
        panel = getattr(self, "_resource_panel", None)
        if panel is None:
            return
        self._bind_resource_panel(panel)
        panel.set_source(self.editor.toPlainText())

    def _insert_resource(self, item: Dict[str, Any]) -> None:
        from ui.dialogs.script_resources import plan_insert_resource

        cursor = self.editor.textCursor()
        block = cursor.block()
        block_pos = block.position()
        same_line = (
            cursor.selectionStart() >= block_pos
            and cursor.selectionEnd() <= block_pos + len(block.text())
        )
        selected = bool(cursor.hasSelection() and same_line)
        plan = plan_insert_resource(
            self.editor.toPlainText(),
            cursor.blockNumber(),
            item or {},
            cursor.positionInBlock(),
            (cursor.selectionStart() - block_pos) if selected else None,
            (cursor.selectionEnd() - block_pos) if selected else None,
        )
        self.editor.apply_edit_plan(plan)
        self._refresh_syntax_status()
        self._refresh_resources()

    def _locate_resource(self, item: Dict[str, Any]) -> None:
        spans = list((item or {}).get("spans") or [])
        if not spans:
            return
        start, end = spans[0]
        self.editor.select_document_span(start, end)

    def _rewrite_source(self, source: str) -> None:
        self.editor.replace_document_text(str(source or ""))
        self._refresh_syntax_status()
        self._refresh_resources()

    def _toggle_help(self) -> None:
        self._set_help_visible(not self._help_visible)

    def _set_help_visible(self, visible: bool) -> None:
        self._apply_help_visible(visible, persist=True)

    def _apply_help_visible(self, visible: bool, persist: bool) -> None:
        self._help_visible = bool(visible)
        self._help_panel.setVisible(self._help_visible)
        self._help_toggle.setText("隐藏命令" if self._help_visible else "显示命令")
        self._sync_insert_enabled()
        self._sync_minimum_size()
        if persist:
            _save_help_visible(self._help_visible)

    def _sync_insert_enabled(self, *_args) -> None:
        can_insert = self._help_visible and self._help_panel.has_selection()
        self._insert_btn.setEnabled(can_insert)

    def _refresh_syntax_status(self) -> None:
        source = self.editor.toPlainText()
        if not source.strip():
            self._syntax_ok = False
            self._syntax_text = "内容为空，运行时会失败。"
            self._refresh_status_bar()
            return
        try:
            validate_script_source(source)
            from app_core.script_environments import normalize_environment

            self._environment = normalize_environment(self.environment_settings())
        except Exception as exc:
            self._syntax_ok = False
            self._syntax_text = str(exc)
            self._refresh_status_bar()
            return
        self._syntax_ok = True
        self._syntax_text = "语法通过。"
        try:
            from task_workflow.script_sandbox import script_warnings

            warnings = script_warnings(source)
        except Exception:
            warnings = []
        if warnings:
            self._syntax_text = f"语法通过。{' '.join(warnings[:2])}"
        self._refresh_status_bar()

    def _refresh_status_bar(self) -> None:
        message = self._find_message or self._syntax_text
        ok = self._syntax_ok and not self._find_message
        extra = "  未应用" if self.is_dirty() else ""
        self._set_status(self._status_text(message) + extra, ok=ok)

    def _status_text(self, message: str) -> str:
        line, column = self.editor.cursor_location()
        return f"行 {line}  列 {column}    {message}"

    def _error_line(self, text: str) -> Optional[int]:
        match = _ERROR_LINE_RE.search(str(text or ""))
        return int(match.group(1)) if match else None

    def _jump_error_line(self, text: str) -> None:
        line = self._error_line(text)
        if line:
            self.editor.goto_line(line)

    def _on_status_clicked(self, event) -> None:
        if not self._syntax_ok:
            self._jump_error_line(self.status_label.text())
        if event is not None:
            event.accept()

    def _set_status(self, text: str, ok: bool) -> None:
        self.status_label.setText(text)
        self.status_label.setProperty("state", "ok" if ok else "error")
        style = self.status_label.style()
        style.unpolish(self.status_label)
        style.polish(self.status_label)

    def _on_reset(self) -> None:
        if self.editor.toPlainText() != DEFAULT_SCRIPT_SOURCE:
            choice = QMessageBox.question(
                self,
                "重置脚本",
                "用默认模板覆盖当前内容？可用撤销找回。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if choice != QMessageBox.StandardButton.Yes:
                return
        self.editor.replace_document_text(DEFAULT_SCRIPT_SOURCE)
        self.editor.setFocus()
        self._refresh_syntax_status()

    def _normalize_editor_source(self) -> str:
        from task_workflow.script_sandbox import normalize_script_punctuation

        source = normalize_script_punctuation(self.editor.toPlainText())
        if source != self.editor.toPlainText():
            cursor = self.editor.textCursor()
            position = cursor.position()
            cursor.beginEditBlock()
            cursor.select(cursor.SelectionType.Document)
            cursor.insertText(source)
            cursor.endEditBlock()
            cursor.setPosition(min(position, len(source)))
            self.editor.setTextCursor(cursor)
        return source

    def _on_apply(self) -> bool:
        source = self._normalize_editor_source()
        if not source.strip():
            self._syntax_ok = False
            self._syntax_text = "内容为空，运行时会失败。"
            self._refresh_status_bar()
            QMessageBox.warning(self, "语法检查", "内容为空，不能应用。")
            return False
        try:
            validate_script_source(source)
            from app_core.script_environments import normalize_environment

            self._environment = normalize_environment(self.environment_settings())
        except Exception as exc:
            self._syntax_ok = False
            self._syntax_text = str(exc)
            self._refresh_status_bar()
            QMessageBox.warning(self, "语法检查", str(exc))
            self._jump_error_line(str(exc))
            return False
        self._applied_source = source
        self._saved_source = source
        self._saved_environment = dict(self._environment)
        logger.info("自定义脚本已应用: 卡片=%s, 长度=%s", self._card_id, len(source))
        if callable(self._on_applied):
            self._on_applied(source)
        self._syntax_ok = True
        self._syntax_text = "已同步到卡片。"
        self._refresh_syntax_status()
        if self._syntax_ok:
            self._syntax_text = "已同步到卡片。"
            self._refresh_status_bar()
        return True

    def _on_apply_and_close(self) -> None:
        if self._on_apply():
            self.accept()

    def _confirm_leave(self) -> bool:
        if self._leave_confirmed:
            return True
        if not self.is_dirty():
            self._leave_confirmed = True
            return True
        box = QMessageBox(self)
        box.setWindowTitle("脚本未应用")
        box.setText("有改动还没应用到卡片。")
        apply_btn = box.addButton("应用并关闭", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("不保存", QMessageBox.ButtonRole.DestructiveRole)
        cancel_btn = box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(apply_btn)
        box.exec()
        clicked = box.clickedButton()
        if clicked is cancel_btn:
            return False
        if clicked is apply_btn:
            if not self._on_apply():
                return False
        self._leave_confirmed = True
        return True

    def reject(self) -> None:
        if not self._confirm_leave():
            return
        super().reject()

    def done(self, result: int) -> None:
        # accept() 和 reject() 都经由 done()；关闭前先安全停下调试线程。
        self._shutdown_debug_thread()
        super().done(result)

    def _shutdown_debug_thread(self) -> None:
        thread = self._debug_thread
        worker = self._debug_worker
        if thread is None:
            try:
                self._debugger.set_callback(None)
            except Exception:
                pass
            return
        if thread.isRunning():
            self._debugger.stop()
            # 关闭流程开始后不再把事件投递到即将销毁的编辑器；线程仍会由
            # stop_checker/host.close 完成自己的资源收尾。
            try:
                self._debugger.set_callback(None)
            except Exception:
                pass
            thread.quit()
            thread.wait(1500)
            if thread.isRunning():
                # 线程还卡在阻塞调用里：从对话框上摘下来，避免对话框销毁时连带析构
                # 仍在运行的 QThread 触发 qFatal。setParent(None) 把 C++ 所有权交还
                # Python，因此必须在别处保留强引用直到线程结束，否则包装器被 GC、
                # PySide 会删掉仍在运行的 QThread。
                thread.setParent(None)
                try:
                    if worker is not None:
                        worker.finished.disconnect(self._debug_finished)
                except (RuntimeError, TypeError):
                    pass
                try:
                    thread.finished.disconnect(self._debug_thread_done)
                except (RuntimeError, TypeError):
                    pass
                # 登记为孤儿线程，保留强引用直到它结束；保留 thread.finished→
                # deleteLater、worker.finished→(quit, deleteLater)，让线程自行清理。
                _orphan_debug_thread(thread, self._debugger)
        else:
            try:
                self._debugger.set_callback(None)
            except Exception:
                pass
        self._debug_thread = None
        self._debug_worker = None

    def closeEvent(self, event) -> None:
        if not self._confirm_leave():
            event.ignore()
            return
        self._shutdown_debug_thread()
        super().closeEvent(event)

    def event(self, event) -> bool:
        if event.type() == QEvent.Type.DeferredDelete:
            self._shutdown_debug_thread()
            param_bar = getattr(self, "_param_bar", None)
            if param_bar is not None:
                param_bar.bind_editor(None)
            for name in ("_resource_timer", "_syntax_timer"):
                timer = getattr(self, name, None)
                if timer is not None:
                    timer.stop()
        return super().event(event)
