# -*- coding: utf-8 -*-
"""实测主窗/中控定时：调度引擎、执行接线、窗口目标、数字框、可取消暂停。"""
import os
import unittest
from datetime import datetime, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject

from app_core.control_plane import JobScheduler, JobState
from app_core.scheduling import (
    ACTION_START,
    ACTION_STOP,
    ACTION_TIMED_PAUSE,
    REPEAT_ONCE,
    START_MODE_INTERVAL,
    ScheduleBundle,
    ScheduleEngine,
    StartPolicy,
    load_bundle,
    wake_delay_ms,
)
from ui.control_center_parts.control_center_batch_ops_mixin import ControlCenterBatchOpsMixin
from ui.control_center_parts.control_center_timer_mixin import ControlCenterTimerMixin
from ui.main_window_parts.main_window_timer_runtime_mixin import MainWindowTimerRuntimeMixin
from ui.main_window_parts.main_window_window_validation_mixin import (
    MainWindowWindowValidationMixin,
)


class _CCHost(ControlCenterTimerMixin, ControlCenterBatchOpsMixin):
    def __init__(self):
        self.parent_window = None
        self.scheduler = JobScheduler()
        self._is_closing = False
        self.logs = []
        self.started = []
        self.stopped = []
        self.timer_status_label = None
        self._apply_control_bundle_to_attrs(ScheduleBundle())
        self.scheduler.sync_targets(
            [
                {"title": "桌面", "hwnd": 65548, "bind_id": "bind-desktop"},
                {"title": "游戏", "hwnd": 65549, "bind_id": "bind-game"},
            ]
        )
        self.scheduler.set_assignments("bind-desktop", [{"file_path": "a.json", "name": "A"}])
        self.scheduler.set_assignments("bind-game", [{"file_path": "b.json", "name": "B"}])

    def log_message(self, message):
        self.logs.append(message)

    def start_all_tasks(self, window_ids=None, interactive=True):
        self.started.append(
            {
                "window_ids": list(window_ids) if window_ids is not None else None,
                "interactive": interactive,
            }
        )
        return True

    def stop_all_tasks(self, window_ids=None):
        resolved, desc = self._resolve_batch_window_ids(window_ids)
        self.stopped.append({"window_ids": window_ids, "resolved": resolved, "desc": desc})
        return True


class _MainHost(QObject, MainWindowTimerRuntimeMixin):
    def __init__(self):
        super().__init__()
        self.config = {}
        self.started = []
        self.stopped = []
        self.paused = []
        self.resumed = []
        self.task_manager = None
        self._setup_main_schedule_runtime()

    def safe_start_tasks(self, reset_jump_cancel=True, interactive=True):
        self.started.append({"interactive": interactive, "reset_jump_cancel": reset_jump_cancel})

    def safe_stop_tasks(self):
        self.stopped.append(True)

    def _pause_workflow(self, source="manual"):
        self.paused.append(source)
        self._is_paused = True
        self._auto_pause_source = source
        return True

    def _resume_workflow(self, source="manual"):
        self.resumed.append(source)
        self._is_paused = False
        self._auto_pause_source = None
        return True


class TimerLiveClockTests(unittest.TestCase):
    def test_wall_clock_same_minute_fires_start(self):
        now = datetime.now()
        bundle = ScheduleBundle()
        bundle.start.enabled = True
        bundle.start.hour = now.hour
        bundle.start.minute = now.minute
        engine = ScheduleEngine(bundle)
        engine.replace_bundle(bundle, now)
        self.assertEqual(engine.take_due(now), ACTION_START)
        self.assertEqual(engine.due_actions(now), [])

    def test_overdue_stop_and_pause_also_catch_up(self):
        armed_at = datetime(2026, 8, 14, 8, 50)
        bundle = ScheduleBundle()
        bundle.stop.enabled = True
        bundle.stop.hour = 9
        bundle.stop.minute = 0
        bundle.timed_pause.enabled = True
        bundle.timed_pause.hour = 9
        bundle.timed_pause.minute = 0
        engine = ScheduleEngine(bundle)
        engine.replace_bundle(bundle, armed_at)
        winner = engine.take_due(datetime(2026, 8, 14, 9, 5))
        self.assertEqual(winner, ACTION_STOP)
        self.assertEqual(engine.runtimes[ACTION_STOP].next_fire_at, datetime(2026, 8, 15, 9, 0))
        self.assertEqual(engine.runtimes[ACTION_TIMED_PAUSE].next_fire_at, datetime(2026, 8, 15, 9, 0))

    def test_once_start_disables_after_fire(self):
        now = datetime(2026, 8, 14, 9, 0, 8)
        bundle = ScheduleBundle()
        bundle.start.enabled = True
        bundle.start.hour = 9
        bundle.start.minute = 0
        bundle.start.repeat = REPEAT_ONCE
        engine = ScheduleEngine(bundle)
        engine.replace_bundle(bundle, now)
        self.assertEqual(engine.take_due(now), ACTION_START)
        self.assertFalse(engine.bundle.start.enabled)
        self.assertIsNone(engine.runtimes[ACTION_START].next_fire_at)

    def test_wake_delay_for_overdue_slot_is_immediate(self):
        now = datetime(2026, 8, 14, 9, 5)
        delay = wake_delay_ms(datetime(2026, 8, 14, 9, 0), now)
        self.assertEqual(delay, 1)

    def test_main_bundle_still_rejects_interval(self):
        bundle = load_bundle(
            {"start": {"enabled": True, "mode": "interval", "interval_value": 15}},
            allow_interval_start=False,
        )
        self.assertNotEqual(bundle.start.mode, START_MODE_INTERVAL)


class TimerLiveMainWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def test_scheduled_start_is_silent(self):
        host = _MainHost()
        now = datetime.now()
        host._main_schedule.start.enabled = True
        host._main_schedule.start.hour = now.hour
        host._main_schedule.start.minute = now.minute
        host._schedule_engine.replace_bundle(host._main_schedule, now)
        host._on_main_schedule_clock()
        self.assertEqual(host.started, [{"interactive": False, "reset_jump_cancel": True}])

    def test_scheduled_start_skips_when_already_running(self):
        host = _MainHost()
        host._is_paused = True
        host._execute_scheduled_start()
        self.assertEqual(host.started, [])

    def test_window_binding_silent_when_unbound(self):
        class Fake(MainWindowWindowValidationMixin):
            bound_windows = []

        self.assertFalse(Fake()._check_window_binding(interactive=False))

    def test_random_pause_timer_is_cancellable(self):
        host = _MainHost()
        host._trigger_random_pause()
        self.assertEqual(host.paused, ["random"])
        self.assertTrue(host._random_pause_resume_timer.isActive())
        host._stop_all_main_timers(resume_if_paused=True)
        self.assertFalse(host._random_pause_resume_timer.isActive())
        self.assertEqual(host.resumed, ["manual"])
        self.assertFalse(host._is_paused)

    def test_timed_pause_uses_timed_source(self):
        host = _MainHost()

        class Tasks:
            def get_running_count(self):
                return 1

        host.task_manager = Tasks()
        host._timed_pause_duration_value = 2
        host._timed_pause_duration_unit = "seconds"
        host._trigger_timed_pause()
        self.assertEqual(host.paused, ["timed"])
        self.assertEqual(host._auto_pause_source, "timed")
        self.assertTrue(host._timed_pause_resume_timer.isActive())

    def test_spinbox_uses_western_digits_under_zh_tw(self):
        from PySide6.QtCore import QLocale
        from PySide6.QtWidgets import QSpinBox

        from ui.scheduling.timer_form import fit_timer_spinbox

        spin = QSpinBox()
        spin.setRange(0, 23)
        spin.setLocale(QLocale(QLocale.Language.Chinese, QLocale.Script.HanScript, QLocale.Country.Taiwan))
        spin.setValue(9)
        fit_timer_spinbox(spin)
        text = spin.text()
        self.assertIn("9", text)
        self.assertNotIn("\u3029", text)


class TimerLiveControlCenterTests(unittest.TestCase):
    def test_scheduled_start_only_idle_and_silent(self):
        host = _CCHost()
        host.scheduler.request_start("bind-desktop")
        host.scheduler.get_job("bind-desktop").state = JobState.RUNNING
        host._execute_control_scheduled_start()
        self.assertEqual(len(host.started), 1)
        self.assertEqual(host.started[0]["window_ids"], ["bind-game"])
        self.assertFalse(host.started[0]["interactive"])

    def test_scheduled_start_skips_invalid_targets(self):
        host = _CCHost()
        host._cc_schedule_window_ids = ["missing-bind"]
        host._execute_control_scheduled_start()
        self.assertEqual(host.started, [])
        self.assertTrue(any("无有效" in item for item in host.logs))

    def test_scheduled_stop_all_uses_empty_list(self):
        host = _CCHost()
        host._cc_stop_window_ids = []
        host._execute_control_scheduled_stop()
        self.assertEqual(len(host.stopped), 1)
        self.assertEqual(host.stopped[0]["window_ids"], [])
        self.assertEqual(host.stopped[0]["resolved"], [])
        self.assertEqual(host.stopped[0]["desc"], "全部窗口")

    def test_scheduled_stop_keeps_resolved_bind_ids(self):
        host = _CCHost()
        host._cc_stop_window_ids = ["bind-game", "65548"]
        host._execute_control_scheduled_stop()
        self.assertEqual(host.stopped[0]["window_ids"], ["bind-game"])
        self.assertEqual(host.stopped[0]["resolved"], ["bind-game"])

    def test_scheduled_stop_skips_invalid(self):
        host = _CCHost()
        host._cc_stop_window_ids = ["missing-bind"]
        host._execute_control_scheduled_stop()
        self.assertEqual(host.stopped, [])
        self.assertTrue(any("无有效" in item for item in host.logs))

    def test_interval_skip_still_advances_then_next_tick_can_start(self):
        now = datetime(2026, 8, 14, 10, 0)
        bundle = ScheduleBundle(
            start=StartPolicy(
                enabled=True,
                mode=START_MODE_INTERVAL,
                interval_value=15,
                interval_unit="minutes",
            )
        )
        engine = ScheduleEngine(bundle, allow_interval_start=True)
        engine.replace_bundle(bundle, now)
        later = now + timedelta(minutes=15)
        self.assertEqual(engine.take_due(later), ACTION_START)
        nxt = later + timedelta(minutes=15)
        self.assertEqual(engine.due_actions(later), [])
        self.assertEqual(engine.take_due(nxt), ACTION_START)


if __name__ == "__main__":
    unittest.main()
