# -*- coding: utf-8 -*-
"""带行号、补全、缩进和查找的自定义脚本编辑框。"""

from __future__ import annotations

from typing import Tuple
import weakref

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, QSize, Qt, QStringListModel, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QInputMethodEvent,
    QKeyEvent,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QTextBlockUserData,
    QTextCursor,
    QTextDocument,
    QTextFormat,
)
from PySide6.QtWidgets import QApplication, QCompleter, QFrame, QLabel, QPlainTextEdit, QTextEdit, QWidget

from ui.system_parts.menu_style import create_themed_edit_menu
from themes import get_theme_manager, theme_color

from tasks.script_hints import (
    EMPTY_PARAM_LABEL,
    completion_insert_text,
    find_call_at,
    format_script_hint_html,
    parameter_choices,
    resolve_script_hint,
)
from task_workflow.script_sandbox import (
    map_script_punct_char,
    normalize_script_punctuation,
    string_open_quote,
)
from tasks.script_task import (
    align_block_keyword_line,
    first_placeholder_span,
    leading_whitespace,
    next_placeholder_span,
    plan_command_insert,
    plan_snippet_insert,
    script_completion_names,
)

from .script_syntax_highlighter import (
    _STATE_TRIPLE_DOUBLE,
    _STATE_TRIPLE_SINGLE,
    ScriptSyntaxHighlighter,
    is_dark_theme,
)


class _BreakpointData(QTextBlockUserData):
    """挂在 QTextBlock 上的断点标记；块随内容增删自动迁移，断点也随之跟随。"""

    def __init__(self) -> None:
        super().__init__()
        self.breakpoint = True


class _LineNumberArea(QWidget):
    def __init__(self, editor: "ScriptCodeEdit") -> None:
        super().__init__(editor)
        self._editor_ref = weakref.ref(editor)

    @property
    def _editor(self):
        return self._editor_ref()

    def sizeHint(self) -> QSize:
        editor = self._editor
        return QSize(editor.line_number_width(), 0) if editor is not None else QSize()

    def paintEvent(self, event) -> None:
        editor = self._editor
        if editor is not None:
            editor.paint_line_numbers(event)

    def mousePressEvent(self, event) -> None:
        # 左键点在行号旁即切换该行断点，和「断点」按钮走同一处理。
        if event.button() == Qt.MouseButton.LeftButton:
            line = self._editor.line_at_area_y(event.position().y())
            if line:
                self._editor.breakpoint_toggle_requested.emit(int(line))
                return
        super().mousePressEvent(event)


