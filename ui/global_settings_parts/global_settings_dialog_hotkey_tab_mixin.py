from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from ..main_window_parts.main_window_dropdown_helpers import NoWheelSpinBox
from ..main_window_parts.main_window_dropdown_widget import CustomDropdown, QComboBox
from ..main_window_parts.main_window_support import get_secondary_text_color, normalize_execution_mode_setting


class GlobalSettingsDialogHotkeyTabMixin:
    def _create_hotkey_tab(self):

        """创建快捷键设置标签页"""

        hotkey_tab = QWidget()

        hotkey_layout = QVBoxLayout(hotkey_tab)

        hotkey_layout.setSpacing(8)

        hotkey_layout.setContentsMargins(10, 8, 10, 10)

        # --- Hotkey Settings Group ---

        self.hotkey_group = QGroupBox("快捷键配置")

        hotkey_main_layout = QVBoxLayout(self.hotkey_group)

        hotkey_main_layout.setSpacing(15)

        hotkey_main_layout.setContentsMargins(15, 15, 15, 15)

        # 第一行：启动任务、停止任务、暂停工作流、录制操作

        hotkey_row1_layout = QHBoxLayout()

        hotkey_row1_layout.setSpacing(20)

        # 第二行：回放操作

        hotkey_row2_layout = QHBoxLayout()

        hotkey_row2_layout.setSpacing(20)

        # 启动任务快捷键

        start_task_container = QVBoxLayout()

        start_task_label = QLabel("启动任务")

        start_task_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        start_task_label.setObjectName("hotkey_label")

        # 使用下拉选择框代替输入框

        self.start_task_hotkey = CustomDropdown(self)

        # 快捷键选项：显示文本 -> 实际值的映射

        hotkey_display_map = {

            'F1': 'F1', 'F2': 'F2', 'F3': 'F3', 'F4': 'F4',

            'F5': 'F5', 'F6': 'F6', 'F7': 'F7', 'F8': 'F8',

            'F9': 'F9', 'F10': 'F10', 'F11': 'F11', 'F12': 'F12',

            'Home': 'Home', 'End': 'End',

            'Insert': 'Insert', 'Delete': 'Delete',

            'PageUp': 'PageUp', 'PageDown': 'PageDown',

            'PrintScreen': 'PrintScreen', 'ScrollLock': 'ScrollLock', 'Pause': 'Pause',

            'NumLock': 'NumLock',

            '小键盘0': 'Num0', '小键盘1': 'Num1', '小键盘2': 'Num2', '小键盘3': 'Num3',

            '小键盘4': 'Num4', '小键盘5': 'Num5', '小键盘6': 'Num6', '小键盘7': 'Num7',

            '小键盘8': 'Num8', '小键盘9': 'Num9',

            '小键盘*': 'NumMultiply', '小键盘+': 'NumAdd', '小键盘-': 'NumSubtract',

            '小键盘/': 'NumDivide', '小键盘.': 'NumDecimal',

            '鼠标侧键1(后退)': 'XButton1',

            '鼠标侧键2(前进)': 'XButton2'

        }

        for display_text, value in hotkey_display_map.items():

            self.start_task_hotkey.addItem(display_text, value)

        # 设置当前值

        current_start_key = self.current_config.get('start_task_hotkey', 'XButton1')

        # 兼容可能保存了中文名称的情况

        chinese_to_code = {

            '鼠标侧键1(后退)': 'XButton1',

            '鼠标侧键2(前进)': 'XButton2'

        }

        if current_start_key in chinese_to_code:

            current_start_key = chinese_to_code[current_start_key]

        # 只对F键进行大写转换，XButton保持原样

        if current_start_key.startswith('F') and len(current_start_key) <= 3:

            current_start_key = current_start_key.upper()

        for i in range(self.start_task_hotkey.count()):

            if self.start_task_hotkey.itemData(i) == current_start_key:

                self.start_task_hotkey.setCurrentIndex(i)

                break

        self.start_task_hotkey.setToolTip("设置启动任务的快捷键\n支持: F1-F12功能键、导航键(Home/End/Insert/Delete等)、小键盘、鼠标侧键")

        self.start_task_hotkey.setFixedWidth(130)

        start_task_container.addWidget(start_task_label)

        start_task_container.addWidget(self.start_task_hotkey)

        # 停止任务快捷键

        stop_task_container = QVBoxLayout()

        stop_task_label = QLabel("停止任务")

        stop_task_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        stop_task_label.setObjectName("hotkey_label")

        # 使用下拉选择框代替输入框

        self.stop_task_hotkey = CustomDropdown(self)

        for display_text, value in hotkey_display_map.items():

            self.stop_task_hotkey.addItem(display_text, value)

        # 设置当前值

        current_stop_key = self.current_config.get('stop_task_hotkey', 'XButton2')

        # 兼容可能保存了中文名称的情况

        if current_stop_key in chinese_to_code:

            current_stop_key = chinese_to_code[current_stop_key]

        # 只对F键进行大写转换，XButton保持原样

        if current_stop_key.startswith('F') and len(current_stop_key) <= 3:

            current_stop_key = current_stop_key.upper()

        for i in range(self.stop_task_hotkey.count()):

            if self.stop_task_hotkey.itemData(i) == current_stop_key:

                self.stop_task_hotkey.setCurrentIndex(i)

                break

        self.stop_task_hotkey.setToolTip("设置停止任务的快捷键\n支持: F1-F12功能键、导航键(Home/End/Insert/Delete等)、小键盘、鼠标侧键")

        self.stop_task_hotkey.setFixedWidth(130)

        stop_task_container.addWidget(stop_task_label)

        stop_task_container.addWidget(self.stop_task_hotkey)

        # 录制快捷键

        record_container = QVBoxLayout()

        record_label = QLabel("录制操作")

        record_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        record_label.setObjectName("hotkey_label")

        # 使用下拉选择框

        self.record_hotkey = CustomDropdown(self)

        for display_text, value in hotkey_display_map.items():

            self.record_hotkey.addItem(display_text, value)

        # 设置当前值

        current_record_key = self.current_config.get('record_hotkey', 'F11')

        # 兼容可能保存了中文名称的情况

        if current_record_key in chinese_to_code:

            current_record_key = chinese_to_code[current_record_key]

        # 只对F键进行大写转换，XButton保持原样

        if current_record_key.startswith('F') and len(current_record_key) <= 3:

            current_record_key = current_record_key.upper()

        for i in range(self.record_hotkey.count()):

            if self.record_hotkey.itemData(i) == current_record_key:

                self.record_hotkey.setCurrentIndex(i)

                break

        self.record_hotkey.setToolTip("设置录制操作的快捷键\n仅在录制卡片参数面板打开时生效\n支持: F1-F12功能键、导航键(Home/End/Insert/Delete等)、小键盘、鼠标侧键")

        self.record_hotkey.setFixedWidth(130)

        record_container.addWidget(record_label)

        record_container.addWidget(self.record_hotkey)

        # 回放快捷键

        replay_container = QVBoxLayout()

        replay_label = QLabel("回放操作")

        replay_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        replay_label.setObjectName("hotkey_label")

        # 使用下拉选择框

        self.replay_hotkey = CustomDropdown(self)

        for display_text, value in hotkey_display_map.items():

            self.replay_hotkey.addItem(display_text, value)

        # 设置当前值

        current_replay_key = self.current_config.get('replay_hotkey', 'F12')

        # 兼容可能保存了中文名称的情况

        if current_replay_key in chinese_to_code:

            current_replay_key = chinese_to_code[current_replay_key]

        # 只对F键进行大写转换，XButton保持原样

        if current_replay_key.startswith('F') and len(current_replay_key) <= 3:

            current_replay_key = current_replay_key.upper()

        for i in range(self.replay_hotkey.count()):

            if self.replay_hotkey.itemData(i) == current_replay_key:

                self.replay_hotkey.setCurrentIndex(i)

                break

        self.replay_hotkey.setToolTip("设置回放操作的快捷键\n仅在录制回放卡片参数面板打开时生效\n支持: F1-F12功能键、导航键(Home/End/Insert/Delete等)、小键盘、鼠标侧键")

        self.replay_hotkey.setFixedWidth(130)

        replay_container.addWidget(replay_label)

        replay_container.addWidget(self.replay_hotkey)

        # 暂停工作流快捷键

        pause_container = QVBoxLayout()

        pause_label = QLabel("暂停工作流")

        pause_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        pause_label.setObjectName("hotkey_label")

        # 使用下拉选择框

        self.pause_workflow_hotkey = CustomDropdown(self)

        for display_text, value in hotkey_display_map.items():

            self.pause_workflow_hotkey.addItem(display_text, value)

        # 设置当前值

        current_pause_key = self.current_config.get('pause_workflow_hotkey', 'F11')

        # 兼容可能保存了中文名称的情况

        if current_pause_key in chinese_to_code:

            current_pause_key = chinese_to_code[current_pause_key]

        # 只对F键进行大写转换，XButton保持原样

        if current_pause_key.startswith('F') and len(current_pause_key) <= 3:

            current_pause_key = current_pause_key.upper()

        for i in range(self.pause_workflow_hotkey.count()):

            if self.pause_workflow_hotkey.itemData(i) == current_pause_key:

                self.pause_workflow_hotkey.setCurrentIndex(i)

                break

        self.pause_workflow_hotkey.setToolTip("设置暂停/恢复工作流的快捷键\n支持: F1-F12功能键、导航键(Home/End/Insert/Delete等)、小键盘、鼠标侧键")

        self.pause_workflow_hotkey.setFixedWidth(130)

        pause_container.addWidget(pause_label)

        pause_container.addWidget(self.pause_workflow_hotkey)

        # 第一行：启动任务、停止任务、暂停工作流、录制操作

        hotkey_row1_layout.addLayout(start_task_container)

        hotkey_row1_layout.addLayout(stop_task_container)

        hotkey_row1_layout.addLayout(pause_container)

        hotkey_row1_layout.addLayout(record_container)

        hotkey_row1_layout.addStretch()  # 添加弹性空间

        # 第二行：回放操作

        hotkey_row2_layout.addLayout(replay_container)

        hotkey_row2_layout.addStretch()  # 添加弹性空间

        # 添加两行到主布局

        hotkey_main_layout.addLayout(hotkey_row1_layout)

        hotkey_main_layout.addLayout(hotkey_row2_layout)

        hotkey_layout.addWidget(self.hotkey_group)

        hotkey_layout.addStretch()

        self.tab_widget.addTab(hotkey_tab, "快捷键设置")

