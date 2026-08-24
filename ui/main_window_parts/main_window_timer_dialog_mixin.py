# -*- coding: utf-8 -*-
import logging

from PySide6.QtWidgets import QMessageBox

from app_core.scheduling import (
    START_MODE_DAILY,
    ScheduleBundle,
    duration_to_seconds,
    format_clock_label,
)
from app_core.scheduling.text import CHECK_INTERVAL_UNITS, DURATION_UNITS
from ui.scheduling.timer_form import (
    TimerComboBox,
    TimerSpinBox,
    add_duration_row,
    add_enable_checkbox,
    add_next_preview_label,
    add_repeat_row,
    add_spin_row,
    add_time_row,
    add_timer_dialog_buttons,
    combo_unit_key,
    create_timer_dialog_shell,
    new_tab,
)
from utils.window_coordinate_common import center_window_on_widget_screen

logger = logging.getLogger(__name__)


class MainWindowTimerDialogMixin:
    def _get_combo_data(self, combo):
        if combo is None:
            return None
        current_index = combo.currentIndex()
        if current_index >= 0:
            data = combo.itemData(current_index)
            if data is not None:
                return data
        return combo.currentText() if hasattr(combo, "currentText") else None

    def _build_main_clock_tab(self, dialog, tab_widget, title, enable_text, time_label, policy, spinbox_cls=None, combo_cls=None, extra_rows=None):
        spinbox_cls = spinbox_cls or TimerSpinBox
        combo_cls = combo_cls or TimerComboBox
        _tab, layout = new_tab(tab_widget, title)
        enabled = add_enable_checkbox(layout, enable_text, policy.enabled)
        hour, minute = add_time_row(layout, dialog, time_label, policy.hour, policy.minute, spinbox_cls)
        repeat = add_repeat_row(layout, dialog, policy.repeat, combo_cls)
        extras = extra_rows(layout) if extra_rows else {}
        preview = add_next_preview_label(layout)
        layout.addStretch(1)

        def refresh():
            if not enabled.isChecked():
                preview.setText(f"{title}未启用")
                return
            repeat_mode = self._get_combo_data(repeat) or "daily"
            suffix = "仅一次" if repeat_mode == "once" else "每天"
            preview.setText(f"将于 {hour.value():02d}:{minute.value():02d} {suffix}")

        enabled.toggled.connect(lambda _=None: refresh())
        hour.valueChanged.connect(lambda _=None: refresh())
        minute.valueChanged.connect(lambda _=None: refresh())
        repeat.currentIndexChanged.connect(lambda _=None: refresh())
        refresh()
        form = {"enabled": enabled, "hour": hour, "minute": minute, "repeat": repeat, "preview": preview}
        form.update(extras)
        return form

    def open_timer_dialog(self):
        bundle = self._main_schedule
        dialog, main_layout, tab_widget = create_timer_dialog_shell(self, "定时任务")

        start_form = self._build_main_clock_tab(
            dialog,
            tab_widget,
            "定时启动",
            "启用定时启动",
            "启动时间:",
            bundle.start,
        )
        stop_form = self._build_main_clock_tab(
            dialog,
            tab_widget,
            "定时停止",
            "启用定时停止",
            "停止时间:",
            bundle.stop,
        )

        def timed_pause_extras(layout):
            duration, unit = add_duration_row(
                layout,
                dialog,
                "暂停时长:",
                bundle.timed_pause.duration_value,
                bundle.timed_pause.duration_unit,
                DURATION_UNITS,
            )
            return {"duration": duration, "duration_unit": unit}

        timed_pause_form = self._build_main_clock_tab(
            dialog,
            tab_widget,
            "定时暂停",
            "启用定时暂停（到点暂停，按时长恢复）",
            "暂停时间:",
            bundle.timed_pause,
            extra_rows=timed_pause_extras,
        )

        _random_tab, random_layout = new_tab(tab_widget, "随机暂停")
        random_enabled = add_enable_checkbox(random_layout, "启用随机暂停（概率触发）", bundle.random_pause.enabled)
        probability = add_spin_row(
            random_layout,
            dialog,
            "触发概率:",
            bundle.random_pause.probability,
            0,
            100,
            suffix=" %",
        )
        check_interval, check_unit = add_duration_row(
            random_layout,
            dialog,
            "检查间隔:",
            bundle.random_pause.check_interval_value,
            bundle.random_pause.check_interval_unit,
            CHECK_INTERVAL_UNITS,
        )
        pause_min, pause_min_unit = add_duration_row(
            random_layout,
            dialog,
            "暂停最小时长:",
            bundle.random_pause.min_value,
            bundle.random_pause.min_unit,
            DURATION_UNITS,
        )
        pause_max, pause_max_unit = add_duration_row(
            random_layout,
            dialog,
            "暂停最大时长:",
            bundle.random_pause.max_value,
            bundle.random_pause.max_unit,
            DURATION_UNITS,
        )
        random_layout.addStretch(1)
        random_form = {
            "enabled": random_enabled,
            "probability": probability,
            "check_interval": check_interval,
            "check_interval_unit": check_unit,
            "pause_min": pause_min,
            "pause_min_unit": pause_min_unit,
            "pause_max": pause_max,
            "pause_max_unit": pause_max_unit,
        }

        buttons = add_timer_dialog_buttons(main_layout)
        buttons["ok"].clicked.connect(
            lambda: self._handle_main_timer_dialog_submit(
                dialog, start_form, stop_form, timed_pause_form, random_form
            )
        )
        buttons["cancel"].clicked.connect(dialog.reject)
        buttons["stop_all"].clicked.connect(lambda: self._handle_main_timer_dialog_stop_all(dialog))
        center_window_on_widget_screen(dialog, self)
        dialog.exec()
        dialog.deleteLater()

    def _collect_main_timer_dialog_values(self, dialog, start_form, stop_form, timed_pause_form, random_form):
        values = {
            "start_enabled": start_form["enabled"].isChecked(),
            "start_hour": start_form["hour"].value(),
            "start_minute": start_form["minute"].value(),
            "start_repeat": self._get_combo_data(start_form["repeat"]) or "daily",
            "stop_enabled": stop_form["enabled"].isChecked(),
            "stop_hour": stop_form["hour"].value(),
            "stop_minute": stop_form["minute"].value(),
            "stop_repeat": self._get_combo_data(stop_form["repeat"]) or "daily",
            "timed_pause_enabled": timed_pause_form["enabled"].isChecked(),
            "timed_pause_hour": timed_pause_form["hour"].value(),
            "timed_pause_minute": timed_pause_form["minute"].value(),
            "timed_pause_repeat": self._get_combo_data(timed_pause_form["repeat"]) or "daily",
            "timed_pause_duration_value": timed_pause_form["duration"].value(),
            "timed_pause_duration_unit": combo_unit_key(
                timed_pause_form["duration_unit"], allowed=DURATION_UNITS
            ),
            "random_pause_enabled": random_form["enabled"].isChecked(),
            "probability": random_form["probability"].value(),
            "check_interval": random_form["check_interval"].value(),
            "check_interval_unit": combo_unit_key(
                random_form["check_interval_unit"], default="seconds", allowed=CHECK_INTERVAL_UNITS
            ),
            "pause_min": random_form["pause_min"].value(),
            "pause_min_unit": combo_unit_key(random_form["pause_min_unit"], allowed=DURATION_UNITS),
            "pause_max": random_form["pause_max"].value(),
            "pause_max_unit": combo_unit_key(random_form["pause_max_unit"], allowed=DURATION_UNITS),
        }
        if values["timed_pause_enabled"] and duration_to_seconds(
            values["timed_pause_duration_value"], values["timed_pause_duration_unit"]
        ) <= 0:
            QMessageBox.warning(dialog, "参数错误", "定时暂停时长必须大于0")
            return None
        if values["random_pause_enabled"]:
            pause_min = duration_to_seconds(values["pause_min"], values["pause_min_unit"])
            pause_max = duration_to_seconds(values["pause_max"], values["pause_max_unit"])
            if pause_min > pause_max:
                QMessageBox.warning(dialog, "参数错误", "随机暂停最小时长不能大于最大时长")
                return None
        return values

    def _handle_main_timer_dialog_submit(self, dialog, start_form, stop_form, timed_pause_form, random_form):
        values = self._collect_main_timer_dialog_values(
            dialog, start_form, stop_form, timed_pause_form, random_form
        )
        if values is None:
            return

        bundle = ScheduleBundle()
        bundle.start.enabled = values["start_enabled"]
        bundle.start.hour = values["start_hour"]
        bundle.start.minute = values["start_minute"]
        bundle.start.repeat = values["start_repeat"]
        bundle.start.mode = START_MODE_DAILY
        bundle.stop.enabled = values["stop_enabled"]
        bundle.stop.hour = values["stop_hour"]
        bundle.stop.minute = values["stop_minute"]
        bundle.stop.repeat = values["stop_repeat"]
        bundle.timed_pause.enabled = values["timed_pause_enabled"]
        bundle.timed_pause.hour = values["timed_pause_hour"]
        bundle.timed_pause.minute = values["timed_pause_minute"]
        bundle.timed_pause.repeat = values["timed_pause_repeat"]
        bundle.timed_pause.duration_value = values["timed_pause_duration_value"]
        bundle.timed_pause.duration_unit = values["timed_pause_duration_unit"]
        bundle.random_pause.enabled = values["random_pause_enabled"]
        bundle.random_pause.probability = values["probability"]
        bundle.random_pause.check_interval_value = values["check_interval"]
        bundle.random_pause.check_interval_unit = values["check_interval_unit"]
        bundle.random_pause.min_value = values["pause_min"]
        bundle.random_pause.min_unit = values["pause_min_unit"]
        bundle.random_pause.max_value = values["pause_max"]
        bundle.random_pause.max_unit = values["pause_max_unit"]

        if not bundle.timed_pause.enabled:
            if hasattr(self, "_timed_pause_resume_timer") and self._timed_pause_resume_timer.isActive():
                self._timed_pause_resume_timer.stop()
            if self._is_paused and getattr(self, "_auto_pause_source", None) == "timed":
                self._resume_workflow(source="timed")

        if bundle.random_pause.enabled:
            running_count = 0
            if hasattr(self, "task_manager") and self.task_manager:
                running_count = self.task_manager.get_running_count()
            self._apply_main_schedule_bundle(bundle)
            if running_count > 0:
                self._start_random_pause_cycle()
        else:
            if hasattr(self, "_random_pause_timer") and self._random_pause_timer.isActive():
                self._random_pause_timer.stop()
            if hasattr(self, "_random_pause_resume_timer") and self._random_pause_resume_timer.isActive():
                self._random_pause_resume_timer.stop()
            if self._is_paused and getattr(self, "_auto_pause_source", None) == "random":
                self._resume_workflow(source="random")
            self._apply_main_schedule_bundle(bundle)

        logger.info("主窗口定时设置已更新: %s", format_clock_label(bundle.start))
        dialog.accept()

    def _handle_main_timer_dialog_stop_all(self, dialog):
        self._stop_all_main_timers(reset_state=True, persist=True, resume_if_paused=True)
        QMessageBox.information(dialog, "定时器已停止", "定时器已停止并重置")
        dialog.accept()
