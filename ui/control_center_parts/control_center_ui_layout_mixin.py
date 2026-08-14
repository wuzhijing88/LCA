import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
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

from ui.scheduling.timer_form import fit_timer_spinbox
from .control_center_window_table_mixin import (
    COL_STATUS,
    COL_STEP,
    COL_TITLE,
    COL_WORKFLOW,
    WINDOW_TABLE_HEADERS,
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
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        layout.addLayout(self._create_toolbar())

        self.window_table = QTableWidget()
        self.window_table.setColumnCount(len(WINDOW_TABLE_HEADERS))
        self.window_table.setHorizontalHeaderLabels(list(WINDOW_TABLE_HEADERS))
        for column in range(self.window_table.columnCount()):
            header_item = self.window_table.horizontalHeaderItem(column)
            if header_item is None:
                continue
            header_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.window_table.setFrameShape(QFrame.Shape.NoFrame)
        self.window_table.setShowGrid(False)
        self.window_table.setWordWrap(False)
        self.window_table.setTextElideMode(Qt.TextElideMode.ElideRight)

        header = self.window_table.horizontalHeader()
        header.setFixedHeight(32)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setHighlightSections(False)
        header.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(72)
        header.setSectionResizeMode(COL_TITLE, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_WORKFLOW, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_STATUS, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_STEP, QHeaderView.ResizeMode.Stretch)

        self.window_table.verticalHeader().setVisible(False)
        self.window_table.verticalHeader().setDefaultSectionSize(34)
        self.window_table.setAlternatingRowColors(True)
        self.window_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.window_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.window_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.window_table.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.window_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.window_table.selectionModel().selectionChanged.connect(self.on_selection_changed)
        self.window_table.cellClicked.connect(self._on_window_table_cell_clicked)
        self.window_table.cellDoubleClicked.connect(self._on_window_table_double_clicked)
        self.window_table.customContextMenuRequested.connect(self._show_window_table_context_menu)

        self.window_table_frame = QFrame()
        self.window_table_frame.setProperty("tableCard", "true")
        table_layout = QVBoxLayout(self.window_table_frame)
        table_layout.setContentsMargins(1, 1, 1, 1)
        table_layout.setSpacing(0)
        table_layout.addWidget(self.window_table)
        layout.addWidget(self.window_table_frame, 1)

        layout.addLayout(self._create_status_bar())
        self.populate_window_table()
        return panel

    def _make_toolbar_button(self, text, tooltip, on_click, enabled=True, primary=False):
        button = QPushButton(text)
        button.setMinimumHeight(32)
        button.setMinimumWidth(72)
        button.setToolTip(tooltip)
        button.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        button.setEnabled(enabled)
        if primary:
            button.setProperty("primary", True)
        button.clicked.connect(on_click)
        return button

    def _create_toolbar(self):
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self.assign_btn = self._make_toolbar_button(
            "分配给选中",
            "给当前选中的窗口分配工作流",
            self.assign_workflow_to_selected,
            enabled=False,
        )
        self.assign_all_btn = self._make_toolbar_button(
            "一键分配",
            "给全部窗口分配同一份工作流",
            self.assign_workflow_to_all,
        )
        toolbar.addWidget(self.assign_btn)
        toolbar.addWidget(self.assign_all_btn)
        toolbar.addStretch(1)

        self.start_all_btn = self._make_toolbar_button(
            "开始",
            "启动已分配工作流的窗口；有选中时只启动选中",
            lambda _checked=False: self.start_all_tasks(),
            primary=True,
        )
        self.stop_all_btn = self._make_toolbar_button(
            "停止",
            "停止正在运行的窗口；有选中时只停止选中",
            lambda _checked=False: self.stop_all_tasks(),
        )
        self.pause_all_btn = self._make_toolbar_button(
            "暂停",
            "暂停或恢复正在运行的窗口 (F11)",
            lambda _checked=False: self.toggle_pause_all_tasks(),
        )
        self.timer_btn = self._make_toolbar_button(
            "定时",
            "设置定时启动、停止、暂停",
            self.open_timer_dialog,
        )
        toolbar.addWidget(self.start_all_btn)
        toolbar.addWidget(self.stop_all_btn)
        toolbar.addWidget(self.pause_all_btn)
        toolbar.addWidget(self.timer_btn)
        return toolbar

    def _create_status_bar(self):
        bar = QHBoxLayout()
        bar.setSpacing(12)

        bar.addWidget(QLabel("启动间隔"))
        self.delay_spinbox = QSpinBox()
        self.delay_spinbox.setRange(0, 300)
        self.delay_spinbox.setValue(0)
        self.delay_spinbox.setSuffix(" 秒")
        fit_timer_spinbox(self.delay_spinbox, min_width=90)
        self.delay_spinbox.setToolTip("每个窗口启动之间的间隔。0 表示默认 100ms")
        self.delay_spinbox.valueChanged.connect(self._on_delay_changed)
        bar.addWidget(self.delay_spinbox)

        self.timer_status_label = QLabel("定时：未启用")
        self.timer_status_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        bar.addWidget(self.timer_status_label, 1)

        self.selection_label = QLabel("未选择")
        self.selection_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        bar.addWidget(self.selection_label)
        return bar


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
