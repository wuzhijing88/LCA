# -*- coding: utf-8 -*-
"""自定义脚本的独立编辑窗口，不走通用参数面板。"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable, Dict, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QFontMetrics, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
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
from ui.dialogs.script_capture import ScriptCaptureBar, ScriptCaptureController, _images_dir_of, _workflow_token_of
from ui.dialogs.script_code_edit import ScriptCodeEdit
from ui.dialogs.script_command_panel import ScriptCommandPanel, script_action_button_size
from ui.dialogs.script_param_bar import ScriptParamBar
from ui.dialogs.script_resource_panel import ScriptResourcePanel
from utils.window.window_coordinate_common import (
    center_window_on_widget_screen,
    clamp_preferred_window_size,
    get_available_geometry_for_widget,
)

logger = logging.getLogger(__name__)
HELP_VISIBLE_SETTING = "script_editor/help_visible"
RESOURCE_VISIBLE_SETTING = "script_editor/resource_visible"
_ERROR_LINE_RE = re.compile(r"第\s*(\d+)\s*行")


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


class ScriptEditorDialog(QDialog):
    """大编辑区 + 命令列表，应用前做语法检查。"""

    def __init__(
        self,
        card_id: int,
        source: str = "",
        custom_name: Optional[str] = None,
        on_applied: Optional[Callable[[str], None]] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._card_id = card_id
        self._initial_source = source if source else DEFAULT_SCRIPT_SOURCE
        self._saved_source = self._initial_source
        self._applied_source: Optional[str] = None
        self._on_applied = on_applied
        self._find_message = ""
        self._custom_name = str(custom_name or "").strip() or None
        self._help_visible = _load_help_visible()
        self._resource_visible = _load_resource_visible()
        self._syntax_ok = True
        self._syntax_text = ""
        self._leave_confirmed = False
        self._build_ui()
        self.editor.setPlainText(self._initial_source)
        self._refresh_syntax_status()
        self._refresh_resources()
        self._register_theme_callback()

    def applied_source(self) -> str:
        if self._applied_source is None:
            return self.editor.toPlainText()
        return self._applied_source

    def current_source(self) -> str:
        return self.editor.toPlainText()

    def is_dirty(self) -> bool:
        return self.editor.toPlainText() != self._saved_source

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
        self.editor.setPlainText(text)
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
        body.addWidget(self._build_editor_column(), 3)
        help_panel = self._build_help_panel()
        body.addWidget(help_panel, 2)
        layout.addLayout(body, 1)
        layout.addLayout(self._build_footer())
        self._apply_help_visible(self._help_visible, persist=False)
        self._bind_shortcuts()
        center_window_on_widget_screen(self, self.parentWidget())

    def _register_theme_callback(self) -> None:
        try:
            from themes import get_theme_manager

            get_theme_manager().register_theme_change_callback(self._on_theme_changed)
        except Exception:
            return

        def _forget(_=None, callback=self._on_theme_changed) -> None:
            try:
                from themes import get_theme_manager

                get_theme_manager().unregister_theme_change_callback(callback)
            except Exception:
                pass

        self.destroyed.connect(_forget)

    def _on_theme_changed(self, _theme=None) -> None:
        widgets = [self, *self.findChildren(QWidget)]
        style = self.style()
        for widget in widgets:
            style.unpolish(widget)
            style.polish(widget)
            widget.update()
        self._set_status(self.status_label.text(), ok=self._syntax_ok)

    def _build_editor_column(self) -> QWidget:
        column = QWidget()
        column.setObjectName("scriptEditorColumn")
        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        capture = ScriptCaptureBar()
        layout.addWidget(capture)
        layout.addWidget(self._build_find_bar())
        layout.addWidget(self._build_editor(), 1)
        param_bar = ScriptParamBar()
        param_bar.bind_editor(self.editor)
        layout.addWidget(param_bar)
        resources = ScriptResourcePanel()
        resources.bind(_images_dir_of(self), self._card_id, _workflow_token_of(self))
        resources.insert_requested.connect(self._insert_resource)
        resources.locate_requested.connect(self._locate_resource)
        resources.source_rewrite_requested.connect(self._rewrite_source)
        layout.addWidget(resources)
        self._capture_bar = capture
        self._param_bar = param_bar
        self._resource_panel = resources
        self._capture = ScriptCaptureController(self, self.editor, capture)
        capture.find_requested.connect(self._show_find_bar)
        capture.resources_toggled.connect(self._set_resources_visible)
        self._resource_timer = QTimer(self)
        self._resource_timer.setSingleShot(True)
        self._resource_timer.setInterval(200)
        self._resource_timer.timeout.connect(self._refresh_resources)
        self.editor.textChanged.connect(self._resource_timer.start)
        self._apply_resources_visible(self._resource_visible, persist=False)
        return column

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

    def _refresh_resources(self) -> None:
        panel = getattr(self, "_resource_panel", None)
        if panel is None:
            return
        panel.bind(_images_dir_of(self), self._card_id, _workflow_token_of(self))
        panel.set_source(self.editor.toPlainText())

    def _insert_resource(self, item: Dict[str, Any]) -> None:
        from ui.dialogs.script_resources import plan_insert_resource

        cursor = self.editor.textCursor()
        plan = plan_insert_resource(
            self.editor.toPlainText(),
            cursor.blockNumber(),
            item or {},
            cursor.positionInBlock(),
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
        self.editor.setPlainText(DEFAULT_SCRIPT_SOURCE)
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
        except Exception as exc:
            self._syntax_ok = False
            self._syntax_text = str(exc)
            self._refresh_status_bar()
            QMessageBox.warning(self, "语法检查", str(exc))
            self._jump_error_line(str(exc))
            return False
        self._applied_source = source
        self._saved_source = source
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

    def closeEvent(self, event) -> None:
        if not self._confirm_leave():
            event.ignore()
            return
        super().closeEvent(event)
