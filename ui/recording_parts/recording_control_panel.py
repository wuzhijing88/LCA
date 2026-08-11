"""
录制控制浮窗面板。
"""

import logging
import time

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QCursor, QFont
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from utils.window_activation_utils import show_and_activate_overlay
from utils.window_coordinate_common import get_available_geometry_for_widget

logger = logging.getLogger(__name__)


class RecordingControlPanel(QWidget):
    """录制控制浮窗。"""

    stop_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.start_time = None
        self.step_count = 0
        self.is_recording = False
        self.init_ui()
        self.setup_timer()

    def init_ui(self):
        """初始化界面。"""
        self.setWindowTitle("录制中")
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        title_layout = QHBoxLayout()
        title_label = QLabel("正在录制")
        title_label.setObjectName("recordingTitle")
        title_font = QFont()
        title_font.setPointSize(11)
        title_font.setBold(True)
        title_label.setFont(title_font)

        status_indicator = QLabel("●")
        status_indicator.setObjectName("recordingIndicator")

        title_layout.addWidget(status_indicator)
        title_layout.addWidget(title_label)
        title_layout.addStretch()
        layout.addLayout(title_layout)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(8)

        self.time_label = QLabel("耗时: 00:00")
        self.time_label.setObjectName("recordingTime")
        info_layout.addWidget(self.time_label)

        self.step_label = QLabel("步骤: 0")
        self.step_label.setObjectName("recordingSteps")
        info_layout.addWidget(self.step_label)

        layout.addLayout(info_layout)

        button_layout = QHBoxLayout()

        self.stop_btn = QPushButton("停止录制")
        self.stop_btn.setObjectName("recordingStopButton")
        self.stop_btn.setMinimumHeight(35)
        self.stop_btn.setMinimumWidth(100)
        self.stop_btn.clicked.connect(self.on_stop_clicked)
        button_layout.addWidget(self.stop_btn)

        self.pause_btn = QPushButton("暂停")
        self.pause_btn.setObjectName("recordingPauseButton")
        self.pause_btn.setMinimumHeight(35)
        self.pause_btn.setMinimumWidth(80)
        self.pause_btn.clicked.connect(self.toggle_pause)
        self.pause_btn.setVisible(False)
        button_layout.addWidget(self.pause_btn)

        layout.addLayout(button_layout)

        self.setFixedWidth(220)
        self.setFixedHeight(140)

    def setup_timer(self):
        """设置定时器。"""
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_time_display)
        self.timer.setInterval(100)

    def start_recording(self):
        """开始录制。"""
        logger.info("RecordingControlPanel.start_recording called")
        self.is_recording = True
        self.start_time = time.time()
        self.step_count = 0
        self.timer.start()
        logger.info(f"recording timer started, interval={self.timer.interval()}")

        try:
            geometry = get_available_geometry_for_widget(self, global_pos=QCursor.pos())
            logger.info(f"recording panel available geometry: {geometry}")
            if geometry and not geometry.isEmpty():
                target_x = geometry.right() - self.width() - 20
                target_y = geometry.top() + 20
                self.move(target_x, target_y)
                logger.info(f"recording panel moved to ({target_x}, {target_y})")
        except Exception as exc:
            logger.warning(f"设置录制面板位置失败：{exc}")

        show_and_activate_overlay(self, log_prefix='录制控制浮窗', focus=True)

    def stop_recording(self):
        """停止录制。"""
        self.is_recording = False
        self.timer.stop()
        self.hide()

    def update_step_count(self, count: int):
        """更新步骤计数。"""
        self.step_count = count
        self.step_label.setText(f"步骤: {count}")

    def increment_step(self):
        """增加一个步骤。"""
        self.step_count += 1
        self.step_label.setText(f"步骤: {self.step_count}")

    def update_time_display(self):
        """更新时间显示。"""
        if self.is_recording and self.start_time:
            elapsed = time.time() - self.start_time
            minutes = int(elapsed // 60)
            seconds = int(elapsed % 60)
            self.time_label.setText(f"耗时: {minutes:02d}:{seconds:02d}")

    def toggle_pause(self):
        """暂停或继续。"""
        if self.pause_btn.text() == "暂停":
            self.pause_btn.setText("继续")
            self.timer.stop()
            self.is_recording = False
        else:
            self.pause_btn.setText("暂停")
            self.timer.start()
            self.is_recording = True

    def on_stop_clicked(self):
        """停止按钮点击处理。"""
        self.stop_recording()
        self.stop_requested.emit()

    def get_elapsed_time(self) -> float:
        """获取已用时长。"""
        if self.start_time:
            return time.time() - self.start_time
        return 0.0

    def set_position(self, x: int, y: int):
        """设置浮窗位置。"""
        self.move(x, y)
