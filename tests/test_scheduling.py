from datetime import datetime, timedelta

from app_core.scheduling.clock import ScheduleEngine, wake_delay_ms
from app_core.scheduling.models import ACTION_START, REPEAT_ONCE, ScheduleBundle, StartPolicy


def test_once_start_fires_only_once():
    bundle = ScheduleBundle(
        start=StartPolicy(enabled=True, hour=9, minute=30, repeat=REPEAT_ONCE),
    )
    engine = ScheduleEngine(bundle)
    now = datetime(2026, 8, 24, 9, 29, 59)
    engine.replace_bundle(bundle, now)

    assert engine.take_due(now) is None
    assert engine.take_due(now + timedelta(seconds=1)) == ACTION_START
    assert engine.take_due(now + timedelta(minutes=1)) is None


def test_wake_delay_is_bounded_and_non_negative():
    now = datetime(2026, 8, 24, 9, 0, 0)
    assert wake_delay_ms(None, now) == 0
    assert wake_delay_ms(now - timedelta(seconds=1), now) == 1
    assert wake_delay_ms(now + timedelta(minutes=5), now, max_seconds=10) == 10_000
# -*- coding: utf-8 -*-
import unittest
from datetime import datetime, timedelta

from app_core.scheduling import (
    ACTION_START,
    ACTION_STOP,
    ACTION_TIMED_PAUSE,
    OLD_SCHEDULE_KEYS,
    START_MODE_INTERVAL,
    ScheduleBundle,
    ScheduleEngine,
    StartPolicy,
    apply_schedule_schema,
    arbitrate,
    dump_bundle,
    interval_to_seconds,
    load_bundle,
    next_daily_fire,
    normalize_window_ids,
    write_control_bundle,
)


