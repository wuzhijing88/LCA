from __future__ import annotations

from typing import Callable

import cv2
import numpy as np

_QT_AVAILABLE = True
try:
    from PySide6.QtCore import Qt, QPointF
    from PySide6.QtGui import QImage, QMouseEvent, QPainter, QPixmap, QWheelEvent, QColor
    from PySide6.QtWidgets import QWidget
except ImportError:
    _QT_AVAILABLE = False

    class _Unavailable:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("需要 PySide6")

    QWidget = QMouseEvent = QWheelEvent = QPainter = QPixmap = QImage = QColor = _Unavailable
    Qt = QPointF = _Unavailable


class MapCanvas(QWidget):
    """Pan/zoom canvas for mosaic + annotation overlay."""

    def __init__(
        self,
        on_click: Callable[[int, int], None],
        parent=None,
    ):
        super().__init__(parent)
        self._on_click = on_click
        self._image_bgr: np.ndarray | None = None
        self._scale = 1.0
        self._offset = QPointF(0, 0)
        self._panning = False
        self._last_pos = QPointF(0, 0)
        self._empty_text = "开始采集后，在游戏中移动以拼接小地图"
        self._bg = QColor(30, 30, 30)
        self._fg = QColor(180, 180, 180)
        self.setMouseTracking(True)
        self.setMinimumSize(480, 360)

    def set_theme_colors(self, background: str, text: str) -> None:
        self._bg = QColor(background)
        self._fg = QColor(text)
        self.update()

    def set_empty_text(self, text: str) -> None:
        self._empty_text = text
        self.update()

    def set_image(self, image_bgr: np.ndarray | None) -> None:
        self._image_bgr = None if image_bgr is None else np.ascontiguousarray(image_bgr)
        self.update()

    def reset_view(self) -> None:
        self._scale = 1.0
        self._offset = QPointF(0, 0)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), self._bg)
        if self._image_bgr is None or self._image_bgr.size == 0:
            painter.setPen(self._fg)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._empty_text)
            return
        rgb = cv2.cvtColor(self._image_bgr, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        qimg = QImage(rgb.data, w, h, w * 3, QImage.Format.Format_RGB888).copy()
        pix = QPixmap.fromImage(qimg)
        target_w = max(1, int(w * self._scale))
        target_h = max(1, int(h * self._scale))
        scaled = pix.scaled(
            target_w,
            target_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        painter.drawPixmap(int(self._offset.x()), int(self._offset.y()), scaled)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self._image_bgr is None:
            return
        delta = event.angleDelta().y()
        factor = 1.15 if delta > 0 else 1 / 1.15
        old = self._scale
        self._scale = float(np.clip(self._scale * factor, 0.15, 8.0))
        pos = event.position()
        # Zoom around cursor.
        self._offset = pos - (pos - self._offset) * (self._scale / old)
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.MiddleButton or (
            event.button() == Qt.MouseButton.LeftButton
            and event.modifiers() & Qt.KeyboardModifier.SpaceModifier
        ):
            self._panning = True
            self._last_pos = event.position()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            image_xy = self._to_image(event.position())
            if image_xy is not None:
                self._on_click(image_xy[0], image_xy[1])
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._panning:
            delta = event.position() - self._last_pos
            self._offset += delta
            self._last_pos = event.position()
            self.update()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.LeftButton):
            self._panning = False
        super().mouseReleaseEvent(event)

    def _to_image(self, pos: QPointF) -> tuple[int, int] | None:
        if self._image_bgr is None:
            return None
        x = int((pos.x() - self._offset.x()) / self._scale)
        y = int((pos.y() - self._offset.y()) / self._scale)
        h, w = self._image_bgr.shape[:2]
        if 0 <= x < w and 0 <= y < h:
            return (x, y)
        return None
