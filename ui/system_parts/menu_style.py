# -*- coding: utf-8 -*-
"""Unified menu styling helpers."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QLineEdit, QMenu, QPlainTextEdit, QTextEdit

from themes.rounded_popup import MENU_RADIUS, apply_rounded_popup


_EDIT_MENU_TEXTS = {
    "Undo": "撤销",
    "Redo": "重做",
    "Cut": "剪切",
    "Copy": "复制",
    "Paste": "粘贴",
    "Delete": "删除",
    "Select All": "全选",
}


def _action_label(text: str) -> str:
    cleaned = str(text or "").replace("&", "").strip()
    if "\t" in cleaned:
        cleaned = cleaned.split("\t", 1)[0].strip()
    return cleaned


def translate_standard_edit_actions(menu: QMenu) -> QMenu:
    for action in menu.actions():
        if action.isSeparator():
            continue
        translated = _EDIT_MENU_TEXTS.get(_action_label(action.text()))
        if translated:
            action.setText(translated)
    return menu


def apply_unified_menu_style(menu: QMenu, *, frameless: bool = False) -> QMenu:
    """Apply project-wide menu behavior while deferring visuals to the active theme."""
    menu.setProperty("unifiedMenu", True)
    apply_rounded_popup(
        menu,
        radius=MENU_RADIUS,
        border_key="border",
        frameless=frameless,
        force_window=False,
    )
    return menu


def polish_standard_edit_menu(menu: QMenu, *, frameless: bool = True) -> QMenu:
    translate_standard_edit_actions(menu)
    return apply_unified_menu_style(menu, frameless=frameless)


def create_themed_edit_menu(widget) -> QMenu:
    menu = widget.createStandardContextMenu()
    return polish_standard_edit_menu(menu, frameless=True)


class EditMenuFixer(QObject):
    """输入框/编辑器右键菜单统一汉化并套主题。"""

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.ContextMenu and isinstance(obj, (QLineEdit, QPlainTextEdit, QTextEdit)):
            menu = create_themed_edit_menu(obj)
            pos = event.globalPos() if hasattr(event, "globalPos") else obj.mapToGlobal(obj.rect().center())
            menu.exec(pos)
            menu.deleteLater()
            return True
        if isinstance(obj, QMenu) and event.type() in (QEvent.Type.Polish, QEvent.Type.Show):
            polish_standard_edit_menu(obj, frameless=not obj.isVisible())
        return False


def install_edit_menu_fixer(app) -> EditMenuFixer:
    fixer = getattr(app, "_edit_menu_fixer", None)
    if fixer is None:
        fixer = EditMenuFixer(parent=app)
        app.installEventFilter(fixer)
        app._edit_menu_fixer = fixer
    return fixer