class SchedulingClockTests(unittest.TestCase):
    def test_daily_next_fire_before_slot(self):
        now = datetime(2026, 8, 14, 8, 30)
        nxt = next_daily_fire(now, 9, 0, False, None, "daily")
        self.assertEqual(nxt, datetime(2026, 8, 14, 9, 0))

    def test_daily_next_fire_after_slot_skips_today(self):
        now = datetime(2026, 8, 14, 10, 0)
        nxt = next_daily_fire(now, 9, 0, False, None, "daily")
        self.assertEqual(nxt, datetime(2026, 8, 15, 9, 0))

    def test_daily_next_fire_in_slot(self):
        now = datetime(2026, 8, 14, 9, 0, 12)
        nxt = next_daily_fire(now, 9, 0, False, None, "daily")
        self.assertEqual(nxt, datetime(2026, 8, 14, 9, 0))

    def test_daily_cross_day_after_executed(self):
        now = datetime(2026, 8, 15, 8, 0)
        nxt = next_daily_fire(now, 9, 0, True, datetime(2026, 8, 14, 9, 0), "daily")
        self.assertEqual(nxt, datetime(2026, 8, 15, 9, 0))

    def test_once_returns_none_after_fire(self):
        now = datetime(2026, 8, 14, 10, 0)
        nxt = next_daily_fire(now, 9, 0, True, datetime(2026, 8, 14, 9, 0), "once")
        self.assertIsNone(nxt)

    def test_interval_does_not_fire_immediately(self):
        now = datetime(2026, 8, 14, 10, 0)
        engine = ScheduleEngine(
            ScheduleBundle(
                start=StartPolicy(
                    enabled=True,
                    mode=START_MODE_INTERVAL,
                    interval_value=30,
                    interval_unit="分钟",
                )
            ),
            allow_interval_start=True,
        )
        engine.replace_bundle(engine.bundle, now)
        self.assertEqual(engine.due_actions(now), [])
        self.assertEqual(engine.next_fire_for(ACTION_START, now), now + timedelta(minutes=30))

    def test_interval_due_and_advances_after_skip(self):
        now = datetime(2026, 8, 14, 10, 0)
        engine = ScheduleEngine(
            ScheduleBundle(
                start=StartPolicy(
                    enabled=True,
                    mode=START_MODE_INTERVAL,
                    interval_value=15,
                    interval_unit="分钟",
                )
            ),
            allow_interval_start=True,
        )
        engine.replace_bundle(engine.bundle, now)
        later = now + timedelta(minutes=15)
        winner = engine.take_due(later)
        self.assertEqual(winner, ACTION_START)
        self.assertEqual(engine.runtimes[ACTION_START].next_fire_at, later + timedelta(minutes=15))
        self.assertEqual(engine.due_actions(later), [])

    def test_interval_units_are_minutes_or_hours(self):
        self.assertEqual(interval_to_seconds(2, "分钟"), 120)
        self.assertEqual(interval_to_seconds(1, "小时"), 3600)
        self.assertEqual(interval_to_seconds(5, "秒"), 300)
        self.assertEqual(interval_to_seconds(2, "minutes"), 120)
        self.assertEqual(interval_to_seconds(1, "hours"), 3600)

    def test_same_minute_stop_beats_pause_and_start(self):
        self.assertEqual(arbitrate([ACTION_START, ACTION_TIMED_PAUSE, ACTION_STOP]), ACTION_STOP)
        self.assertEqual(arbitrate([ACTION_START, ACTION_TIMED_PAUSE]), ACTION_TIMED_PAUSE)
        self.assertEqual(arbitrate([ACTION_START]), ACTION_START)

    def test_same_minute_winner_consumes_losers(self):
        now = datetime(2026, 8, 14, 9, 0, 5)
        bundle = ScheduleBundle()
        bundle.start.enabled = True
        bundle.start.hour = 9
        bundle.start.minute = 0
        bundle.stop.enabled = True
        bundle.stop.hour = 9
        bundle.stop.minute = 0
        engine = ScheduleEngine(bundle, allow_interval_start=False)
        engine.replace_bundle(bundle, now)
        winner = engine.take_due(now)
        self.assertEqual(winner, ACTION_STOP)
        self.assertTrue(engine.runtimes[ACTION_START].executed)
        self.assertTrue(engine.runtimes[ACTION_STOP].executed)
        self.assertEqual(engine.due_actions(now), [])

    def test_overdue_daily_still_fires_and_advances(self):
        now = datetime(2026, 8, 14, 8, 50)
        bundle = ScheduleBundle()
        bundle.start.enabled = True
        bundle.start.hour = 9
        bundle.start.minute = 0
        engine = ScheduleEngine(bundle)
        engine.replace_bundle(bundle, now)
        self.assertEqual(engine.runtimes[ACTION_START].next_fire_at, datetime(2026, 8, 14, 9, 0))
        winner = engine.take_due(datetime(2026, 8, 14, 9, 5))
        self.assertEqual(winner, ACTION_START)
        self.assertEqual(engine.runtimes[ACTION_START].next_fire_at, datetime(2026, 8, 15, 9, 0))

    def test_enable_after_slot_does_not_fire_immediately(self):
        now = datetime(2026, 8, 14, 10, 0)
        bundle = ScheduleBundle()
        bundle.start.enabled = True
        bundle.start.hour = 9
        bundle.start.minute = 0
        engine = ScheduleEngine(bundle)
        engine.replace_bundle(bundle, now)
        self.assertEqual(engine.due_actions(now), [])
        self.assertEqual(engine.runtimes[ACTION_START].next_fire_at, datetime(2026, 8, 15, 9, 0))

    def test_replace_bundle_without_now_keeps_interval_next_fire(self):
        now = datetime(2026, 8, 14, 10, 0)
        bundle = ScheduleBundle(
            start=StartPolicy(
                enabled=True,
                mode=START_MODE_INTERVAL,
                interval_value=30,
                interval_unit="minutes",
            )
        )
        engine = ScheduleEngine(bundle, allow_interval_start=True)
        engine.replace_bundle(bundle, now)
        armed = engine.runtimes[ACTION_START].next_fire_at
        self.assertEqual(armed, now + timedelta(minutes=30))
        later = now + timedelta(minutes=7)
        same = ScheduleBundle(
            start=StartPolicy(
                enabled=True,
                mode=START_MODE_INTERVAL,
                interval_value=30,
                interval_unit="minutes",
            )
        )
        engine.runtimes[ACTION_START].next_fire_at = later
        engine.replace_bundle(same)
        self.assertEqual(engine.runtimes[ACTION_START].next_fire_at, later)

    def test_replace_bundle_without_now_keeps_daily_next_fire(self):
        now = datetime(2026, 8, 14, 8, 50)
        bundle = ScheduleBundle()
        bundle.start.enabled = True
        bundle.start.hour = 9
        bundle.start.minute = 0
        engine = ScheduleEngine(bundle)
        engine.replace_bundle(bundle, now)
        armed = engine.runtimes[ACTION_START].next_fire_at
        engine.replace_bundle(bundle)
        self.assertEqual(engine.runtimes[ACTION_START].next_fire_at, armed)


