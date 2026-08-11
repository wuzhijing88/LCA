import logging

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from utils.window_coordinate_common import center_window_on_widget_screen

logger = logging.getLogger(__name__)


class MainWindowTimerDialogMixin:
        def _get_combo_data(self, combo):

            """从QComboBox获取数据，兼容currentData方法"""

            if combo is None:

                return None

            current_index = combo.currentIndex()

            if current_index >= 0:

                data = combo.itemData(current_index)

                if data is not None:

                    return data

            return combo.currentText() if hasattr(combo, 'currentText') else None

        def open_timer_dialog(self):

            """打开定时器设置对话框"""

            from .main_window_dropdown_helpers import NoWheelSpinBox
            from .main_window_dropdown_widget import QComboBox

            dialog = QDialog(self)

            dialog.setWindowTitle("定时任务")

            dialog.setModal(True)

            dialog.setMinimumWidth(660)

            dialog.setMaximumWidth(800)

            dialog.setMinimumHeight(420)

            dialog.setMaximumHeight(620)

            dialog.resize(720, 500)

            dialog.setSizeGripEnabled(True)

            main_layout = QVBoxLayout(dialog)

            main_layout.setSpacing(10)

            main_layout.setContentsMargins(15, 15, 15, 15)

            tab_widget = QTabWidget()

            tab_widget.setUsesScrollButtons(True)

            main_layout.addWidget(tab_widget)

            # =======================================

            # 标签页1: 定时停止

            # =======================================

            stop_tab = QWidget()

            stop_tab_layout = QVBoxLayout(stop_tab)

            stop_tab_layout.setSpacing(10)

            stop_tab_layout.setContentsMargins(15, 15, 15, 15)

            # --- 定时停止设置组 ---

            stop_settings_group = QGroupBox("停止时间设置")

            stop_settings_layout = QVBoxLayout(stop_settings_group)

            stop_settings_layout.setSpacing(8)

            stop_settings_layout.setContentsMargins(15, 10, 15, 10)

            # 启用复选框

            enable_checkbox = QCheckBox("启用定时停止")

            enable_checkbox.setChecked(self._global_timer_enabled)

            stop_settings_layout.addWidget(enable_checkbox)

            # 定时器选项容器

            timer_options_container = QWidget()

            timer_options_layout = QVBoxLayout(timer_options_container)

            timer_options_layout.setContentsMargins(0, 5, 0, 0)

            timer_options_layout.setSpacing(12)

            # 停止时间设置

            stop_time_layout = QHBoxLayout()

            stop_time_layout.setSpacing(8)

            stop_time_label = QLabel("停止时间:")

            stop_time_label.setFixedWidth(80)

            stop_hour_spinbox = NoWheelSpinBox()

            stop_hour_spinbox.setRange(0, 23)

            stop_hour_spinbox.setValue(getattr(self, '_stop_hour', 17))

            stop_hour_spinbox.setSuffix(" 时")

            stop_time_colon = QLabel(":")

            stop_minute_spinbox = NoWheelSpinBox()

            stop_minute_spinbox.setRange(0, 59)

            stop_minute_spinbox.setValue(getattr(self, '_stop_minute', 0))

            stop_minute_spinbox.setSuffix(" 分")

            stop_time_layout.addWidget(stop_time_label)

            stop_time_layout.addWidget(stop_hour_spinbox)

            stop_time_layout.addWidget(stop_time_colon)

            stop_time_layout.addWidget(stop_minute_spinbox)

            stop_time_layout.addStretch(1)

            timer_options_layout.addLayout(stop_time_layout)

            # 重复模式设置

            stop_repeat_layout = QHBoxLayout()

            stop_repeat_layout.setSpacing(8)

            stop_repeat_label = QLabel("重复模式:")

            stop_repeat_label.setFixedWidth(80)

            stop_repeat_combo = QComboBox(dialog)

            stop_repeat_combo.addItem("仅一次", "once")

            stop_repeat_combo.addItem("每天", "daily")

            stop_repeat_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)

            current_stop_repeat = getattr(self, '_stop_repeat', 'daily')

            index = stop_repeat_combo.findData(current_stop_repeat)

            if index >= 0:

                stop_repeat_combo.setCurrentIndex(index)

            stop_repeat_layout.addWidget(stop_repeat_label)

            stop_repeat_layout.addWidget(stop_repeat_combo)

            stop_repeat_layout.addStretch(1)

            timer_options_layout.addLayout(stop_repeat_layout)

            # 状态显示标签

            stop_status_label = QLabel()

            stop_status_label.setObjectName("timer_status_label")

            timer_options_layout.addWidget(stop_status_label)

            # 更新状态显示函数

            def update_stop_status():

                if enable_checkbox.isChecked():

                    hour = stop_hour_spinbox.value()

                    minute = stop_minute_spinbox.value()

                    repeat_mode = self._get_combo_data(stop_repeat_combo) or stop_repeat_combo.currentText()

                    if repeat_mode == 'once':

                        stop_status_label.setText(f"将于 {hour:02d}:{minute:02d} 停止（仅一次）")

                    else:

                        stop_status_label.setText(f"将在每天 {hour:02d}:{minute:02d} 停止")

                    stop_status_label.setProperty("status", "active")

                else:

                    stop_status_label.setText("定时停止未启用")

                    stop_status_label.setProperty("status", "inactive")

                stop_status_label.style().unpolish(stop_status_label)

                stop_status_label.style().polish(stop_status_label)

            # 连接信号

            enable_checkbox.toggled.connect(update_stop_status)

            stop_hour_spinbox.valueChanged.connect(update_stop_status)

            stop_minute_spinbox.valueChanged.connect(update_stop_status)

            stop_repeat_combo.currentIndexChanged.connect(update_stop_status)

            # 初始化状态显示

            update_stop_status()

            stop_settings_layout.addWidget(timer_options_container)

            # 根据"启用定时停止"复选框状态显示/隐藏定时器参数

            timer_options_container.setVisible(enable_checkbox.isChecked())

            # 连接"启用定时停止"复选框状态改变事件

            def on_enable_checkbox_changed(state):

                timer_options_container.setVisible(state == 2)  # 2 = Qt.Checked

                update_stop_status()

            enable_checkbox.stateChanged.connect(on_enable_checkbox_changed)

            stop_tab_layout.addWidget(stop_settings_group)

            stop_tab_layout.addStretch()  # 添加弹性空间

            # =======================================

            # 标签页2: 定时启动

            # =======================================

            start_tab = QWidget()

            start_tab_layout = QVBoxLayout(start_tab)

            start_tab_layout.setSpacing(10)

            start_tab_layout.setContentsMargins(15, 15, 15, 15)

            # --- 定时启动设置组 ---

            start_settings_group = QGroupBox("启动设置")

            start_settings_layout = QVBoxLayout(start_settings_group)

            start_settings_layout.setSpacing(8)

            start_settings_layout.setContentsMargins(15, 10, 15, 10)

            # 启用定时启动复选框

            schedule_enable_checkbox = QCheckBox("启用定时启动")

            schedule_enable_checkbox.setChecked(self._schedule_enabled)

            start_settings_layout.addWidget(schedule_enable_checkbox)

            # 定时启动选项容器

            schedule_options_container = QWidget()

            schedule_options_layout = QVBoxLayout(schedule_options_container)

            schedule_options_layout.setSpacing(12)

            schedule_options_layout.setContentsMargins(0, 5, 0, 0)

            schedule_mode_layout = QHBoxLayout()

            schedule_mode_layout.setSpacing(8)

            schedule_mode_label = QLabel("启动方式:")

            schedule_mode_label.setFixedWidth(80)

            schedule_mode_combo = QComboBox(dialog)

            schedule_mode_combo.addItem("按时间点", "fixed_time")

            schedule_mode_combo.addItem("按间隔", "interval")

            current_schedule_mode = str(getattr(self, '_schedule_mode', 'fixed_time') or '').strip().lower()

            mode_index = schedule_mode_combo.findData(current_schedule_mode if current_schedule_mode == 'interval' else 'fixed_time')

            if mode_index >= 0:

                schedule_mode_combo.setCurrentIndex(mode_index)

            schedule_mode_layout.addWidget(schedule_mode_label)

            schedule_mode_layout.addWidget(schedule_mode_combo)

            schedule_mode_layout.addStretch(1)

            schedule_options_layout.addLayout(schedule_mode_layout)

            schedule_fixed_time_container = QWidget()

            schedule_fixed_time_layout = QVBoxLayout(schedule_fixed_time_container)

            schedule_fixed_time_layout.setSpacing(12)

            schedule_fixed_time_layout.setContentsMargins(0, 0, 0, 0)

            # 启动时间设置

            time_layout = QHBoxLayout()

            time_layout.setSpacing(8)

            time_label = QLabel("启动时间:")

            time_label.setFixedWidth(80)

            schedule_hour_spinbox = NoWheelSpinBox()

            schedule_hour_spinbox.setRange(0, 23)

            schedule_hour_spinbox.setValue(self._schedule_hour)

            schedule_hour_spinbox.setSuffix(" 时")

            hour_minute_label = QLabel(":")

            schedule_minute_spinbox = NoWheelSpinBox()

            schedule_minute_spinbox.setRange(0, 59)

            schedule_minute_spinbox.setValue(self._schedule_minute)

            schedule_minute_spinbox.setSuffix(" 分")

            time_layout.addWidget(time_label)

            time_layout.addWidget(schedule_hour_spinbox)

            time_layout.addWidget(hour_minute_label)

            time_layout.addWidget(schedule_minute_spinbox)

            time_layout.addStretch(1)

            schedule_fixed_time_layout.addLayout(time_layout)

            # 重复模式设置

            repeat_layout = QHBoxLayout()

            repeat_layout.setSpacing(8)

            repeat_label = QLabel("重复模式:")

            repeat_label.setFixedWidth(80)

            schedule_repeat_combo = QComboBox(dialog)

            schedule_repeat_combo.addItem("仅一次", "once")

            schedule_repeat_combo.addItem("每天", "daily")

            schedule_repeat_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)

            current_repeat = getattr(self, '_schedule_repeat', 'daily')

            index = schedule_repeat_combo.findData(current_repeat)

            if index >= 0:

                schedule_repeat_combo.setCurrentIndex(index)

            repeat_layout.addWidget(repeat_label)

            repeat_layout.addWidget(schedule_repeat_combo)

            repeat_layout.addStretch(1)

            schedule_fixed_time_layout.addLayout(repeat_layout)

            schedule_options_layout.addWidget(schedule_fixed_time_container)

            schedule_interval_container = QWidget()

            schedule_interval_layout = QVBoxLayout(schedule_interval_container)

            schedule_interval_layout.setSpacing(12)

            schedule_interval_layout.setContentsMargins(0, 0, 0, 0)

            schedule_interval_value_layout = QHBoxLayout()

            schedule_interval_value_layout.setSpacing(8)

            schedule_interval_label = QLabel("启动间隔:")

            schedule_interval_label.setFixedWidth(80)

            schedule_interval_spinbox = NoWheelSpinBox()

            schedule_interval_spinbox.setRange(1, 86400)

            schedule_interval_spinbox.setValue(int(getattr(self, '_schedule_interval_value', 5)))

            schedule_interval_unit_combo = QComboBox(dialog)

            schedule_interval_unit_combo.addItems(["秒", "分钟", "小时"])

            schedule_interval_unit_combo.setCurrentText(getattr(self, '_schedule_interval_unit', '分钟'))

            schedule_interval_unit_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)

            schedule_interval_value_layout.addWidget(schedule_interval_label)

            schedule_interval_value_layout.addWidget(schedule_interval_spinbox)

            schedule_interval_value_layout.addWidget(schedule_interval_unit_combo)

            schedule_interval_value_layout.addStretch(1)

            schedule_interval_layout.addLayout(schedule_interval_value_layout)

            schedule_options_layout.addWidget(schedule_interval_container)

            # 状态显示标签

            schedule_status_label = QLabel()

            schedule_status_label.setObjectName("schedule_status_label")

            schedule_options_layout.addWidget(schedule_status_label)

            # 更新状态显示函数

            def update_schedule_status():

                if schedule_enable_checkbox.isChecked():

                    schedule_mode = self._get_combo_data(schedule_mode_combo) or schedule_mode_combo.currentText()

                    if schedule_mode == 'interval':

                        interval_value = schedule_interval_spinbox.value()

                        interval_unit = schedule_interval_unit_combo.currentText()

                        schedule_status_label.setText(f"将每隔 {interval_value} {interval_unit} 尝试启动一次，执行中跳过")

                    else:

                        hour = schedule_hour_spinbox.value()

                        minute = schedule_minute_spinbox.value()

                        repeat_mode = self._get_combo_data(schedule_repeat_combo) or schedule_repeat_combo.currentText()

                        if repeat_mode == 'once':

                            schedule_status_label.setText(f"将于 {hour:02d}:{minute:02d} 执行（仅一次）")

                        else:

                            schedule_status_label.setText(f"将在每天 {hour:02d}:{minute:02d} 执行")

                    schedule_status_label.setProperty("status", "active")

                else:

                    schedule_status_label.setText("定时启动未启用")

                    schedule_status_label.setProperty("status", "inactive")

                schedule_status_label.style().unpolish(schedule_status_label)

                schedule_status_label.style().polish(schedule_status_label)

            # 连接信号

            schedule_enable_checkbox.toggled.connect(update_schedule_status)

            def update_schedule_mode_visibility():

                schedule_mode = self._get_combo_data(schedule_mode_combo) or schedule_mode_combo.currentText()

                is_interval_mode = schedule_mode == 'interval'

                schedule_fixed_time_container.setVisible(not is_interval_mode)

                schedule_interval_container.setVisible(is_interval_mode)

                update_schedule_status()

            schedule_mode_combo.currentIndexChanged.connect(update_schedule_mode_visibility)

            schedule_hour_spinbox.valueChanged.connect(update_schedule_status)

            schedule_minute_spinbox.valueChanged.connect(update_schedule_status)

            schedule_repeat_combo.currentIndexChanged.connect(update_schedule_status)

            schedule_interval_spinbox.valueChanged.connect(update_schedule_status)

            schedule_interval_unit_combo.currentIndexChanged.connect(update_schedule_status)

            # 初始化状态显示

            update_schedule_mode_visibility()

            update_schedule_status()

            start_settings_layout.addWidget(schedule_options_container)

            # 根据"启用定时启动"复选框状态显示/隐藏定时启动参数

            schedule_options_container.setVisible(schedule_enable_checkbox.isChecked())

            # 连接"启用定时启动"复选框状态改变事件

            def on_schedule_checkbox_changed(state):

                schedule_options_container.setVisible(state == 2)  # 2 = Qt.Checked

                update_schedule_status()

            schedule_enable_checkbox.stateChanged.connect(on_schedule_checkbox_changed)

            start_tab_layout.addWidget(start_settings_group)

            start_tab_layout.addStretch()  # 添加弹性空间

            # =======================================

            # 标签页4: 定时暂停

            # =======================================

            timed_pause_tab = QWidget()

            timed_pause_tab_layout = QVBoxLayout(timed_pause_tab)

            timed_pause_tab_layout.setSpacing(10)

            timed_pause_tab_layout.setContentsMargins(15, 15, 15, 15)

            # --- 定时暂停设置组 ---

            timed_pause_settings_group = QGroupBox("定时暂停设置")

            timed_pause_settings_layout = QVBoxLayout(timed_pause_settings_group)

            timed_pause_settings_layout.setSpacing(8)

            timed_pause_settings_layout.setContentsMargins(15, 10, 15, 10)

            timed_pause_checkbox = QCheckBox("启用定时暂停（到点自动暂停，按时长自动恢复）")

            timed_pause_checkbox.setChecked(getattr(self, '_timed_pause_enabled', False))

            timed_pause_settings_layout.addWidget(timed_pause_checkbox)

            timed_pause_container = QWidget()

            timed_pause_layout = QVBoxLayout(timed_pause_container)

            timed_pause_layout.setSpacing(12)

            timed_pause_layout.setContentsMargins(0, 5, 0, 0)

            timed_pause_time_layout = QHBoxLayout()

            timed_pause_time_layout.setSpacing(8)

            timed_pause_time_label = QLabel("暂停时间:")

            timed_pause_time_label.setFixedWidth(100)

            timed_pause_hour_spinbox = NoWheelSpinBox()

            timed_pause_hour_spinbox.setRange(0, 23)

            timed_pause_hour_spinbox.setValue(int(getattr(self, '_timed_pause_hour', 12)))

            timed_pause_hour_spinbox.setSuffix(" 时")

            timed_pause_colon = QLabel(":")

            timed_pause_minute_spinbox = NoWheelSpinBox()

            timed_pause_minute_spinbox.setRange(0, 59)

            timed_pause_minute_spinbox.setValue(int(getattr(self, '_timed_pause_minute', 0)))

            timed_pause_minute_spinbox.setSuffix(" 分")

            timed_pause_time_layout.addWidget(timed_pause_time_label)

            timed_pause_time_layout.addWidget(timed_pause_hour_spinbox)

            timed_pause_time_layout.addWidget(timed_pause_colon)

            timed_pause_time_layout.addWidget(timed_pause_minute_spinbox)

            timed_pause_time_layout.addStretch(1)

            timed_pause_layout.addLayout(timed_pause_time_layout)

            timed_pause_repeat_layout = QHBoxLayout()

            timed_pause_repeat_layout.setSpacing(8)

            timed_pause_repeat_label = QLabel("重复模式:")

            timed_pause_repeat_label.setFixedWidth(100)

            timed_pause_repeat_combo = QComboBox(dialog)

            timed_pause_repeat_combo.addItem("仅一次", "once")

            timed_pause_repeat_combo.addItem("每天", "daily")

            timed_pause_repeat_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)

            current_timed_pause_repeat = getattr(self, '_timed_pause_repeat', 'daily')

            timed_repeat_index = timed_pause_repeat_combo.findData(current_timed_pause_repeat)

            if timed_repeat_index >= 0:

                timed_pause_repeat_combo.setCurrentIndex(timed_repeat_index)

            timed_pause_repeat_layout.addWidget(timed_pause_repeat_label)

            timed_pause_repeat_layout.addWidget(timed_pause_repeat_combo)

            timed_pause_repeat_layout.addStretch(1)

            timed_pause_layout.addLayout(timed_pause_repeat_layout)

            timed_pause_duration_layout = QHBoxLayout()

            timed_pause_duration_layout.setSpacing(8)

            timed_pause_duration_label = QLabel("暂停时长:")

            timed_pause_duration_label.setFixedWidth(100)

            timed_pause_duration_spinbox = NoWheelSpinBox()

            timed_pause_duration_spinbox.setRange(1, 86400)

            timed_pause_duration_spinbox.setValue(int(getattr(self, '_timed_pause_duration_value', 10)))

            timed_pause_duration_unit_combo = QComboBox(dialog)

            timed_pause_duration_unit_combo.addItems(["秒", "分钟", "小时"])

            timed_pause_duration_unit_combo.setCurrentText(getattr(self, '_timed_pause_duration_unit', '分钟'))

            timed_pause_duration_unit_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)

            timed_pause_duration_layout.addWidget(timed_pause_duration_label)

            timed_pause_duration_layout.addWidget(timed_pause_duration_spinbox)

            timed_pause_duration_layout.addWidget(timed_pause_duration_unit_combo)

            timed_pause_duration_layout.addStretch(1)

            timed_pause_layout.addLayout(timed_pause_duration_layout)

            timed_pause_status_label = QLabel()

            timed_pause_status_label.setObjectName("timer_status_label")

            timed_pause_layout.addWidget(timed_pause_status_label)

            def update_timed_pause_status():

                if timed_pause_checkbox.isChecked():

                    hour = timed_pause_hour_spinbox.value()

                    minute = timed_pause_minute_spinbox.value()

                    repeat_mode = self._get_combo_data(timed_pause_repeat_combo) or timed_pause_repeat_combo.currentText()

                    duration_value = timed_pause_duration_spinbox.value()

                    duration_unit = timed_pause_duration_unit_combo.currentText()

                    if repeat_mode == 'once':

                        timed_pause_status_label.setText(

                            f"将于 {hour:02d}:{minute:02d} 自动暂停（仅一次），时长 {duration_value} {duration_unit}"

                        )

                    else:

                        timed_pause_status_label.setText(

                            f"将在每天 {hour:02d}:{minute:02d} 自动暂停，时长 {duration_value} {duration_unit}"

                        )

                    timed_pause_status_label.setProperty("status", "active")

                else:

                    timed_pause_status_label.setText("定时暂停未启用")

                    timed_pause_status_label.setProperty("status", "inactive")

                timed_pause_status_label.style().unpolish(timed_pause_status_label)

                timed_pause_status_label.style().polish(timed_pause_status_label)

            timed_pause_checkbox.toggled.connect(update_timed_pause_status)

            timed_pause_hour_spinbox.valueChanged.connect(update_timed_pause_status)

            timed_pause_minute_spinbox.valueChanged.connect(update_timed_pause_status)

            timed_pause_repeat_combo.currentIndexChanged.connect(update_timed_pause_status)

            timed_pause_duration_spinbox.valueChanged.connect(update_timed_pause_status)

            timed_pause_duration_unit_combo.currentIndexChanged.connect(update_timed_pause_status)

            update_timed_pause_status()

            timed_pause_settings_layout.addWidget(timed_pause_container)

            timed_pause_container.setVisible(timed_pause_checkbox.isChecked())

            def on_timed_pause_checkbox_changed(state):

                timed_pause_container.setVisible(state == 2)

                update_timed_pause_status()

            timed_pause_checkbox.stateChanged.connect(on_timed_pause_checkbox_changed)

            timed_pause_tab_layout.addWidget(timed_pause_settings_group)

            timed_pause_tab_layout.addStretch()

            # =======================================

            # 标签页5: 随机暂停

            # =======================================

            pause_tab = QWidget()

            pause_tab_layout = QVBoxLayout(pause_tab)

            pause_tab_layout.setSpacing(10)

            pause_tab_layout.setContentsMargins(15, 15, 15, 15)

            # --- 随机暂停设置组 ---

            pause_settings_group = QGroupBox("暂停参数设置")

            pause_settings_layout = QVBoxLayout(pause_settings_group)

            pause_settings_layout.setSpacing(8)

            pause_settings_layout.setContentsMargins(15, 10, 15, 10)

            pause_checkbox = QCheckBox("启用随机暂停（运行过程中随机触发暂停，暂停后自动恢复）")

            pause_checkbox.setChecked(self._random_pause_enabled)

            pause_settings_layout.addWidget(pause_checkbox)

            pause_settings_layout.addSpacing(5)

            # 暂停选项容器

            pause_container = QWidget()

            pause_layout = QVBoxLayout(pause_container)

            pause_layout.setSpacing(12)

            pause_layout.setContentsMargins(0, 5, 0, 0)

            # 触发概率

            probability_layout = QHBoxLayout()

            probability_layout.setSpacing(8)

            probability_label = QLabel("触发概率:")

            probability_label.setFixedWidth(100)

            probability_spinbox = NoWheelSpinBox()

            probability_spinbox.setRange(1, 100)

            probability_spinbox.setValue(int(getattr(self, '_pause_probability', 20)))

            probability_spinbox.setSuffix(" %")

            probability_hint = QLabel("(每次检查时的暂停概率)")

            probability_hint.setObjectName("hint_label")

            probability_layout.addWidget(probability_label)

            probability_layout.addWidget(probability_spinbox)

            probability_layout.addWidget(probability_hint)

            probability_layout.addStretch(1)

            pause_layout.addLayout(probability_layout)

            # 检查间隔

            interval_layout = QHBoxLayout()

            interval_layout.setSpacing(8)

            interval_label = QLabel("检查间隔:")

            interval_label.setFixedWidth(100)

            interval_spinbox = NoWheelSpinBox()

            interval_spinbox.setRange(1, 3600)

            interval_spinbox.setValue(int(getattr(self, '_pause_check_interval', 30)))

            interval_unit_combo = QComboBox(dialog)

            interval_unit_combo.addItems(["秒", "分钟"])

            interval_unit_combo.setCurrentText(getattr(self, '_pause_check_interval_unit', '秒'))

            interval_unit_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)

            interval_layout.addWidget(interval_label)

            interval_layout.addWidget(interval_spinbox)

            interval_layout.addWidget(interval_unit_combo)

            interval_layout.addStretch(1)

            pause_layout.addLayout(interval_layout)

            # 暂停最小时长

            pause_min_layout = QHBoxLayout()

            pause_min_layout.setSpacing(8)

            pause_min_label = QLabel("暂停最小时长:")

            pause_min_label.setFixedWidth(100)

            pause_min_spinbox = NoWheelSpinBox()

            pause_min_spinbox.setRange(1, 86400)

            pause_min_spinbox.setValue(int(self._pause_min_value))

            pause_min_unit_combo = QComboBox(dialog)

            pause_min_unit_combo.addItems(["秒", "分钟", "小时"])

            pause_min_unit_combo.setCurrentText(self._pause_min_unit)

            pause_min_unit_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)

            pause_min_layout.addWidget(pause_min_label)

            pause_min_layout.addWidget(pause_min_spinbox)

            pause_min_layout.addWidget(pause_min_unit_combo)

            pause_min_layout.addStretch(1)

            pause_layout.addLayout(pause_min_layout)

            # 暂停最大时长

            pause_max_layout = QHBoxLayout()

            pause_max_layout.setSpacing(8)

            pause_max_label = QLabel("暂停最大时长:")

            pause_max_label.setFixedWidth(100)

            pause_max_spinbox = NoWheelSpinBox()

            pause_max_spinbox.setRange(1, 86400)

            pause_max_spinbox.setValue(int(self._pause_max_value))

            pause_max_unit_combo = QComboBox(dialog)

            pause_max_unit_combo.addItems(["秒", "分钟", "小时"])

            pause_max_unit_combo.setCurrentText(self._pause_max_unit)

            pause_max_unit_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)

            pause_max_layout.addWidget(pause_max_label)

            pause_max_layout.addWidget(pause_max_spinbox)

            pause_max_layout.addWidget(pause_max_unit_combo)

            pause_max_layout.addStretch(1)

            pause_layout.addLayout(pause_max_layout)

            pause_settings_layout.addWidget(pause_container)

            # 根据"启用随机暂停"复选框状态显示/隐藏暂停参数

            pause_container.setVisible(pause_checkbox.isChecked())

            # 连接"启用随机暂停"复选框状态改变事件

            def on_pause_checkbox_changed(state):

                pause_container.setVisible(state == 2)  # 2 = Qt.Checked

            pause_checkbox.stateChanged.connect(on_pause_checkbox_changed)

            pause_tab_layout.addWidget(pause_settings_group)

            pause_tab_layout.addStretch()  # 添加弹性空间

            # =======================================

            # 将标签页添加到QTabWidget

            # =======================================

            tab_widget.addTab(stop_tab, "定时停止")

            tab_widget.addTab(start_tab, "定时启动")

            tab_widget.addTab(timed_pause_tab, "定时暂停")

            tab_widget.addTab(pause_tab, "随机暂停")

            # 辅助函数

            def convert_to_seconds(value: int, unit: str) -> int:

                if unit == "分钟":

                    return value * 60

                elif unit == "小时":

                    return value * 3600

                return value

            def format_time_display(seconds: int) -> str:

                """将秒数格式化为可读的时间显示"""

                if seconds < 60:

                    return f"{seconds} 秒"

                elif seconds < 3600:

                    minutes = seconds // 60

                    remaining_seconds = seconds % 60

                    if remaining_seconds > 0:

                        return f"{minutes} 分 {remaining_seconds} 秒"

                    return f"{minutes} 分钟"

                else:

                    hours = seconds // 3600

                    remaining_minutes = (seconds % 3600) // 60

                    remaining_seconds = seconds % 60

                    parts = [f"{hours} 小时"]

                    if remaining_minutes > 0:

                        parts.append(f"{remaining_minutes} 分")

                    if remaining_seconds > 0:

                        parts.append(f"{remaining_seconds} 秒")

                    return " ".join(parts)

            # 按钮区域

            main_layout.addSpacing(5)

            button_layout = QHBoxLayout()

            button_layout.setSpacing(10)

            button_layout.addStretch()

            ok_button = QPushButton("确定")

            ok_button.setObjectName("ok_button")

            cancel_button = QPushButton("取消")

            cancel_button.setObjectName("cancel_button")

            stop_button = QPushButton("停止定时器")

            stop_button.setObjectName("stop_button")

            # 检查任意定时器是否活动

            any_timer_active = (

                self._global_timer.isActive() or

                (hasattr(self, '_stop_timer') and self._stop_timer.isActive()) or

                (hasattr(self, '_schedule_timer') and self._schedule_timer.isActive()) or

                (hasattr(self, '_random_pause_timer') and self._random_pause_timer.isActive()) or

                (hasattr(self, '_timed_pause_timer') and self._timed_pause_timer.isActive()) or

                (hasattr(self, '_timed_pause_resume_timer') and self._timed_pause_resume_timer.isActive())

            )

            stop_button.setEnabled(any_timer_active)

            button_layout.addWidget(stop_button)

            button_layout.addWidget(cancel_button)

            button_layout.addWidget(ok_button)

            main_layout.addLayout(button_layout)

            def on_ok():

                self._global_timer_enabled = enable_checkbox.isChecked()

                # 保存定时停止设置(改为时间点模式)

                self._stop_hour = stop_hour_spinbox.value()

                self._stop_minute = stop_minute_spinbox.value()

                self._stop_repeat = self._get_combo_data(stop_repeat_combo) or stop_repeat_combo.currentText()

                # 保存定时暂停设置

                self._timed_pause_enabled = timed_pause_checkbox.isChecked()

                self._timed_pause_hour = timed_pause_hour_spinbox.value()

                self._timed_pause_minute = timed_pause_minute_spinbox.value()

                self._timed_pause_repeat = self._get_combo_data(timed_pause_repeat_combo) or timed_pause_repeat_combo.currentText()

                self._timed_pause_duration_value = timed_pause_duration_spinbox.value()

                self._timed_pause_duration_unit = timed_pause_duration_unit_combo.currentText()

                timed_pause_duration_sec = convert_to_seconds(

                    self._timed_pause_duration_value, self._timed_pause_duration_unit

                )

                if self._timed_pause_enabled and timed_pause_duration_sec <= 0:

                    QMessageBox.warning(dialog, "参数错误", "定时暂停时长必须大于0")

                    return

                if not self._timed_pause_enabled:

                    if hasattr(self, '_timed_pause_resume_timer') and self._timed_pause_resume_timer.isActive():

                        self._timed_pause_resume_timer.stop()

                    if self._is_paused and getattr(self, '_auto_pause_source', None) == 'timed':

                        self._resume_workflow()

                        self._is_paused = False

                        self._auto_pause_source = None

                # 保存随机暂停设置

                self._random_pause_enabled = pause_checkbox.isChecked()

                if self._random_pause_enabled:

                    # 保存触发概率

                    self._pause_probability = probability_spinbox.value()

                    # 保存检查间隔

                    self._pause_check_interval = interval_spinbox.value()

                    self._pause_check_interval_unit = interval_unit_combo.currentText()

                    # 保存暂停时长

                    self._pause_min_value = pause_min_spinbox.value()

                    self._pause_min_unit = pause_min_unit_combo.currentText()

                    self._pause_max_value = pause_max_spinbox.value()

                    self._pause_max_unit = pause_max_unit_combo.currentText()

                    # 验证暂停时间范围

                    pause_min_sec = convert_to_seconds(self._pause_min_value, self._pause_min_unit)

                    pause_max_sec = convert_to_seconds(self._pause_max_value, self._pause_max_unit)

                    if pause_min_sec > pause_max_sec:

                        QMessageBox.warning(dialog, "参数错误", "暂停最小时长不能大于最大时长")

                        return

                    logger.info(f"随机暂停功能已配置: 概率={self._pause_probability}%, 检查间隔={self._pause_check_interval}{self._pause_check_interval_unit}, 暂停范围={pause_min_sec}-{pause_max_sec}秒")

                    # 如果当前有任务正在运行，立即启动随机暂停定时器

                    running_count = 0

                    if hasattr(self, 'task_manager') and self.task_manager:

                        running_count = self.task_manager.get_running_count()

                    if running_count > 0:

                        self._start_random_pause_cycle()

                        logger.info("随机暂停已立即启动（检测到运行中的任务）")

                    else:

                        logger.info("随机暂停将在下次任务启动时生效")

                else:

                    # 停止随机暂停定时器

                    if hasattr(self, '_random_pause_timer') and self._random_pause_timer.isActive():

                        self._random_pause_timer.stop()

                    # 如果当前处于暂停状态，恢复任务（使用与主窗口按钮一致的方法）

                    if self._is_paused and getattr(self, '_auto_pause_source', None) == 'random':

                        self._resume_workflow()

                        self._is_paused = False

                        self._auto_pause_source = None

                        logger.info("已恢复处于暂停状态的任务")

                    logger.info("随机暂停功能已禁用")

                # 更新定时停止配置

                self._update_stop_config()

                # 保存定时器设置到配置文件

                self.config['timer_enabled'] = self._global_timer_enabled

                self.config['stop_hour'] = self._stop_hour

                self.config['stop_minute'] = self._stop_minute

                self.config['stop_repeat'] = self._stop_repeat

                self.config['timed_pause_enabled'] = self._timed_pause_enabled

                self.config['timed_pause_hour'] = self._timed_pause_hour

                self.config['timed_pause_minute'] = self._timed_pause_minute

                self.config['timed_pause_repeat'] = self._timed_pause_repeat

                self.config['timed_pause_duration_value'] = self._timed_pause_duration_value

                self.config['timed_pause_duration_unit'] = self._timed_pause_duration_unit

                self.config['pause_enabled'] = self._random_pause_enabled

                self.config['pause_probability'] = self._pause_probability

                self.config['pause_check_interval'] = self._pause_check_interval

                self.config['pause_check_interval_unit'] = self._pause_check_interval_unit

                self.config['pause_min_value'] = self._pause_min_value

                self.config['pause_min_unit'] = self._pause_min_unit

                self.config['pause_max_value'] = self._pause_max_value

                self.config['pause_max_unit'] = self._pause_max_unit

                # 保存定时启动设置

                self._schedule_enabled = schedule_enable_checkbox.isChecked()

                self._schedule_mode = self._get_combo_data(schedule_mode_combo) or schedule_mode_combo.currentText()

                self._schedule_hour = schedule_hour_spinbox.value()

                self._schedule_minute = schedule_minute_spinbox.value()

                self._schedule_repeat = self._get_combo_data(schedule_repeat_combo) or schedule_repeat_combo.currentText()

                self._schedule_interval_value = schedule_interval_spinbox.value()

                self._schedule_interval_unit = schedule_interval_unit_combo.currentText()

                self.config['enable_schedule'] = self._schedule_enabled

                self.config['schedule_mode'] = self._schedule_mode

                self.config['schedule_hour'] = self._schedule_hour

                self.config['schedule_minute'] = self._schedule_minute

                self.config['schedule_repeat'] = self._schedule_repeat

                self.config['schedule_interval_value'] = self._schedule_interval_value

                self.config['schedule_interval_unit'] = self._schedule_interval_unit

                # 更新定时启动配置

                self._update_schedule_config()

                self._update_timed_pause_config()

                # 调用保存配置函数

                if self.save_config_func:

                    self.save_config_func(self.config)

                    logger.info("定时器设置已保存到配置文件")

                dialog.accept()

            def on_stop():

                self._global_timer.stop()

                self._global_timer_enabled = False

                # 重置定时器相关参数

                logger.info("停止定时器并重置所有参数")

                # 重置启用定时停止复选框

                enable_checkbox.setChecked(False)

                # 停止定时停止定时器

                if hasattr(self, '_stop_timer') and self._stop_timer.isActive():

                    self._stop_timer.stop()

                # 重置启用定时启动复选框

                schedule_enable_checkbox.setChecked(False)

                self._schedule_enabled = False

                # 停止定时启动定时器

                if hasattr(self, '_schedule_timer') and self._schedule_timer.isActive():

                    self._schedule_timer.stop()

                # 重置启用定时暂停复选框

                timed_pause_checkbox.setChecked(False)

                self._timed_pause_enabled = False

                # 停止定时暂停检查与恢复定时器

                if hasattr(self, '_timed_pause_timer') and self._timed_pause_timer.isActive():

                    self._timed_pause_timer.stop()

                if hasattr(self, '_timed_pause_resume_timer') and self._timed_pause_resume_timer.isActive():

                    self._timed_pause_resume_timer.stop()

                # 重置启用随机暂停复选框

                pause_checkbox.setChecked(False)

                # 停止随机暂停定时器

                if hasattr(self, '_random_pause_timer') and self._random_pause_timer.isActive():

                    self._random_pause_timer.stop()

                # 如果当前处于暂停状态，恢复任务（使用与主窗口按钮一致的方法）

                if self._is_paused:

                    self._resume_workflow()

                    self._is_paused = False

                    self._auto_pause_source = None

                    logger.info("已恢复处于暂停状态的任务")

                self._random_pause_enabled = False

                self._shutdown_after_timer = False

                self._auto_pause_source = None

                self._schedule_executed = False

                self._schedule_last_exec_date = None

                self._schedule_next_trigger_monotonic = None

                self._timed_pause_executed = False

                self._timed_pause_last_exec_date = None

                self._stop_executed = False

                self._stop_last_exec_date = None

                self._timer_slot_key = None

                self._timer_slot_priority = -1

                self._timer_slot_action = None

                self.config['timer_enabled'] = False

                self.config['enable_schedule'] = False

                self.config['timed_pause_enabled'] = False

                self.config['pause_enabled'] = False

                if self.save_config_func:

                    self.save_config_func(self.config)

                    logger.info("停止定时器后已持久化配置")

                logger.info("全局定时器已停止，所有参数已重置")

                QMessageBox.information(self, "定时器已停止", "全局定时器已停止，所有参数已重置")

                dialog.accept()

            ok_button.clicked.connect(on_ok)

            cancel_button.clicked.connect(dialog.reject)

            stop_button.clicked.connect(on_stop)

            center_window_on_widget_screen(dialog, self)

            dialog.exec()

            dialog.deleteLater()
