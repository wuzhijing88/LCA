import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QMenu, QVBoxLayout

from ...system_parts.menu_style import apply_unified_menu_style


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


class ThumbnailWidget(QLabel):
    clicked = Signal(str)
    delete_requested = Signal(str)

    def __init__(self, image_path: str, size: int = 60, parent=None):
        super().__init__(parent)
        self.image_path = image_path
        self.thumbnail_size = size
        self.is_valid = False

        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self._load_thumbnail()

        filename = os.path.basename(image_path)
        if self.is_valid:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setToolTip(f"{filename}\n左键点击查看大图\n右键点击删除")
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.setToolTip(f"{filename}\n文件不存在\n右键点击删除")

    def _show_context_menu(self, pos):
        menu = apply_unified_menu_style(QMenu(self), frameless=True)
        delete_action = menu.addAction("删除此图片")
        delete_action.triggered.connect(lambda: self.delete_requested.emit(self.image_path))
        if self.is_valid:
            view_action = menu.addAction("查看大图")
            view_action.triggered.connect(lambda: self.clicked.emit(self.image_path))
        menu.exec(self.mapToGlobal(pos))

    def _load_thumbnail(self):
        from PySide6.QtGui import QPixmap

        resolved_path = self.image_path
        if not os.path.exists(self.image_path):
            try:
                from tasks.task_utils import get_image_path_resolver
                resolver = get_image_path_resolver()
                resolved = resolver.resolve(self.image_path)
                if resolved:
                    resolved_path = resolved
            except Exception:
                pass

        if os.path.exists(resolved_path):
            pixmap = QPixmap(resolved_path)
            if not pixmap.isNull():
                scaled = pixmap.scaled(
                    self.thumbnail_size - 4,
                    self.thumbnail_size - 4,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self.setPixmap(scaled)
                self.is_valid = True
                if resolved_path != self.image_path:
                    self.image_path = resolved_path
            else:
                self.setText("?")
                self.is_valid = False
        else:
            self.setText("!")
            self.is_valid = False

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.is_valid:
            self.clicked.emit(self.image_path)
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.is_valid:
            self.clicked.emit(self.image_path)
        super().mousePressEvent(event)