class SchedulingStoreTests(unittest.TestCase):
    def test_old_keys_are_dropped(self):
        config = {
            "enable_schedule": True,
            "schedule_hour": 8,
            "cc_schedule_enabled": True,
            "cc_schedule_window_ids": ["bind-a"],
            "other": 1,
        }
        apply_schedule_schema(config)
        for key in ("enable_schedule", "schedule_hour", "cc_schedule_enabled", "cc_schedule_window_ids"):
            self.assertNotIn(key, config)
        self.assertFalse(config["main_schedule"]["start"]["enabled"])
        self.assertFalse(config["control_schedule"]["start"]["enabled"])
        self.assertEqual(config["other"], 1)
        self.assertTrue(set(OLD_SCHEDULE_KEYS))

    def test_chinese_units_normalize_to_english_keys(self):
        bundle = load_bundle(
            {
                "start": {
                    "enabled": True,
                    "mode": "interval",
                    "interval_value": 30,
                    "interval_unit": "分钟",
                },
                "timed_pause": {"duration_unit": "分钟"},
                "random_pause": {
                    "check_interval_unit": "秒",
                    "min_unit": "秒",
                    "max_unit": "小时",
                },
            },
            allow_interval_start=True,
        )
        dumped = dump_bundle(bundle, include_windows=True)
        self.assertEqual(dumped["start"]["interval_unit"], "minutes")
        self.assertEqual(dumped["timed_pause"]["duration_unit"], "minutes")
        self.assertEqual(dumped["random_pause"]["check_interval_unit"], "seconds")
        self.assertEqual(dumped["random_pause"]["min_unit"], "seconds")
        self.assertEqual(dumped["random_pause"]["max_unit"], "hours")

    def test_invalid_window_ids_stay_non_empty(self):
        bundle = load_bundle(
            {
                "start": {
                    "enabled": True,
                    "mode": "interval",
                    "interval_value": 30,
                    "interval_unit": "分钟",
                    "window_ids": ["65548"],
                }
            },
            allow_interval_start=True,
        )
        self.assertEqual(bundle.start.window_ids, ["65548"])
        dumped = dump_bundle(bundle, include_windows=True)
        self.assertEqual(dumped["start"]["window_ids"], ["65548"])
        self.assertNotEqual(dumped["start"]["window_ids"], [])

    def test_main_bundle_rejects_interval_mode(self):
        bundle = load_bundle(
            {"start": {"enabled": True, "mode": "interval", "hour": 9, "minute": 0}},
            allow_interval_start=False,
        )
        self.assertEqual(bundle.start.mode, "daily")

    def test_normalize_window_ids_keeps_bind_id(self):
        self.assertEqual(normalize_window_ids(["65548", "bind-abc", "全部", "0"]), ["65548", "bind-abc"])

    def test_write_control_bundle_keeps_invalid_ids(self):
        bundle = ScheduleBundle()
        bundle.start.window_ids = ["65548"]
        config = {}
        write_control_bundle(config, bundle)
        self.assertEqual(config["control_schedule"]["start"]["window_ids"], ["65548"])

    def test_config_store_drops_old_timer_keys(self):
        from app_core.config_store import _normalize_config

        normalized = _normalize_config(
            {
                "enable_schedule": True,
                "schedule_hour": 8,
                "cc_schedule_enabled": True,
                "cc_schedule_window_ids": ["65548"],
            }
        )
        self.assertNotIn("enable_schedule", normalized)
        self.assertNotIn("cc_schedule_enabled", normalized)
        self.assertFalse(normalized["main_schedule"]["start"]["enabled"])
        self.assertEqual(normalized["control_schedule"]["start"]["window_ids"], [])


if __name__ == "__main__":
    unittest.main()
