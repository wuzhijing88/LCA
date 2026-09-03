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
            "暂停或恢复正在运行的窗口",
            lambda _checked=False: self.toggle_pause_all_tasks(),
        )
        self.timer_btn = self._make_toolbar_button(
            "定时",
            "设置定时启动、停止、暂停",
            self.open_timer_dialog,
        )
        self.stability_test_btn = self._make_toolbar_button(
            "稳定性实测",
            "为每个窗口生成互不相同的全功能随机脚本并启动",
            self.run_stability_test,
        )
        toolbar.addWidget(self.start_all_btn)
        toolbar.addWidget(self.stop_all_btn)
        toolbar.addWidget(self.pause_all_btn)
        toolbar.addWidget(self.timer_btn)
        toolbar.addWidget(self.stability_test_btn)
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
        """注册开始/停止/暂停热键，键位跟随全局设置。"""
        self._refresh_shortcuts()

    def _refresh_shortcuts(self):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QKeySequence, QShortcut

        from app_core.hotkey_spec import display_hotkey
        from app_core.player.hotkey_runtime import install_global_player_hotkeys
        from .control_center_hotkeys import resolve_control_center_hotkeys, to_qt_shortcut_text

        self._release_control_center_hotkeys()
        get_parent_config = getattr(self, "_get_parent_config", None)
        config = get_parent_config() if callable(get_parent_config) else None
        hotkeys = resolve_control_center_hotkeys(config)
        callbacks = {
            "start": self.start_all_tasks,
            "stop": self.stop_all_tasks,
            "pause": self.toggle_pause_all_tasks,
        }
        session = install_global_player_hotkeys(self, hotkeys, callbacks)
        self._cc_hotkey_session = session
        self._cc_window_shortcuts = []
        if not session.keyboard_active:
            for action, callback in callbacks.items():
                text = to_qt_shortcut_text(hotkeys.get(action))
                if not text:
                    continue
                shortcut = QShortcut(QKeySequence(text), self)
                shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
                shortcut.activated.connect(callback)
                self._cc_window_shortcuts.append(shortcut)
        self._apply_hotkey_button_tooltips(hotkeys)
        logger.info(
            "中控软件：已按全局设置注册热键 start=%s stop=%s pause=%s",
            display_hotkey(hotkeys["start"]),
            display_hotkey(hotkeys["stop"]),
            display_hotkey(hotkeys["pause"]),
        )

    def _apply_hotkey_button_tooltips(self, hotkeys):
        from app_core.hotkey_spec import display_hotkey

        start_hint = display_hotkey(hotkeys.get("start"))
        stop_hint = display_hotkey(hotkeys.get("stop"))
        pause_hint = display_hotkey(hotkeys.get("pause"))
        if hasattr(self, "start_all_btn") and self.start_all_btn is not None:
            self.start_all_btn.setToolTip(f"启动已分配工作流的窗口；有选中时只启动选中 ({start_hint})")
        if hasattr(self, "stop_all_btn") and self.stop_all_btn is not None:
            self.stop_all_btn.setToolTip(f"停止正在运行的窗口；有选中时只停止选中 ({stop_hint})")
        if hasattr(self, "pause_all_btn") and self.pause_all_btn is not None:
            self.pause_all_btn.setToolTip(f"暂停或恢复正在运行的窗口 ({pause_hint})")

    def _release_control_center_hotkeys(self):
        session = getattr(self, "_cc_hotkey_session", None)
        if session is not None:
            try:
                session.release()
            except Exception:
                logger.debug("释放中控全局热键失败", exc_info=True)
        self._cc_hotkey_session = None
        for shortcut in list(getattr(self, "_cc_window_shortcuts", []) or []):
            try:
                shortcut.setEnabled(False)
                shortcut.deleteLater()
            except Exception:
                pass
        self._cc_window_shortcuts = []

    def _on_pause_shortcut(self):
        logger.info("=== 中控软件：暂停快捷键被触发 ===")
        self.toggle_pause_all_tasks()
