"""忽略鼠标滚轮的数值输入框，避免在可滚动面板里误改参数。"""

from PySide6.QtWidgets import QDoubleSpinBox, QSpinBox


class NoWheelSpinBox(QSpinBox):
    """Spin box that ignores mouse wheel input."""

    def wheelEvent(self, event):
        event.ignore()


class NoWheelDoubleSpinBox(QDoubleSpinBox):
    """Double spin box that ignores mouse wheel input."""

    def wheelEvent(self, event):
        event.ignore()


__all__ = ["NoWheelDoubleSpinBox", "NoWheelSpinBox"]
