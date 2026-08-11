"""
DPI变化通知组件
当检测到DPI变化时显示通知并提供自动调整功能
"""

import logging
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                              QPushButton, QFrame, QMessageBox, QProgressBar)
from PySide6.QtCore import Qt, QTimer, Signal, QThread
from PySide6.QtGui import QFont, QIcon
from utils.window_activation_utils import show_and_raise_widget

logger = logging.getLogger(__name__)


class WindowAdjustmentWorker(QThread):
    """窗口自动调整工作线程"""

    progress_updated = Signal(int)  # 进度更新
    adjustment_completed = Signal(bool, str)  # 调整完成 (成功, 消息)

    def __init__(self, window_list, old_dpi_info, new_dpi_info):
        super().__init__()
        self.window_list = window_list
        self.old_dpi_info = old_dpi_info
        self.new_dpi_info = new_dpi_info
        self._stop_requested = False

    def run(self):
        """执行窗口调整"""
        try:
            total_windows = len(self.window_list)
            adjusted_count = 0

            for i, window_info in enumerate(self.window_list):
                if self._stop_requested:
                    break

                hwnd = window_info.get('hwnd', 0)
                title = window_info.get('title', '')

                if hwnd:
                    success = self._adjust_window(hwnd, title)
                    if success:
                        adjusted_count += 1

                # 更新进度
                progress = int((i + 1) * 100 / total_windows)
                self.progress_updated.emit(progress)

                # 短暂延迟
                self.msleep(100)

            if self._stop_requested:
                self.adjustment_completed.emit(False, "调整被用户取消")
            else:
                success_rate = adjusted_count / total_windows if total_windows > 0 else 0
                if success_rate >= 0.8:
                    self.adjustment_completed.emit(True, f"成功调整 {adjusted_count}/{total_windows} 个窗口")
                else:
                    self.adjustment_completed.emit(False, f"仅成功调整 {adjusted_count}/{total_windows} 个窗口")

        except Exception as e:
            logger.error(f"窗口自动调整失败: {e}")
            self.adjustment_completed.emit(False, f"调整失败: {str(e)}")

    def _adjust_window(self, hwnd: int, title: str) -> bool:
        """调整单个窗口"""
        try:
            # 这里可以添加具体的窗口调整逻辑
            # 例如：重新计算窗口大小、位置等
            logger.info(f"正在调整窗口: {title} (HWND: {hwnd})")

            # 模拟调整过程
            self.msleep(50)

            return True

        except Exception as e:
            logger.error(f"调整窗口 {title} 失败: {e}")
            return False

    def stop(self):
        """停止调整"""
        self._stop_requested = True


