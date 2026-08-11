import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


class ControlCenterUiLayoutMixin:

    def init_ui(self):
        """初始化用户界面"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        self.log_output = None

        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        window_panel = self.create_window_panel()
        main_layout.addWidget(window_panel)

    def create_window_panel(self):
        """创建窗口状态面板"""
        group = QGroupBox("绑定窗口管理")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(15, 10, 15, 10)
        layout.setSpacing(8)

        info_label = QLabel("为每个窗口分配工作流并控制执行")
        layout.addWidget(info_label)
        layout.addSpacing(5)

        self.window_table = QTableWidget()
        self.window_table.setColumnCount(5)
        self.window_table.setHorizontalHeaderLabels([
            "窗口标题", "句柄", "分配的工作流", "状态", "当前步骤"
        ])
        for column in range(self.window_table.columnCount()):
            header_item = self.window_table.horizontalHeaderItem(column)
            if header_item is None:
                continue
            header_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        self.window_table.setFrameShape(QFrame.Shape.NoFrame)
        self.window_table.setShowGrid(False)
        self.window_table.setWordWrap(False)

        header = self.window_table.horizontalHeader()
        header.setFixedHeight(32)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        header.setHighlightSections(False)
        header.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)

        self.window_table.verticalHeader().setVisible(False)
        self.window_table.verticalHeader().setDefaultSectionSize(34)
        self.window_table.setAlternatingRowColors(True)
        self.window_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.window_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.window_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.window_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.window_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.window_table.selectionModel().selectionChanged.connect(self.on_selection_changed)
        self.window_table.cellDoubleClicked.connect(self._on_window_table_double_clicked)
        self.window_table.customContextMenuRequested.connect(self._show_window_table_context_menu)

        self.window_table_frame = QFrame()
        self.window_table_frame.setProperty("tableCard", "true")
        table_layout = QVBoxLayout(self.window_table_frame)
        table_layout.setContentsMargins(1, 1, 1, 1)
        table_layout.setSpacing(0)
        table_layout.addWidget(self.window_table)
        layout.addWidget(self.window_table_frame)

        button_panel = self.create_button_panel()
        layout.addWidget(button_panel)

        self.populate_window_table()
        return group

    def create_button_panel(self):
        """创建独立的按钮操作面板"""
        panel = QGroupBox("窗口操作")
        main_layout = QVBoxLayout(panel)
        main_layout.setContentsMargins(15, 10, 15, 10)
        main_layout.setSpacing(8)

        action_layout = QHBoxLayout()
        action_layout.setSpacing(8)

        self.assign_btn = QPushButton("分配工作流")
        self.assign_btn.setMinimumHeight(35)
        self.assign_btn.setMinimumWidth(108)
        self.assign_btn.setToolTip("为选中的窗口分配工作流文件")
        self.assign_btn.clicked.connect(self.assign_workflow_to_selected)
        self.assign_btn.setEnabled(False)
        action_layout.addWidget(self.assign_btn)

        self.assign_all_btn = QPushButton("一键分配全部")
        self.assign_all_btn.setMinimumHeight(35)
        self.assign_all_btn.setMinimumWidth(126)
        self.assign_all_btn.setToolTip("为所有窗口分配相同的工作流文件")
        self.assign_all_btn.clicked.connect(self.assign_workflow_to_all)
        self.assign_all_btn.setObjectName("assignAllButton")
        action_layout.addWidget(self.assign_all_btn)

        self.start_all_btn = QPushButton("全部开始")
        self.start_all_btn.setMinimumHeight(35)
        self.start_all_btn.setMinimumWidth(108)
        self.start_all_btn.setToolTip("启动所有已分配工作流的窗口")
        self.start_all_btn.clicked.connect(lambda _checked=False: self.start_all_tasks())
        action_layout.addWidget(self.start_all_btn)

        self.stop_all_btn = QPushButton("停止全部")
        self.stop_all_btn.setMinimumHeight(35)
        self.stop_all_btn.setMinimumWidth(108)
        self.stop_all_btn.setToolTip("通过主程序停止所有正在运行的工作流")
        self.stop_all_btn.clicked.connect(lambda _checked=False: self.stop_all_tasks())
        self.stop_all_btn.setObjectName("stopAllButton")
        action_layout.addWidget(self.stop_all_btn)

        self.pause_all_btn = QPushButton("暂停全部")
        self.pause_all_btn.setMinimumHeight(35)
        self.pause_all_btn.setMinimumWidth(108)
        self.pause_all_btn.setToolTip("暂停/恢复所有正在运行的工作流 (F11)")
        self.pause_all_btn.clicked.connect(lambda _checked=False: self.toggle_pause_all_tasks())
        self.pause_all_btn.setObjectName("pauseAllButton")
        action_layout.addWidget(self.pause_all_btn)

        self.timer_btn = QPushButton("定时设置")
        self.timer_btn.setMinimumHeight(35)
        self.timer_btn.setMinimumWidth(108)
        self.timer_btn.setToolTip("设置中控定时启动/停止/暂停")
        self.timer_btn.clicked.connect(self.open_timer_dialog)
        action_layout.addWidget(self.timer_btn)
        action_layout.addStretch(1)

        for btn in [self.assign_btn, self.assign_all_btn, self.start_all_btn, self.stop_all_btn, self.pause_all_btn, self.timer_btn]:
            btn.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        main_layout.addLayout(action_layout)

        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(8)

        delay_label = QLabel("启动间隔:")
        bottom_layout.addWidget(delay_label)

        self.delay_spinbox = QSpinBox()
        self.delay_spinbox.setRange(0, 300)
        self.delay_spinbox.setValue(0)
        self.delay_spinbox.setSuffix(" 秒")
        self.delay_spinbox.setMinimumWidth(90)
        self.delay_spinbox.setToolTip("设置每个窗口启动之间的间隔时间（秒）\n0 = 默认启动间隔100ms")
        self.delay_spinbox.valueChanged.connect(self._on_delay_changed)
        bottom_layout.addWidget(self.delay_spinbox)

        self.timer_status_label = QLabel("定时：未启用")
        self.timer_status_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.timer_status_label.setMinimumWidth(220)
        self.timer_status_label.setWordWrap(True)
        bottom_layout.addWidget(self.timer_status_label, 1)

        self.selection_label = QLabel("未选择窗口时，批量操作将作用于全部窗口")
        self.selection_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.selection_label.setMinimumWidth(220)
        self.selection_label.setWordWrap(True)
        self.selection_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        bottom_layout.addWidget(self.selection_label, 1)

        main_layout.addLayout(bottom_layout)
        return panel


    def _on_delay_changed(self, value):
        """启动间隔延迟值变化时的处理"""
        if value > 0:
            self._window_start_delay_sec = value
            logger.info(f"设置窗口启动间隔延迟: {value}秒")
        else:
            self._window_start_delay_sec = None
            logger.info("窗口启动间隔延迟已重置为默认值(100ms)")



    def _setup_shortcuts(self):
        """设置快捷键"""
        from PySide6.QtGui import QShortcut, QKeySequence
        from PySide6.QtCore import Qt

        # F9 - 全部启动
        self.start_all_shortcut = QShortcut(QKeySequence("F9"), self)
        self.start_all_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self.start_all_shortcut.activated.connect(self.start_all_tasks)
        logger.info("中控软件：已注册F9快捷键（全部启动）")

        # F10 - 全部停止
        self.stop_all_shortcut = QShortcut(QKeySequence("F10"), self)
        self.stop_all_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self.stop_all_shortcut.activated.connect(self.stop_all_tasks)
        logger.info("中控软件：已注册F10快捷键（全部停止）")

        # F11 - 全部暂停/恢复
        self.pause_all_shortcut = QShortcut(QKeySequence("F11"), self)
        self.pause_all_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self.pause_all_shortcut.activated.connect(self._on_pause_shortcut)
        logger.info("中控软件：已注册F11快捷键（全部暂停/恢复）")

    def _on_pause_shortcut(self):
        """F11快捷键回调"""
        logger.info("=== 中控软件：F11快捷键被触发 ===")
        self.toggle_pause_all_tasks()
