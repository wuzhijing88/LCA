"""
执行日志面板模块
主窗口缩小模式时显示工作流执行状态
"""
import time
import logging
import re
import os
from datetime import datetime
from app_core.config_sections import DEFAULT_HOTKEYS
from utils.app_paths import get_config_path, get_logs_dir
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTextEdit, QFrame, QSizePolicy, QSizeGrip,
    QMessageBox, QApplication, QGridLayout, QSlider
)
from PySide6.QtCore import Qt, Signal, Slot, QTimer, QSize, QEvent, QPoint
from PySide6.QtGui import (
    QColor, QPainter, QBrush, QIcon, QPixmap, QPen, QPalette,
    QDesktopServices, QCursor,
)
from PySide6.QtCore import QUrl
from ui.main_window_parts.main_window_support import (
    create_window_restore_icon,
    create_open_toolbar_icon,
    create_window_topmost_icon,
)
from utils.window.window_activation_utils import show_and_raise_widget

logger = logging.getLogger(__name__)

_STATUS_TEXT_MAP = {
    "failed": "失败",
    "success": "成功",
    "succeeded": "成功",
    "ok": "成功",
    "pass": "成功",
    "passed": "成功",
    "stopped": "已停止",
    "stop": "停止",
    "completed": "完成",
    "complete": "完成",
    "done": "完成",
    "no_next": "无后续",
    "paused": "已暂停",
    "running": "执行中",
    "error": "错误",
}

_STATUS_WORD_PATTERN = re.compile(r"\b(" + "|".join(_STATUS_TEXT_MAP.keys()) + r")\b", re.IGNORECASE)
_CARD_ID_PATTERN = re.compile(r"卡片ID\s*(?:=|：|:)\s*([^\s|；]+)")

def _translate_status_message(message: str) -> str:
    if not message:
        return message
    text = message.strip()
    if not text:
        return text
    text = re.sub(r"卡片ID\s*(?:=|：|:)\s*", "卡片ID：", text)
    lower = text.lower()
    if lower in _STATUS_TEXT_MAP:
        return _STATUS_TEXT_MAP[lower]

    def _replace(match: re.Match) -> str:
        return _STATUS_TEXT_MAP.get(match.group(0).lower(), match.group(0))

    return _STATUS_WORD_PATTERN.sub(_replace, text)


def _normalize_log_context(source: str, message: str) -> tuple[str, str]:
    source_text = re.sub(r"\s*/\s*", " · ", str(source or "").strip())
    message_text = _translate_status_message(message)

    card_id_match = re.search(r"(?:^|\s*\|\s*)卡片ID：\s*([^\s|]+)", message_text)
    if card_id_match:
        source_text = f"{source_text}（ID：{card_id_match.group(1)}）"
        message_text = (
            f"{message_text[:card_id_match.start()].rstrip()}"
            f"{message_text[card_id_match.end():].lstrip()}"
        ).strip(" |")
    message_text = re.sub(r"\s*\|\s*", "；", message_text)
    message_text = re.sub(
        r"(卡片名称|结果|下一步|步骤序号|耗时|总耗时|步骤数|成功|失败)\s*=\s*",
        r"\1：",
        message_text,
    )
    return source_text, message_text


def _format_log_line(timestamp: str, status: str, source: str, message: str) -> str:
    """按统一的中文日志格式生成一行日志。"""
    source_text, message_text = _normalize_log_context(source, message)
    if source_text and message_text:
        return f"[{timestamp}] [{status}] {source_text}：{message_text}"
    return f"[{timestamp}] [{status}] {source_text or message_text}"


def _format_workflow_finish(success: bool, message: str) -> tuple[str, str]:
    translated = _translate_status_message(message)
    if success:
        if translated in {"", "完成", "执行完成"}:
            return "完成", "执行完成"
        return "完成", f"执行完成：{translated}"
    if translated in {"", "停止", "已停止", "执行失败"}:
        return "停止", "执行停止"
    return "停止", f"执行停止：{translated}"


def _resolve_icon_color(enabled: bool = True) -> str:
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app:
        palette = app.palette()
        group = QPalette.ColorGroup.Active if enabled else QPalette.ColorGroup.Disabled
        return palette.color(group, QPalette.ColorRole.ButtonText).name()
    return "#e0e0e0" if enabled else "#aaaaaa"


