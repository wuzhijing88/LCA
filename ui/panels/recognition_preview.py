"""识别按钮的结果覆盖层；所有窗口均在界面线程创建并完整回收。"""
import logging

from PySide6.QtCore import QObject, QCoreApplication, QEvent, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import isValid

from themes import theme_color
from .action_context import ActionWindowContext
from utils.window.window_overlay_utils import (
    draw_dynamic_center_crosshair, get_window_client_overlay_metrics,
    map_native_rect_to_local, sync_overlay_geometry,
)

logger = logging.getLogger(__name__)


class RecognitionOverlay(QWidget):
    def __init__(self, hwnd, results, on_close, source_size, owner):
        super().__init__()
        try:
            self.setObjectName('recognitionPreviewOverlay')
            self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            self._on_close = on_close
            self._owner = owner
            self._results = []
            metrics = get_window_client_overlay_metrics(hwnd)
            if not metrics or not metrics.get('native_rect') or not metrics.get('physical_size'):
                raise ValueError('无法确定识别窗口的客户区尺寸')
            self._native_rect = tuple(metrics['native_rect'])
            self._physical_size = tuple(metrics['physical_size'])
            if len(self._native_rect) != 4 or len(self._physical_size) != 2 or min(self._physical_size) <= 0:
                raise ValueError('识别窗口的客户区尺寸无效')
            for result in results:
                if len(result) < 6:
                    raise ValueError('识别结果字段不完整')
                dimensions = result[6:8] if len(result) >= 8 else source_size
                if not dimensions or len(dimensions) != 2 or min(dimensions) <= 0:
                    raise ValueError('识别结果缺少有效的来源尺寸')
                self._results.append((tuple(result[:6]), tuple(dimensions)))
            sync_overlay_geometry(self)
            self._timer = QTimer(self)
            self._timer.setSingleShot(True)
            self._timer.timeout.connect(self.close)
            self._timer.start(3000)
            if owner is not None:
                if isinstance(owner, ActionWindowContext):
                    owner.cancelled.connect(self.close)
                owner.destroyed.connect(self.close)

        except Exception:
            self.deleteLater()
            raise

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        left, top, _right, _bottom = self._native_rect
        client_width, client_height = self._physical_size
        painter.setFont(self.font())
        for index, (result, size) in enumerate(self._results):
            name, x, y, width, height, confidence = result
            source_width, source_height = size
            native_x = round(left + x * client_width / source_width)
            native_y = round(top + y * client_height / source_height)
            native_width = round(width * client_width / source_width)
            native_height = round(height * client_height / source_height)
            rect = map_native_rect_to_local(self, (native_x, native_y, native_x + native_width, native_y + native_height))
            if rect.isEmpty():
                continue
            color = QColor(theme_color(f'recognition_preview_{index % 6 + 1}'))
            painter.setPen(QPen(color, 3))
            painter.drawRect(rect)
            draw_dynamic_center_crosshair(painter, rect, color=color, inset=3)
            painter.drawText(int(rect.left()), int(rect.top()) - 5, f'{name}: {confidence:.2%}')
        painter.end()

    def closeEvent(self, event):
        self._timer.stop()
        callback, self._on_close = self._on_close, None
        owner, self._owner = self._owner, None
        if owner is not None and isValid(owner):
            if isinstance(owner, ActionWindowContext):
                owner.cancelled.disconnect(self.close)
            owner.destroyed.disconnect(self.close)
        if callback is not None:
            try:
                callback()
            except Exception as exc:
                logger.error('恢复识别预览窗口失败：%s', exc)
        super().closeEvent(event)

class RecognitionPreviewManager(QObject):
    requested = Signal(object)

    def __init__(self, app):
        super().__init__(app)
        self._windows = {}
        self.requested.connect(self._show, Qt.ConnectionType.QueuedConnection)
        app.aboutToQuit.connect(self.close_all)

    @Slot(object)
    def _show(self, request):
        hwnd, results, restore, source_size, owner = request
        if isinstance(owner, ActionWindowContext) and owner._cancelled.is_set():
            return
        if owner is not None and not isValid(owner):
            return
        key = id(owner) if owner is not None else None
        old = self._windows.pop(key, None)
        if old is not None and isValid(old):
            old.close()
        overlay = None
        try:
            overlay = RecognitionOverlay(hwnd, results, restore, source_size, owner)
            self._windows[key] = overlay
            overlay.destroyed.connect(lambda: self._forget(key, overlay))
            overlay.show()
            overlay.raise_()
            overlay.update()
        except Exception as exc:
            logger.error('创建识别预览覆盖层失败：%s', exc, exc_info=True)
            if overlay is not None:
                overlay.deleteLater()
            if restore is not None:
                restore()

    def _forget(self, key, overlay):
        if self._windows.get(key) is overlay:
            self._windows.pop(key)

    def close_all(self):
        for overlay in list(self._windows.values()):
            if isValid(overlay):
                overlay.close()
                overlay.deleteLater()
        self._windows.clear()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def initialize_recognition_preview():
    app = QApplication.instance()
    if app is None or QThread.currentThread() != app.thread():
        raise RuntimeError('识别预览服务必须在界面线程初始化')
    if not hasattr(app, '_lca_recognition_preview'):
        app._lca_recognition_preview = RecognitionPreviewManager(app)
    return app._lca_recognition_preview


def request_recognition_preview(hwnd, results, restore=None, source_size=None, owner=None):
    app = QApplication.instance()
    if app is None or not hasattr(app, '_lca_recognition_preview'):
        raise RuntimeError('识别预览服务尚未初始化')
    app._lca_recognition_preview.requested.emit((hwnd, list(results), restore, source_size, owner))
