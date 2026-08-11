import logging

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


class ControlCenterTimerDialogMixin:
    def _get_available_timer_window_options(self):
        options = []
        windows = self.sorted_windows if self.sorted_windows else self.bound_windows
        for idx, window_info in enumerate(windows):
            try:
                hwnd = window_info.get("hwnd", idx)
                window_id = str(hwnd)
                title = window_info.get("title", "未知窗口")
                display_title = self.format_window_title(title, idx)
                options.append((window_id, display_title))
            except Exception:
                continue
        return options

    def _format_target_windows_summary(self, selected_window_ids):
        selected = self._normalize_window_id_list(selected_window_ids)
        if not selected:
            return "目标窗口：全部窗口"

        option_map = {window_id: title for window_id, title in self._get_available_timer_window_options()}
        names = [option_map.get(window_id, window_id) for window_id in selected]
        if len(names) <= 2:
            return "目标窗口：" + "、".join(names)
        preview = "、".join(names[:2])
        return f"目标窗口：{len(names)}个（{preview} 等）"

    def _choose_timer_target_windows(self, initial_window_ids, title):
        options = self._get_available_timer_window_options()
        if not options:
            QMessageBox.warning(self, "无可选窗口", "当前没有可选窗口。")
            return None

        selected_ids = set(self._normalize_window_id_list(initial_window_ids))

        picker = QDialog(self)
        picker.setWindowTitle(title)
        picker.setModal(True)
        picker.setMinimumWidth(420)
        picker.setMaximumWidth(620)
        picker.resize(460, 420)

        layout = QVBoxLayout(picker)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        tip_label = QLabel("勾选后仅对这些窗口生效；不勾选任何窗口表示全部窗口。")
        tip_label.setWordWrap(True)
        layout.addWidget(tip_label)

        scroll = QScrollArea(picker)
        scroll.setWidgetResizable(True)
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(6, 6, 6, 6)
        container_layout.setSpacing(6)
        checkbox_map = {}
        for window_id, display_name in options:
            cb = QCheckBox(display_name)
            cb.setChecked(window_id in selected_ids)
            checkbox_map[window_id] = cb
            container_layout.addWidget(cb)
        container_layout.addStretch(1)
        scroll.setWidget(container)
        layout.addWidget(scroll, 1)

        tool_layout = QHBoxLayout()
        select_all_btn = QPushButton("全选")
        clear_all_btn = QPushButton("清空")
        tool_layout.addWidget(select_all_btn)
        tool_layout.addWidget(clear_all_btn)
        tool_layout.addStretch(1)
        layout.addLayout(tool_layout)

        button_layout = QHBoxLayout()
        button_layout.addStretch(1)
        cancel_btn = QPushButton("取消")
        ok_btn = QPushButton("确定")
        button_layout.addWidget(cancel_btn)
        button_layout.addWidget(ok_btn)
        layout.addLayout(button_layout)

        def on_select_all():
            for cb in checkbox_map.values():
                cb.setChecked(True)

        def on_clear_all():
            for cb in checkbox_map.values():
                cb.setChecked(False)

        select_all_btn.clicked.connect(on_select_all)
        clear_all_btn.clicked.connect(on_clear_all)
        cancel_btn.clicked.connect(picker.reject)
        ok_btn.clicked.connect(picker.accept)

        if picker.exec() != QDialog.DialogCode.Accepted:
            picker.deleteLater()
            return None

        result_ids = [window_id for window_id, cb in checkbox_map.items() if cb.isChecked()]
        picker.deleteLater()
        return result_ids

    def _create_control_timer_dialog_shell(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("中控定时任务")
        dialog.setModal(True)
        dialog.setMinimumWidth(560)
        dialog.setMaximumWidth(820)
        dialog.setMinimumHeight(380)
        dialog.setMaximumHeight(560)
        dialog.resize(620, 440)
        dialog.setSizeGripEnabled(True)

        main_layout = QVBoxLayout(dialog)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(15, 15, 15, 15)

        tab_widget = QTabWidget(dialog)
        main_layout.addWidget(tab_widget)
        return dialog, main_layout, tab_widget

    def _add_control_timer_target_selector(self, layout, selected_window_ids, picker_title):
        target_holder = {"ids": list(self._normalize_window_id_list(selected_window_ids))}
        target_row = QHBoxLayout()
        target_label = QLabel(self._format_target_windows_summary(target_holder["ids"]))
        target_label.setWordWrap(True)
        target_button = QPushButton("选择窗口")
        target_row.addWidget(target_label, 1)
        target_row.addWidget(target_button)
        layout.addLayout(target_row)

        def on_choose_windows():
            selected = self._choose_timer_target_windows(target_holder["ids"], picker_title)
            if selected is None:
                return
            target_holder["ids"] = selected
            target_label.setText(self._format_target_windows_summary(selected))

        target_button.clicked.connect(on_choose_windows)
        return target_holder

    def _build_control_schedule_timer_tab(self, dialog, tab_widget):
        schedule_tab = QWidget()
        schedule_layout = QVBoxLayout(schedule_tab)
        schedule_layout.setSpacing(10)
        schedule_layout.setContentsMargins(10, 10, 10, 10)

        schedule_enable_checkbox = QCheckBox("启用定时启动")
        schedule_enable_checkbox.setChecked(self._cc_schedule_enabled)
        schedule_layout.addWidget(schedule_enable_checkbox)

        schedule_time_layout = QHBoxLayout()
        schedule_time_layout.addWidget(QLabel("启动时间:"))
        schedule_hour_spinbox = QSpinBox(dialog)
        schedule_hour_spinbox.setRange(0, 23)
        schedule_hour_spinbox.setValue(self._cc_schedule_hour)
        schedule_hour_spinbox.setSuffix(" 时")
        schedule_minute_spinbox = QSpinBox(dialog)
        schedule_minute_spinbox.setRange(0, 59)
        schedule_minute_spinbox.setValue(self._cc_schedule_minute)
        schedule_minute_spinbox.setSuffix(" 分")
        schedule_time_layout.addWidget(schedule_hour_spinbox)
        schedule_time_layout.addWidget(QLabel(":"))
        schedule_time_layout.addWidget(schedule_minute_spinbox)
        schedule_time_layout.addStretch(1)
        schedule_layout.addLayout(schedule_time_layout)

        schedule_repeat_layout = QHBoxLayout()
        schedule_repeat_layout.addWidget(QLabel("重复模式:"))
        schedule_repeat_combo = QComboBox(dialog)
        schedule_repeat_combo.addItem("仅一次", "once")
        schedule_repeat_combo.addItem("每天", "daily")
        schedule_repeat_index = schedule_repeat_combo.findData(self._cc_schedule_repeat)
        if schedule_repeat_index >= 0:
            schedule_repeat_combo.setCurrentIndex(schedule_repeat_index)
        schedule_repeat_layout.addWidget(schedule_repeat_combo)
        schedule_repeat_layout.addStretch(1)
        schedule_layout.addLayout(schedule_repeat_layout)

        schedule_target_holder = self._add_control_timer_target_selector(
            schedule_layout,
            self._cc_schedule_window_ids,
            "定时启动 - 选择目标窗口",
        )
        schedule_layout.addStretch(1)
        tab_widget.addTab(schedule_tab, "定时启动")
        return {
            "enabled": schedule_enable_checkbox,
            "hour": schedule_hour_spinbox,
            "minute": schedule_minute_spinbox,
            "repeat": schedule_repeat_combo,
            "target_holder": schedule_target_holder,
        }

    def _build_control_stop_timer_tab(self, dialog, tab_widget):
        stop_tab = QWidget()
        stop_layout = QVBoxLayout(stop_tab)
        stop_layout.setSpacing(10)
        stop_layout.setContentsMargins(10, 10, 10, 10)

        stop_enable_checkbox = QCheckBox("启用定时停止")
        stop_enable_checkbox.setChecked(self._cc_stop_enabled)
        stop_layout.addWidget(stop_enable_checkbox)

        stop_time_layout = QHBoxLayout()
        stop_time_layout.addWidget(QLabel("停止时间:"))
        stop_hour_spinbox = QSpinBox(dialog)
        stop_hour_spinbox.setRange(0, 23)
        stop_hour_spinbox.setValue(self._cc_stop_hour)
        stop_hour_spinbox.setSuffix(" 时")
        stop_minute_spinbox = QSpinBox(dialog)
        stop_minute_spinbox.setRange(0, 59)
        stop_minute_spinbox.setValue(self._cc_stop_minute)
        stop_minute_spinbox.setSuffix(" 分")
        stop_time_layout.addWidget(stop_hour_spinbox)
        stop_time_layout.addWidget(QLabel(":"))
        stop_time_layout.addWidget(stop_minute_spinbox)
        stop_time_layout.addStretch(1)
        stop_layout.addLayout(stop_time_layout)

        stop_repeat_layout = QHBoxLayout()
        stop_repeat_layout.addWidget(QLabel("重复模式:"))
        stop_repeat_combo = QComboBox(dialog)
        stop_repeat_combo.addItem("仅一次", "once")
        stop_repeat_combo.addItem("每天", "daily")
        stop_repeat_index = stop_repeat_combo.findData(self._cc_stop_repeat)
        if stop_repeat_index >= 0:
            stop_repeat_combo.setCurrentIndex(stop_repeat_index)
        stop_repeat_layout.addWidget(stop_repeat_combo)
        stop_repeat_layout.addStretch(1)
        stop_layout.addLayout(stop_repeat_layout)

        stop_target_holder = self._add_control_timer_target_selector(
            stop_layout,
            self._cc_stop_window_ids,
            "定时停止 - 选择目标窗口",
        )
        stop_layout.addStretch(1)
        tab_widget.addTab(stop_tab, "定时停止")
        return {
            "enabled": stop_enable_checkbox,
            "hour": stop_hour_spinbox,
            "minute": stop_minute_spinbox,
            "repeat": stop_repeat_combo,
            "target_holder": stop_target_holder,
        }

    def _build_control_timed_pause_tab(self, dialog, tab_widget):
        timed_pause_tab = QWidget()
        timed_pause_layout = QVBoxLayout(timed_pause_tab)
        timed_pause_layout.setSpacing(10)
        timed_pause_layout.setContentsMargins(10, 10, 10, 10)

        timed_pause_enable_checkbox = QCheckBox("启用定时暂停（到点暂停，按时长恢复）")
        timed_pause_enable_checkbox.setChecked(self._cc_timed_pause_enabled)
        timed_pause_layout.addWidget(timed_pause_enable_checkbox)

        timed_pause_time_layout = QHBoxLayout()
        timed_pause_time_layout.addWidget(QLabel("暂停时间:"))
        timed_pause_hour_spinbox = QSpinBox(dialog)
        timed_pause_hour_spinbox.setRange(0, 23)
        timed_pause_hour_spinbox.setValue(self._cc_timed_pause_hour)
        timed_pause_hour_spinbox.setSuffix(" 时")
        timed_pause_minute_spinbox = QSpinBox(dialog)
        timed_pause_minute_spinbox.setRange(0, 59)
        timed_pause_minute_spinbox.setValue(self._cc_timed_pause_minute)
        timed_pause_minute_spinbox.setSuffix(" 分")
        timed_pause_time_layout.addWidget(timed_pause_hour_spinbox)
        timed_pause_time_layout.addWidget(QLabel(":"))
        timed_pause_time_layout.addWidget(timed_pause_minute_spinbox)
        timed_pause_time_layout.addStretch(1)
        timed_pause_layout.addLayout(timed_pause_time_layout)

        timed_pause_repeat_layout = QHBoxLayout()
        timed_pause_repeat_layout.addWidget(QLabel("重复模式:"))
        timed_pause_repeat_combo = QComboBox(dialog)
        timed_pause_repeat_combo.addItem("仅一次", "once")
        timed_pause_repeat_combo.addItem("每天", "daily")
        timed_pause_repeat_index = timed_pause_repeat_combo.findData(self._cc_timed_pause_repeat)
        if timed_pause_repeat_index >= 0:
            timed_pause_repeat_combo.setCurrentIndex(timed_pause_repeat_index)
        timed_pause_repeat_layout.addWidget(timed_pause_repeat_combo)
        timed_pause_repeat_layout.addStretch(1)
        timed_pause_layout.addLayout(timed_pause_repeat_layout)

        timed_pause_duration_layout = QHBoxLayout()
        timed_pause_duration_layout.addWidget(QLabel("暂停时长:"))
        timed_pause_duration_spinbox = QSpinBox(dialog)
        timed_pause_duration_spinbox.setRange(1, 999999)
        timed_pause_duration_spinbox.setValue(self._cc_timed_pause_duration_value)
        timed_pause_duration_unit_combo = QComboBox(dialog)
        timed_pause_duration_unit_combo.addItems(["秒", "分钟", "小时"])
        timed_pause_duration_unit_combo.setCurrentText(self._cc_timed_pause_duration_unit)
        timed_pause_duration_layout.addWidget(timed_pause_duration_spinbox)
        timed_pause_duration_layout.addWidget(timed_pause_duration_unit_combo)
        timed_pause_duration_layout.addStretch(1)
        timed_pause_layout.addLayout(timed_pause_duration_layout)

        timed_pause_target_holder = self._add_control_timer_target_selector(
            timed_pause_layout,
            self._cc_timed_pause_window_ids,
            "定时暂停 - 选择目标窗口",
        )
        timed_pause_layout.addStretch(1)
        tab_widget.addTab(timed_pause_tab, "定时暂停")
        return {
            "enabled": timed_pause_enable_checkbox,
            "hour": timed_pause_hour_spinbox,
            "minute": timed_pause_minute_spinbox,
            "repeat": timed_pause_repeat_combo,
            "duration": timed_pause_duration_spinbox,
            "duration_unit": timed_pause_duration_unit_combo,
            "target_holder": timed_pause_target_holder,
        }

    def _build_control_random_pause_tab(self, dialog, tab_widget):
        random_pause_tab = QWidget()
        random_pause_layout = QVBoxLayout(random_pause_tab)
        random_pause_layout.setSpacing(10)
        random_pause_layout.setContentsMargins(10, 10, 10, 10)

        random_pause_enable_checkbox = QCheckBox("启用随机暂停（概率触发）")
        random_pause_enable_checkbox.setChecked(self._cc_random_pause_enabled)
        random_pause_layout.addWidget(random_pause_enable_checkbox)

        probability_layout = QHBoxLayout()
        probability_layout.addWidget(QLabel("触发概率:"))
        probability_spinbox = QSpinBox(dialog)
        probability_spinbox.setRange(0, 100)
        probability_spinbox.setValue(self._cc_pause_probability)
        probability_spinbox.setSuffix(" %")
        probability_layout.addWidget(probability_spinbox)
        probability_layout.addStretch(1)
        random_pause_layout.addLayout(probability_layout)

        check_interval_layout = QHBoxLayout()
        check_interval_layout.addWidget(QLabel("检查间隔:"))
        check_interval_spinbox = QSpinBox(dialog)
        check_interval_spinbox.setRange(1, 86400)
        check_interval_spinbox.setValue(self._cc_pause_check_interval)
        check_interval_unit_combo = QComboBox(dialog)
        check_interval_unit_combo.addItems(["秒", "分钟"])
        check_interval_unit_combo.setCurrentText(self._cc_pause_check_interval_unit)
        check_interval_layout.addWidget(check_interval_spinbox)
        check_interval_layout.addWidget(check_interval_unit_combo)
        check_interval_layout.addStretch(1)
        random_pause_layout.addLayout(check_interval_layout)

        pause_min_layout = QHBoxLayout()
        pause_min_layout.addWidget(QLabel("暂停最小时长:"))
        pause_min_spinbox = QSpinBox(dialog)
        pause_min_spinbox.setRange(1, 86400)
        pause_min_spinbox.setValue(self._cc_pause_min_value)
        pause_min_unit_combo = QComboBox(dialog)
        pause_min_unit_combo.addItems(["秒", "分钟", "小时"])
        pause_min_unit_combo.setCurrentText(self._cc_pause_min_unit)
        pause_min_layout.addWidget(pause_min_spinbox)
        pause_min_layout.addWidget(pause_min_unit_combo)
        pause_min_layout.addStretch(1)
        random_pause_layout.addLayout(pause_min_layout)

        pause_max_layout = QHBoxLayout()
        pause_max_layout.addWidget(QLabel("暂停最大时长:"))
        pause_max_spinbox = QSpinBox(dialog)
        pause_max_spinbox.setRange(1, 86400)
        pause_max_spinbox.setValue(self._cc_pause_max_value)
        pause_max_unit_combo = QComboBox(dialog)
        pause_max_unit_combo.addItems(["秒", "分钟", "小时"])
        pause_max_unit_combo.setCurrentText(self._cc_pause_max_unit)
        pause_max_layout.addWidget(pause_max_spinbox)
        pause_max_layout.addWidget(pause_max_unit_combo)
        pause_max_layout.addStretch(1)
        random_pause_layout.addLayout(pause_max_layout)

        random_pause_target_holder = self._add_control_timer_target_selector(
            random_pause_layout,
            self._cc_random_pause_window_ids,
            "随机暂停 - 选择目标窗口",
        )
        random_pause_layout.addStretch(1)
        tab_widget.addTab(random_pause_tab, "随机暂停")
        return {
            "enabled": random_pause_enable_checkbox,
            "probability": probability_spinbox,
            "check_interval": check_interval_spinbox,
            "check_interval_unit": check_interval_unit_combo,
            "pause_min": pause_min_spinbox,
            "pause_min_unit": pause_min_unit_combo,
            "pause_max": pause_max_spinbox,
            "pause_max_unit": pause_max_unit_combo,
            "target_holder": random_pause_target_holder,
        }

    def _build_control_timer_dialog_buttons(self, main_layout):
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        stop_all_timer_btn = QPushButton("停止定时器")
        cancel_btn = QPushButton("取消")
        ok_btn = QPushButton("确定")
        button_layout.addWidget(stop_all_timer_btn)
        button_layout.addWidget(cancel_btn)
        button_layout.addWidget(ok_btn)
        main_layout.addLayout(button_layout)
        return {
            "stop_all": stop_all_timer_btn,
            "cancel": cancel_btn,
            "ok": ok_btn,
        }

    def _collect_control_timer_dialog_values(self, dialog, schedule_form, stop_form, timed_pause_form, random_pause_form):
        values = {
            "schedule_enabled": schedule_form["enabled"].isChecked(),
            "schedule_hour": schedule_form["hour"].value(),
            "schedule_minute": schedule_form["minute"].value(),
            "schedule_repeat": schedule_form["repeat"].currentData() or "daily",
            "schedule_window_ids": schedule_form["target_holder"]["ids"],
            "stop_enabled": stop_form["enabled"].isChecked(),
            "stop_hour": stop_form["hour"].value(),
            "stop_minute": stop_form["minute"].value(),
            "stop_repeat": stop_form["repeat"].currentData() or "daily",
            "stop_window_ids": stop_form["target_holder"]["ids"],
            "timed_pause_enabled": timed_pause_form["enabled"].isChecked(),
            "timed_pause_hour": timed_pause_form["hour"].value(),
            "timed_pause_minute": timed_pause_form["minute"].value(),
            "timed_pause_repeat": timed_pause_form["repeat"].currentData() or "daily",
            "timed_pause_duration_value": timed_pause_form["duration"].value(),
            "timed_pause_duration_unit": timed_pause_form["duration_unit"].currentText(),
            "timed_pause_window_ids": timed_pause_form["target_holder"]["ids"],
            "random_pause_enabled": random_pause_form["enabled"].isChecked(),
            "pause_probability": random_pause_form["probability"].value(),
            "pause_check_interval": random_pause_form["check_interval"].value(),
            "pause_check_interval_unit": random_pause_form["check_interval_unit"].currentText(),
            "pause_min_value": random_pause_form["pause_min"].value(),
            "pause_min_unit": random_pause_form["pause_min_unit"].currentText(),
            "pause_max_value": random_pause_form["pause_max"].value(),
            "pause_max_unit": random_pause_form["pause_max_unit"].currentText(),
            "random_pause_window_ids": random_pause_form["target_holder"]["ids"],
        }

        duration_seconds = self._convert_duration_to_seconds(
            values["timed_pause_duration_value"],
            values["timed_pause_duration_unit"],
        )
        if values["timed_pause_enabled"] and duration_seconds <= 0:
            QMessageBox.warning(dialog, "参数错误", "定时暂停时长必须大于0")
            return None

        pause_min_seconds = self._convert_duration_to_seconds(values["pause_min_value"], values["pause_min_unit"])
        pause_max_seconds = self._convert_duration_to_seconds(values["pause_max_value"], values["pause_max_unit"])
        if values["random_pause_enabled"] and pause_min_seconds > pause_max_seconds:
            QMessageBox.warning(dialog, "参数错误", "随机暂停最小时长不能大于最大时长")
            return None

        return values

    def _apply_control_timer_dialog_values(self, values):
        self._apply_control_schedule_timer_settings(
            schedule_enabled=values["schedule_enabled"],
            schedule_hour=values["schedule_hour"],
            schedule_minute=values["schedule_minute"],
            schedule_repeat=values["schedule_repeat"],
            schedule_window_ids=values["schedule_window_ids"],
            stop_enabled=values["stop_enabled"],
            stop_hour=values["stop_hour"],
            stop_minute=values["stop_minute"],
            stop_repeat=values["stop_repeat"],
            stop_window_ids=values["stop_window_ids"],
        )
        self._apply_control_pause_timer_settings(
            timed_pause_enabled=values["timed_pause_enabled"],
            timed_pause_hour=values["timed_pause_hour"],
            timed_pause_minute=values["timed_pause_minute"],
            timed_pause_repeat=values["timed_pause_repeat"],
            timed_pause_duration_value=values["timed_pause_duration_value"],
            timed_pause_duration_unit=values["timed_pause_duration_unit"],
            timed_pause_window_ids=values["timed_pause_window_ids"],
            random_pause_enabled=values["random_pause_enabled"],
            pause_probability=values["pause_probability"],
            pause_check_interval=values["pause_check_interval"],
            pause_check_interval_unit=values["pause_check_interval_unit"],
            pause_min_value=values["pause_min_value"],
            pause_min_unit=values["pause_min_unit"],
            pause_max_value=values["pause_max_value"],
            pause_max_unit=values["pause_max_unit"],
            random_pause_window_ids=values["random_pause_window_ids"],
        )
        self._save_control_timer_settings()

    def _handle_control_timer_dialog_submit(self, dialog, schedule_form, stop_form, timed_pause_form, random_pause_form):
        values = self._collect_control_timer_dialog_values(
            dialog,
            schedule_form,
            stop_form,
            timed_pause_form,
            random_pause_form,
        )
        if values is None:
            return

        self._apply_control_timer_dialog_values(values)
        logger.info("中控定时设置已更新")
        dialog.accept()

    def _handle_control_timer_dialog_stop_all(self, dialog):
        self._stop_all_control_timers(reset_state=True, persist=True, resume_if_timed=True)
        logger.info("中控定时器已全部停止")
        QMessageBox.information(dialog, "已停止", "中控定时器已停止并重置。")
        dialog.accept()

    def open_timer_dialog(self):
        dialog, main_layout, tab_widget = self._create_control_timer_dialog_shell()
        schedule_form = self._build_control_schedule_timer_tab(dialog, tab_widget)
        stop_form = self._build_control_stop_timer_tab(dialog, tab_widget)
        timed_pause_form = self._build_control_timed_pause_tab(dialog, tab_widget)
        random_pause_form = self._build_control_random_pause_tab(dialog, tab_widget)
        button_refs = self._build_control_timer_dialog_buttons(main_layout)

        button_refs["ok"].clicked.connect(
            lambda: self._handle_control_timer_dialog_submit(
                dialog,
                schedule_form,
                stop_form,
                timed_pause_form,
                random_pause_form,
            )
        )
        button_refs["cancel"].clicked.connect(dialog.reject)
        button_refs["stop_all"].clicked.connect(lambda: self._handle_control_timer_dialog_stop_all(dialog))

        dialog.exec()
        dialog.deleteLater()
