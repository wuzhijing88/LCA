import logging
from datetime import datetime
from typing import Any, Dict, Optional

from PySide6.QtCore import QTimer

logger = logging.getLogger(__name__)


class ControlCenterTimerMixin:
    def _get_parent_config(self) -> Optional[Dict[str, Any]]:
        if self.parent_window is None:
            return None
        config = getattr(self.parent_window, "config", None)
        if isinstance(config, dict):
            return config
        return None

    def _load_control_timer_settings(self):
        config = self._get_parent_config() or {}
        self._load_control_schedule_timer_settings(config)
        self._load_control_pause_timer_settings(config)

    def _save_control_timer_settings(self):
        config = self._get_parent_config()
        if config is None:
            return

        self._save_control_schedule_timer_settings(config)
        self._save_control_pause_timer_settings(config)

        save_config_func = getattr(self.parent_window, "save_config_func", None) if self.parent_window else None
        if callable(save_config_func):
            try:
                save_config_func(config)
            except Exception as e:
                logger.warning(f"保存中控定时设置失败: {e}")

    def _setup_control_schedule_timers(self):
        self._cc_schedule_timer = QTimer(self)
        self._cc_schedule_timer.timeout.connect(self._check_control_schedule_time)

        self._cc_stop_timer = QTimer(self)
        self._cc_stop_timer.timeout.connect(self._check_control_stop_time)

        self._cc_timer_slot_key = None
        self._cc_timer_slot_priority = -1
        self._cc_timer_slot_action = None

    def _load_control_schedule_timer_settings(self, config):
        self._cc_schedule_enabled = self._coerce_bool(config.get("cc_schedule_enabled", False), False)
        self._cc_schedule_hour = self._coerce_int(config.get("cc_schedule_hour", 9), 9, 0, 23)
        self._cc_schedule_minute = self._coerce_int(config.get("cc_schedule_minute", 0), 0, 0, 59)
        self._cc_schedule_repeat = self._normalize_repeat_mode(config.get("cc_schedule_repeat", "daily"))
        self._cc_schedule_executed = False
        self._cc_schedule_last_exec_date = None

        self._cc_stop_enabled = self._coerce_bool(config.get("cc_stop_enabled", False), False)
        self._cc_stop_hour = self._coerce_int(config.get("cc_stop_hour", 17), 17, 0, 23)
        self._cc_stop_minute = self._coerce_int(config.get("cc_stop_minute", 0), 0, 0, 59)
        self._cc_stop_repeat = self._normalize_repeat_mode(config.get("cc_stop_repeat", "daily"))
        self._cc_stop_executed = False
        self._cc_stop_last_exec_date = None

        self._cc_schedule_window_ids = self._normalize_window_id_list(config.get("cc_schedule_window_ids"))
        self._cc_stop_window_ids = self._normalize_window_id_list(config.get("cc_stop_window_ids"))

    def _save_control_schedule_timer_settings(self, config):
        config["cc_schedule_enabled"] = self._cc_schedule_enabled
        config["cc_schedule_hour"] = self._cc_schedule_hour
        config["cc_schedule_minute"] = self._cc_schedule_minute
        config["cc_schedule_repeat"] = self._cc_schedule_repeat
        config["cc_stop_enabled"] = self._cc_stop_enabled
        config["cc_stop_hour"] = self._cc_stop_hour
        config["cc_stop_minute"] = self._cc_stop_minute
        config["cc_stop_repeat"] = self._cc_stop_repeat
        config["cc_schedule_window_ids"] = list(self._cc_schedule_window_ids)
        config["cc_stop_window_ids"] = list(self._cc_stop_window_ids)

    def _apply_control_schedule_timer_settings(
        self,
        *,
        schedule_enabled,
        schedule_hour,
        schedule_minute,
        schedule_repeat,
        schedule_window_ids,
        stop_enabled,
        stop_hour,
        stop_minute,
        stop_repeat,
        stop_window_ids,
    ):
        self._cc_schedule_enabled = schedule_enabled
        self._cc_schedule_hour = self._coerce_int(schedule_hour, 9, 0, 23)
        self._cc_schedule_minute = self._coerce_int(schedule_minute, 0, 0, 59)
        self._cc_schedule_repeat = self._normalize_repeat_mode(schedule_repeat)
        self._cc_schedule_window_ids = self._normalize_window_id_list(schedule_window_ids)

        self._cc_stop_enabled = stop_enabled
        self._cc_stop_hour = self._coerce_int(stop_hour, 17, 0, 23)
        self._cc_stop_minute = self._coerce_int(stop_minute, 0, 0, 59)
        self._cc_stop_repeat = self._normalize_repeat_mode(stop_repeat)
        self._cc_stop_window_ids = self._normalize_window_id_list(stop_window_ids)

        self._update_control_schedule_config()
        self._update_control_stop_config()

    def _update_control_schedule_config(self):
        if self._cc_schedule_timer.isActive():
            self._cc_schedule_timer.stop()

        self._cc_schedule_executed = False
        self._cc_schedule_last_exec_date = None
        if self._cc_schedule_enabled:
            self._cc_schedule_timer.start(1000)
            logger.info(
                f"中控定时启动已启用，将在 {self._cc_schedule_hour:02d}:{self._cc_schedule_minute:02d} 执行，"
                f"重复模式: {self._cc_schedule_repeat}"
            )
        self._refresh_control_timer_status_label()

    def _update_control_stop_config(self):
        if self._cc_stop_timer.isActive():
            self._cc_stop_timer.stop()

        self._cc_stop_executed = False
        self._cc_stop_last_exec_date = None
        if self._cc_stop_enabled:
            self._cc_stop_timer.start(1000)
            logger.info(
                f"中控定时停止已启用，将在 {self._cc_stop_hour:02d}:{self._cc_stop_minute:02d} 停止，"
                f"重复模式: {self._cc_stop_repeat}"
            )
        self._refresh_control_timer_status_label()

    def _refresh_control_timer_status_label(self):
        if not hasattr(self, "timer_status_label") or self.timer_status_label is None:
            return

        def _window_scope_text(window_ids):
            if not window_ids:
                return "全部"
            return f"{len(window_ids)}窗"

        parts = []
        if getattr(self, "_cc_schedule_enabled", False):
            parts.append(
                f"启动 {self._cc_schedule_hour:02d}:{self._cc_schedule_minute:02d}"
                f"({_window_scope_text(self._cc_schedule_window_ids)})"
            )
        if getattr(self, "_cc_stop_enabled", False):
            parts.append(
                f"停止 {self._cc_stop_hour:02d}:{self._cc_stop_minute:02d}"
                f"({_window_scope_text(self._cc_stop_window_ids)})"
            )
        if getattr(self, "_cc_timed_pause_enabled", False):
            parts.append(
                f"定时暂停 {self._cc_timed_pause_hour:02d}:{self._cc_timed_pause_minute:02d}"
                f"({_window_scope_text(self._cc_timed_pause_window_ids)})"
            )
        if getattr(self, "_cc_random_pause_enabled", False):
            parts.append(
                f"随机暂停 {self._cc_pause_probability}%"
                f"({_window_scope_text(self._cc_random_pause_window_ids)})"
            )

        if parts:
            text = "定时：" + " | ".join(parts)
        else:
            text = "定时：未启用"
        self.timer_status_label.setText(text)
        self.timer_status_label.setToolTip(text)

    def _stop_all_control_timers(self, reset_state=False, persist=False, resume_if_timed=True):
        if self._cc_schedule_timer.isActive():
            self._cc_schedule_timer.stop()
        if self._cc_stop_timer.isActive():
            self._cc_stop_timer.stop()
        if self._cc_timed_pause_timer.isActive():
            self._cc_timed_pause_timer.stop()
        if self._cc_timed_pause_resume_timer.isActive():
            self._cc_timed_pause_resume_timer.stop()
        if self._cc_random_pause_timer.isActive():
            self._cc_random_pause_timer.stop()
        if self._cc_random_pause_resume_timer.isActive():
            self._cc_random_pause_resume_timer.stop()
        if self._cc_random_pause_countdown_timer.isActive():
            self._cc_random_pause_countdown_timer.stop()

        if resume_if_timed and self._cc_auto_pause_source == "timed":
            self._resume_all_paused_runners(
                "停止中控定时器",
                target_window_ids=self._cc_timed_auto_paused_window_ids,
            )
        self._clear_random_pause_runtime(resume=resume_if_timed, reason="停止中控定时器")

        self._cc_auto_pause_source = None
        self._cc_timer_slot_key = None
        self._cc_timer_slot_priority = -1
        self._cc_timer_slot_action = None
        self._cc_timed_auto_paused_window_ids = set()

        if reset_state:
            self._cc_schedule_enabled = False
            self._cc_stop_enabled = False
            self._cc_timed_pause_enabled = False
            self._cc_random_pause_enabled = False

            self._cc_schedule_executed = False
            self._cc_schedule_last_exec_date = None
            self._cc_stop_executed = False
            self._cc_stop_last_exec_date = None
            self._cc_timed_pause_executed = False
            self._cc_timed_pause_last_exec_date = None

        if persist:
            self._save_control_timer_settings()
        self._refresh_control_timer_status_label()

    def _can_execute_control_timer_action(self, action_name: str, now: datetime) -> bool:
        priority_map = {
            "schedule": 1,
            "timed_pause": 2,
            "stop": 3,
        }
        action_priority = priority_map.get(action_name, 0)
        current_slot_key = (now.date(), now.hour, now.minute)

        if self._cc_timer_slot_key != current_slot_key:
            self._cc_timer_slot_key = current_slot_key
            self._cc_timer_slot_priority = -1
            self._cc_timer_slot_action = None

        if self._cc_timer_slot_priority >= action_priority:
            return False

        self._cc_timer_slot_priority = action_priority
        self._cc_timer_slot_action = action_name
        return True

    def _check_control_schedule_time(self):
        if not self._cc_schedule_enabled or getattr(self, "_is_closing", False):
            return

        now = datetime.now()
        current_hour = now.hour
        current_minute = now.minute
        today = now.date()

        if self._cc_schedule_repeat == "daily" and self._cc_schedule_executed:
            if self._cc_schedule_last_exec_date is not None and self._cc_schedule_last_exec_date != today:
                self._cc_schedule_executed = False
                logger.info("[中控定时启动] 跨日重置执行标记")

        if current_hour == self._cc_schedule_hour and current_minute == self._cc_schedule_minute:
            if self._cc_schedule_executed:
                return

            if not self._can_execute_control_timer_action("schedule", now):
                return

            self._cc_schedule_executed = True
            self._cc_schedule_last_exec_date = today
            logger.info(
                f"[中控定时启动] 到达触发时间 {self._cc_schedule_hour:02d}:{self._cc_schedule_minute:02d}，开始启动"
            )
            self.log_message("中控定时启动触发：开始启动目标窗口任务")
            try:
                self.start_all_tasks(window_ids=self._cc_schedule_window_ids)
            except Exception as e:
                logger.error(f"中控定时启动失败: {e}")

            if self._cc_schedule_repeat == "once":
                self._cc_schedule_enabled = False
                self._cc_schedule_timer.stop()
                logger.info("[中控定时启动] 仅一次模式执行完成，已自动停用")

    def _check_control_stop_time(self):
        if not self._cc_stop_enabled or getattr(self, "_is_closing", False):
            return

        now = datetime.now()
        current_hour = now.hour
        current_minute = now.minute
        today = now.date()

        if self._cc_stop_repeat == "daily" and self._cc_stop_executed:
            if self._cc_stop_last_exec_date is not None and self._cc_stop_last_exec_date != today:
                self._cc_stop_executed = False
                logger.info("[中控定时停止] 跨日重置执行标记")

        if current_hour == self._cc_stop_hour and current_minute == self._cc_stop_minute:
            if self._cc_stop_executed:
                return

            if not self._can_execute_control_timer_action("stop", now):
                return

            self._cc_stop_executed = True
            self._cc_stop_last_exec_date = today
            logger.info(
                f"[中控定时停止] 到达触发时间 {self._cc_stop_hour:02d}:{self._cc_stop_minute:02d}，开始停止"
            )
            self.log_message("中控定时停止触发：开始停止目标窗口任务")
            try:
                self.stop_all_tasks(window_ids=self._cc_stop_window_ids)
            except Exception as e:
                logger.error(f"中控定时停止失败: {e}")

            if self._cc_stop_repeat == "once":
                self._cc_stop_enabled = False
                self._cc_stop_timer.stop()
                logger.info("[中控定时停止] 仅一次模式执行完成，已自动停用")

    def setup_timer(self):
        """初始化中控定时器功能。"""
        self._setup_control_schedule_timers()
        self._setup_control_pause_timers()

        self._cc_auto_pause_source = None

        self._load_control_timer_settings()
        self._update_control_schedule_config()
        self._update_control_stop_config()
        self._update_control_timed_pause_config()
        self._update_control_random_pause_config()
        self._refresh_control_timer_status_label()

    @staticmethod
    def _coerce_bool(value, default=False):
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"1", "true", "yes", "on"}:
                return True
            if lowered in {"0", "false", "no", "off"}:
                return False
        return default

    @staticmethod
    def _coerce_int(value, default, min_value, max_value):
        try:
            parsed = int(value)
        except Exception:
            parsed = int(default)
        return max(min_value, min(max_value, parsed))

    @staticmethod
    def _normalize_repeat_mode(value, default="daily"):
        mode = str(value or "").strip().lower()
        if mode not in {"once", "daily"}:
            return default
        return mode

    @staticmethod
    def _normalize_duration_unit(value, default="分钟"):
        unit = str(value or "").strip()
        if unit not in {"秒", "分钟", "小时"}:
            return default
        return unit

    @staticmethod
    def _normalize_interval_unit(value, default="秒"):
        unit = str(value or "").strip()
        if unit not in {"秒", "分钟"}:
            return default
        return unit

    @staticmethod
    def _normalize_window_id_list(value):
        if value is None:
            return []
        if isinstance(value, bool):
            return []
        if isinstance(value, (str, int)):
            raw_items = [value]
        elif isinstance(value, (list, tuple, set)):
            raw_items = list(value)
        else:
            return []

        normalized = []
        seen = set()
        for item in raw_items:
            window_id = str(item).strip()
            if not window_id:
                continue

            lowered = window_id.lower()
            if lowered in {"false", "none", "null", "no", "否", "0", "all", "全部"}:
                continue

            try:
                canonical_window_id = str(int(window_id))
            except Exception:
                continue

            if canonical_window_id in seen:
                continue
            seen.add(canonical_window_id)
            normalized.append(canonical_window_id)
        return normalized