class DPINotificationWidget(QWidget):
    """DPI变化通知组件"""

    # 信号
    recalibrate_requested = Signal()  # 请求重新校准
    dismiss_requested = Signal()      # 请求关闭通知
    auto_adjust_requested = Signal()  # 请求自动调整
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.adjustment_worker = None
        self.current_window_list = []
        self.current_old_dpi = None
        self.current_new_dpi = None
        self.setup_ui()
        self.setup_auto_hide()
    
    def setup_ui(self):
        """设置UI"""
        self.setFixedHeight(120)  # 增加高度以容纳进度条
        self.setStyleSheet("""
            QWidget {
                /* background-color removed - use theme */
                border: 1px solid #ffeaa7;
                border-radius: 4px;
            }
            QLabel {
                color: #856404;
                background: transparent;
                border: none;
            }
            QPushButton {
                background-color: #ffc107;
                border: 1px solid #ffb300;
                border-radius: 3px;
                padding: 4px 8px;
                color: #212529;
                font-weight: bold;
                min-width: 80px;
            }
            QPushButton:hover {
                background-color: #e0a800;
            }
            QPushButton:pressed {
                background-color: #d39e00;
            }
            QPushButton:disabled {
                background-color: #f8f9fa;
                color: #6c757d;
                border-color: #dee2e6;
            }
            QProgressBar {
                border: 1px solid #dee2e6;
                border-radius: 3px;
                text-align: center;
                background-color: #f8f9fa;
            }
            QProgressBar::chunk {
                background-color: #28a745;
                border-radius: 2px;
            }
        """)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(12)
        
        # 图标
        icon_label = QLabel("警告")
        icon_label.setFont(QFont("Segoe UI Emoji", 16))
        layout.addWidget(icon_label)
        
        # 消息区域
        message_layout = QVBoxLayout()
        message_layout.setSpacing(2)

        self.title_label = QLabel("检测到DPI变化")
        title_font = QFont()
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        message_layout.addWidget(self.title_label)

        self.detail_label = QLabel("窗口和OCR区域可能需要重新调整以确保准确识别")
        detail_font = QFont()
        detail_font.setPointSize(detail_font.pointSize() - 1)
        self.detail_label.setFont(detail_font)
        message_layout.addWidget(self.detail_label)

        # 进度条（初始隐藏）
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setMaximum(100)
        message_layout.addWidget(self.progress_bar)

        layout.addLayout(message_layout)

        # 弹簧
        layout.addStretch()

        # 按钮区域
        button_layout = QVBoxLayout()
        button_layout.setSpacing(4)

        # 第一行按钮
        button_row1 = QHBoxLayout()
        button_row1.setSpacing(4)

        self.auto_adjust_btn = QPushButton("自动调整")
        self.auto_adjust_btn.clicked.connect(self._on_auto_adjust_clicked)
        button_row1.addWidget(self.auto_adjust_btn)

        self.recalibrate_btn = QPushButton("手动校准")
        self.recalibrate_btn.clicked.connect(self.recalibrate_requested.emit)
        button_row1.addWidget(self.recalibrate_btn)

        button_layout.addLayout(button_row1)

        # 第二行按钮
        button_row2 = QHBoxLayout()
        button_row2.setSpacing(4)

        self.dismiss_btn = QPushButton("忽略")
        self.dismiss_btn.clicked.connect(self.dismiss_requested.emit)
        button_row2.addWidget(self.dismiss_btn)

        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.clicked.connect(self._on_cancel_clicked)
        self.cancel_btn.setVisible(False)  # 初始隐藏
        button_row2.addWidget(self.cancel_btn)

        button_layout.addLayout(button_row2)

        layout.addLayout(button_layout)
    
    def setup_auto_hide(self):
        """设置自动隐藏"""
        self.auto_hide_timer = QTimer(self)
        self.auto_hide_timer.timeout.connect(self.dismiss_requested.emit)
        self.auto_hide_timer.setSingleShot(True)
    
    def _on_auto_adjust_clicked(self):
        """处理自动调整按钮点击"""
        try:
            if not self.current_window_list:
                QMessageBox.warning(self, "无法调整", "没有找到需要调整的窗口")
                return

            # 开始自动调整
            self._start_auto_adjustment()

        except Exception as e:
            logger.error(f"启动自动调整失败: {e}")
            QMessageBox.critical(self, "错误", f"启动自动调整失败: {str(e)}")

    def _on_cancel_clicked(self):
        """处理取消按钮点击"""
        try:
            if self.adjustment_worker and self.adjustment_worker.isRunning():
                self.adjustment_worker.stop()
                self.adjustment_worker.wait(3000)  # 等待3秒

            self._reset_ui_state()

        except Exception as e:
            logger.error(f"取消自动调整失败: {e}")

    def _start_auto_adjustment(self):
        """开始自动调整"""
        try:
            # 更新UI状态
            self.auto_adjust_btn.setEnabled(False)
            self.recalibrate_btn.setEnabled(False)
            self.dismiss_btn.setVisible(False)
            self.cancel_btn.setVisible(True)
            self.progress_bar.setVisible(True)
            self.progress_bar.setValue(0)

            # 更新提示文本
            self.detail_label.setText("正在自动调整窗口，请稍候...")

            # 创建并启动工作线程
            self.adjustment_worker = WindowAdjustmentWorker(
                self.current_window_list,
                self.current_old_dpi,
                self.current_new_dpi
            )

            # 连接信号
            self.adjustment_worker.progress_updated.connect(self.progress_bar.setValue)
            self.adjustment_worker.adjustment_completed.connect(self._on_adjustment_completed)
            self.adjustment_worker.finished.connect(self._on_adjustment_worker_finished)

            # 启动线程
            self.adjustment_worker.start()

        except Exception as e:
            logger.error(f"启动自动调整失败: {e}")
            self._reset_ui_state()

    def _on_adjustment_completed(self, success: bool, message: str):
        """处理调整完成"""
        try:
            self._reset_ui_state()

            if success:
                self.detail_label.setText(f"成功 {message}")
                # 3秒后自动隐藏
                QTimer.singleShot(3000, self.hide_notification)
            else:
                self.detail_label.setText(f"错误 {message}")
                QMessageBox.warning(self, "调整结果", message)

        except Exception as e:
            logger.error(f"处理调整完成失败: {e}")

    def _on_adjustment_worker_finished(self):
        """自动调整线程结束清理"""
        worker = getattr(self, 'adjustment_worker', None)
        if not worker:
            return
        self.adjustment_worker = None
        try:
            worker.deleteLater()
        except RuntimeError:
            pass

    def _reset_ui_state(self):
        """重置UI状态"""
        try:
            self.auto_adjust_btn.setEnabled(True)
            self.recalibrate_btn.setEnabled(True)
            self.dismiss_btn.setVisible(True)
            self.cancel_btn.setVisible(False)
            self.progress_bar.setVisible(False)

        except Exception as e:
            logger.error(f"重置UI状态失败: {e}")

    def show_notification(self, old_dpi: int, new_dpi: int, window_list: list = None, auto_hide_seconds: int = 15):
        """
        显示DPI变化通知

        Args:
            old_dpi: 旧DPI值
            new_dpi: 新DPI值
            window_list: 受影响的窗口列表
            auto_hide_seconds: 自动隐藏秒数
        """
        old_scale = old_dpi / 96.0
        new_scale = new_dpi / 96.0

        # 保存当前状态
        self.current_window_list = window_list or []
        self.current_old_dpi = {'dpi': old_dpi, 'scale_factor': old_scale}
        self.current_new_dpi = {'dpi': new_dpi, 'scale_factor': new_scale}

        # 更新显示文本
        window_count = len(self.current_window_list)
        if window_count > 0:
            self.detail_label.setText(
                f"DPI从 {old_dpi} ({old_scale:.0%}) 变更为 {new_dpi} ({new_scale:.0%})，"
                f"影响 {window_count} 个窗口，建议进行调整"
            )
        else:
            self.detail_label.setText(
                f"DPI从 {old_dpi} ({old_scale:.0%}) 变更为 {new_dpi} ({new_scale:.0%})，"
                f"OCR区域可能需要重新校准"
            )

        # 重置UI状态
        self._reset_ui_state()

        # 根据窗口数量决定是否显示自动调整按钮
        self.auto_adjust_btn.setVisible(window_count > 0)

        show_and_raise_widget(self, log_prefix='DPI变化通知')

        # 启动自动隐藏定时器
        if auto_hide_seconds > 0:
            self.auto_hide_timer.start(auto_hide_seconds * 1000)
    
    def hide_notification(self):
        """隐藏通知"""
        self.auto_hide_timer.stop()
        self.hide()
