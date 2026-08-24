# -*- coding: utf-8 -*-
import unittest

from app_core.control_plane import JobScheduler, JobState
from ui.control_center_parts.control_center_timer_mixin import ControlCenterTimerMixin


class ControlCenterScheduleTests(unittest.TestCase):
    def _make_host(self):
        class Host:
            _normalize_window_id_list = staticmethod(
                ControlCenterTimerMixin._normalize_window_id_list
            )
            _canonicalize_timer_window_ids = ControlCenterTimerMixin._canonicalize_timer_window_ids
            _resolve_configured_window_filter = (
                ControlCenterTimerMixin._resolve_configured_window_filter
            )
            _scheduled_start_window_ids = ControlCenterTimerMixin._scheduled_start_window_ids
            _commit_timer_target_picker_ids = (
                ControlCenterTimerMixin._commit_timer_target_picker_ids
            )

            def __init__(self):
                self.scheduler = JobScheduler()
                self._cc_schedule_window_ids = []

        host = Host()
        host.scheduler.sync_targets(
            [
                {"title": "桌面", "hwnd": 65548, "bind_id": "bind-desktop"},
                {"title": "游戏", "hwnd": 65549, "bind_id": "bind-game"},
            ]
        )
        host.scheduler.set_assignments(
            "bind-desktop",
            [{"file_path": "a.json", "name": "A"}],
        )
        host.scheduler.set_assignments(
            "bind-game",
            [{"file_path": "b.json", "name": "B"}],
        )
        return host

    def test_scheduled_start_skips_busy_jobs(self):
        host = self._make_host()
        host.scheduler.request_start("bind-desktop")
        desktop = host.scheduler.get_job("bind-desktop")
        desktop.state = JobState.RUNNING
        ids, desc = ControlCenterTimerMixin._scheduled_start_window_ids(host)
        self.assertEqual(ids, ["bind-game"])
        self.assertIn("空闲", desc)

    def test_scheduled_start_all_busy_is_skip(self):
        host = self._make_host()
        for job_id in ("bind-desktop", "bind-game"):
            host.scheduler.request_start(job_id)
            host.scheduler.get_job(job_id).state = JobState.RUNNING
        ids, desc = ControlCenterTimerMixin._scheduled_start_window_ids(host)
        self.assertIsNone(ids)
        self.assertEqual(desc, "没有空闲窗口")

    def test_scheduled_start_skips_idle_queued_jobs(self):
        host = self._make_host()
        host.scheduler.request_start("bind-desktop")
        self.assertEqual(host.scheduler.get_job("bind-desktop").state, JobState.IDLE)
        ids, desc = ControlCenterTimerMixin._scheduled_start_window_ids(host)
        self.assertEqual(ids, ["bind-game"])
        self.assertIn("空闲", desc)

    def test_resolve_stop_empty_means_all(self):
        host = self._make_host()
        target_ids, ok = ControlCenterTimerMixin._resolve_configured_window_filter(host, [])
        self.assertTrue(ok)
        self.assertIsNone(target_ids)

    def test_resolve_stop_invalid_does_not_become_all(self):
        host = self._make_host()
        target_ids, ok = ControlCenterTimerMixin._resolve_configured_window_filter(
            host, ["missing-bind"]
        )
        self.assertFalse(ok)
        self.assertIsNone(target_ids)

    def test_picker_empty_keeps_invalid_and_does_not_become_all(self):
        host = self._make_host()
        kept = ControlCenterTimerMixin._commit_timer_target_picker_ids(
            host, ["missing-bind"], []
        )
        self.assertEqual(kept, ["missing-bind"])

    def test_picker_empty_from_all_stays_all(self):
        host = self._make_host()
        self.assertEqual(
            ControlCenterTimerMixin._commit_timer_target_picker_ids(host, [], []),
            [],
        )

    def test_picker_uncheck_valid_means_all(self):
        host = self._make_host()
        self.assertEqual(
            ControlCenterTimerMixin._commit_timer_target_picker_ids(
                host, ["bind-desktop"], []
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
