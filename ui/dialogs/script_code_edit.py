# -*- coding: utf-8 -*-
"""带行号、补全、缩进和查找的自定义脚本编辑框。"""

from __future__ import annotations

from typing import Tuple

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, QSize, Qt, QStringListModel, QTimer
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
    QTextCursor,
    QTextDocument,
    QTextFormat,
)
from PySide6.QtWidgets import QCompleter, QFrame, QLabel, QPlainTextEdit, QTextEdit, QWidget

from ui.system_parts.menu_style import create_themed_edit_menu

from tasks.script_hints import (
    EMPTY_PARAM_LABEL,
    completion_insert_text,
    find_call_at,
    format_script_hint_html,
    parameter_choices,
    resolve_script_hint,
)
from task_workflow.script_sandbox import (
    normalize_script_punctuation,
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

from .script_syntax_highlighter import ScriptSyntaxHighlighter, is_dark_theme


class _LineNumberArea(QWidget):
    def __init__(self, editor: "ScriptCodeEdit") -> None:
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self._editor.line_number_width(), 0)

    def paintEvent(self, event) -> None:
        self._editor.paint_line_numbers(event)


class ScriptCodeEdit(QPlainTextEdit):
    """自定义脚本编辑区：语法高亮、行号、当前行、补全和缩进。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("scriptEditor")
        self._dark = is_dark_theme()
        self._line_area = _LineNumberArea(self)
        self._highlighter = ScriptSyntaxHighlighter(self.document(), dark=self._dark)
        self._completer = None
        self._signature_hint = None
        self._hide_hint_timer = QTimer(self)
        self._hide_hint_timer.setSingleShot(True)
        self._hide_hint_timer.timeout.connect(self._hide_signature_hint_if_away)
        self._completer = self._build_completer()
        self._completer_mode = "command"
        self._signature_hint = ScriptSignatureHint(self)
        self._signature_hint.installEventFilter(self)
        self.blockCountChanged.connect(self._update_line_number_width)
        self.updateRequest.connect(self._update_line_number_area)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.viewport().installEventFilter(self)
        self.cursorPositionChanged.connect(self._on_cursor_moved)
        self._update_line_number_width(0)
        self._highlight_current_line()

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
        try:
            from themes import get_theme_manager

            manager = get_theme_manager()
            manager.register_theme_change_callback(self._on_theme_changed)
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
        popup.setStyleSheet(
            f"""
            QListView#scriptCompleterPopup {{
                background: transparent;
                color: {colors['text']};
                border: none;
                outline: none;
                padding: 4px 2px;
                font-family: Consolas, "Microsoft YaHei UI", monospace;
                font-size: 12px;
            }}
            QListView#scriptCompleterPopup::viewport {{
                background: transparent;
            }}
            QListView#scriptCompleterPopup::item {{
                padding: 6px 12px;
                min-height: 20px;
                border: none;
                border-radius: 3px;
                margin: 1px 2px;
            }}
            QListView#scriptCompleterPopup::item:hover {{
                background-color: {colors['hover']};
            }}
            QListView#scriptCompleterPopup::item:selected {{
                background-color: {colors['selected']};
                color: #ffffff;
            }}
            QListView#scriptCompleterPopup QScrollBar:vertical {{
                background: transparent;
                width: 8px;
                margin: 0px;
                border: none;
            }}
            QListView#scriptCompleterPopup QScrollBar::handle:vertical {{
                background-color: {colors['scroll']};
                border-radius: 4px;
                min-height: 24px;
                margin: 2px;
            }}
            """
        )
        from themes.rounded_popup import apply_transparent_popup_palette

        apply_transparent_popup_palette(popup)
        palette = popup.palette()
        palette.setColor(QPalette.ColorRole.Text, QColor(colors["text"]))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(colors["selected"]))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
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
        painter.fillRect(event.rect(), QColor(theme_color("surface", "#2d2d2d" if self._dark else "#f5f5f5")))
        number_color = QColor(theme_color("text_disabled", "#666666" if self._dark else "#999999"))
        current_color = QColor(theme_color("text", "#e0e0e0" if self._dark else "#333333"))

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        current = self.textCursor().blockNumber()
        width = self._line_area.width() - 8
        height = self.fontMetrics().height()

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
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
        if key == Qt.Key.Key_Escape and self._signature_hint.isVisible():
            self._signature_hint.hide()
            return
        if key in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            super().keyPressEvent(event)
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
        converted = self._normalized_typed_text(commit)
        if commit and converted != commit:
            replacement = QInputMethodEvent(event.preeditString(), event.attributes())
            replacement.setCommitString(converted, event.replacementStart(), event.replacementLength())
            super().inputMethodEvent(replacement)
            self._after_inserted_text(converted)
            return
        super().inputMethodEvent(event)
        if commit:
            self._after_inserted_text(converted)

    def insertFromMimeData(self, source) -> None:
        if source is not None and source.hasText():
            text = normalize_script_punctuation(source.text())
            self.insertPlainText(text)
            self._after_inserted_text(text)
            return
        super().insertFromMimeData(source)

    def _normalized_typed_text(self, text: str) -> str:
        return normalize_script_punctuation(text)

    def _insert_normalized_punct(self, text: str) -> bool:
        converted = self._normalized_typed_text(text)
        if not text or converted == text:
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
        from themes import theme_color

        selection = QTextEdit.ExtraSelection()
        selection.format.setBackground(QColor(theme_color("hover", "#3a3a3a" if self._dark else "#e8e8e8")))
        selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        selection.cursor = self.textCursor()
        selection.cursor.clearSelection()
        self.setExtraSelections([selection])
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
        super().__init__(None, flags)
        self.setObjectName("scriptSignatureHint")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setWordWrap(False)
        self._bg = QColor("#252525")
        self._fg = QColor("#e0e0e0")
        self._border = QColor("#3e3e3e")
        self.apply_theme(editor._dark)
        self.hide()

    def apply_theme(self, dark: bool) -> None:
        colors = _script_popup_colors()
        self._bg = QColor(colors["canvas"])
        self._fg = QColor(colors["text"])
        self._border = QColor(colors["border"])
        self.setStyleSheet(
            f"QLabel#scriptSignatureHint {{"
            f"background:transparent;color:{colors['text']};"
            f"border:none;padding:6px 8px;"
            f'font-family:Consolas,"Microsoft YaHei UI",monospace;font-size:12px;'
            f"}}"
        )
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
    fallback = {
        "surface": "#2d2d2d",
        "canvas": "#252525",
        "text": "#e0e0e0",
        "border": "#3e3e3e",
        "combo_popup_border": "#707070",
        "hover": "#3a3a3a",
        "selected": "#0078d4",
        "scroll": "rgba(255, 255, 255, 0.2)",
    }
    light = {
        "surface": "#ffffff",
        "canvas": "#ffffff",
        "text": "#333333",
        "border": "#e0e0e0",
        "combo_popup_border": "#707070",
        "hover": "#e8e8e8",
        "selected": "#0078d4",
        "scroll": "rgba(0, 0, 0, 0.2)",
    }
    try:
        from themes import get_theme_manager

        manager = get_theme_manager()
        colors = light if not manager.is_dark_mode() else fallback
        for key in ("surface", "canvas", "text", "border", "combo_popup_border", "hover", "selected"):
            value = str(manager.get_color(key) or "").strip()
            if value:
                colors[key] = value
        colors["scroll"] = "rgba(255, 255, 255, 0.2)" if manager.is_dark_mode() else "rgba(0, 0, 0, 0.2)"
        return colors
    except Exception:
        return fallback if is_dark_theme() else light


def _is_completion_char(char: str) -> bool:
    return char.isalnum() or char in {".", "_"} or ("\u4e00" <= char <= "\u9fff")
