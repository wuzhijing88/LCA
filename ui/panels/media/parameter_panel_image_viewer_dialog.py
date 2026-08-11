from ..parameter_panel_support import *
from PySide6.QtGui import QPixmap, QWheelEvent


class ParameterPanelImageViewerDialog(QDialog):
    """Image viewer dialog."""

    def __init__(self, image_path: str, parent=None):
        super().__init__(parent)
        self.image_path = image_path
        self.scale_factor = 1.0
        self.min_scale = 0.1
        self.max_scale = 10.0
        self.is_dragging = False
        self.last_mouse_pos = None
        self.original_pixmap = QPixmap(image_path)

        self.setWindowTitle(f"图片查看器 - {os.path.basename(image_path)}")
        self.resize(800, 600)

        self._setup_ui()
        self._initialize_image_state()

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(False)
        self.scroll_area.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.info_label = QLabel()

        self.scroll_area.setWidget(self.image_label)
        main_layout.addWidget(self.scroll_area)
        main_layout.addLayout(self._build_button_layout())

        self.scroll_area.wheelEvent = self._wheel_event
        self.image_label.setMouseTracking(True)
        self.scroll_area.setMouseTracking(True)

    def _build_button_layout(self) -> QHBoxLayout:
        button_layout = QHBoxLayout()

        zoom_in_btn = QPushButton("放大 (+)")
        zoom_in_btn.clicked.connect(lambda: self._zoom(1.2))

        zoom_out_btn = QPushButton("缩小 (-)")
        zoom_out_btn.clicked.connect(lambda: self._zoom(0.8))

        actual_size_btn = QPushButton("实际大小 (1:1)")
        actual_size_btn.clicked.connect(self._actual_size)

        fit_window_btn = QPushButton("适应窗口")
        fit_window_btn.clicked.connect(self._fit_window)

        button_layout.addWidget(zoom_in_btn)
        button_layout.addWidget(zoom_out_btn)
        button_layout.addWidget(actual_size_btn)
        button_layout.addWidget(fit_window_btn)
        button_layout.addStretch()
        button_layout.addWidget(self.info_label)
        return button_layout

    def _initialize_image_state(self) -> None:
        if self.original_pixmap.isNull():
            self.image_label.setText("无法加载图片")
            return
        self._fit_window_on_init()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_dragging = True
            self.last_mouse_pos = event.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        event.accept()

    def mouseMoveEvent(self, event):
        if self.is_dragging and self.last_mouse_pos is not None:
            delta = event.pos() - self.last_mouse_pos
            self.last_mouse_pos = event.pos()
            h_bar = self.scroll_area.horizontalScrollBar()
            v_bar = self.scroll_area.verticalScrollBar()
            h_bar.setValue(h_bar.value() - delta.x())
            v_bar.setValue(v_bar.value() - delta.y())
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_dragging = False
            self.last_mouse_pos = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
        event.accept()

    def _fit_window_on_init(self) -> None:
        if self.original_pixmap.isNull():
            return
        self.scale_factor = self._calculate_fit_scale()
        self._update_image()

    def _calculate_fit_scale(self) -> float:
        available_width = max(1, self.width() - 40)
        available_height = max(1, self.height() - 100)
        width_ratio = available_width / self.original_pixmap.width()
        height_ratio = available_height / self.original_pixmap.height()
        return min(width_ratio, height_ratio, 1.0)

    def _update_image(self) -> None:
        if self.original_pixmap.isNull():
            return
        scaled_pixmap = self.original_pixmap.scaled(
            max(1, int(self.original_pixmap.width() * self.scale_factor)),
            max(1, int(self.original_pixmap.height() * self.scale_factor)),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.image_label.setPixmap(scaled_pixmap)
        self.image_label.resize(scaled_pixmap.size())
        self._update_info()

    def _update_info(self) -> None:
        if self.original_pixmap.isNull():
            return
        self.info_label.setText(
            f"原始尺寸: {self.original_pixmap.width()}x{self.original_pixmap.height()} | "
            f"缩放: {self.scale_factor:.1%}"
        )

    def _zoom(self, factor: float) -> None:
        new_scale = self.scale_factor * factor
        if self.min_scale <= new_scale <= self.max_scale:
            self.scale_factor = new_scale
            self._update_image()

    def _actual_size(self) -> None:
        self.scale_factor = 1.0
        self._update_image()

    def _fit_window(self) -> None:
        if self.original_pixmap.isNull():
            return
        self.scale_factor = self._calculate_fit_scale()
        self._update_image()

    def _wheel_event(self, event: QWheelEvent) -> None:
        if event.angleDelta().y() > 0:
            self._zoom(1.1)
        else:
            self._zoom(0.9)
        event.accept()