class ScriptCodeEdit(QPlainTextEdit):
    """自定义脚本编辑区：语法高亮、行号、当前行、补全和缩进。"""

    # 断点集合变化时发出当前全部断点行号（1 基）的集合。
    breakpoints_changed = Signal(object)
    # 行号区被点击请求切换某行断点（1 基行号）。
    breakpoint_toggle_requested = Signal(int)

    def __init__(self, parent=None) -> None:
        from ui.panels.managed_resources import dispose_partial_widget
        if QApplication.instance() is None:
            raise RuntimeError("创建参数界面前必须创建应用程序")
        super().__init__(parent)
        try:
            self.setObjectName("scriptEditor")
            self._dark = is_dark_theme()
            self._line_area = _LineNumberArea(self)
            self._highlighter = ScriptSyntaxHighlighter(self.document(), dark=self._dark)
            self._completer = None
            self._signature_hint = None
            self._execution_line = None
            self._breakpoint_snapshot: set = set()
            self._hide_hint_timer = QTimer(self)
            self._hide_hint_timer.setSingleShot(True)
            self._hide_hint_timer.timeout.connect(self._hide_signature_hint_if_away)
            self._execution_repaint_timer = QTimer(self)
            self._execution_repaint_timer.setSingleShot(True)
            self._execution_repaint_timer.timeout.connect(self._apply_extra_selections)
            self._completer = self._build_completer()
            self._completer_mode = "command"
            self._signature_hint = ScriptSignatureHint(self)
            self._signature_hint.installEventFilter(self)
            self.blockCountChanged.connect(self._update_line_number_width)
            self.updateRequest.connect(self._update_line_number_area)
            self.document().contentsChange.connect(self._on_contents_change)
            self.setMouseTracking(True)
            self.viewport().setMouseTracking(True)
            self.viewport().installEventFilter(self)
            self.cursorPositionChanged.connect(self._on_cursor_moved)
            self._update_line_number_width(0)
            self._highlight_current_line()

        except Exception:
            dispose_partial_widget(self, parent)
            raise

    def refresh_line_number_area(self) -> None:
        self._line_area.update()

    # ------------------------------------------------------------------
    # 断点：以 QTextBlockUserData 块标记为准，块随内容增删自动迁移。
    # ------------------------------------------------------------------
    def _block_has_breakpoint(self, block) -> bool:
        data = block.userData()
        return isinstance(data, _BreakpointData) and bool(getattr(data, "breakpoint", False))

    def _set_block_breakpoint(self, block, enabled: bool) -> None:
        if not block.isValid():
            return
        if enabled:
            if not self._block_has_breakpoint(block):
                block.setUserData(_BreakpointData())
        elif isinstance(block.userData(), _BreakpointData):
            block.setUserData(None)

    def breakpoint_lines(self) -> set:
        """返回当前带断点标记的全部行号（1 基）集合。"""
        lines = set()
        block = self.document().firstBlock()
        while block.isValid():
            if self._block_has_breakpoint(block):
                lines.add(block.blockNumber() + 1)
            block = block.next()
        return lines

    def _publish_breakpoints(self, *, force: bool) -> None:
        lines = self.breakpoint_lines()
        if not force and lines == self._breakpoint_snapshot:
            return
        self._breakpoint_snapshot = set(lines)
        self.breakpoints_changed.emit(set(lines))

    def toggle_breakpoint(self, line: int) -> bool:
        block = self.document().findBlockByNumber(int(line) - 1)
        if not block.isValid():
            return False
        enabled = not self._block_has_breakpoint(block)
        self._set_block_breakpoint(block, enabled)
        self._publish_breakpoints(force=True)
        self.refresh_line_number_area()
        return enabled

    def set_breakpoint(self, line: int, enabled: bool = True) -> None:
        block = self.document().findBlockByNumber(int(line) - 1)
        if not block.isValid():
            return
        self._set_block_breakpoint(block, bool(enabled))
        self._publish_breakpoints(force=True)
        self.refresh_line_number_area()

    def set_breakpoints(self, lines) -> None:
        """用给定行号集合整体覆盖断点标记。"""
        wanted = {int(line) for line in (lines or set())}
        block = self.document().firstBlock()
        while block.isValid():
            want = (block.blockNumber() + 1) in wanted
            if self._block_has_breakpoint(block) != want:
                self._set_block_breakpoint(block, want)
            block = block.next()
        self._publish_breakpoints(force=True)
        self.refresh_line_number_area()

    def line_at_area_y(self, y: float) -> int:
        """把行号区内的 y 坐标换算成 1 基行号；不在任何可见块内返回 0。"""
        block = self.firstVisibleBlock()
        top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        bottom = top + self.blockBoundingRect(block).height()
        target = float(y)
        while block.isValid():
            if block.isVisible() and top <= target <= bottom:
                return block.blockNumber() + 1
            block = block.next()
            top = bottom
            bottom = top + self.blockBoundingRect(block).height()
        return 0

    def _relocate_breakpoint_after_leading_split(self) -> None:
        # 在断点行行首回车：Qt 把块标记留在上方新空行上，但用户是在断点行上方
        # 插入空行，断点应随代码下移。把标记从空行搬到下面的代码块。
        cursor = self.textCursor()
        code_block = cursor.block()
        empty_block = code_block.previous()
        if (
            empty_block.isValid()
            and self._block_has_breakpoint(empty_block)
            and not self._block_has_breakpoint(code_block)
        ):
            self._set_block_breakpoint(empty_block, False)
            self._set_block_breakpoint(code_block, True)
            self._publish_breakpoints(force=True)
            self.refresh_line_number_area()

    def set_execution_line(self, line) -> None:
        """标记当前执行行（仅视觉高亮），80ms 合并重绘，不抢焦点、不居中。"""
        self._execution_line = int(line) if line else None
        timer = getattr(self, "_execution_repaint_timer", None)
        if timer is not None and not timer.isActive():
            timer.start(80)

    def _on_contents_change(self, position: int, removed: int, added: int) -> None:
        # 块标记随 QTextBlock 自动跟随内容增删；这里只在存在断点时把更新后的
        # 断点行号集合原子地推给控制器，并重绘行号区。没有断点时零开销。
        self._line_area.update()
        if self._breakpoint_snapshot:
            self._publish_breakpoints(force=False)

    def _build_completer(self) -> QCompleter:
        completer = QCompleter(self)
        completer.setWidget(self)
        completer.setModel(QStringListModel(script_completion_names(), completer))
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.activated.connect(self._insert_completion)
        popup = completer.popup()
        popup.setObjectName("scriptCompleterPopup")
        popup.installEventFilter(self)
        self._prepare_completer_popup(popup)
        self._apply_completer_theme(popup)
        self._register_theme_callback()
        return completer

    def _register_theme_callback(self) -> None:
        import weakref

        manager = get_theme_manager()
        owner = weakref.ref(self)

        def changed(theme) -> None:
            editor = owner()
            if editor is not None:
                editor._on_theme_changed(theme)

        manager.register_theme_change_callback(changed)
        self.destroyed.connect(lambda _obj=None: manager.unregister_theme_change_callback(changed))

    def _on_theme_changed(self, _theme=None) -> None:
        self._dark = is_dark_theme()
        if getattr(self, "_highlighter", None) is not None:
            self._highlighter.set_dark(self._dark)
        popup = self._completer.popup() if self._completer is not None else None
        if popup is not None:
            self._apply_completer_theme(popup)
        if getattr(self, "_signature_hint", None) is not None:
            self._signature_hint.apply_theme(self._dark)
        self._highlight_current_line()
        if getattr(self, "_line_area", None) is not None:
            self._line_area.update()

    def _prepare_completer_popup(self, popup) -> None:
        if popup.property("scriptPopupPrepared"):
            return
        popup.setProperty("scriptPopupPrepared", True)
        from themes.rounded_popup import COMBO_RADIUS, apply_rounded_popup, apply_transparent_popup_palette

        apply_rounded_popup(
            popup,
            radius=COMBO_RADIUS,
            border_key="combo_popup_border",
            frameless=True,
        )
        popup.setFrameShape(QFrame.Shape.NoFrame)
        popup.setLineWidth(0)
        popup.setMidLineWidth(0)
        viewport = popup.viewport()
        if viewport is not None:
            apply_transparent_popup_palette(viewport)
        for child in popup.findChildren(QWidget):
            name = child.objectName()
            class_name = child.metaObject().className() if hasattr(child, "metaObject") else ""
            if name in {
                "qt_scrollarea_up_button",
                "qt_scrollarea_down_button",
                "qt_scrollarea_up_scroller",
                "qt_scrollarea_down_scroller",
            } or "Scroller" in class_name:
                child.hide()
                child.setEnabled(False)
                child.setFixedSize(0, 0)

    def _apply_completer_theme(self, popup) -> None:
        self._prepare_completer_popup(popup)
        colors = _script_popup_colors()
        from themes.rounded_popup import apply_transparent_popup_palette

        apply_transparent_popup_palette(popup)
        palette = popup.palette()
        palette.setColor(QPalette.ColorRole.Text, QColor(colors["text"]))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(colors["selected"]))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(theme_color("accent_text")))
        popup.setPalette(palette)
        viewport = popup.viewport()
        if viewport is not None:
            apply_transparent_popup_palette(viewport)
            viewport.setPalette(palette)

    def setFont(self, font) -> None:
        super().setFont(font)
        self._update_line_number_width()

    def cursor_location(self) -> Tuple[int, int]:
        cursor = self.textCursor()
        return cursor.blockNumber() + 1, cursor.positionInBlock() + 1

    def select_document_span(self, start: int, end: int) -> None:
        limit = len(self.toPlainText())
        begin = max(0, min(int(start), limit))
        finish = max(begin, min(int(end), limit))
        cursor = self.textCursor()
        cursor.setPosition(begin)
        cursor.setPosition(finish, QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(cursor)
        self.centerCursor()
        self.setFocus()

    def replace_document_text(self, text: str) -> None:
        source = str(text or "")
        if source == self.toPlainText():
            return
        cursor = self.textCursor()
        position = cursor.position()
        cursor.beginEditBlock()
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.insertText(source)
        cursor.endEditBlock()
        cursor.setPosition(min(position, len(source)))
        self.setTextCursor(cursor)

    def goto_line(self, line: int, column: int = 1) -> None:
        block = self.document().findBlockByNumber(max(0, int(line) - 1))
        if not block.isValid():
            return
        cursor = QTextCursor(block)
        offset = max(0, min(max(1, int(column)) - 1, len(block.text())))
        cursor.setPosition(block.position() + offset)
        self.setTextCursor(cursor)
        self.centerCursor()
        self.setFocus()
        self._highlight_current_line()

    def insert_snippet(self, snippet: str) -> None:
        self.apply_edit_plan(plan_snippet_insert(str(snippet or ""), self.toPlainText(), self.textCursor().blockNumber()))

    def insert_command(self, item) -> None:
        cursor = self.textCursor()
        block = cursor.block()
        block_pos = block.position()
        same_line = (
            cursor.selectionStart() >= block_pos
            and cursor.selectionEnd() <= block_pos + len(block.text())
        )
        self.apply_edit_plan(
            plan_command_insert(
                item or {},
                self.toPlainText(),
                cursor.blockNumber(),
                cursor.positionInBlock(),
                (cursor.selectionStart() - block_pos) if same_line else None,
                (cursor.selectionEnd() - block_pos) if same_line else None,
            )
        )

    def apply_edit_plan(self, plan) -> None:
        payload = plan or {}
        text = str(payload.get("text") or "")
        block = self.document().findBlockByNumber(int(payload.get("line") or 0))
        cursor = QTextCursor(block)
        if payload.get("mode") == "replace":
            cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
        else:
            cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        start = cursor.selectionStart() if cursor.hasSelection() else cursor.position()
        cursor.insertText(text)
        span = first_placeholder_span(text)
        if span:
            cursor.setPosition(start + span[0])
            cursor.setPosition(start + span[1], QTextCursor.MoveMode.KeepAnchor)
        else:
            cursor.setPosition(start + len(text))
        self.setTextCursor(cursor)
        self.setFocus()
        self._completer.popup().hide()
        self._refresh_signature_hint()

    def replace_current_line(self, text: str) -> None:
        block = self.textCursor().block()
        cursor = self.textCursor()
        cursor.setPosition(block.position())
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(str(text or ""))
        self.setTextCursor(cursor)

    def select_line_span(self, start: int, end: int) -> None:
        block = self.textCursor().block()
        cursor = self.textCursor()
        begin = block.position() + max(0, int(start))
        finish = block.position() + max(int(begin - block.position()), int(end))
        cursor.setPosition(begin)
        cursor.setPosition(finish, QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(cursor)

    def find_text(self, query: str, backward: bool = False, case_sensitive: bool = False) -> bool:
        needle = str(query or "")
        if not needle:
            return False
        flags = QTextDocument.FindFlag(0)
        if backward:
            flags |= QTextDocument.FindFlag.FindBackward
        if case_sensitive:
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        if self.find(needle, flags):
            return True
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End if backward else QTextCursor.MoveOperation.Start)
        self.setTextCursor(cursor)
        return bool(self.find(needle, flags))

    def line_number_width(self) -> int:
        digits = max(2, len(str(max(1, self.blockCount()))))
        return 16 + self.fontMetrics().horizontalAdvance("9") * digits

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        rect = self.contentsRect()
        self._line_area.setGeometry(QRect(rect.left(), rect.top(), self.line_number_width(), rect.height()))

    def paint_line_numbers(self, event) -> None:
        from themes import theme_color

        painter = QPainter(self._line_area)
        painter.fillRect(event.rect(), QColor(theme_color("surface")))
        number_color = QColor(theme_color("text_disabled"))
        current_color = QColor(theme_color("text"))

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        current = self.textCursor().blockNumber()
        width = self._line_area.width() - 8
        height = self.fontMetrics().height()
        marker_color = QColor(theme_color("error"))

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                if self._block_has_breakpoint(block):
                    radius = max(3, height // 4)
                    center_y = top + height // 2
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QBrush(marker_color))
                    painter.drawEllipse(QPoint(radius + 2, center_y), radius, radius)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(current_color if block_number == current else number_color)
                painter.drawText(0, top, width, height, Qt.AlignmentFlag.AlignRight, str(block_number + 1))
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            block_number += 1

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self._handle_completer_key(event):
            return
        key = event.key()
        shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if key == Qt.Key.Key_Tab and not shift:
            if self._select_next_placeholder(False):
                return
            self._indent()
            return
        if key == Qt.Key.Key_Backtab or (key == Qt.Key.Key_Tab and shift):
            if self._select_next_placeholder(True):
                return
            self._dedent()
            return
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier and key == Qt.Key.Key_Space:
            self._update_completer_prefix(force=True)
            return
        if event.modifiers() & Qt.KeyboardModifier.AltModifier and key == Qt.Key.Key_Slash:
            self._update_completer_prefix(force=True)
            return
        if key == Qt.Key.Key_Escape and self._signature_hint.isVisible():
            self._signature_hint.hide()
            return
        if key in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            cursor = self.textCursor()
            relocate = (
                not cursor.hasSelection()
                and cursor.positionInBlock() == 0
                and self._block_has_breakpoint(cursor.block())
            )
            super().keyPressEvent(event)
            if relocate:
                self._relocate_breakpoint_after_leading_split()
            self._apply_auto_indent()
            self._refresh_signature_hint()
            return
        typed = event.text()
        if self._insert_normalized_punct(typed):
            return
        super().keyPressEvent(event)
        self._after_inserted_text(typed)

    def inputMethodEvent(self, event: QInputMethodEvent) -> None:
        commit = event.commitString()
        if commit and not self._caret_in_string_or_comment():
            converted = self._normalized_typed_text(commit)
            if converted != commit:
                replacement = QInputMethodEvent(event.preeditString(), event.attributes())
                replacement.setCommitString(converted, event.replacementStart(), event.replacementLength())
                super().inputMethodEvent(replacement)
                self._after_inserted_text(converted)
                return
        super().inputMethodEvent(event)
        if commit:
            self._after_inserted_text(commit)

    def insertFromMimeData(self, source) -> None:
        if source is not None and source.hasText():
            text = source.text()
            # 光标不在字符串/注释里才把整段的代码标点半角化；
            # normalize_script_punctuation 本身会保留粘贴片段内部字符串里的标点。
            if not self._caret_in_string_or_comment():
                text = normalize_script_punctuation(text)
            self.insertPlainText(text)
            self._after_inserted_text(text)
            return
        super().insertFromMimeData(source)

    def _normalized_typed_text(self, text: str) -> str:
        return normalize_script_punctuation(text)

    def _caret_open_quote(self):
        """返回光标所在字符串的开引号：单行字符串返回半角 ``"`` 或 ``'``，注释返回
        ``"#"``，三引号字符串返回 ``'\"\"\"'`` 或 ``"'''"``，都不在时返回 ``None``。"""
        cursor = self.textCursor()
        block = cursor.block()
        column = cursor.positionInBlock()
        line = block.text()
        # 多行三引号字符串：语法高亮把未闭合状态写进上一块的 userState。
        # 若上一块以三引号字符串结尾，本块起始即在字符串内；无该状态时退回单行判断。
        previous = block.previous()
        if previous.isValid():
            state = previous.userState()
            if state in (_STATE_TRIPLE_DOUBLE, _STATE_TRIPLE_SINGLE):
                quote = '"""' if state == _STATE_TRIPLE_DOUBLE else "'''"
                close = line.find(quote)
                if close < 0 or column <= close + len(quote):
                    return quote
                tail_start = close + len(quote)
                return string_open_quote(line[tail_start:], column - tail_start)
        return string_open_quote(line, column)

    def _caret_in_string_or_comment(self) -> bool:
        """判断光标是否落在字符串或注释内，此时输入的标点应原样保留。"""
        return self._caret_open_quote() is not None

    def _insert_normalized_punct(self, text: str) -> bool:
        if not text:
            return False
        open_quote = self._caret_open_quote()
        if open_quote is not None:
            # 字符串/注释里原样保留；但正在“闭合当前字符串”的那个引号要半角化，
            # 否则闭合引号残留全角，后续整行会被误判为仍在字符串内。
            if (
                open_quote in {'"', "'"}
                and len(text) == 1
                and map_script_punct_char(text) == open_quote
            ):
                self.insertPlainText(open_quote)
                self._after_inserted_text(open_quote)
                return True
            return False
        converted = self._normalized_typed_text(text)
        if converted == text:
            return False
        self.insertPlainText(converted)
        self._after_inserted_text(converted)
        return True

    def _after_inserted_text(self, text: str) -> None:
        if ":" in str(text or ""):
            self._align_block_keyword()
        self._update_completer_prefix(force=any(char in str(text or "") for char in {"(", ","}))
        self._refresh_signature_hint()

    def _handle_completer_key(self, event: QKeyEvent) -> bool:
        popup = self._completer.popup()
        if not popup.isVisible():
            return False
        key = event.key()
        if key in {Qt.Key.Key_Enter, Qt.Key.Key_Return, Qt.Key.Key_Tab}:
            # 插入弹窗里高亮的那一行，而不是模型第 0 行。
            index = popup.currentIndex()
            current = ""
            if index.isValid():
                data = index.data(Qt.ItemDataRole.DisplayRole)
                if data is not None:
                    current = str(data)
            if not current:
                current = self._completer.currentCompletion()
            if current:
                self._insert_completion(current)
            popup.hide()
            return True
        if key == Qt.Key.Key_Escape:
            popup.hide()
            self._signature_hint.hide()
            return True
        return False

    def _current_word(self) -> Tuple[str, int]:
        cursor = self.textCursor()
        text = cursor.block().text()
        column = cursor.positionInBlock()
        start = column
        while start > 0 and _is_completion_char(text[start - 1]):
            start -= 1
        return text[start:column], start

    def _update_completer_prefix(self, force: bool = False) -> None:
        cursor = self.textCursor()
        line = cursor.block().text()
        column = cursor.positionInBlock()
        model = self._completer.model()
        choices = parameter_choices(line, column)
        if choices:
            self._completer_mode = "param"
            if isinstance(model, QStringListModel):
                model.setStringList(choices)
            prefix = self._current_argument_prefix(line, column)
            self._completer.setCompletionPrefix(prefix)
            if self._completer.completionCount() <= 0:
                self._completer.popup().hide()
                return
            if (
                not force
                and self._completer.completionCount() == 1
                and self._completer.currentCompletion() == prefix
            ):
                self._completer.popup().hide()
                return
            self._show_completer_popup()
            return

        self._completer_mode = "command"
        if isinstance(model, QStringListModel):
            model.setStringList(script_completion_names())
        word, _start = self._current_word()
        if not word or word == ".":
            if force and self._can_list_all_commands(line, column):
                self._completer.setCompletionPrefix("")
            else:
                self._completer.popup().hide()
                return
        else:
            self._completer.setCompletionPrefix(word)
        if self._completer.completionCount() <= 0:
            self._completer.popup().hide()
            return
        if not force and self._completer.completionCount() == 1 and self._completer.currentCompletion() == word:
            self._completer.popup().hide()
            return
        self._show_completer_popup()

    def _can_list_all_commands(self, line: str, column: int) -> bool:
        before = str(line or "")[: max(0, int(column))].rstrip()
        if not before:
            return True
        return before[-1] not in {")", ":", ",", '"', "'"}

    def _show_completer_popup(self) -> None:
        popup = self._completer.popup()
        self._prepare_completer_popup(popup)
        self._signature_hint.hide()
        rect = self.cursorRect()
        rect.setWidth(max(220, popup.sizeHintForColumn(0) + 28))
        self._completer.complete(rect)

    def _current_argument_prefix(self, line: str, column: int) -> str:
        call = find_call_at(line, column)
        if not call:
            word, _start = self._current_word()
            return word
        start = int(call.get("arg_start") or 0)
        while start < column and start < len(line) and line[start] in {" ", "\t"}:
            start += 1
        return line[start:column]

    def _insert_completion(self, completion: str) -> None:
        if self._completer_mode == "param":
            self._insert_parameter(completion)
            return
        word, start = self._current_word()
        insert = completion_insert_text(completion)
        cursor = self.textCursor()
        block_pos = cursor.block().position()
        cursor.setPosition(block_pos + start)
        cursor.setPosition(block_pos + start + len(word), QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(insert)
        span = first_placeholder_span(insert)
        if span:
            cursor.setPosition(block_pos + start + span[0])
            cursor.setPosition(block_pos + start + span[1], QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(cursor)
        self._completer.popup().hide()
        self._refresh_signature_hint()
        self._update_completer_prefix(force=False)

    def _insert_parameter(self, completion: str) -> None:
        cursor = self.textCursor()
        line = cursor.block().text()
        column = cursor.positionInBlock()
        call = find_call_at(line, column)
        start = int(call.get("arg_start") or column) if call else column
        while start < column and start < len(line) and line[start] in {" ", "\t"}:
            start += 1
        block_pos = cursor.block().position()
        cursor.setPosition(block_pos + start)
        cursor.setPosition(block_pos + column, QTextCursor.MoveMode.KeepAnchor)
        insert = "" if completion == EMPTY_PARAM_LABEL else completion
        cursor.insertText(insert)
        span = first_placeholder_span(insert)
        if span:
            cursor.setPosition(block_pos + start + span[0])
            cursor.setPosition(block_pos + start + span[1], QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(cursor)
        self._completer.popup().hide()
        self._refresh_signature_hint()

    def _select_next_placeholder(self, backward: bool) -> bool:
        cursor = self.textCursor()
        block = cursor.block()
        if backward:
            column = cursor.selectionStart() - block.position()
        else:
            column = cursor.selectionEnd() - block.position()
        span = next_placeholder_span(block.text(), column, backward)
        if not span:
            return False
        start, end = span
        if start == cursor.selectionStart() - block.position() and end == cursor.selectionEnd() - block.position():
            follow = end if not backward else start
            span = next_placeholder_span(block.text(), follow, backward)
            if not span:
                return False
            start, end = span
        cursor.setPosition(block.position() + start)
        cursor.setPosition(block.position() + end, QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(cursor)
        return True

    def _indent(self) -> None:
        cursor = self.textCursor()
        if cursor.hasSelection():
            self._change_indent(4)
            return
        cursor.insertText("    ")

    def _dedent(self) -> None:
        self._change_indent(-4)

    def _change_indent(self, delta: int) -> None:
        cursor = self.textCursor()
        start = cursor.selectionStart()
        end = cursor.selectionEnd()
        cursor.setPosition(start)
        start_block = cursor.blockNumber()
        cursor.setPosition(end)
        end_block = cursor.blockNumber()
        if end > start and cursor.positionInBlock() == 0:
            end_block -= 1
        cursor.beginEditBlock()
        for block_number in range(start_block, end_block + 1):
            block = self.document().findBlockByNumber(block_number)
            line_cursor = QTextCursor(block)
            text = block.text()
            if delta > 0:
                line_cursor.insertText(" " * delta)
            else:
                remove = min(-delta, len(leading_whitespace(text)))
                if remove:
                    line_cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, remove)
                    line_cursor.removeSelectedText()
        cursor.endEditBlock()

    def _apply_auto_indent(self) -> None:
        cursor = self.textCursor()
        previous = cursor.block().previous()
        if not previous.isValid():
            return
        indent = leading_whitespace(previous.text())
        if previous.text().rstrip().endswith(":"):
            indent += "    "
        if indent:
            cursor.insertText(indent)

    def _align_block_keyword(self) -> None:
        cursor = self.textCursor()
        block = cursor.block()
        aligned = align_block_keyword_line(block.text(), self.toPlainText(), block.blockNumber())
        if aligned is None:
            return
        cursor.beginEditBlock()
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(aligned)
        cursor.endEditBlock()
        self.setTextCursor(cursor)

    def _update_line_number_width(self, _count: int = 0) -> None:
        self.setViewportMargins(self.line_number_width(), 0, 0, 0)

    def _update_line_number_area(self, rect, dy: int) -> None:
        if dy:
            self._line_area.scroll(0, dy)
        else:
            self._line_area.update(0, rect.y(), self._line_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_line_number_width()

    def _on_cursor_moved(self) -> None:
        self._highlight_current_line()
        self._refresh_signature_hint()

    def _highlight_current_line(self) -> None:
        self._apply_extra_selections()

    def _apply_extra_selections(self) -> None:
        from themes import theme_color

        selections = []
        current = QTextEdit.ExtraSelection()
        current.format.setBackground(QColor(theme_color("hover")))
        current.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        current.cursor = self.textCursor()
        current.cursor.clearSelection()
        selections.append(current)
        exec_line = getattr(self, "_execution_line", None)
        if exec_line:
            block = self.document().findBlockByNumber(int(exec_line) - 1)
            if block.isValid():
                marker = QTextEdit.ExtraSelection()
                color = QColor(theme_color("warning"))
                color.setAlpha(55)
                marker.format.setBackground(color)
                marker.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
                marker.cursor = QTextCursor(block)
                selections.append(marker)
        self.setExtraSelections(selections)
        self._line_area.update()

    def _mouse_on_code_line(self) -> bool:
        if not self.isVisible():
            return False
        pos = self.viewport().mapFromGlobal(QCursor.pos())
        if not self.viewport().rect().contains(pos):
            return False
        hovered = self.cursorForPosition(pos)
        caret = self.textCursor()
        return hovered.block().blockNumber() == caret.block().blockNumber()

    def _widget_contains_cursor(self, widget, margin: int = 4) -> bool:
        if widget is None:
            return False
        try:
            if not widget.isVisible():
                return False
            return widget.frameGeometry().adjusted(-margin, -margin, margin, margin).contains(QCursor.pos())
        except RuntimeError:
            return False

    def _mouse_over_parameter_ui(self) -> bool:
        if self._widget_contains_cursor(getattr(self, "_signature_hint", None)):
            return True
        completer = getattr(self, "_completer", None)
        popup = completer.popup() if completer is not None else None
        return self._widget_contains_cursor(popup)

    def _cancel_hide_signature_hint(self) -> None:
        timer = getattr(self, "_hide_hint_timer", None)
        if timer is not None and timer.isActive():
            timer.stop()

    def _schedule_hide_signature_hint(self) -> None:
        timer = getattr(self, "_hide_hint_timer", None)
        if timer is not None:
            timer.start(150)

    def _hide_signature_hint_if_away(self) -> None:
        hint = getattr(self, "_signature_hint", None)
        if hint is None:
            return
        if self._mouse_on_code_line() or self._mouse_over_parameter_ui():
            return
        hint.hide()

    def _refresh_signature_hint(self) -> None:
        hint = getattr(self, "_signature_hint", None)
        completer = getattr(self, "_completer", None)
        if hint is None:
            return
        if completer is not None and completer.popup().isVisible():
            self._cancel_hide_signature_hint()
            hint.hide()
            return
        if self._mouse_over_parameter_ui():
            self._cancel_hide_signature_hint()
            return
        if not self._mouse_on_code_line():
            self._schedule_hide_signature_hint()
            return
        self._cancel_hide_signature_hint()
        cursor = self.textCursor()
        payload = resolve_script_hint(cursor.block().text(), cursor.positionInBlock())
        html = format_script_hint_html(payload)
        if not html:
            hint.hide()
            return
        caret = self.cursorRect()
        global_pos = self.mapToGlobal(caret.bottomLeft() + QPoint(self.line_number_width(), 6))
        hint.show_hint(html, global_pos)

    def contextMenuEvent(self, event) -> None:
        menu = create_themed_edit_menu(self)
        menu.exec(event.globalPos())
        menu.deleteLater()

    def eventFilter(self, obj, event) -> bool:
        completer = getattr(self, "_completer", None)
        popup = completer.popup() if completer is not None else None
        hint = getattr(self, "_signature_hint", None)
        if hint is not None and obj is hint and event.type() == QEvent.Type.Leave:
            self._schedule_hide_signature_hint()
        if obj is self.viewport() and hint is not None:
            event_type = event.type()
            if event_type == QEvent.Type.Leave:
                if not self._mouse_over_parameter_ui():
                    self._schedule_hide_signature_hint()
            elif event_type in {QEvent.Type.Enter, QEvent.Type.MouseMove}:
                self._refresh_signature_hint()
        return super().eventFilter(obj, event)

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        if self._mouse_over_parameter_ui():
            return
        self._schedule_hide_signature_hint()

    def hideEvent(self, event) -> None:
        self._hide_hint_timer.stop()
        self._execution_repaint_timer.stop()
        self._completer.popup().hide()
        self._signature_hint.hide()
        super().hideEvent(event)


class ScriptSignatureHint(QLabel):
    """跟在光标下面的参数格式提示。自己画圆角，避免 Windows 垫一层直角底。"""

    def __init__(self, editor: ScriptCodeEdit) -> None:
        flags = (
            Qt.WindowType.ToolTip
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        if hasattr(Qt.WindowType, "NoDropShadowWindowHint"):
            flags |= Qt.WindowType.NoDropShadowWindowHint
        super().__init__(editor, flags)
        self.setObjectName("scriptSignatureHint")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setWordWrap(False)
        self.apply_theme(editor._dark)
        self.hide()

    @property
    def _editor(self):
        return self._editor_ref()

    def apply_theme(self, dark: bool) -> None:
        colors = _script_popup_colors()
        self._bg = QColor(colors["canvas"])
        self._fg = QColor(colors["text"])
        self._border = QColor(colors["border"])
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, 4.0, 4.0)
        painter.fillPath(path, QBrush(self._bg))
        painter.setPen(QPen(self._border, 1))
        painter.drawPath(path)
        painter.end()
        super().paintEvent(event)

    def show_hint(self, html: str, global_pos: QPoint) -> None:
        if self.isVisible() and self.text() == html and self.pos() == global_pos:
            return
        self.setText(html)
        self.adjustSize()
        self.move(global_pos)
        self.show()
        self.raise_()


def _script_popup_colors() -> dict:
    return {key: theme_color(key) for key in
            ("surface", "canvas", "text", "border", "combo_popup_border", "hover", "selected")}


def _is_completion_char(char: str) -> bool:
    return char.isalnum() or char in {".", "_"} or ("\u4e00" <= char <= "\u9fff")
