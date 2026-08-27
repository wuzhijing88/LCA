# -*- coding: utf-8 -*-
"""易语言式参数栏：当前命令的每个参数一格，改格子就改代码。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QWidget,
)

from tasks.script_task import apply_param_value, parse_param_fields
from ui.widgets.custom_widgets import CustomDropdown as QComboBox


class ScriptParamBar(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("scriptParamBar")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(42)
        self._editor = None
        self._syncing = False
        self._fields: List[Dict[str, Any]] = []
        self._name = ""
        self._active = 0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self._sync_from_editor)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        scroll = QScrollArea()
        scroll.setObjectName("scriptParamScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        inner = QWidget()
        inner.setObjectName("scriptParamInner")
        row = QHBoxLayout(inner)
        row.setContentsMargins(8, 4, 8, 4)
        row.setSpacing(8)
        name = QLabel("参数")
        name.setObjectName("scriptParamName")
        row.addWidget(name)
        empty = QLabel("点到命令上，这里改参数。")
        empty.setObjectName("scriptParamEmpty")
        row.addWidget(empty, 1)
        row.addStretch(1)
        scroll.setWidget(inner)
        layout.addWidget(scroll)
        self._scroll = scroll
        self._inner = inner
        self._row = row
        self._name_label = name
        self._empty = empty
        self._widgets: List[QWidget] = []

    def bind_editor(self, editor) -> None:
        self._editor = editor
        editor.cursorPositionChanged.connect(self._timer.start)
        editor.textChanged.connect(self._timer.start)

    def _editors(self) -> List[QWidget]:
        return [widget for widget in self._widgets if isinstance(widget, (QLineEdit, QComboBox))]

    def _signature(self, parsed: Optional[Dict[str, Any]]) -> Tuple[str, List[Tuple[str, str]]]:
        fields = list((parsed or {}).get("fields") or [])
        name = str((parsed or {}).get("name") or "")
        return name, [(str(item.get("label") or ""), str(item.get("spec") or "")) for item in fields]

    def _sync_from_editor(self) -> None:
        if self._syncing or self._editor is None:
            return
        cursor = self._editor.textCursor()
        parsed = parse_param_fields(cursor.block().text(), cursor.positionInBlock())
        if self._field_has_focus():
            name, signature = self._signature(parsed)
            current = [(str(item.get("label") or ""), str(item.get("spec") or "")) for item in self._fields]
            if name != self._name or signature != current:
                self._render(parsed)
            elif parsed:
                self._fields = list(parsed.get("fields") or [])
                self._active = int(parsed.get("active") or 0)
                self._fill(self._fields)
                self._highlight(self._active)
            return
        self._render(parsed)

    def _field_has_focus(self) -> bool:
        widget = self.focusWidget()
        if widget is None:
            return False
        if widget in self._widgets:
            return True
        return any(isinstance(item, QComboBox) and item.lineEdit() is widget for item in self._widgets)

    def _render(self, parsed: Optional[Dict[str, Any]]) -> None:
        fields = list((parsed or {}).get("fields") or [])
        name = str((parsed or {}).get("name") or "")
        active = int((parsed or {}).get("active") or 0)
        signature = [(str(item.get("label") or ""), str(item.get("spec") or "")) for item in fields]
        current = [(str(item.get("label") or ""), str(item.get("spec") or "")) for item in self._fields]
        if signature != current or name != self._name:
            self._rebuild(name, fields)
        else:
            self._fill(fields)
        self._name = name
        self._fields = fields
        self._active = active
        self._highlight(active)

    def _clear_fields(self) -> None:
        for widget in self._widgets:
            self._row.removeWidget(widget)
            widget.deleteLater()
        self._widgets = []

    def _rebuild(self, name: str, fields: List[Dict[str, Any]]) -> None:
        self._clear_fields()
        self._name_label.setText(name or "参数")
        self._empty.setVisible(not fields)
        for index, field in enumerate(fields):
            label = QLabel(str(field.get("label") or "参数"))
            label.setObjectName("scriptParamLabel")
            choices = tuple(field.get("choices") or ())
            if choices:
                box = QComboBox(self._inner)
                box.setObjectName("scriptParamField")
                box.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
                box.setEditable(True)
                box.setMaximumHeight(26)
                line_edit = box.lineEdit()
                if line_edit is not None:
                    line_edit.setMaximumHeight(26)
                    line_edit.setFrame(False)
                    line_edit.setAutoFillBackground(False)
                    line_edit.setPlaceholderText(str(field.get("value") or field.get("label") or ""))
                    line_edit.installEventFilter(self)
                box.addItems(list(choices))
                box.setCurrentText(str(field.get("value") or ""))
                box.currentTextChanged.connect(self._on_field_changed)
                editor = box
            else:
                editor = QLineEdit()
                editor.setObjectName("scriptParamField")
                editor.setText(str(field.get("value") or ""))
                editor.setPlaceholderText(str(field.get("value") or field.get("label") or ""))
                editor.editingFinished.connect(self._on_field_changed)
                editor.textEdited.connect(self._on_field_changed)
            editor.setMinimumWidth(88)
            editor.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            editor.installEventFilter(self)
            self._row.insertWidget(self._row.count() - 1, label)
            self._row.insertWidget(self._row.count() - 1, editor)
            self._widgets.extend((label, editor))
            editor.setProperty("_param_index", index)

    def _fill(self, fields: List[Dict[str, Any]]) -> None:
        focused = self.focusWidget()
        editors = self._editors()
        for editor, field in zip(editors, fields):
            if editor is focused or (isinstance(editor, QComboBox) and editor.lineEdit() is focused):
                continue
            value = str(field.get("value") or "")
            if isinstance(editor, QComboBox):
                if editor.currentText() != value:
                    editor.blockSignals(True)
                    editor.setCurrentText(value)
                    editor.blockSignals(False)
            elif editor.text() != value:
                editor.blockSignals(True)
                editor.setText(value)
                editor.blockSignals(False)

    def _highlight(self, active: int) -> None:
        editors = self._editors()
        for index, editor in enumerate(editors):
            is_active = index == active
            self._set_active_param(editor, is_active)
            line_edit = editor.lineEdit() if hasattr(editor, "lineEdit") else None
            if line_edit is not None:
                self._set_active_param(line_edit, is_active)
            arrow = getattr(editor, "display_button", None)
            if arrow is not None:
                self._set_active_param(arrow, is_active)

    def _set_active_param(self, widget, active: bool) -> None:
        widget.setProperty("activeParam", active)
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.FocusIn:
            index = self._widget_index(obj)
            if index is not None:
                self._jump_to_field(index)
        return super().eventFilter(obj, event)

    def _widget_index(self, widget) -> Optional[int]:
        editors = self._editors()
        if widget in editors:
            return editors.index(widget)
        for index, editor in enumerate(editors):
            if isinstance(editor, QComboBox) and editor.lineEdit() is widget:
                return index
        return None

    def _jump_to_field(self, index: int) -> None:
        if self._editor is None or index < 0 or index >= len(self._fields):
            return
        field = self._fields[index]
        start = int(field.get("start") or 0)
        end = int(field.get("end") or start)
        if hasattr(self._editor, "select_line_span"):
            self._editor.select_line_span(start, end)
        self._highlight(index)

    def _on_field_changed(self) -> None:
        if self._syncing or self._editor is None:
            return
        editors = self._editors()
        sender = self.sender()
        try:
            index = editors.index(sender)
        except ValueError:
            return
        value = sender.currentText() if isinstance(sender, QComboBox) else sender.text()
        cursor = self._editor.textCursor()
        line = cursor.block().text()
        column = cursor.positionInBlock()
        updated = apply_param_value(line, column, index, value)
        if updated == line:
            return
        self._syncing = True
        self._editor.replace_current_line(updated)
        parsed = parse_param_fields(updated, min(column, max(0, len(updated) - 1)))
        self._render(parsed)
        self._syncing = False
