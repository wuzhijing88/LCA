import logging
import time
from datetime import datetime

from PySide6.QtCore import QTimer

logger = logging.getLogger(__name__)


class ControlCenterPauseTimerMixin:
    def _setup_control_pause_timers(self):
        self._cc_timed_pause_timer = QTimer(self)
        self._cc_timed_pause_timer.timeout.connect(self._check_control_timed_pause_time)

        self._cc_timed_pause_resume_timer = QTimer(self)
        self._cc_timed_pause_resume_timer.setSingleShot(True)
        self._cc_timed_pause_resume_timer.timeout.connect(self._on_control_timed_pause_resume_timeout)

        self._cc_random_pause_timer = QTimer(self)
        self._cc_random_pause_timer.timeout.connect(self._on_control_random_pause_check)

        self._cc_random_pause_resume_timer = QTimer(self)
        self._cc_random_pause_resume_timer.setSingleShot(True)
        self._cc_random_pause_resume_timer.timeout.connect(self._on_control_random_pause_resume_timeout)

        self._cc_random_pause_countdown_timer = QTimer(self)
        self._cc_random_pause_countdown_timer.setInterval(1000)
        self._cc_random_pause_countdown_timer.timeout.connect(self._on_control_random_pause_countdown_tick)
        self._cc_random_pause_deadlines_by_window = {}
        self._cc_random_auto_paused_window_ids = set()

    def _load_control_pause_timer_settings(self, config):
        self._cc_timed_pause_enabled = self._coerce_bool(config.get("cc_timed_pause_enabled", False), False)
        self._cc_timed_pause_hour = self._coerce_int(config.get("cc_timed_pause_hour", 12), 12, 0, 23)
        self._cc_timed_pause_minute = self._coerce_int(config.get("cc_timed_pause_minute", 0), 0, 0, 59)
        self._cc_timed_pause_repeat = self._normalize_repeat_mode(config.get("cc_timed_pause_repeat", "daily"))
        self._cc_timed_pause_duration_value = self._coerce_int(
            config.get("cc_timed_pause_duration_value", 10), 10, 1, 999999
        )
        self._cc_timed_pause_duration_unit = self._normalize_duration_unit(
            config.get("cc_timed_pause_duration_unit", "分钟")
        )
        self._cc_timed_pause_executed = False
        self._cc_timed_pause_last_exec_date = None
        self._cc_timed_auto_paused_window_ids = set()

        self._cc_random_pause_enabled = self._coerce_bool(config.get("cc_random_pause_enabled", False), False)
        self._cc_pause_probability = self._coerce_int(config.get("cc_pause_probability", 20), 20, 0, 100)
        self._cc_pause_check_interval = self._coerce_int(config.get("cc_pause_check_interval", 30), 30, 1, 86400)
        self._cc_pause_check_interval_unit = self._normalize_interval_unit(
            config.get("cc_pause_check_interval_unit", "秒")
        )
        self._cc_pause_min_value = self._coerce_int(config.get("cc_pause_min_value", 60), 60, 1, 86400)
        self._cc_pause_min_unit = self._normalize_duration_unit(config.get("cc_pause_min_unit", "秒"), "秒")
        self._cc_pause_max_value = self._coerce_int(config.get("cc_pause_max_value", 120), 120, 1, 86400)
        self._cc_pause_max_unit = self._normalize_duration_unit(config.get("cc_pause_max_unit", "秒"), "秒")
        self._cc_random_pause_deadlines_by_window = {}
        self._cc_random_auto_paused_window_ids = set()

        self._cc_timed_pause_window_ids = self._normalize_window_id_list(config.get("cc_timed_pause_window_ids"))
        self._cc_random_pause_window_ids = self._normalize_window_id_list(config.get("cc_random_pause_window_ids"))

    def _save_control_pause_timer_settings(self, config):
        config["cc_timed_pause_enabled"] = self._cc_timed_pause_enabled
        config["cc_timed_pause_hour"] = self._cc_timed_pause_hour
        config["cc_timed_pause_minute"] = self._cc_timed_pause_minute
        config["cc_timed_pause_repeat"] = self._cc_timed_pause_repeat
        config["cc_timed_pause_duration_value"] = self._cc_timed_pause_duration_value
        config["cc_timed_pause_duration_unit"] = self._cc_timed_pause_duration_unit

        config["cc_random_pause_enabled"] = self._cc_random_pause_enabled
        config["cc_pause_probability"] = self._cc_pause_probability
        config["cc_pause_check_interval"] = self._cc_pause_check_interval
        config["cc_pause_check_interval_unit"] = self._cc_pause_check_interval_unit
        config["cc_pause_min_value"] = self._cc_pause_min_value
        config["cc_pause_min_unit"] = self._cc_pause_min_unit
        config["cc_pause_max_value"] = self._cc_pause_max_value
        config["cc_pause_max_unit"] = self._cc_pause_max_unit

        config["cc_timed_pause_window_ids"] = list(self._cc_timed_pause_window_ids)
        config["cc_random_pause_window_ids"] = list(self._cc_random_pause_window_ids)

    def _apply_control_pause_timer_settings(
        self,
        *,
        timed_pause_enabled,
        timed_pause_hour,
        timed_pause_minute,
        timed_pause_repeat,
        timed_pause_duration_value,
        timed_pause_duration_unit,
        timed_pause_window_ids,
        random_pause_enabled,
        pause_probability,
        pause_check_interval,
        pause_check_interval_unit,
        pause_min_value,
        pause_min_unit,
        pause_max_value,
        pause_max_unit,
        random_pause_window_ids,
    ):
        self._cc_timed_pause_enabled = timed_pause_enabled
        self._cc_timed_pause_hour = self._coerce_int(timed_pause_hour, 12, 0, 23)
        self._cc_timed_pause_minute = self._coerce_int(timed_pause_minute, 0, 0, 59)
        self._cc_timed_pause_repeat = self._normalize_repeat_mode(timed_pause_repeat)
        self._cc_timed_pause_duration_value = self._coerce_int(timed_pause_duration_value, 10, 1, 999999)
        self._cc_timed_pause_duration_unit = self._normalize_duration_unit(timed_pause_duration_unit)
        self._cc_timed_pause_window_ids = self._normalize_window_id_list(timed_pause_window_ids)

        self._cc_random_pause_enabled = random_pause_enabled
        self._cc_pause_probability = self._coerce_int(pause_probability, 20, 0, 100)
        self._cc_pause_check_interval = self._coerce_int(pause_check_interval, 30, 1, 86400)
        self._cc_pause_check_interval_unit = self._normalize_interval_unit(pause_check_interval_unit, "秒")
        self._cc_pause_min_value = self._coerce_int(pause_min_value, 60, 1, 86400)
        self._cc_pause_min_unit = self._normalize_duration_unit(pause_min_unit, "秒")
        self._cc_pause_max_value = self._coerce_int(pause_max_value, 120, 1, 86400)
        self._cc_pause_max_unit = self._normalize_duration_unit(pause_max_unit, "秒")
        self._cc_random_pause_window_ids = self._normalize_window_id_list(random_pause_window_ids)

        if not self._cc_timed_pause_enabled:
            if self._cc_timed_pause_resume_timer.isActive():
                self._cc_timed_pause_resume_timer.stop()
            if self._cc_auto_pause_source == "timed":
                self._resume_all_paused_runners(
                    "中控定时暂停已禁用",
                    target_window_ids=self._cc_timed_auto_paused_window_ids,
                )
                self._cc_auto_pause_source = None
            self._cc_timed_auto_paused_window_ids = set()

        if not self._cc_random_pause_enabled:
            self._clear_random_pause_runtime(resume=True, reason="中控随机暂停已禁用")

        self._update_control_timed_pause_config()
        self._update_control_random_pause_config()

    def _update_control_timed_pause_config(self):
        if self._cc_timed_pause_timer.isActive():
            self._cc_timed_pause_timer.stop()

        self._cc_timed_pause_executed = False
        self._cc_timed_pause_last_exec_date = None
        if self._cc_timed_pause_enabled:
            self._cc_timed_pause_timer.start(1000)
            logger.info(
                f"中控定时暂停已启用，将在 {self._cc_timed_pause_hour:02d}:{self._cc_timed_pause_minute:02d} 暂停，"
                f"持续 {self._cc_timed_pause_duration_value}{self._cc_timed_pause_duration_unit}，"
                f"重复模式: {self._cc_timed_pause_repeat}"
            )
        self._refresh_control_timer_status_label()

    def _update_control_random_pause_config(self):
        if self._cc_random_pause_timer.isActive():
            self._cc_random_pause_timer.stop()

        if self._cc_random_pause_enabled:
            interval_ms = self._convert_interval_to_milliseconds(
                self._cc_pause_check_interval,
                self._cc_pause_check_interval_unit,
            )
            self._cc_random_pause_timer.start(interval_ms)
            logger.info(
                f"中控随机暂停已启用: 间隔={interval_ms}ms "
                f"({self._cc_pause_check_interval}{self._cc_pause_check_interval_unit}), "
                f"概率={self._cc_pause_probability}%"
            )
        else:
            self._clear_random_pause_runtime(resume=True, reason="中控随机暂停已禁用")
        self._refresh_control_timer_status_label()

    def _clear_random_pause_runtime(self, resume=False, reason="", target_window_ids=None):
        runtime_map = getattr(self, "_cc_random_pause_deadlines_by_window", None)
        if not isinstance(runtime_map, dict):
            runtime_map = {}
            self._cc_random_pause_deadlines_by_window = runtime_map

        target_filter = set(self._normalize_window_id_list(target_window_ids)) if target_window_ids else None
        tracked_window_ids = set(runtime_map.keys())
        if target_filter is not None:
            tracked_window_ids &= target_filter

        resumed_window_ids = set()
        if resume and tracked_window_ids:
            for window_id in sorted(tracked_window_ids):
                if self._resume_single_window_runners(window_id):
                    resumed_window_ids.add(window_id)

        for window_id in tracked_window_ids:
            runtime_map.pop(window_id, None)

        restored_window_ids = set(resumed_window_ids)
        for window_id in tracked_window_ids:
            if window_id in restored_window_ids:
                continue
            if self._window_has_running_runner(window_id) and (not self._window_has_paused_runner(window_id)):
                restored_window_ids.add(window_id)

        if restored_window_ids:
            step_text = reason if reason else "中控随机暂停已恢复"
            self._update_window_table_status(restored_window_ids, "正在运行", step_text)

        self._cc_random_auto_paused_window_ids = set(runtime_map.keys())

        if hasattr(self, "_cc_random_pause_resume_timer") and self._cc_random_pause_resume_timer.isActive():
            self._cc_random_pause_resume_timer.stop()

        if not runtime_map and hasattr(self, "_cc_random_pause_countdown_timer"):
            if self._cc_random_pause_countdown_timer.isActive():
                self._cc_random_pause_countdown_timer.stop()

        self._sync_pause_all_button_text()

    def _convert_duration_to_seconds(self, value: int, unit: str) -> int:
        if unit == "小时":
            return int(value) * 3600
        if unit == "分钟":
            return int(value) * 60
        return int(value)

    def _convert_interval_to_milliseconds(self, value: int, unit: str) -> int:
        if unit == "分钟":
            return max(1000, int(value) * 60 * 1000)
        return max(1000, int(value) * 1000)

    def _trigger_control_timed_pause(self) -> bool:
        duration_sec = self._convert_duration_to_seconds(
            self._cc_timed_pause_duration_value,
            self._cc_timed_pause_duration_unit,
        )
        duration_sec = max(1, int(duration_sec))

        paused_window_ids = self._pause_all_running_runners(
            "中控定时暂停",
            target_window_ids=self._cc_timed_pause_window_ids,
        )
        if not paused_window_ids:
            return False

        self._cc_timed_auto_paused_window_ids = set(paused_window_ids)
        self._cc_auto_pause_source = "timed"
        duration_ms = duration_sec * 1000
        max_qtimer_ms = 2147483647
        if duration_ms > max_qtimer_ms:
            duration_ms = max_qtimer_ms
            logger.warning("[中控定时暂停] 恢复时长超过QTimer上限，已截断到最大值")
        self._cc_timed_pause_resume_timer.start(duration_ms)
        logger.info(f"[中控定时暂停] 已暂停，将在 {duration_sec} 秒后自动恢复")
        return True

    def _check_control_timed_pause_time(self):
        if not self._cc_timed_pause_enabled or getattr(self, "_is_closing", False):
            return

        now = datetime.now()
        current_hour = now.hour
        current_minute = now.minute
        today = now.date()

        if self._cc_timed_pause_repeat == "daily" and self._cc_timed_pause_executed:
            if self._cc_timed_pause_last_exec_date is not None and self._cc_timed_pause_last_exec_date != today:
                self._cc_timed_pause_executed = False
                logger.info("[中控定时暂停] 跨日重置执行标记")

        if current_hour == self._cc_timed_pause_hour and current_minute == self._cc_timed_pause_minute:
            if self._cc_timed_pause_executed:
                return

            if self._count_unpaused_running_runners(target_window_ids=self._cc_timed_pause_window_ids) <= 0:
                logger.info("[中控定时暂停] 当前无可暂停的运行任务，跳过本次触发")
                return

            if not self._can_execute_control_timer_action("timed_pause", now):
                return

            try:
                triggered = self._trigger_control_timed_pause()
            except Exception as e:
                logger.error(f"[中控定时暂停] 触发失败: {e}")
                triggered = False

            if not triggered:
                return

            self._cc_timed_pause_executed = True
            self._cc_timed_pause_last_exec_date = today

            if self._cc_timed_pause_repeat == "once":
                self._cc_timed_pause_enabled = False
                self._cc_timed_pause_timer.stop()
                logger.info("[中控定时暂停] 仅一次模式执行完成，已自动停用")

    def _on_control_timed_pause_resume_timeout(self):
        if self._cc_auto_pause_source != "timed":
            return
        self._resume_all_paused_runners(
            "中控定时暂停自动恢复",
            target_window_ids=self._cc_timed_auto_paused_window_ids,
        )
        self._cc_timed_auto_paused_window_ids = set()
        self._cc_auto_pause_source = None

    def _release_timed_pause_targets(self, target_window_ids=None):
        tracked_window_ids = set(
            self._normalize_window_id_list(getattr(self, "_cc_timed_auto_paused_window_ids", None))
        )
        if not tracked_window_ids:
            return set()

        target_filter = set(self._normalize_window_id_list(target_window_ids)) if target_window_ids else None
        released_window_ids = set(tracked_window_ids) if target_filter is None else (tracked_window_ids & target_filter)
        if not released_window_ids:
            return set()

        remaining_window_ids = tracked_window_ids - released_window_ids
        self._cc_timed_auto_paused_window_ids = remaining_window_ids

        if not remaining_window_ids:
            if hasattr(self, "_cc_timed_pause_resume_timer") and self._cc_timed_pause_resume_timer.isActive():
                self._cc_timed_pause_resume_timer.stop()
            if self._cc_auto_pause_source == "timed":
                self._cc_auto_pause_source = None

        return released_window_ids

    def _on_control_random_pause_check(self):
        if not self._cc_random_pause_enabled or getattr(self, "_is_closing", False):
            return
        if self._cc_pause_probability <= 0:
            return

        pause_min_sec = self._convert_duration_to_seconds(self._cc_pause_min_value, self._cc_pause_min_unit)
        pause_max_sec = self._convert_duration_to_seconds(self._cc_pause_max_value, self._cc_pause_max_unit)
        if pause_min_sec > pause_max_sec:
            pause_min_sec, pause_max_sec = pause_max_sec, pause_min_sec
        pause_min_sec = max(1, int(pause_min_sec))
        pause_max_sec = max(1, int(pause_max_sec))

        target_filter = None
        if self._cc_random_pause_window_ids:
            target_filter = set(self._normalize_window_id_list(self._cc_random_pause_window_ids))

        import random as rand

        triggered_window_ids = []
        for window_id in list(self.window_runners.keys()):
            if target_filter is not None and window_id not in target_filter:
                continue
            if window_id in self._cc_random_pause_deadlines_by_window:
                continue
            if self._window_has_paused_runner(window_id):
                continue
            if not self._window_has_running_runner(window_id):
                continue

            roll = rand.randint(1, 100)
            if roll > self._cc_pause_probability:
                continue

            pause_duration = rand.randint(pause_min_sec, pause_max_sec)
            if self._trigger_control_random_pause(window_id, pause_duration):
                triggered_window_ids.append(window_id)

        if triggered_window_ids:
            logger.info("[中控随机暂停] 本轮触发窗口: %s", ", ".join(triggered_window_ids))

    def _trigger_control_random_pause(self, window_id: str, pause_duration: int) -> bool:
        window_id = str(window_id).strip()
        if not window_id:
            return False
        if window_id in self._cc_random_pause_deadlines_by_window:
            return False
        if not self._window_has_running_runner(window_id):
            return False
        if self._window_has_paused_runner(window_id):
            return False

        if not self._pause_single_window_runners(window_id):
            return False

        pause_duration = max(1, int(pause_duration))
        self._cc_random_pause_deadlines_by_window[window_id] = time.monotonic() + pause_duration
        self._cc_random_auto_paused_window_ids = set(self._cc_random_pause_deadlines_by_window.keys())

        self._update_single_window_table_status(
            window_id,
            "已触发随机暂停",
            f"中控随机暂停剩余 {pause_duration} 秒",
        )

        if not self._cc_random_pause_countdown_timer.isActive():
            self._cc_random_pause_countdown_timer.start()

        logger.info(f"[中控随机暂停] 窗口 {window_id} 已暂停，将在 {pause_duration} 秒后自动恢复")
        return True

    def _on_control_random_pause_resume_timeout(self):
        self._on_control_random_pause_countdown_tick()

    def _on_control_random_pause_countdown_tick(self):
        runtime_map = getattr(self, "_cc_random_pause_deadlines_by_window", None)
        if not isinstance(runtime_map, dict) or not runtime_map:
            if self._cc_random_pause_countdown_timer.isActive():
                self._cc_random_pause_countdown_timer.stop()
            self._cc_random_auto_paused_window_ids = set()
            return

        now_ts = time.monotonic()
        for window_id, deadline_ts in list(runtime_map.items()):
            if not self._window_has_paused_runner(window_id):
                runtime_map.pop(window_id, None)
                continue

            remaining_sec = int(max(0.0, float(deadline_ts) - now_ts) + 0.999)
            if remaining_sec > 0:
                self._update_single_window_table_status(
                    window_id,
                    "已触发随机暂停",
                    f"中控随机暂停剩余 {remaining_sec} 秒",
                )
                continue

            self._resume_single_window_runners(window_id)
            runtime_map.pop(window_id, None)
            if self._window_has_running_runner(window_id):
                self._update_single_window_table_status(window_id, "正在运行", "中控随机暂停已恢复")

        self._cc_random_auto_paused_window_ids = set(runtime_map.keys())
        if not runtime_map and self._cc_random_pause_countdown_timer.isActive():
            self._cc_random_pause_countdown_timer.stop()

        self._sync_pause_all_button_text()