def create_icon(icon_type: str, size: int = 16, color: str = None) -> QIcon:
    """创建简单的图标"""
    if color is None:
        color = _resolve_icon_color(True)
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidth(2)
    painter.setPen(pen)

    margin = 3
    if icon_type == "play":
        # 三角形播放图标
        points = [
            (margin + 1, margin),
            (size - margin, size // 2),
            (margin + 1, size - margin)
        ]
        painter.setBrush(QBrush(QColor(color)))
        from PySide6.QtGui import QPolygon
        from PySide6.QtCore import QPoint as QP
        polygon = QPolygon([QP(p[0], p[1]) for p in points])
        painter.drawPolygon(polygon)
    elif icon_type == "pause":
        # 双竖线暂停图标
        w = 3
        painter.fillRect(margin, margin, w, size - margin * 2, QColor(color))
        painter.fillRect(size - margin - w, margin, w, size - margin * 2, QColor(color))
    elif icon_type == "stop":
        # 方形停止图标
        painter.fillRect(margin, margin, size - margin * 2, size - margin * 2, QColor(color))
    elif icon_type == "expand":
        # 向下箭头
        painter.drawLine(margin, margin + 2, size // 2, size - margin - 2)
        painter.drawLine(size // 2, size - margin - 2, size - margin, margin + 2)
    elif icon_type == "collapse":
        # 向上箭头
        painter.drawLine(margin, size - margin - 2, size // 2, margin + 2)
        painter.drawLine(size // 2, margin + 2, size - margin, size - margin - 2)
    elif icon_type == "hide":
        # 叉号关闭图标
        painter.drawLine(margin, margin, size - margin, size - margin)
        painter.drawLine(size - margin, margin, margin, size - margin)

    painter.end()
    return QIcon(pixmap)


class StatusIndicator(QWidget):
    """状态指示器"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(8, 8)
        self._color = QColor("#808080")
        self._blinking = False
        self._blink_state = True

        self._blink_timer = QTimer(self)
        self._blink_timer.timeout.connect(self._toggle_blink)

    def set_running(self):
        self._color = QColor("#4CAF50")
        self._blinking = True
        self._blink_timer.start(500)
        self.update()

    def set_paused(self):
        self._blinking = False
        self._blink_timer.stop()
        self._color = QColor("#FFC107")
        self._blink_state = True
        self.update()

    def set_stopped(self):
        self._blinking = False
        self._blink_timer.stop()
        self._color = QColor("#808080")
        self._blink_state = True
        self.update()

    def _toggle_blink(self):
        self._blink_state = not self._blink_state
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._blink_state:
            painter.setBrush(QBrush(self._color))
        else:
            painter.setBrush(QBrush(self._color.darker(150)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(0, 0, 8, 8)


class LogView(QTextEdit):
    """日志显示（支持彩色文本）"""

    # 参数颜色映射
    _PARAM_COLORS = {
        # 状态标签颜色
        "成功": "#4CAF50",  # 绿色
        "失败": "#F44336",  # 红色
        "警告": "#FFC107",  # 黄色
        "信息": "#2196F3",  # 蓝色
        # 重要参数颜色
        "主卡片ID": "#FF9800",  # 橙色
        "子卡片ID": "#FFB74D",  # 浅橙色
        "卡片ID": "#FF9800",  # 橙色
        "目标文字": "#E91E63",  # 粉色
        "窗口": "#9C27B0",  # 紫色
        "置信度": "#00BCD4",  # 青色
        "操作": "#8BC34A",  # 浅绿色
        "图片": "#795548",  # 棕色
        "识别区域": "#607D8B",  # 蓝灰色
        "区域尺寸": "#607D8B",  # 蓝灰色
        "匹配": "#3F51B5",  # 靛蓝色
        "识别": "#009688",  # 蓝绿色
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.setUndoRedoEnabled(False)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._max_blocks = 100
        # 使用文档级环形块上限，避免日志文本在内存中持续累积
        self.document().setMaximumBlockCount(self._max_blocks)

    def appendColoredLog(self, log_text: str):
        """添加带颜色的日志"""
        colored_html = self._colorize_log(log_text)
        self.append(colored_html)

    def _colorize_log(self, text: str) -> str:
        """将日志文本转换为带颜色的HTML"""
        import html
        # 先转义HTML特殊字符
        escaped = html.escape(text)

        # 处理状态标签 [成功] [失败] 等
        for status, color in [("成功", "#4CAF50"), ("完成", "#4CAF50"),
                              ("失败", "#F44336"), ("停止", "#FFC107"),
                              ("警告", "#FFC107"), ("信息", "#2196F3")]:
            escaped = escaped.replace(
                f"[{status}]",
                f'<span style="color:{color};font-weight:bold;">[{status}]</span>'
            )

        # 处理参数名：值格式
        result = []
        parts = escaped.split(" | ")
        for i, part in enumerate(parts):
            separator = "：" if "：" in part else ("=" if "=" in part else "")
            if separator and i > 0:  # 跳过时间戳部分
                # 分离参数名和值
                separator_pos = part.find(separator)
                param_name = part[:separator_pos]
                param_value = part[separator_pos + 1:]

                # 查找匹配的颜色
                color = None
                for key, c in self._PARAM_COLORS.items():
                    if key in param_name:
                        color = c
                        break

                if color:
                    part = f'<span style="color:{color};">{param_name}</span>{separator}<span style="color:{color};">{param_value}</span>'
                else:
                    part = f'{param_name}{separator}{param_value}'
            result.append(part)

        return " | ".join(result)

    def clear(self):
        """清空日志"""
        super().clear()


class ExecutionLogPanel(QWidget):
    """执行日志面板"""

    request_start = Signal()
    request_pause = Signal()
    request_stop = Signal()
    request_restore = Signal()
    request_auto_log_enter = Signal()
    EXPANDED_HEIGHT = 420
    PANEL_WIDTH = 560
    MIN_PANEL_WIDTH = 420
    MIN_PANEL_HEIGHT = 220
    MIN_OPACITY = 30
    MAX_OPACITY = 100
    DEFAULT_OPACITY = 100

    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_running = False
        self._is_paused = False
        self._execution_log_file = None
        self._log_save_error = None
        self._execution_started_at = None
        self._step_started_at = {}
        self._step_sequence = 0
        self._step_success_count = 0
        self._step_failure_count = 0
        self._dragging = False
        self._drag_start_pos = QPoint()
        self._window_start_pos = QPoint()
        self._drag_event_application = None
        self._saved_window_size = self._load_saved_window_size()
        self._size_save_pending = False
        self._size_save_timer = QTimer(self)
        self._size_save_timer.setSingleShot(True)
        self._size_save_timer.setInterval(250)
        self._size_save_timer.timeout.connect(self._save_window_size)
        self._saved_opacity = self._load_saved_opacity()
        self._opacity_save_pending = False
        self._opacity_save_timer = QTimer(self)
        self._opacity_save_timer.setSingleShot(True)
        self._opacity_save_timer.setInterval(250)
        self._opacity_save_timer.timeout.connect(self._save_opacity)
        self._window_topmost = bool(self.window().windowFlags() & Qt.WindowType.WindowStaysOnTopHint)

        self._start_hotkey = DEFAULT_HOTKEYS["start_task_hotkey"]
        self._pause_hotkey = DEFAULT_HOTKEYS["pause_workflow_hotkey"]

        self._init_ui()
        self._load_hotkey_config()

        self.setMinimumSize(self.MIN_PANEL_WIDTH, self.MIN_PANEL_HEIGHT)
        # 注册主题切换回调
        self._register_theme_callback()

    def _register_theme_callback(self):
        """注册主题切换回调"""
        try:
            from themes import get_theme_manager
            theme_manager = get_theme_manager()
            self._theme_manager = theme_manager
            theme_manager.register_theme_change_callback(self._on_theme_changed)
        except Exception as e:
            logger.debug(f"注册主题回调失败: {e}")

    def cleanup(self):
        self._size_save_timer.stop()
        self._opacity_save_timer.stop()
        self._save_window_size()
        self._save_opacity()
        self.reset_window_opacity()
        self._clear_drag_tracking()
        theme_manager = getattr(self, "_theme_manager", None)
        if theme_manager is not None:
            theme_manager.unregister_theme_change_callback(self._on_theme_changed)
            self._theme_manager = None
        self._status_indicator._blink_timer.stop()

    def _load_saved_window_size(self):
        try:
            from app_core.config_store import load_config

            config = getattr(self.window(), "config", None)
            if not isinstance(config, dict):
                config = load_config()
            size_config = config.get("execution_log_panel_size")
            if not isinstance(size_config, dict):
                return None
            width = size_config.get("width")
            height = size_config.get("height")
            if isinstance(width, bool) or isinstance(height, bool):
                return None
            width = int(width)
            height = int(height)
            if width < self.MIN_PANEL_WIDTH or height < self.MIN_PANEL_HEIGHT:
                return None
            return QSize(width, height)
        except (TypeError, ValueError, OSError):
            return None

    def saved_window_size(self):
        if self._saved_window_size is None:
            return None
        return QSize(self._saved_window_size)

    def _load_saved_opacity(self):
        try:
            from app_core.config_store import load_config

            config = getattr(self.window(), "config", None)
            if not isinstance(config, dict):
                config = load_config()
            opacity = config.get("execution_log_panel_opacity", self.DEFAULT_OPACITY)
            if isinstance(opacity, bool):
                return self.DEFAULT_OPACITY
            opacity = int(opacity)
            if not self.MIN_OPACITY <= opacity <= self.MAX_OPACITY:
                return self.DEFAULT_OPACITY
            return opacity
        except (TypeError, ValueError, OSError):
            return self.DEFAULT_OPACITY

    def saved_opacity(self):
        return self._saved_opacity

    def _save_window_size(self):
        if not self._size_save_pending:
            return
        self._size_save_pending = False
        if self._saved_window_size is None:
            return
        try:
            from app_core.config_store import load_config, save_config

            config = getattr(self.window(), "config", None)
            if not isinstance(config, dict):
                config = load_config()
            config["execution_log_panel_size"] = {
                "width": self._saved_window_size.width(),
                "height": self._saved_window_size.height(),
            }
            save_config(config)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            logger.warning("保存执行日志框尺寸失败: %s", exc)

    def _save_opacity(self):
        if not self._opacity_save_pending:
            return
        self._opacity_save_pending = False
        try:
            from app_core.config_store import load_config, save_config

            config = getattr(self.window(), "config", None)
            if not isinstance(config, dict):
                config = load_config()
            config["execution_log_panel_opacity"] = self._saved_opacity
            save_config(config)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            logger.warning("保存执行日志框透明度失败: %s", exc)

    def _on_opacity_changed(self, opacity: int):
        self._saved_opacity = max(self.MIN_OPACITY, min(self.MAX_OPACITY, int(opacity)))
        self._opacity_value_label.setText(f"{self._saved_opacity}%")
        if getattr(self.window(), "_compact_log_mode", False):
            self.apply_window_opacity()
        self._opacity_save_pending = True
        self._opacity_save_timer.start()

    def apply_window_opacity(self):
        self.window().setWindowOpacity(self._saved_opacity / 100.0)

    def reset_window_opacity(self):
        self.window().setWindowOpacity(1.0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        main_window = self.window()
        if not self.isVisible() or not getattr(main_window, "_compact_log_mode", False):
            return
        self._saved_window_size = QSize(main_window.size())
        self._size_save_pending = True
        self._size_save_timer.start()

    def _on_theme_changed(self, theme_name: str = None):
        """主题切换时更新样式"""
        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app:
                self.setStyleSheet(app.styleSheet())
                self._update_button_states()
                self._btn_topmost.setIcon(create_window_topmost_icon(16))
                self._btn_restore.setIcon(create_window_restore_icon(16))
                self._btn_view_log.setIcon(create_open_toolbar_icon(16))
                logger.debug(f"执行日志面板主题已更新: {theme_name}")
        except Exception as e:
            logger.debug(f"更新执行日志面板主题失败: {e}")

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(0)

        # 容器
        self._container = QFrame()
        self._container.setObjectName("executionLogContainer")
        self._container.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        container_layout = QVBoxLayout(self._container)
        container_layout.setContentsMargins(12, 8, 12, 8)
        container_layout.setSpacing(0)

        # 头部
        header = QWidget()
        header.installEventFilter(self)
        self._drag_bar = header
        header_layout = QGridLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setHorizontalSpacing(0)
        header_layout.setVerticalSpacing(0)
        header_layout.setColumnStretch(0, 1)
        header_layout.setColumnStretch(2, 1)
        header_layout.setColumnMinimumWidth(0, 132)
        header_layout.setColumnMinimumWidth(2, 132)

        # 状态指示器
        self._status_indicator = StatusIndicator()
        self._status_label = QLabel("就绪")
        self._status_label.setObjectName("executionLogStatusLabel")
        status_widget = QWidget()
        status_layout = QHBoxLayout(status_widget)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(10)
        status_layout.addWidget(self._status_indicator)
        status_layout.addWidget(self._status_label)
        header_layout.addWidget(
            status_widget,
            0,
            0,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )

        # 控制按钮
        btn_widget = QWidget()
        btn_layout = QHBoxLayout(btn_widget)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(4)
        btn_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        btn_widget.setFixedWidth(132)

        self._btn_start = QPushButton()
        self._btn_start.setObjectName("executionLogCtrlBtn")
        self._btn_start.setFixedSize(28, 28)
        self._btn_start.setToolTip("开始")
        self._btn_start.setIcon(create_icon("play"))
        self._btn_start.setIconSize(QSize(16, 16))
        self._btn_start.clicked.connect(self._on_start_clicked)
        btn_layout.addWidget(self._btn_start)

        self._btn_pause = QPushButton()
        self._btn_pause.setObjectName("executionLogCtrlBtn")
        self._btn_pause.setFixedSize(28, 28)
        self._btn_pause.setToolTip("暂停")
        self._btn_pause.setIcon(create_icon("pause"))
        self._btn_pause.setIconSize(QSize(16, 16))
        self._btn_pause.clicked.connect(self._on_pause_clicked)
        btn_layout.addWidget(self._btn_pause)

        self._btn_stop = QPushButton()
        self._btn_stop.setObjectName("executionLogCtrlBtn")
        self._btn_stop.setFixedSize(28, 28)
        self._btn_stop.setToolTip("停止")
        self._btn_stop.setIcon(create_icon("stop"))
        self._btn_stop.setIconSize(QSize(16, 16))
        self._btn_stop.clicked.connect(self._on_stop_clicked)
        btn_layout.addWidget(self._btn_stop)

        header_layout.addWidget(btn_widget, 0, 1, Qt.AlignmentFlag.AlignCenter)

        utility_widget = QWidget()
        utility_layout = QHBoxLayout(utility_widget)
        utility_layout.setContentsMargins(0, 0, 0, 0)
        utility_layout.setSpacing(4)
        utility_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self._btn_topmost = QPushButton()
        self._btn_topmost.setObjectName("executionLogCtrlBtn")
        self._btn_topmost.setFixedSize(28, 28)
        self._btn_topmost.setCheckable(True)
        self._btn_topmost.setIcon(create_window_topmost_icon(16))
        self._btn_topmost.setIconSize(QSize(16, 16))
        self._btn_topmost.clicked.connect(self._toggle_topmost)
        utility_layout.addWidget(self._btn_topmost)

        self._btn_view_log = QPushButton()
        self._btn_view_log.setObjectName("executionLogCtrlBtn")
        self._btn_view_log.setFixedSize(28, 28)
        self._btn_view_log.setToolTip("打开日志文件夹")
        self._btn_view_log.setIcon(create_open_toolbar_icon(16))
        self._btn_view_log.setIconSize(QSize(16, 16))
        self._btn_view_log.clicked.connect(self._view_log_file)
        utility_layout.addWidget(self._btn_view_log)

        self._btn_restore = QPushButton()
        self._btn_restore.setObjectName("executionLogCtrlBtn")
        self._btn_restore.setFixedSize(28, 28)
        self._btn_restore.setToolTip("恢复主窗口")
        self._btn_restore.setIcon(create_window_restore_icon(16))
        self._btn_restore.setIconSize(QSize(16, 16))
        self._btn_restore.clicked.connect(self.request_restore.emit)
        utility_layout.addWidget(self._btn_restore)

        self._sync_topmost_button()

        header_layout.addWidget(
            utility_widget,
            0,
            2,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )

        container_layout.addWidget(header)

        # 日志区域
        self._log_panel = QWidget()
        self._log_panel.setVisible(True)
        self._log_panel.setObjectName("executionLogPanel")
        self._log_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        log_layout = QVBoxLayout(self._log_panel)
        log_layout.setContentsMargins(0, 8, 0, 0)
        log_layout.setSpacing(0)

        self._log_view = LogView()
        self._log_view.setObjectName("executionLogView")
        self._log_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        log_layout.addWidget(self._log_view, 1)

        container_layout.addWidget(self._log_panel, 1)
        main_layout.addWidget(self._container, 1)

        footer = QHBoxLayout()
        opacity_label = QLabel("透明度")
        self._opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setObjectName("executionLogOpacitySlider")
        self._opacity_slider.setRange(self.MIN_OPACITY, self.MAX_OPACITY)
        self._opacity_slider.setValue(self._saved_opacity)
        self._opacity_slider.setFixedWidth(110)
        self._opacity_slider.setFixedHeight(22)
        self._opacity_slider.setToolTip("调节日志框透明度")
        self._opacity_value_label = QLabel(f"{self._saved_opacity}%")
        self._opacity_value_label.setMinimumWidth(36)
        self._opacity_value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._opacity_slider.valueChanged.connect(self._on_opacity_changed)
        footer.addWidget(opacity_label, 0, Qt.AlignmentFlag.AlignVCenter)
        footer.addWidget(self._opacity_slider, 0, Qt.AlignmentFlag.AlignVCenter)
        footer.addWidget(self._opacity_value_label, 0, Qt.AlignmentFlag.AlignVCenter)
        footer.addStretch(1)
        self._size_grip = QSizeGrip(self)
        footer.addWidget(self._size_grip, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        main_layout.addLayout(footer)

        self._update_button_states()

    def _sync_topmost_button(self):
        self._window_topmost = bool(self.window().windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        self._btn_topmost.setChecked(self._window_topmost)
        self._btn_topmost.setToolTip("取消置顶" if self._window_topmost else "窗口置顶")
        title_bar = getattr(self.window(), "title_bar", None)
        sync_topmost_state = getattr(title_bar, "set_topmost_state", None)
        if callable(sync_topmost_state):
            sync_topmost_state(self._window_topmost)

    def _toggle_topmost(self):
        self._window_topmost = not self._window_topmost
        self.window().setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self._window_topmost)
        self._sync_topmost_button()
        show_and_raise_widget(self.window(), log_prefix="执行日志框置顶切换")

    def _load_hotkey_config(self):
        try:
            import json
            import os
            config_path = get_config_path()
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                self._start_hotkey = config.get('start_task_hotkey', DEFAULT_HOTKEYS['start_task_hotkey'])
                self._pause_hotkey = config.get('pause_workflow_hotkey', DEFAULT_HOTKEYS['pause_workflow_hotkey'])
        except Exception as e:
            logger.warning(f"加载快捷键配置失败: {e}")

    def _update_button_states(self):
        if self._is_running:
            if self._is_paused:
                # 暂停状态：开始按钮可用(用于恢复)，暂停按钮禁用
                self._btn_start.setEnabled(True)
                self._btn_start.setIcon(create_icon("play", color=_resolve_icon_color(True)))
                self._btn_start.setToolTip("恢复执行")
                self._btn_pause.setEnabled(False)
            else:
                # 运行状态：开始按钮禁用，暂停按钮可用
                self._btn_start.setEnabled(False)
                self._btn_start.setIcon(create_icon("play", color=_resolve_icon_color(False)))
                self._btn_start.setToolTip("开始")
                self._btn_pause.setEnabled(True)
            self._btn_stop.setEnabled(True)
            self._btn_pause.setIcon(create_icon("pause", color=_resolve_icon_color(self._btn_pause.isEnabled())))
            self._btn_pause.setToolTip("暂停")
        else:
            # 未运行状态
            self._btn_start.setEnabled(True)
            self._btn_start.setIcon(create_icon("play", color=_resolve_icon_color(True)))
            self._btn_start.setToolTip("开始")
            self._btn_pause.setEnabled(False)
            self._btn_stop.setEnabled(False)
            self._btn_pause.setIcon(create_icon("pause", color=_resolve_icon_color(False)))
            self._btn_pause.setToolTip("暂停")
        self._btn_stop.setIcon(create_icon("stop", color=_resolve_icon_color(self._btn_stop.isEnabled())))
        self._opacity_slider.setEnabled(not self._is_running or self._is_paused)

    def show_logs(self):
        self._sync_topmost_button()
        self._log_panel.setVisible(True)
        self.setMinimumSize(self.MIN_PANEL_WIDTH, self.MIN_PANEL_HEIGHT)
        self.setMaximumSize(16777215, 16777215)
        self.apply_window_opacity()

    def _append_execution_log(self, timestamp, status, source, message, display_limit=None):
        if self._log_save_error is None:
            try:
                if self._execution_log_file is None:
                    self._execution_log_file = os.path.join(
                        get_logs_dir("LCA"),
                        f"execution_{datetime.now():%Y%m%d}.log",
                    )
                with open(self._execution_log_file, "a", encoding="utf-8") as log_file:
                    log_file.write(_format_log_line(timestamp, status, source, message) + "\n")
            except OSError as exc:
                self._log_save_error = str(exc)
                logger.exception("自动保存执行日志失败")
                self._log_view.appendColoredLog(
                    _format_log_line(timestamp, "警告", "日志保存", f"自动保存失败，日志文件可能不完整：{exc}")
                )
        display_message = message
        if display_limit is not None and len(display_message) > display_limit:
            display_message = display_message[:display_limit - 3] + "..."
        self._log_view.appendColoredLog(_format_log_line(timestamp, status, source, display_message))

    def _enrich_step_log(self, card_type: str, message: str, success: bool) -> str:
        if message.startswith("自定义日志："):
            return message
        card_id_match = _CARD_ID_PATTERN.search(message)
        if card_id_match is None:
            return message
        step_key = (str(card_type or "").strip(), card_id_match.group(1))
        is_start_log = "开始执行" in message and "执行成功" not in message and "执行失败" not in message
        if is_start_log:
            self._step_sequence += 1
            self._step_started_at[step_key] = time.monotonic()
            return f"{message} | 步骤序号：{self._step_sequence}"

        sequence = self._step_sequence
        started_at = self._step_started_at.pop(step_key, None)
        if success:
            self._step_success_count += 1
        else:
            self._step_failure_count += 1
        duration_text = ""
        if started_at is not None:
            duration_text = f" | 耗时：{max(0.0, time.monotonic() - started_at):.2f}秒"
        return f"{message} | 步骤序号：{sequence}{duration_text}"

    def _view_log_file(self):
        log_dir = get_logs_dir("LCA")
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(log_dir)):
            QMessageBox.warning(self.window(), "打开日志文件夹失败", "系统无法打开日志文件夹。")

    def _begin_drag_tracking(self) -> None:
        self._dragging = True
        self._drag_start_pos = QCursor.pos()
        self._window_start_pos = self.window().pos()
        application = QApplication.instance()
        if application is not None:
            application.installEventFilter(self)
            self._drag_event_application = application

    def _clear_drag_tracking(self) -> None:
        self._dragging = False
        application = self._drag_event_application
        if application is not None:
            try:
                application.removeEventFilter(self)
            except RuntimeError:
                pass
            self._drag_event_application = None

    def is_drag_active(self) -> bool:
        return self._dragging

    def _move_drag_to_cursor(self, cursor_pos: QPoint) -> None:
        delta = cursor_pos - self._drag_start_pos
        target_pos = self._window_start_pos + delta
        if target_pos != self.window().pos():
            self.window().move(target_pos)

    def _finish_drag(self) -> None:
        if self._dragging:
            self._clear_drag_tracking()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.MouseButtonPress and watched is self._drag_bar and event.button() == Qt.MouseButton.LeftButton:
            if self._is_running and not self._is_paused:
                return False
            self._begin_drag_tracking()
            return True
        if self._dragging and event.type() == QEvent.Type.MouseMove and event.buttons() & Qt.MouseButton.LeftButton:
            if watched is self._drag_bar or watched is not self:
                self._move_drag_to_cursor(event.globalPosition().toPoint())
                return True
        if self._dragging and event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            self._finish_drag()
        return super().eventFilter(watched, event)

    def _on_start_clicked(self):
        if self._is_paused:
            # 暂停状态下点击开始按钮，发送恢复信号
            self.request_pause.emit()
        else:
            self.request_start.emit()

    def _on_pause_clicked(self):
        self.request_pause.emit()

    def _on_stop_clicked(self):
        self.request_stop.emit()

    @Slot(str, str)
    def on_step_started(self, card_type: str, card_name: str):
        text = f"{card_type}: {card_name}" if card_name else card_type
        if len(text) > 40:
            text = text[:37] + "..."
        self._status_label.setText(text)

    @Slot(str, str, bool)
    def on_step_log(self, card_type: str, message: str, success: bool):
        try:
            timestamp = time.strftime("%H:%M:%S")
            message = _translate_status_message(message)
            message = self._enrich_step_log(card_type, message, success)
            is_start_log = "开始执行" in message and "执行成功" not in message and "执行失败" not in message
            is_custom_log = message.startswith("自定义日志：")
            status = "信息" if is_start_log or is_custom_log else ("成功" if success else "失败")
            self._append_execution_log(timestamp, status, card_type, message, display_limit=200)
            # 确保滚动到底部
            self._log_view.verticalScrollBar().setValue(
                self._log_view.verticalScrollBar().maximum()
            )
        except Exception as e:
            logger.error(f"on_step_log error: {e}")

    @Slot()
    def on_execution_started(self):
        self._finish_drag()
        if not self._is_running:
            self._execution_log_file = os.path.join(
                get_logs_dir("LCA"),
                f"execution_{datetime.now():%Y%m%d}.log",
            )
            self._log_save_error = None
            self._execution_started_at = time.monotonic()
            self._step_started_at.clear()
            self._step_sequence = 0
            self._step_success_count = 0
            self._step_failure_count = 0
        self._is_running = True
        self._is_paused = False
        self._status_indicator.set_running()
        self._status_label.setText("执行中...")
        self._update_button_states()
        # 添加开始日志
        timestamp = time.strftime("%H:%M:%S")
        self._append_execution_log(timestamp, "信息", "主工作流", "开始执行")

    @Slot(bool, str)
    def on_execution_finished(self, success: bool, message: str):
        self._apply_execution_finished(success, message)

    def _apply_execution_finished(self, success: bool, message: str):
        self._is_running = False
        self._is_paused = False
        self._status_indicator.set_stopped()
        if success:
            self._status_label.setText("执行完成")
        else:
            translated = _translate_status_message(message)
            msg = translated[:20] + "..." if len(translated) > 20 else translated
            self._status_label.setText(f"已停止: {msg}" if msg else "已停止")
        self._update_button_states()
        # 添加结束日志
        timestamp = time.strftime("%H:%M:%S")
        status, finish_message = _format_workflow_finish(success, message)
        elapsed_text = ""
        if self._execution_started_at is not None:
            elapsed_text = f"；总耗时：{max(0.0, time.monotonic() - self._execution_started_at):.2f}秒"
        finish_message = (
            f"{finish_message}；步骤数：{self._step_sequence}；"
            f"成功：{self._step_success_count}；失败：{self._step_failure_count}"
            f"{elapsed_text}"
        )
        self._append_execution_log(timestamp, status, "主工作流", finish_message, display_limit=200)

    @Slot()
    def on_execution_paused(self):
        self._is_paused = True
        self._status_indicator.set_paused()
        self._status_label.setText("已暂停")
        self._update_button_states()

    @Slot()
    def on_execution_resumed(self):
        self._finish_drag()
        self._is_paused = False
        self._status_indicator.set_running()
        self._status_label.setText("执行中...")
        self._update_button_states()

    def reset(self):
        self._is_running = False
        self._is_paused = False
        self._status_indicator.set_stopped()
        self._status_label.setText("就绪")
        self._log_view.clear()
        self._update_button_states()

    def clear_logs(self):
        self._log_view.clear()

    def set_enabled(self, enabled: bool):
        return None

    def on_main_window_state_changed(self, minimized: bool):
        return None

    def on_workflow_started(self):
        if not self._is_running:
            self.clear_logs()
        self.on_execution_started()
        self.request_auto_log_enter.emit()

    def on_workflow_finished(self, success: bool, message: str):
        self.on_execution_finished(success, message)

    def on_workflow_paused(self):
        self.on_execution_paused()

    def on_workflow_resumed(self):
        self.on_execution_resumed()



