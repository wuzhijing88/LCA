"""Shared dropdown helper exports and wheel-safe spin boxes."""

from PySide6.QtWidgets import QDoubleSpinBox, QSpinBox

from ..widgets.custom_widgets import CenteredTextDelegate, FullBleedListWidget, RoundedPopupFrame


class NoWheelSpinBox(QSpinBox):
    """Spin box that ignores mouse wheel input."""

    def wheelEvent(self, event):
        event.ignore()


class NoWheelDoubleSpinBox(QDoubleSpinBox):
    """Double spin box that ignores mouse wheel input."""

    def wheelEvent(self, event):
        event.ignore()


__all__ = [
    "CenteredTextDelegate",
    "FullBleedListWidget",
    "NoWheelDoubleSpinBox",
    "NoWheelSpinBox",
    "RoundedPopupFrame",
]
