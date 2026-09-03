"""全局 QComboBox 下拉修补：强制向下展开、限制可见行数、保持圆角主题，并顺带修饰标准编辑菜单。"""

from __future__ import annotations

import logging

from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtWidgets import QAbstractItemView, QApplication, QComboBox, QFrame, QMenu, QWidget

_MAX_VISIBLE_ITEMS = 8
_SCROLLER_OBJECT_NAMES = (
    "qt_scrollarea_up_button",
    "qt_scrollarea_down_button",
    "qt_scrollarea_up_scroller",
    "qt_scrollarea_down_scroller",
)


class ComboBoxPopupFixer(QObject):
    def __init__(self, radius: int = 8, parent=None):
        super().__init__(parent)
        self._radius = radius

    def eventFilter(self, obj, event):
        if event.type() not in (QEvent.Type.Show, QEvent.Type.ShowToParent):
            return False

        try:
            from ui.system_parts.menu_style import polish_standard_edit_menu

            if isinstance(obj, QMenu):
                polish_standard_edit_menu(obj, frameless=False)
                return False
        except Exception:
            pass

        popup = None
        combo = None
        try:
            if isinstance(obj, QAbstractItemView):
                popup = obj.window()
                if popup:
                    combo = popup.parentWidget()
            else:
                class_name = obj.metaObject().className() if hasattr(obj, "metaObject") else ""
                if class_name == "QComboBoxPrivateContainer":
                    popup = obj
                    combo = obj.parentWidget()
        except Exception:
            return False

        if not popup or not combo or not isinstance(combo, QComboBox):
            return False
        if popup.property("_combo_popup_fixing"):
            return False

        popup.setProperty("_combo_popup_fixing", True)
        QTimer.singleShot(0, lambda: self._fix_popup(combo, popup))
        return False

    def _fix_popup(self, combo, popup):
        try:
            if not popup or not combo or not popup.isVisible():
                return

            popup.setContentsMargins(0, 0, 0, 0)
            self._apply_popup_theme(combo, popup)
            if not popup.isVisible():
                popup.show()

            combo_bottom_left = combo.mapToGlobal(combo.rect().bottomLeft())
            popup.move(combo_bottom_left)

            combo.setMaxVisibleItems(_MAX_VISIBLE_ITEMS)
            view = combo.view()
            if view:
                self._style_view(view)
                self._hide_builtin_scrollers(popup)
                self._enforce_popup_height(combo, view, popup)

            screen = combo.screen() or QApplication.primaryScreen()
            if screen:
                screen_geometry = screen.availableGeometry()
                if popup.geometry().bottom() > screen_geometry.bottom():
                    new_height = screen_geometry.bottom() - combo_bottom_left.y() - 5
                    if 0 < new_height < popup.height():
                        popup.setFixedHeight(new_height)
                        popup.move(combo_bottom_left)
        finally:
            if popup:
                popup.setProperty("_combo_popup_fixing", False)

    @staticmethod
    def _apply_popup_theme(combo, popup) -> None:
        try:
            from themes import get_theme_manager

            get_theme_manager().apply_combo_popup_theme(popup, combo.view())
        except Exception:
            from themes.rounded_popup import COMBO_RADIUS, apply_rounded_popup

            apply_rounded_popup(
                popup,
                radius=COMBO_RADIUS,
                border_key="combo_popup_border",
                frameless=True,
                force_window=True,
            )

    @staticmethod
    def _style_view(view) -> None:
        view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        view.setAutoFillBackground(False)
        if view.viewport():
            view.viewport().setAutoFillBackground(False)
            view.viewport().setContentsMargins(0, 0, 0, 0)
        view.setContentsMargins(0, 0, 0, 0)
        view.setFrameShape(QFrame.Shape.NoFrame)
        view.setLineWidth(0)
        view.setMidLineWidth(0)

    @staticmethod
    def _hide_builtin_scrollers(popup) -> None:
        for child in popup.findChildren(QWidget):
            name = child.objectName()
            class_name = child.metaObject().className() if hasattr(child, "metaObject") else ""
            if name in _SCROLLER_OBJECT_NAMES or "Scroller" in class_name:
                child.hide()
                child.setEnabled(False)
                child.setFixedSize(0, 0)

    @staticmethod
    def _enforce_popup_height(combo, view, popup) -> None:
        try:
            item_count = combo.count()
            visible_count = min(item_count, _MAX_VISIBLE_ITEMS) if item_count > 0 else _MAX_VISIBLE_ITEMS
            row_height = view.sizeHintForRow(0) if item_count > 0 else view.sizeHint().height()
            if row_height <= 0:
                row_height = view.fontMetrics().height() + 8
            spacing = view.spacing() if hasattr(view, "spacing") else 0
            margins = view.contentsMargins()
            desired_view_height = (
                row_height * visible_count
                + max(0, visible_count - 1) * spacing
                + margins.top()
                + margins.bottom()
                + view.frameWidth() * 2
            )
            extra = max(0, popup.height() - view.height())
            view.setMinimumHeight(desired_view_height)
            view.setMaximumHeight(desired_view_height)
            popup.setFixedHeight(extra + desired_view_height)
        except Exception:
            pass


def install_combo_popup_fixer(app) -> bool:
    """在 QApplication 上安装全局下拉修补器；重复调用只安装一次。"""
    try:
        if getattr(app, "_combo_popup_fixer", None) is not None:
            return True
        app._combo_popup_fixer = ComboBoxPopupFixer(parent=app)
        app.installEventFilter(app._combo_popup_fixer)
        logging.info("Installed global QComboBox popup fixer.")
        return True
    except Exception as popup_fix_error:
        logging.warning(f"安装 QComboBox 下拉修复器失败：{popup_fix_error}")
        return False
