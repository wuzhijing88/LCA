# -*- coding: utf-8 -*-
"""Unified menu styling helpers."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMenu


def apply_unified_menu_style(menu: QMenu, *, frameless: bool = False) -> QMenu:
    """Apply project-wide menu behavior while deferring visuals to the active theme."""
    menu.setProperty("unifiedMenu", True)
    menu.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

    if frameless:
        menu.setWindowFlags(
            menu.windowFlags()
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    menu.style().unpolish(menu)
    menu.style().polish(menu)
    return menu

