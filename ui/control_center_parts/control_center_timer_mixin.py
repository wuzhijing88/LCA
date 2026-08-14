# -*- coding: utf-8 -*-
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from PySide6.QtCore import QTimer

from app_core.control_plane.job_state import ACTIVE_JOB_STATES
from app_core.scheduling import (
    ACTION_START,
    ACTION_STOP,
    ACTION_TIMED_PAUSE,
    START_MODE_DAILY,
    START_MODE_INTERVAL,
    ScheduleBundle,
    ScheduleEngine,
    format_next_fire,
    load_control_bundle,
    wake_delay_ms,
    write_control_bundle,
)
from app_core.scheduling.text import (
    CHECK_INTERVAL_UNITS,
    DURATION_UNITS,
    INTERVAL_UNITS,
    UNIT_MINUTES,
    UNIT_SECONDS,
    normalize_unit,
    unit_label,
)

logger = logging.getLogger(__name__)

class ControlCenterTimerMixin:
    def _get_parent_config(self) -> Optional[Dict[str, Any]]:
        if self.parent_window is None:
            return None
        config = getattr(self.parent_window, "config", None)
        if isinstance(config, dict):
            return config
        return None

    def _canonicalize_timer_window_ids(self, window_ids):
        normalized = self._normalize_window_id_list(window_ids)
        scheduler = getattr(self, "scheduler", None)
        if scheduler is not None:
            return scheduler.canonicalize_ids(normalized)
        return normalized

    def _retain_timer_window_ids(self, window_ids):
        """有效 bind_id 留下；原列表非空但全部无效时原样保留，避免变成全部窗口。"""
        normalized = self._normalize_window_id_list(window_ids)
        if not normalized:
            return []
        canonical = self._canonicalize_timer_window_ids(normalized)
        return canonical if canonical else normalized

    def _resolve_configured_window_filter(self, window_ids):
        """解析配置里的目标窗口。

        返回 (target_ids, ok)：
        - ok 为 False：原列表非空但没有有效 bind_id，调用方应跳过
        - target_ids 为 None：全部窗口
        - target_ids 为列表：指定窗口
        """
        normalized = self._normalize_window_id_list(window_ids)
        if not normalized:
            return None, True
        canonical = self._canonicalize_timer_window_ids(normalized)
        if not canonical:
            return None, False
        return canonical, True

    def _commit_timer_target_picker_ids(self, initial_window_ids, result_ids):
        """选择窗口对话框点确定后的落盘列表。

        空结果通常表示全部窗口。但原配置非空且全部无效时，空结果必须保住原列表，
        不能改写成 []，否则无效目标会变成全部窗口。
        """
        selected = self._normalize_window_id_list(result_ids)
        if selected:
            return selected
        initial = self._normalize_window_id_list(initial_window_ids)
        if not initial:
            return []
        if self._canonicalize_timer_window_ids(initial):
            return []
        return initial

    def _canonicalize_stored_timer_window_ids(self) -> bool:
        changed = False
        for attr in (
            "_cc_schedule_window_ids",
            "_cc_stop_window_ids",
            "_cc_timed_pause_window_ids",
            "_cc_random_pause_window_ids",
        ):
            current = list(getattr(self, attr, []) or [])
            if not current:
                continue
            canonical = self._canonicalize_timer_window_ids(current)
            if not canonical or canonical == current:
                continue
            setattr(self, attr, canonical)
            changed = True
        return changed

    def _apply_control_bundle_to_attrs(self, bundle: ScheduleBundle):
        self._cc_schedule_enabled = bundle.start.enabled
        self._cc_schedule_hour = bundle.start.hour
        self._cc_schedule_minute = bundle.start.minute
        self._cc_schedule_repeat = bundle.start.repeat
        self._cc_schedule_mode = bundle.start.mode
        self._cc_schedule_interval_value = bundle.start.interval_value
        self._cc_schedule_interval_unit = bundle.start.interval_unit
        self._cc_schedule_window_ids = list(bundle.start.window_ids)

        self._cc_stop_enabled = bundle.stop.enabled
        self._cc_stop_hour = bundle.stop.hour
        self._cc_stop_minute = bundle.stop.minute
        self._cc_stop_repeat = bundle.stop.repeat
        self._cc_stop_window_ids = list(bundle.stop.window_ids)

        self._cc_timed_pause_enabled = bundle.timed_pause.enabled
        self._cc_timed_pause_hour = bundle.timed_pause.hour
        self._cc_timed_pause_minute = bundle.timed_pause.minute
        self._cc_timed_pause_repeat = bundle.timed_pause.repeat
        self._cc_timed_pause_duration_value = bundle.timed_pause.duration_value
        self._cc_timed_pause_duration_unit = bundle.timed_pause.duration_unit
        self._cc_timed_pause_window_ids = list(bundle.timed_pause.window_ids)

        self._cc_random_pause_enabled = bundle.random_pause.enabled
        self._cc_pause_probability = bundle.random_pause.probability
        self._cc_pause_check_interval = bundle.random_pause.check_interval_value
        self._cc_pause_check_interval_unit = bundle.random_pause.check_interval_unit
        self._cc_pause_min_value = bundle.random_pause.min_value
        self._cc_pause_min_unit = bundle.random_pause.min_unit
        self._cc_pause_max_value = bundle.random_pause.max_value
        self._cc_pause_max_unit = bundle.random_pause.max_unit
        self._cc_random_pause_window_ids = list(bundle.random_pause.window_ids)

    def _control_bundle_from_attrs(self) -> ScheduleBundle:
        bundle = ScheduleBundle()
        bundle.start.enabled = getattr(self, "_cc_schedule_enabled", False)
        bundle.start.hour = getattr(self, "_cc_schedule_hour", 9)
        bundle.start.minute = getattr(self, "_cc_schedule_minute", 0)
        bundle.start.repeat = getattr(self, "_cc_schedule_repeat", "daily")
        bundle.start.mode = getattr(self, "_cc_schedule_mode", START_MODE_DAILY)
        bundle.start.interval_value = getattr(self, "_cc_schedule_interval_value", 30)
        bundle.start.interval_unit = getattr(self, "_cc_schedule_interval_unit", UNIT_MINUTES)
        bundle.start.window_ids = list(getattr(self, "_cc_schedule_window_ids", []) or [])

        bundle.stop.enabled = getattr(self, "_cc_stop_enabled", False)
        bundle.stop.hour = getattr(self, "_cc_stop_hour", 17)
        bundle.stop.minute = getattr(self, "_cc_stop_minute", 0)
        bundle.stop.repeat = getattr(self, "_cc_stop_repeat", "daily")
        bundle.stop.window_ids = list(getattr(self, "_cc_stop_window_ids", []) or [])

        bundle.timed_pause.enabled = getattr(self, "_cc_timed_pause_enabled", False)
        bundle.timed_pause.hour = getattr(self, "_cc_timed_pause_hour", 12)
        bundle.timed_pause.minute = getattr(self, "_cc_timed_pause_minute", 0)
        bundle.timed_pause.repeat = getattr(self, "_cc_timed_pause_repeat", "daily")
        bundle.timed_pause.duration_value = getattr(self, "_cc_timed_pause_duration_value", 10)
        bundle.timed_pause.duration_unit = getattr(self, "_cc_timed_pause_duration_unit", UNIT_MINUTES)
        bundle.timed_pause.window_ids = list(getattr(self, "_cc_timed_pause_window_ids", []) or [])

        bundle.random_pause.enabled = getattr(self, "_cc_random_pause_enabled", False)
        bundle.random_pause.probability = getattr(self, "_cc_pause_probability", 20)
        bundle.random_pause.check_interval_value = getattr(self, "_cc_pause_check_interval", 30)
        bundle.random_pause.check_interval_unit = getattr(self, "_cc_pause_check_interval_unit", UNIT_SECONDS)
        bundle.random_pause.min_value = getattr(self, "_cc_pause_min_value", 60)
        bundle.random_pause.min_unit = getattr(self, "_cc_pause_min_unit", UNIT_SECONDS)
        bundle.random_pause.max_value = getattr(self, "_cc_pause_max_value", 120)
        bundle.random_pause.max_unit = getattr(self, "_cc_pause_max_unit", UNIT_SECONDS)
        bundle.random_pause.window_ids = list(getattr(self, "_cc_random_pause_window_ids", []) or [])
        return bundle

    def _load_control_timer_settings(self):
        config = self._get_parent_config() or {}
        bundle = load_control_bundle(config)
        self._apply_control_bundle_to_attrs(bundle)
        self._cc_timed_auto_paused_window_ids = set()
        self._cc_random_pause_deadlines_by_window = {}
        self._cc_random_auto_paused_window_ids = set()
        if self._canonicalize_stored_timer_window_ids():
            self._save_control_timer_settings()

    def _save_control_timer_settings(self):
        config = self._get_parent_config()
        if config is None:
            return
        write_control_bundle(config, self._control_bundle_from_attrs())
        save_config_func = getattr(self.parent_window, "save_config_func", None) if self.parent_window else None
        if callable(save_config_func):
            try:
                save_config_func(config)
            except Exception as e:
                logger.warning(f"保存中控定时设置失败: {e}")

    def _setup_control_clock(self):
        self._cc_clock_timer = QTimer(self)
        self._cc_clock_timer.setSingleShot(True)
        self._cc_clock_timer.timeout.connect(self._on_control_schedule_clock)
        self._cc_schedule_engine = ScheduleEngine(self._control_bundle_from_attrs(), allow_interval_start=True)

    def _sync_control_schedule_engine(self):
        bundle = self._control_bundle_from_attrs()
        if not hasattr(self, "_cc_schedule_engine"):
            self._cc_schedule_engine = ScheduleEngine(bundle, allow_interval_start=True)
        else:
            self._cc_schedule_engine.replace_bundle(bundle)
        self._arm_control_schedule_clock()

    def _arm_control_schedule_clock(self):
        timer = getattr(self, "_cc_clock_timer", None)
        if timer is None:
            return
        if timer.isActive():
            timer.stop()
        bundle = self._control_bundle_from_attrs()
        if not bundle.any_clock_enabled():
            self._refresh_control_timer_status_label()
            return
        now = datetime.now()
        nxt = self._cc_schedule_engine.next_wake(now)
        delay = wake_delay_ms(nxt, now)
        if delay > 0:
            timer.start(delay)
        self._refresh_control_timer_status_label()

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
        schedule_mode=START_MODE_DAILY,
        schedule_interval_value=30,
        schedule_interval_unit=UNIT_MINUTES,
    ):
        self._cc_schedule_enabled = schedule_enabled
        self._cc_schedule_hour = self._coerce_int(schedule_hour, 9, 0, 23)
        self._cc_schedule_minute = self._coerce_int(schedule_minute, 0, 0, 59)
        self._cc_schedule_repeat = self._normalize_repeat_mode(schedule_repeat)
        self._cc_schedule_mode = (
            START_MODE_INTERVAL if str(schedule_mode).strip().lower() == START_MODE_INTERVAL else START_MODE_DAILY
        )
        self._cc_schedule_interval_value = self._coerce_int(schedule_interval_value, 30, 1, 999999)
        self._cc_schedule_interval_unit = self._normalize_start_interval_unit(schedule_interval_unit)
        self._cc_schedule_window_ids = self._retain_timer_window_ids(schedule_window_ids)

        self._cc_stop_enabled = stop_enabled
        self._cc_stop_hour = self._coerce_int(stop_hour, 17, 0, 23)
        self._cc_stop_minute = self._coerce_int(stop_minute, 0, 0, 59)
        self._cc_stop_repeat = self._normalize_repeat_mode(stop_repeat)
        self._cc_stop_window_ids = self._retain_timer_window_ids(stop_window_ids)
        self._sync_control_schedule_engine()

    def _update_control_schedule_config(self):
        self._sync_control_schedule_engine()

    def _update_control_stop_config(self):
        self._sync_control_schedule_engine()

    def _refresh_control_timer_status_label(self):
        if not hasattr(self, "timer_status_label") or self.timer_status_label is None:
            return

        def _window_scope_text(window_ids):
            target_ids, ok = self._resolve_configured_window_filter(window_ids)
            if not ok:
                return "无有效"
            if target_ids is None:
                return "全部"
            return f"{len(target_ids)}窗"

        parts = []
        now = datetime.now()
        if getattr(self, "_cc_schedule_enabled", False):
            scope = _window_scope_text(self._cc_schedule_window_ids)
            if getattr(self, "_cc_schedule_mode", START_MODE_DAILY) == START_MODE_INTERVAL:
                nxt = ""
                engine = getattr(self, "_cc_schedule_engine", None)
                if engine is not None:
                    nxt = format_next_fire(engine.next_fire_for(ACTION_START, now))
                next_text = f" 下次{nxt}" if nxt else ""
                parts.append(
                    f"启动 每{self._cc_schedule_interval_value}{unit_label(self._cc_schedule_interval_unit)}({scope}){next_text}"
                )
            else:
                parts.append(
                    f"启动 {self._cc_schedule_hour:02d}:{self._cc_schedule_minute:02d}({scope})"
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

        text = "定时：" + " | ".join(parts) if parts else "定时：未启用"
        self.timer_status_label.setText(text)
        self.timer_status_label.setToolTip(text)

    def _stop_all_control_timers(self, reset_state=False, persist=False, resume_if_timed=True):
        if hasattr(self, "_cc_clock_timer") and self._cc_clock_timer.isActive():
            self._cc_clock_timer.stop()
        if hasattr(self, "_cc_timed_pause_resume_timer") and self._cc_timed_pause_resume_timer.isActive():
            self._cc_timed_pause_resume_timer.stop()
        if hasattr(self, "_cc_random_pause_timer") and self._cc_random_pause_timer.isActive():
            self._cc_random_pause_timer.stop()
        if hasattr(self, "_cc_random_pause_resume_timer") and self._cc_random_pause_resume_timer.isActive():
            self._cc_random_pause_resume_timer.stop()
        if hasattr(self, "_cc_random_pause_countdown_timer") and self._cc_random_pause_countdown_timer.isActive():
            self._cc_random_pause_countdown_timer.stop()

        if resume_if_timed and getattr(self, "_cc_auto_pause_source", None) == "timed":
            self._resume_all_paused_runners(
                "停止中控定时器",
                target_window_ids=self._cc_timed_auto_paused_window_ids,
            )
        self._clear_random_pause_runtime(resume=resume_if_timed, reason="停止中控定时器")

        self._cc_auto_pause_source = None
        self._cc_timed_auto_paused_window_ids = set()

        if reset_state:
            self._cc_schedule_enabled = False
            self._cc_stop_enabled = False
            self._cc_timed_pause_enabled = False
            self._cc_random_pause_enabled = False
            if hasattr(self, "_cc_schedule_engine"):
                self._cc_schedule_engine.replace_bundle(self._control_bundle_from_attrs())

        if persist:
            self._save_control_timer_settings()
        self._refresh_control_timer_status_label()

    def _scheduled_start_window_ids(self):
        target_ids, ok = self._resolve_configured_window_filter(self._cc_schedule_window_ids)
        if not ok:
            return None, "无有效窗口"

        scheduler = getattr(self, "scheduler", None)
        if scheduler is None:
            return (list(target_ids) if target_ids is not None else []), "全部窗口"

        idle_ids = []
        for snap in scheduler.list_jobs():
            if target_ids is not None and not scheduler.matches_filter(snap.job_id, target_ids, snap.hwnd):
                continue
            if not snap.has_assignments:
                continue
            if snap.state in ACTIVE_JOB_STATES:
                continue
            idle_ids.append(snap.job_id)
        if not idle_ids:
            return None, "没有空闲窗口"
        return idle_ids, f"空闲窗口 {len(idle_ids)} 个"

    def _on_control_schedule_clock(self):
        if getattr(self, "_is_closing", False):
            return
        now = datetime.now()
        enabled_before = (
            self._cc_schedule_enabled,
            self._cc_stop_enabled,
            self._cc_timed_pause_enabled,
        )
        winner = self._cc_schedule_engine.take_due(now)
        if winner == ACTION_START:
            self._execute_control_scheduled_start()
        elif winner == ACTION_STOP:
            self._execute_control_scheduled_stop()
        elif winner == ACTION_TIMED_PAUSE:
            self._execute_control_timed_pause()

        self._cc_schedule_enabled = self._cc_schedule_engine.bundle.start.enabled
        self._cc_stop_enabled = self._cc_schedule_engine.bundle.stop.enabled
        self._cc_timed_pause_enabled = self._cc_schedule_engine.bundle.timed_pause.enabled
        if enabled_before != (
            self._cc_schedule_enabled,
            self._cc_stop_enabled,
            self._cc_timed_pause_enabled,
        ):
            self._save_control_timer_settings()
        self._arm_control_schedule_clock()

    def _execute_control_scheduled_start(self):
        window_ids, desc = self._scheduled_start_window_ids()
        if window_ids is None:
            logger.info("[中控定时启动] 跳过：%s", desc)
            self.log_message(f"中控定时启动跳过：{desc}")
            return
        logger.info("[中控定时启动] 开始启动 %s", desc)
        self.log_message(f"中控定时启动触发：{desc}")
        try:
            self.start_all_tasks(window_ids=window_ids, interactive=False)
        except Exception as e:
            logger.error(f"中控定时启动失败: {e}")

    def _execute_control_scheduled_stop(self):
        target_ids, ok = self._resolve_configured_window_filter(self._cc_stop_window_ids)
        if not ok:
            logger.info("[中控定时停止] 无有效窗口，跳过本次触发")
            self.log_message("中控定时停止跳过：无有效窗口")
            return
        stop_ids = [] if target_ids is None else list(target_ids)
        logger.info("[中控定时停止] 开始停止")
        self.log_message("中控定时停止触发：开始停止目标窗口任务")
        try:
            self.stop_all_tasks(window_ids=stop_ids)
        except Exception as e:
            logger.error(f"中控定时停止失败: {e}")

    def setup_timer(self):
        """初始化中控定时器功能。"""
        self._setup_control_clock()
        self._setup_control_pause_timers()
        self._cc_auto_pause_source = None
        self._load_control_timer_settings()
        self._sync_control_schedule_engine()
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
    def _normalize_duration_unit(value, default=UNIT_MINUTES):
        return normalize_unit(value, default=default, allowed=DURATION_UNITS)

    @staticmethod
    def _normalize_interval_unit(value, default=UNIT_SECONDS):
        return normalize_unit(value, default=default, allowed=CHECK_INTERVAL_UNITS)

    @staticmethod
    def _normalize_start_interval_unit(value, default=UNIT_MINUTES):
        return normalize_unit(value, default=default, allowed=INTERVAL_UNITS)

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
                canonical_window_id = window_id

            if canonical_window_id in seen:
                continue
            seen.add(canonical_window_id)
            normalized.append(canonical_window_id)
        return normalized
