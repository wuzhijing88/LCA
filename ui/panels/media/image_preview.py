"""参数面板图片预览：后台读取、限尺寸解码和随控件取消。"""

import os
from dataclasses import dataclass
from threading import Event
from typing import Optional

from PySide6.QtCore import QCoreApplication, QObject, QRunnable, QSize, Qt, QThreadPool, QTimer, Signal, Slot
from PySide6.QtGui import QImage, QImageReader, QPixmap
from PySide6.QtWidgets import QLabel
from ui.panels.background_jobs import reserve_background_job, release_background_job


@dataclass
class PreviewImage:
    path: str = ""
    image: Optional[QImage] = None
    source_size: Optional[QSize] = None
    file_size: int = 0
    error: str = ""


def read_preview_image(image_path: str, images_dir: str, size: QSize, cancelled: Event) -> PreviewImage:
    """只读取指定图片或当前工程图片目录，不搜索其他工程或同名文件。"""
    path = image_path.replace("\\", "/").strip()
    if not os.path.isabs(path):
        if not images_dir:
            return PreviewImage(error="未设置工程图片目录")
        suffix = path[len("images/"):] if path.startswith("images/") else path
        path = os.path.join(images_dir, suffix)
    path = os.path.abspath(path)
    if cancelled.is_set():
        return PreviewImage()
    if not path.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tiff", ".webp")):
        return PreviewImage(error="不是图片文件")
    try:
        file_size = os.path.getsize(path)
        if cancelled.is_set():
            return PreviewImage()
        reader = QImageReader(path)
        source_size = reader.size()
        if cancelled.is_set():
            return PreviewImage()
        if source_size.isValid():
            reader.setScaledSize(source_size.scaled(size, Qt.AspectRatioMode.KeepAspectRatio))
        image = reader.read()
        if image.isNull():
            return PreviewImage(error="无法加载图片")
        if cancelled.is_set():
            return PreviewImage()
        return PreviewImage(path, image, source_size, file_size)
    except FileNotFoundError:
        return PreviewImage(error="文件不存在")
    except OSError as exc:
        return PreviewImage(error=f"无法读取图片：{exc}")


class _PreviewSignals(QObject):
    finished = Signal(int, object)


class _PreviewJob(QRunnable):
    def __init__(self, generation, image_path, images_dir, size, lifetime_cancelled):
        super().__init__()
        reserve_background_job()
        self.generation = generation
        self.image_path = image_path
        self.images_dir = images_dir
        self.size = size
        self.cancelled = Event()
        self.lifetime_cancelled = lifetime_cancelled
        self.signals = _PreviewSignals(_get_preview_pool())

    def run(self):
        try:
            if self.cancelled.is_set() or self.lifetime_cancelled.is_set():
                return
            try:
                result = read_preview_image(self.image_path, self.images_dir, self.size, self.cancelled)
            except Exception as exc:
                result = PreviewImage(error=f"预览失败：{exc}")
            if not self.cancelled.is_set() and not self.lifetime_cancelled.is_set():
                self.signals.finished.emit(self.generation, result)
        finally:
            release_background_job()
            self.signals.deleteLater()


_preview_pool = None


def _get_preview_pool():
    global _preview_pool
    if _preview_pool is None:
        _preview_pool = QThreadPool(QCoreApplication.instance())
        _preview_pool.setMaxThreadCount(2)
        _preview_pool.setExpiryTimeout(1000)
    return _preview_pool


class ImagePreviewLabel(QLabel):
    clicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.image_path = ""
        self.is_valid = False
        self._images_dir = ""
        self._generation = 0
        self._job = None
        self._loaded = False
        self._lifetime_cancelled = Event()
        self.destroyed.connect(self._lifetime_cancelled.set)
        self._load_timer = QTimer(self)
        self._load_timer.setSingleShot(True)
        self._load_timer.timeout.connect(self._start_loading)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setText("未选择图片")

    def set_image_path(self, image_path: str, images_dir: str):
        self.cancel_loading()
        self.image_path = str(image_path or "").strip()
        self._images_dir = str(images_dir or "")
        self._loaded = False
        self.setText("正在加载图片…" if self.image_path else "未选择图片")
        if self.image_path and self.isVisible():
            self._load_timer.start(50)

    def cancel_loading(self):
        self._generation += 1
        self._load_timer.stop()
        if self._job is not None:
            self.destroyed.disconnect(self._job.cancelled.set)
            self._job.cancelled.set()
            self._job = None
        self._loaded = False
        self.is_valid = False
        self.clear()
        self.setProperty("image_path", "")
        self.setToolTip("")
        self.setCursor(Qt.CursorShape.ArrowCursor)

    @Slot()
    def _start_loading(self):
        if not self.isVisible() or not self.image_path or self._job is not None:
            return
        size = QSize(max(1, self.width() - 6), max(1, self.height() - 6))
        try:
            self._job = _PreviewJob(self._generation, self.image_path, self._images_dir, size, self._lifetime_cancelled)
        except Exception as error:
            self._loaded = True
            self.setText(f"预览失败：{error}")
            return
        self.destroyed.connect(self._job.cancelled.set)
        self._job.signals.finished.connect(self._preview_ready, Qt.ConnectionType.QueuedConnection)
        _get_preview_pool().start(self._job)

    @Slot(int, object)
    def _preview_ready(self, generation, result):
        if generation != self._generation or not self.isVisible():
            return
        self.destroyed.disconnect(self._job.cancelled.set)
        self._job = None
        self._loaded = True
        if result.error:
            self.setText(result.error)
            return
        if result.image is None:
            self.setText("无法加载图片")
            return
        self.setPixmap(QPixmap.fromImage(result.image))
        self.setProperty("image_path", result.path)
        self.is_valid = True
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        source_size = result.source_size
        self.setToolTip(
            f"路径: {result.path}\n"
            f"尺寸: {source_size.width()} x {source_size.height()} 像素\n"
            f"大小: {result.file_size / 1024:.1f} KB\n\n"
            "提示: 双击可查看原图（支持放大缩小）"
        )

    def showEvent(self, event):
        super().showEvent(event)
        if not self.image_path:
            self.setText("未选择图片")
        elif not self._loaded and self._job is None:
            self.setText("正在加载图片…")
            self._load_timer.start(0)

    def hideEvent(self, event):
        self.cancel_loading()
        super().hideEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.is_valid:
            self.clicked.emit(self.property("image_path"))
            event.accept()
            return
        super().mouseDoubleClickEvent(event)
