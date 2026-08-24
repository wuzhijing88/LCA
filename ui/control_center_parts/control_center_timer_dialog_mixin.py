# -*- coding: utf-8 -*-
import logging

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app_core.scheduling import START_MODE_DAILY, START_MODE_INTERVAL, duration_to_seconds
from app_core.scheduling.text import CHECK_INTERVAL_UNITS, DURATION_UNITS, INTERVAL_UNITS, UNIT_MINUTES, UNIT_SECONDS
from ui.scheduling.timer_form import (
    FORM_BUTTON_WIDTH,
    FORM_DIALOG_MARGINS,
    FORM_MODE_WIDTH,
    FORM_ROW_SPACING,
    add_combo_row,
    add_duration_row,
    add_enable_checkbox,
    add_next_preview_label,
    add_repeat_row,
    add_spin_row,
    add_target_row,
    add_time_row,
    add_timer_dialog_buttons,
    apply_timer_dialog_font,
    combo_unit_key,
    create_timer_dialog_shell,
    new_form_container,
    new_tab,
)
from utils.window_coordinate_common import center_window_on_widget_screen

logger = logging.getLogger(__name__)


class ControlCenterTimerDialogMixin:
    def _get_available_timer_window_options(self):
        options = []
        windows = self.sorted_windows if self.sorted_windows else self.bound_windows
        for idx, window_info in enumerate(windows or []):
            try:
                if not isinstance(window_info, dict):
                    continue
                window_id = ""
                resolve_id = getattr(self, "_window_runtime_id", None)
                if callable(resolve_id):
                    window_id = str(resolve_id(window_info, idx) or "").strip()
                if not window_id:
                    window_id = str(window_info.get("bind_id") or "").strip()
                if not window_id:
                    continue
                title = window_info.get("title", "未知窗口")
                display_title = self.format_window_title(title, idx)
                options.append((window_id, display_title))
            except Exception:
                continue
        return options

    def _format_target_windows_summary(self, selected_window_ids):
        selected, ok = self._resolve_configured_window_filter(selected_window_ids)
        if not ok:
            return "目标窗口：无有效窗口"
        if selected is None:
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

        initial_ids = self._normalize_window_id_list(initial_window_ids)
        selected_ids = set(self._canonicalize_timer_window_ids(initial_ids))
        invalid_only = bool(initial_ids) and not selected_ids

        picker = QDialog(self)
        apply_timer_dialog_font(picker)
        picker.setWindowTitle(title)
        picker.setModal(True)
        picker.setMinimumWidth(420)
        picker.setMaximumWidth(620)
        picker.resize(460, 420)

        layout = QVBoxLayout(picker)
        layout.setContentsMargins(*FORM_DIALOG_MARGINS)
        layout.setSpacing(FORM_ROW_SPACING)

        tip_label = QLabel(
            "原配置窗口已失效。请重新勾选；不勾选并确定将保持原配置，不会变成全部窗口。"
            if invalid_only
            else "勾选后仅对这些窗口生效；不勾选任何窗口表示全部窗口。"
        )
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
        cancel_btn.setFixedWidth(FORM_BUTTON_WIDTH)
        ok_btn.setFixedWidth(FORM_BUTTON_WIDTH)
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
        return self._commit_timer_target_picker_ids(initial_ids, result_ids)

    def _add_control_timer_target_selector(self, layout, selected_window_ids, picker_title):
        target_holder = {"ids": list(self._retain_timer_window_ids(selected_window_ids))}
        target_label, target_button = add_target_row(
            layout, self._format_target_windows_summary(target_holder["ids"])
        )

        def on_choose_windows():
            selected = self._choose_timer_target_windows(target_holder["ids"], picker_title)
            if selected is None:
                return
            target_holder["ids"] = selected
            target_label.setText(self._format_target_windows_summary(selected))

        target_button.clicked.connect(on_choose_windows)
        return target_holder

    def _build_control_schedule_timer_tab(self, dialog, tab_widget):
        _tab, schedule_layout = new_tab(tab_widget, "定时启动")
        schedule_enable_checkbox = add_enable_checkbox(
            schedule_layout, "启用定时启动", self._cc_schedule_enabled
        )
        schedule_mode_combo = add_combo_row(
            schedule_layout,
            dialog,
            "启动方式:",
            (("每天/仅一次", START_MODE_DAILY), ("每隔", START_MODE_INTERVAL)),
            current=getattr(self, "_cc_schedule_mode", START_MODE_DAILY),
            min_width=FORM_MODE_WIDTH,
        )

        daily_container, daily_layout = new_form_container()
        schedule_hour_spinbox, schedule_minute_spinbox = add_time_row(
            daily_layout,
            dialog,
            "启动时间:",
            self._cc_schedule_hour,
            self._cc_schedule_minute,
        )
        schedule_repeat_combo = add_repeat_row(daily_layout, dialog, self._cc_schedule_repeat)
        schedule_layout.addWidget(daily_container)

        interval_container, interval_layout = new_form_container()
        interval_spinbox, interval_unit_combo = add_duration_row(
            interval_layout,
            dialog,
            "每隔:",
            getattr(self, "_cc_schedule_interval_value", 30),
            getattr(self, "_cc_schedule_interval_unit", UNIT_MINUTES),
            INTERVAL_UNITS,
        )
        schedule_layout.addWidget(interval_container)

        preview_label = add_next_preview_label(schedule_layout)

        def refresh_start_mode():
            is_interval = schedule_mode_combo.currentData() == START_MODE_INTERVAL
            daily_container.setVisible(not is_interval)
            interval_container.setVisible(is_interval)
            if is_interval:
                preview_label.setText(
                    f"启用后先等 {interval_spinbox.value()}{interval_unit_combo.currentText()}，"
                    "到点只启动空闲窗口"
                )
            else:
                repeat_mode = schedule_repeat_combo.currentData() or "daily"
                suffix = "仅一次" if repeat_mode == "once" else "每天"
                preview_label.setText(
                    f"将于 {schedule_hour_spinbox.value():02d}:{schedule_minute_spinbox.value():02d} {suffix}"
                )

        schedule_mode_combo.currentIndexChanged.connect(lambda _=None: refresh_start_mode())
        interval_spinbox.valueChanged.connect(lambda _=None: refresh_start_mode())
        interval_unit_combo.currentIndexChanged.connect(lambda _=None: refresh_start_mode())
        schedule_hour_spinbox.valueChanged.connect(lambda _=None: refresh_start_mode())
        schedule_minute_spinbox.valueChanged.connect(lambda _=None: refresh_start_mode())
        schedule_repeat_combo.currentIndexChanged.connect(lambda _=None: refresh_start_mode())
        refresh_start_mode()

        schedule_target_holder = self._add_control_timer_target_selector(
            schedule_layout,
            self._cc_schedule_window_ids,
            "定时启动 - 选择目标窗口",
        )
        schedule_layout.addStretch(1)
        return {
            "enabled": schedule_enable_checkbox,
            "mode": schedule_mode_combo,
            "hour": schedule_hour_spinbox,
            "minute": schedule_minute_spinbox,
            "repeat": schedule_repeat_combo,
            "interval": interval_spinbox,
            "interval_unit": interval_unit_combo,
            "target_holder": schedule_target_holder,
        }

    def _build_control_stop_timer_tab(self, dialog, tab_widget):
        _tab, stop_layout = new_tab(tab_widget, "定时停止")
        stop_enable_checkbox = add_enable_checkbox(stop_layout, "启用定时停止", self._cc_stop_enabled)
        stop_hour_spinbox, stop_minute_spinbox = add_time_row(
            stop_layout, dialog, "停止时间:", self._cc_stop_hour, self._cc_stop_minute
        )
        stop_repeat_combo = add_repeat_row(stop_layout, dialog, self._cc_stop_repeat)
        stop_target_holder = self._add_control_timer_target_selector(
            stop_layout,
            self._cc_stop_window_ids,
            "定时停止 - 选择目标窗口",
        )
        stop_layout.addStretch(1)
        return {
            "enabled": stop_enable_checkbox,
            "hour": stop_hour_spinbox,
            "minute": stop_minute_spinbox,
            "repeat": stop_repeat_combo,
            "target_holder": stop_target_holder,
        }

    def _build_control_timed_pause_tab(self, dialog, tab_widget):
        _tab, timed_pause_layout = new_tab(tab_widget, "定时暂停")
        timed_pause_enable_checkbox = add_enable_checkbox(
            timed_pause_layout,
            "启用定时暂停（到点暂停，按时长恢复）",
            self._cc_timed_pause_enabled,
        )
        timed_pause_hour_spinbox, timed_pause_minute_spinbox = add_time_row(
            timed_pause_layout,
            dialog,
            "暂停时间:",
            self._cc_timed_pause_hour,
            self._cc_timed_pause_minute,
        )
        timed_pause_repeat_combo = add_repeat_row(
            timed_pause_layout, dialog, self._cc_timed_pause_repeat
        )
        timed_pause_duration_spinbox, timed_pause_duration_unit_combo = add_duration_row(
            timed_pause_layout,
            dialog,
            "暂停时长:",
            self._cc_timed_pause_duration_value,
            self._cc_timed_pause_duration_unit,
            DURATION_UNITS,
        )
        timed_pause_target_holder = self._add_control_timer_target_selector(
            timed_pause_layout,
            self._cc_timed_pause_window_ids,
            "定时暂停 - 选择目标窗口",
        )
        timed_pause_layout.addStretch(1)
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
        _tab, random_pause_layout = new_tab(tab_widget, "随机暂停")
        random_pause_enable_checkbox = add_enable_checkbox(
            random_pause_layout,
            "启用随机暂停（概率触发）",
            self._cc_random_pause_enabled,
        )
        probability_spinbox = add_spin_row(
            random_pause_layout,
            dialog,
            "触发概率:",
            self._cc_pause_probability,
            0,
            100,
            suffix=" %",
        )
        check_interval_spinbox, check_interval_unit_combo = add_duration_row(
            random_pause_layout,
            dialog,
            "检查间隔:",
            self._cc_pause_check_interval,
            self._cc_pause_check_interval_unit,
            CHECK_INTERVAL_UNITS,
        )
        pause_min_spinbox, pause_min_unit_combo = add_duration_row(
            random_pause_layout,
            dialog,
            "暂停最小时长:",
            self._cc_pause_min_value,
            self._cc_pause_min_unit,
            DURATION_UNITS,
        )
        pause_max_spinbox, pause_max_unit_combo = add_duration_row(
            random_pause_layout,
            dialog,
            "暂停最大时长:",
            self._cc_pause_max_value,
            self._cc_pause_max_unit,
            DURATION_UNITS,
        )
        random_pause_target_holder = self._add_control_timer_target_selector(
            random_pause_layout,
            self._cc_random_pause_window_ids,
            "随机暂停 - 选择目标窗口",
        )
        random_pause_layout.addStretch(1)
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

    def _collect_control_timer_dialog_values(self, dialog, schedule_form, stop_form, timed_pause_form, random_pause_form):
        values = {
            "schedule_enabled": schedule_form["enabled"].isChecked(),
            "schedule_mode": schedule_form["mode"].currentData() or START_MODE_DAILY,
            "schedule_hour": schedule_form["hour"].value(),
            "schedule_minute": schedule_form["minute"].value(),
            "schedule_repeat": schedule_form["repeat"].currentData() or "daily",
            "schedule_interval_value": schedule_form["interval"].value(),
            "schedule_interval_unit": combo_unit_key(
                schedule_form["interval_unit"], default=UNIT_MINUTES, allowed=INTERVAL_UNITS
            ),
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
            "timed_pause_duration_unit": combo_unit_key(
                timed_pause_form["duration_unit"], default=UNIT_MINUTES, allowed=DURATION_UNITS
            ),
            "timed_pause_window_ids": timed_pause_form["target_holder"]["ids"],
            "random_pause_enabled": random_pause_form["enabled"].isChecked(),
            "pause_probability": random_pause_form["probability"].value(),
            "pause_check_interval": random_pause_form["check_interval"].value(),
            "pause_check_interval_unit": combo_unit_key(
                random_pause_form["check_interval_unit"],
                default=UNIT_SECONDS,
                allowed=CHECK_INTERVAL_UNITS,
            ),
            "pause_min_value": random_pause_form["pause_min"].value(),
            "pause_min_unit": combo_unit_key(
                random_pause_form["pause_min_unit"], default=UNIT_SECONDS, allowed=DURATION_UNITS
            ),
            "pause_max_value": random_pause_form["pause_max"].value(),
            "pause_max_unit": combo_unit_key(
                random_pause_form["pause_max_unit"], default=UNIT_SECONDS, allowed=DURATION_UNITS
            ),
            "random_pause_window_ids": random_pause_form["target_holder"]["ids"],
        }

        duration_seconds = duration_to_seconds(
            values["timed_pause_duration_value"],
            values["timed_pause_duration_unit"],
        )
        if values["timed_pause_enabled"] and duration_seconds <= 0:
            QMessageBox.warning(dialog, "参数错误", "定时暂停时长必须大于0")
            return None

        pause_min_seconds = duration_to_seconds(values["pause_min_value"], values["pause_min_unit"])
        pause_max_seconds = duration_to_seconds(values["pause_max_value"], values["pause_max_unit"])
        if values["random_pause_enabled"] and pause_min_seconds > pause_max_seconds:
            QMessageBox.warning(dialog, "参数错误", "随机暂停最小时长不能大于最大时长")
            return None

        return values

    def _apply_control_timer_dialog_values(self, values):
        self._apply_control_schedule_timer_settings(
            schedule_enabled=values["schedule_enabled"],
            schedule_mode=values["schedule_mode"],
            schedule_hour=values["schedule_hour"],
            schedule_minute=values["schedule_minute"],
            schedule_repeat=values["schedule_repeat"],
            schedule_interval_value=values["schedule_interval_value"],
            schedule_interval_unit=values["schedule_interval_unit"],
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
        dialog, main_layout, tab_widget = create_timer_dialog_shell(self, "中控定时任务")
        schedule_form = self._build_control_schedule_timer_tab(dialog, tab_widget)
        stop_form = self._build_control_stop_timer_tab(dialog, tab_widget)
        timed_pause_form = self._build_control_timed_pause_tab(dialog, tab_widget)
        random_pause_form = self._build_control_random_pause_tab(dialog, tab_widget)
        button_refs = add_timer_dialog_buttons(main_layout)

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
        center_window_on_widget_screen(dialog, self)
        dialog.exec()
        dialog.deleteLater()
