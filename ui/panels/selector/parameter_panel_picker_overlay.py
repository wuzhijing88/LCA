from ..parameter_panel_support import *
from utils.window_activation_utils import activate_overlay_widget
from utils.window_overlay_utils import (
    draw_selection_overlay,
    map_native_rect_to_local,
    sync_overlay_geometry,
)


class ParameterPanelPickerOverlay(QWidget):
    """Transparent overlay for element picking."""

    def __init__(self, parent_panel):
        super().__init__()
        self.parent_panel = parent_panel
        self.highlight_rect = None
        self.device_pixel_ratio = self.devicePixelRatioF()

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        sync_overlay_geometry(self)
        self.setCursor(Qt.CrossCursor)
        self._apply_transparent_window_style()

    def _apply_transparent_window_style(self) -> None:
        import ctypes

        hwnd = int(self.winId())
        GWL_EXSTYLE = -20
        WS_EX_LAYERED = 0x00080000
        WS_EX_TRANSPARENT = 0x00000020
        style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT)
        logger.debug(f"[元素拾取] 设置窗口透明样式: hwnd={hwnd}")

    def showEvent(self, event):
        super().showEvent(event)
        activate_overlay_widget(self, log_prefix='元素拾取覆盖层', focus=True)
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        logger.debug(f"[元素拾取] showEvent: 窗口获得焦点，hasFocus={self.hasFocus()}")

    def hideEvent(self, event):
        super().hideEvent(event)
        logger.debug("[元素拾取] hideEvent: 窗口已隐藏")

    def paintEvent(self, event):
        if not self.highlight_rect:
            logger.debug("[picker] paintEvent: highlight_rect is None")
            return

        logger.debug(f"[picker] paintEvent: highlight_rect={self.highlight_rect}")
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        x, y, w, h = self.highlight_rect
        native_rect = (int(x), int(y), int(x) + int(w), int(y) + int(h))
        draw_rect = map_native_rect_to_local(self, native_rect)
        if draw_rect.isEmpty():
            logger.debug("[picker] mapped rect is empty, skip draw")
            return

        logger.debug(
            f"[picker] draw rect: ({draw_rect.x()}, {draw_rect.y()}, "
            f"{draw_rect.width()}, {draw_rect.height()})"
        )
        draw_selection_overlay(
            painter,
            draw_rect,
            border_color=QColor(255, 0, 0),
            border_width=3,
            fill_color=QColor(255, 0, 0, 30),
        )

    def mouseDoubleClickEvent(self, event):
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self.parent_panel._confirm_current_element_pick()
        event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.parent_panel._cancel_current_element_pick()
        event.accept()
