from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QMenu, QVBoxLayout

from ...system_parts.menu_style import apply_unified_menu_style
from ..media.image_preview import ImagePreviewLabel


class FlowLayout(QVBoxLayout):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []
        self._spacing = 8
        self._margin = 8

    def setSpacing(self, spacing):
        self._spacing = spacing
        super().setSpacing(spacing)

    def setContentsMargins(self, left, top, right, bottom):
        self._margin = left
        super().setContentsMargins(left, top, right, bottom)

    def addWidget(self, widget):
        self._items.append(widget)
        super().addWidget(widget)


class ThumbnailWidget(ImagePreviewLabel):
    delete_requested = Signal(str)

    def __init__(self, image_path: str, size: int = 60, parent=None, *, images_dir=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.set_image_path(image_path, images_dir)

    def _show_context_menu(self, pos):
        menu = apply_unified_menu_style(QMenu(self), frameless=True)
        delete_action = menu.addAction("删除此图片")
        delete_action.triggered.connect(lambda: self.delete_requested.emit(self.image_path))
        if self.is_valid:
            view_action = menu.addAction("查看大图")
            view_action.triggered.connect(lambda: self.clicked.emit(self.property("image_path")))
        try:
            menu.exec(self.mapToGlobal(pos))
        finally:
            menu.deleteLater()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.is_valid:
            self.clicked.emit(self.property("image_path"))
        super().mousePressEvent(event)
