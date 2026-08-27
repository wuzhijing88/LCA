# -*- coding: utf-8 -*-
"""自定义脚本右侧命令列表：筛选、补全插入、按当前缩进对齐。"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QLabel,
    QLineEdit,
    QSizePolicy,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tasks.script_task import (
    SCRIPT_INSERT_GROUPS,
    command_help_text,
    command_matches_query,
    split_command_signatures,
)


def script_action_button_size(widget) -> tuple:
    metrics = widget.fontMetrics()
    text_width = max(
        metrics.horizontalAdvance(label)
        for label in ("显示命令", "隐藏命令", "应用", "重置", "插入")
    )
    width = max(96, text_width + 28)
    height = max(32, metrics.height() + 14)
    return width, height


def script_action_button_width(widget) -> int:
    return script_action_button_size(widget)[0]


class ScriptCommandPanel(QWidget):
    """分组命令列表，支持筛选后插入。"""

    can_insert_changed = Signal(bool)

    def __init__(self, on_insert: Callable[[Dict[str, Any]], None], parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("scriptHelpPanel")
        self.setMinimumWidth(360)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self._on_insert = on_insert
        self._selected: Optional[Dict[str, Any]] = None
        self._build_ui()
        self._populate()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 0, 0, 0)
        layout.setSpacing(8)

        title = QLabel("可用命令")
        title.setObjectName("scriptHelpTitle")
        layout.addWidget(title)

        search = QLineEdit()
        search.setObjectName("scriptCommandSearch")
        search.setPlaceholderText("筛选命令，回车插入")
        search.setClearButtonEnabled(True)
        search.textChanged.connect(self._filter_items)
        search.installEventFilter(self)
        layout.addWidget(search)
        self._search = search

        tree = QTreeWidget()
        tree.setObjectName("scriptCommandTree")
        tree.setHeaderHidden(True)
        tree.setRootIsDecorated(True)
        tree.setIndentation(14)
        tree.setExpandsOnDoubleClick(False)
        tree.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        tree.itemClicked.connect(self._on_item_clicked)
        tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        tree.installEventFilter(self)
        tree.setMinimumHeight(160)
        tree.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(tree, 2)
        self._tree = tree

        help_view = QTextEdit()
        help_view.setObjectName("scriptHelpNotes")
        help_view.setReadOnly(True)
        help_view.setAcceptRichText(False)
        help_view.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        help_view.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        help_view.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        help_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        help_view.setMinimumHeight(200)
        help_view.document().setDocumentMargin(8)
        layout.addWidget(help_view, 3)
        self._help_view = help_view

    def _populate(self) -> None:
        self._tree.clear()
        for group in SCRIPT_INSERT_GROUPS:
            parent = QTreeWidgetItem([str(group.get("title") or "")])
            parent.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self._tree.addTopLevelItem(parent)
            for item in group.get("items") or ():
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "")
                child = QTreeWidgetItem([name])
                child.setData(0, Qt.ItemDataRole.UserRole, item)
                child.setToolTip(0, "\n".join(split_command_signatures(str(item.get("signature") or name))))
                parent.addChild(child)
            parent.setExpanded(True)
        self._select_first_visible()

    def _filter_items(self, query: str = "") -> None:
        needle = str(query or "")
        for index in range(self._tree.topLevelItemCount()):
            parent = self._tree.topLevelItem(index)
            if parent is None:
                continue
            visible_count = 0
            for child_index in range(parent.childCount()):
                child = parent.child(child_index)
                payload = child.data(0, Qt.ItemDataRole.UserRole)
                visible = isinstance(payload, dict) and command_matches_query(payload, needle)
                child.setHidden(not visible)
                if visible:
                    visible_count += 1
            parent.setHidden(visible_count == 0)
            if visible_count:
                parent.setExpanded(True)
        self._select_first_visible()

    def _visible_command_items(self) -> list:
        items = []
        for index in range(self._tree.topLevelItemCount()):
            parent = self._tree.topLevelItem(index)
            if parent is None or parent.isHidden():
                continue
            for child_index in range(parent.childCount()):
                child = parent.child(child_index)
                if child is None or child.isHidden():
                    continue
                payload = child.data(0, Qt.ItemDataRole.UserRole)
                if isinstance(payload, dict):
                    items.append(child)
        return items

    def _select_first_visible(self) -> None:
        items = self._visible_command_items()
        if not items:
            self._show_item(None)
            return
        current = self._tree.currentItem()
        if current is not None and current in items:
            self._show_item(current.data(0, Qt.ItemDataRole.UserRole))
            return
        self._tree.setCurrentItem(items[0])
        self._show_item(items[0].data(0, Qt.ItemDataRole.UserRole))

    def _move_visible_selection(self, delta: int) -> None:
        items = self._visible_command_items()
        if not items:
            return
        current = self._tree.currentItem()
        try:
            index = items.index(current)
        except ValueError:
            index = 0 if delta > 0 else len(items) - 1
        else:
            index = max(0, min(len(items) - 1, index + delta))
        self._tree.setCurrentItem(items[index])
        self._show_item(items[index].data(0, Qt.ItemDataRole.UserRole))

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
            key = event.key()
            if obj is self._search:
                if key in {Qt.Key.Key_Down, Qt.Key.Key_Up}:
                    self._move_visible_selection(1 if key == Qt.Key.Key_Down else -1)
                    return True
                if key in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
                    self._insert_selected_or_first()
                    return True
            if obj is self._tree and key in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
                self._insert_selected_or_first()
                return True
        return super().eventFilter(obj, event)

    def _on_item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        payload = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(payload, dict):
            self._show_item(payload)

    def _on_item_double_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        payload = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(payload, dict):
            self._show_item(payload)
            self._on_insert(payload)

    def _show_item(self, item: Optional[Dict[str, Any]]) -> None:
        self._selected = item if isinstance(item, dict) else None
        self.can_insert_changed.emit(self._selected is not None)
        self._help_view.setPlainText(command_help_text(self._selected))

    def has_selection(self) -> bool:
        return self._selected is not None

    def insert_current(self) -> None:
        self._insert_selected()

    def _insert_selected(self) -> None:
        if self._selected:
            self._on_insert(self._selected)

    def _insert_selected_or_first(self) -> None:
        if self._selected:
            self._on_insert(self._selected)
            return
        items = self._visible_command_items()
        if not items:
            return
        payload = items[0].data(0, Qt.ItemDataRole.UserRole)
        if isinstance(payload, dict):
            self._show_item(payload)
            self._on_insert(payload)
