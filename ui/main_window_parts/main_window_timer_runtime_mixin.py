import logging
import random as rand

from PySide6.QtCore import QTimer

from app_core.scheduling import (
    ACTION_START,
    ACTION_STOP,
    ACTION_TIMED_PAUSE,
    ScheduleEngine,
    duration_to_seconds,
    load_main_bundle,
    wake_delay_ms,
    write_main_bundle,
)

logger = logging.getLogger(__name__)
_MAX_QTIMER_MS = 2147483647


class MainWindowTimerRuntimeMixin:
    def _setup_main_schedule_runtime(self):
        self._main_schedule = load_main_bundle(getattr(self, "config", {}) or {})
        self._schedule_engine = ScheduleEngine(self._main_schedule, allow_interval_start=False)
        self._sync_main_schedule_aliases()

        self._schedule_clock_timer = QTimer(self)
        self._schedule_clock_timer.setSingleShot(True)
        self._schedule_clock_timer.timeout.connect(self._on_main_schedule_clock)

        self._random_pause_timer = QTimer(self)
        self._random_pause_timer.timeout.connect(self._on_random_pause_check)
        self._timed_pause_resume_timer = QTimer(self)
        self._timed_pause_resume_timer.setSingleShot(True)
        self._timed_pause_resume_timer.timeout.connect(self._on_timed_pause_resume_timeout)
        self._random_pause_resume_timer = QTimer(self)
        self._random_pause_resume_timer.setSingleShot(True)
        self._random_pause_resume_timer.timeout.connect(self._on_random_resume_timeout)
        self._is_paused = False
        self._auto_pause_source = None

    def _sync_main_schedule_aliases(self):
        bundle = self._main_schedule
        self._schedule_enabled = bundle.start.enabled
        self._schedule_hour = bundle.start.hour
        self._schedule_minute = bundle.start.minute
        self._schedule_repeat = bundle.start.repeat
        self._stop_enabled = bundle.stop.enabled
        self._stop_hour = bundle.stop.hour
        self._stop_minute = bundle.stop.minute
        self._stop_repeat = bundle.stop.repeat
        self._timed_pause_enabled = bundle.timed_pause.enabled
        self._timed_pause_hour = bundle.timed_pause.hour
        self._timed_pause_minute = bundle.timed_pause.minute
        self._timed_pause_repeat = bundle.timed_pause.repeat
        self._timed_pause_duration_value = bundle.timed_pause.duration_value
        self._timed_pause_duration_unit = bundle.timed_pause.duration_unit
        self._random_pause_enabled = bundle.random_pause.enabled
        self._pause_probability = bundle.random_pause.probability
        self._pause_check_interval = bundle.random_pause.check_interval_value
        self._pause_check_interval_unit = bundle.random_pause.check_interval_unit
        self._pause_min_value = bundle.random_pause.min_value
        self._pause_min_unit = bundle.random_pause.min_unit
        self._pause_max_value = bundle.random_pause.max_value
        self._pause_max_unit = bundle.random_pause.max_unit

    def _persist_main_schedule(self):
        config = getattr(self, "config", None)
        if not isinstance(config, dict):
            return
        write_main_bundle(config, self._main_schedule)
        save_config_func = getattr(self, "save_config_func", None)
        if callable(save_config_func):
            save_config_func(config)

    def _reload_main_schedule_from_config(self):
        self._main_schedule = load_main_bundle(getattr(self, "config", {}) or {})
        self._schedule_engine.replace_bundle(self._main_schedule)
        self._sync_main_schedule_aliases()
        self._arm_main_schedule_clock()

    def _apply_main_schedule_bundle(self, bundle, persist=True):
        self._main_schedule = bundle
        self._schedule_engine.replace_bundle(bundle)
        self._sync_main_schedule_aliases()
        if persist:
            self._persist_main_schedule()
        self._arm_main_schedule_clock()

    def _arm_main_schedule_clock(self):
        timer = getattr(self, "_schedule_clock_timer", None)
        if timer is None:
            return
        if timer.isActive():
            timer.stop()
        if not self._main_schedule.any_clock_enabled():
            return
        from datetime import datetime
        now = datetime.now()
        nxt = self._schedule_engine.next_wake(now)
        delay = wake_delay_ms(nxt, now)
        if delay > 0:
            timer.start(delay)

    def _stop_main_schedule_clock(self):
        timer = getattr(self, "_schedule_clock_timer", None)
        if timer is not None and timer.isActive():
            timer.stop()

    def _start_schedule_timer(self):
        self._arm_main_schedule_clock()

    def _stop_schedule_timer(self):
        self._stop_main_schedule_clock()

    def _start_timed_pause_timer(self):
        self._arm_main_schedule_clock()

    def _update_schedule_config(self):
        self._schedule_engine.replace_bundle(self._main_schedule)
        self._sync_main_schedule_aliases()
        self._arm_main_schedule_clock()

    def _update_stop_config(self):
        self._update_schedule_config()

    def _update_timed_pause_config(self):
        self._update_schedule_config()

    def _has_active_workflow_execution(self) -> bool:
        if bool(getattr(self, "_is_paused", False)):
            return True
        task_state_manager = getattr(self, "task_state_manager", None)
        if task_state_manager is not None:
            try:
                if bool(task_state_manager.is_running()):
                    return True
            except Exception as exc:
                logger.warning(f"[定时启动] 读取任务状态失败: {exc}")
        task_manager = getattr(self, "task_manager", None)
        if task_manager is None:
            return False
        try:
            for task in task_manager.get_all_tasks():
                if getattr(task, "status", None) in ("running", "paused"):
                    return True
        except Exception as exc:
            logger.warning(f"[定时启动] 遍历任务状态失败: {exc}")
        return False

    def _on_main_schedule_clock(self):
        from datetime import datetime

        now = datetime.now()
        enabled_before = (
            self._main_schedule.start.enabled,
            self._main_schedule.stop.enabled,
            self._main_schedule.timed_pause.enabled,
        )
        winner = self._schedule_engine.take_due(now)
        if winner == ACTION_START:
            self._execute_scheduled_start()
        elif winner == ACTION_STOP:
            self._execute_scheduled_stop()
        elif winner == ACTION_TIMED_PAUSE:
            self._execute_scheduled_timed_pause()
        self._sync_main_schedule_aliases()
        enabled_after = (
            self._main_schedule.start.enabled,
            self._main_schedule.stop.enabled,
            self._main_schedule.timed_pause.enabled,
        )
        if enabled_before != enabled_after:
            self._persist_main_schedule()
        self._arm_main_schedule_clock()

    def _execute_scheduled_start(self):
        if self._has_active_workflow_execution():
            logger.info("[定时启动] 当前工作流正在执行，跳过本次触发")
            return
        logger.info("[定时启动] 开始执行工作流")
        try:
            self.safe_start_tasks(interactive=False)
        except Exception as exc:
            logger.error(f"定时启动工作流失败: {exc}")

    def _execute_scheduled_stop(self):
        logger.info("[定时停止] 停止工作流")
        self.safe_stop_tasks()

    def _execute_scheduled_timed_pause(self):
        if getattr(self, "_is_paused", False):
            logger.info("[定时暂停] 当前已经处于暂停状态，跳过本次触发")
            return
        running_count = 0
        if hasattr(self, "task_manager") and self.task_manager:
            running_count = self.task_manager.get_running_count()
        if running_count <= 0:
            logger.info("[定时暂停] 当前没有运行中的任务，跳过本次触发")
            return
        self._trigger_timed_pause()

    def _trigger_timed_pause(self):
        duration_sec = max(
            1,
            duration_to_seconds(self._timed_pause_duration_value, self._timed_pause_duration_unit),
        )
        logger.info(f"[定时暂停] 开始暂停，时长: {duration_sec} 秒")
        if not self._pause_workflow(source="timed"):
            logger.info("[定时暂停] 暂停失败，跳过本次触发")
            return
        self._is_paused = True
        self._auto_pause_source = "timed"
        if hasattr(self, "_timed_pause_resume_timer"):
            if self._timed_pause_resume_timer.isActive():
                self._timed_pause_resume_timer.stop()
            duration_ms = min(duration_sec * 1000, _MAX_QTIMER_MS)
            self._timed_pause_resume_timer.start(duration_ms)
        logger.info(f"[定时暂停] 已暂停，将在 {duration_sec} 秒后自动恢复")

    def _on_timed_pause_resume_timeout(self):
        if self._is_paused and getattr(self, "_auto_pause_source", None) == "timed":
            logger.info("[定时暂停] 恢复定时器触发，恢复工作流")
            self._resume_workflow(source="timed")

    def _start_random_pause_cycle(self):
        logger.info(f"[随机暂停] _start_random_pause_cycle 被调用, enabled={self._random_pause_enabled}")
        if not self._random_pause_enabled:
            return
        interval_ms = min(
            _MAX_QTIMER_MS,
            max(1000, duration_to_seconds(self._pause_check_interval, self._pause_check_interval_unit) * 1000),
        )
        self._random_pause_timer.stop()
        self._random_pause_timer.start(interval_ms)
        logger.info(
            f"[随机暂停] 定时器已启动: 间隔={interval_ms}ms "
            f"({self._pause_check_interval} {self._pause_check_interval_unit}), 概率={self._pause_probability}%"
        )

    def _on_random_pause_check(self):
        if not self._random_pause_enabled or self._is_paused:
            return
        running_count = 0
        if hasattr(self, "task_manager") and self.task_manager:
            running_count = self.task_manager.get_running_count()
        if running_count == 0 or self._pause_probability <= 0:
            return
        roll = rand.randint(1, 100)
        if roll <= self._pause_probability:
            self._trigger_random_pause()

    def _trigger_random_pause(self):
        pause_min_sec = duration_to_seconds(self._pause_min_value, self._pause_min_unit)
        pause_max_sec = duration_to_seconds(self._pause_max_value, self._pause_max_unit)
        if pause_min_sec > pause_max_sec:
            pause_min_sec, pause_max_sec = pause_max_sec, pause_min_sec
        pause_duration = rand.randint(pause_min_sec, pause_max_sec)
        logger.info(f"开始随机暂停，暂停时长: {pause_duration} 秒")
        if not self._pause_workflow(source="random"):
            logger.info("[随机暂停] 暂停失败，跳过本次触发")
            return
        self._is_paused = True
        self._auto_pause_source = "random"
        if hasattr(self, "_random_pause_resume_timer"):
            if self._random_pause_resume_timer.isActive():
                self._random_pause_resume_timer.stop()
            self._random_pause_resume_timer.start(min(pause_duration * 1000, _MAX_QTIMER_MS))

    def _on_random_resume_timeout(self):
        if self._is_paused and getattr(self, "_auto_pause_source", None) == "random":
            logger.info("恢复定时器触发，恢复所有工作流")
            self._resume_workflow(source="random")

    def _stop_all_main_timers(self, reset_state=False, persist=False, resume_if_paused=True):
        self._stop_main_schedule_clock()
        if hasattr(self, "_timed_pause_resume_timer") and self._timed_pause_resume_timer.isActive():
            self._timed_pause_resume_timer.stop()
        if hasattr(self, "_random_pause_resume_timer") and self._random_pause_resume_timer.isActive():
            self._random_pause_resume_timer.stop()
        if hasattr(self, "_random_pause_timer") and self._random_pause_timer.isActive():
            self._random_pause_timer.stop()
        if resume_if_paused and getattr(self, "_is_paused", False):
            self._resume_workflow()
            self._is_paused = False
            self._auto_pause_source = None
        if reset_state:
            self._main_schedule.start.enabled = False
            self._main_schedule.stop.enabled = False
            self._main_schedule.timed_pause.enabled = False
            self._main_schedule.random_pause.enabled = False
            self._schedule_engine.replace_bundle(self._main_schedule)
            self._sync_main_schedule_aliases()
        if persist:
            self._persist_main_schedule()
