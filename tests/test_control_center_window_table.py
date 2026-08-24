# -*- coding: utf-8 -*-
import unittest

from app_core.control_plane import JobScheduler
from ui.control_center_parts.control_center_batch_ops_mixin import ControlCenterBatchOpsMixin
from ui.control_center_parts.control_center_timer_dialog_mixin import ControlCenterTimerDialogMixin
from ui.control_center_parts.control_center_timer_mixin import ControlCenterTimerMixin
from ui.control_center_parts.control_center_window_table_mixin import (
    format_bound_window_display_title,
    resolve_control_center_window_id,
)


class ControlCenterWindowTableTests(unittest.TestCase):
    def test_unique_title_has_no_suffix(self):
        windows = [{"title": "桌面"}]
        self.assertEqual(format_bound_window_display_title("桌面", 0, windows), "桌面")

    def test_duplicate_titles_are_numbered(self):
        windows = [{"title": "游戏"}, {"title": "游戏"}]
        self.assertEqual(format_bound_window_display_title("游戏", 0, windows), "游戏-1")
        self.assertEqual(format_bound_window_display_title("游戏", 1, windows), "游戏-2")

    def test_normalize_window_id_keeps_bind_id(self):
        values = ControlCenterTimerMixin._normalize_window_id_list(
            ["65548", "bind-abc", "全部", "0"]
        )
        self.assertEqual(values, ["65548", "bind-abc"])

    def test_runtime_id_prefers_bind_id(self):
        window = {"title": "桌面", "hwnd": 65548, "bind_id": "bind-abc"}
        self.assertEqual(resolve_control_center_window_id(window), "bind-abc")

    def test_timer_ids_keep_bind_id_and_drop_hwnd(self):
        class Host:
            _normalize_window_id_list = staticmethod(
                ControlCenterTimerMixin._normalize_window_id_list
            )

            def __init__(self):
                self.scheduler = JobScheduler()

        host = Host()
        host.scheduler.sync_targets(
            [{"title": "桌面", "hwnd": 65548, "bind_id": "bind-desktop"}]
        )
        self.assertEqual(
            ControlCenterTimerMixin._canonicalize_timer_window_ids(host, ["bind-desktop"]),
            ["bind-desktop"],
        )
        self.assertEqual(
            ControlCenterTimerMixin._canonicalize_timer_window_ids(host, ["65548"]),
            [],
        )

    def test_stored_timer_ids_keep_hwnd_only_list(self):
        class Host:
            _normalize_window_id_list = staticmethod(
                ControlCenterTimerMixin._normalize_window_id_list
            )
            _canonicalize_timer_window_ids = ControlCenterTimerMixin._canonicalize_timer_window_ids
            _canonicalize_stored_timer_window_ids = (
                ControlCenterTimerMixin._canonicalize_stored_timer_window_ids
            )

            def __init__(self):
                self.scheduler = JobScheduler()
                self._cc_schedule_window_ids = ["65548"]
                self._cc_stop_window_ids = ["bind-desktop", "65548"]
                self._cc_timed_pause_window_ids = []
                self._cc_random_pause_window_ids = []

        host = Host()
        host.scheduler.sync_targets(
            [{"title": "桌面", "hwnd": 65548, "bind_id": "bind-desktop"}]
        )
        changed = ControlCenterTimerMixin._canonicalize_stored_timer_window_ids(host)
        self.assertEqual(host._cc_schedule_window_ids, ["65548"])
        self.assertEqual(host._cc_stop_window_ids, ["bind-desktop"])
        self.assertTrue(changed)

    def test_batch_ids_drop_hwnd_and_do_not_mean_all(self):
        class Host:
            _normalize_window_id_list = staticmethod(
                ControlCenterTimerMixin._normalize_window_id_list
            )

            def __init__(self):
                self.scheduler = JobScheduler()

            def _get_selected_window_ids(self):
                return []

        host = Host()
        host.scheduler.sync_targets(
            [{"title": "桌面", "hwnd": 65548, "bind_id": "bind-desktop"}]
        )
        ids, desc = ControlCenterBatchOpsMixin._resolve_batch_window_ids(host, ["65548"])
        self.assertIsNone(ids)
        self.assertEqual(desc, "无有效窗口")
        ids, desc = ControlCenterBatchOpsMixin._resolve_batch_window_ids(host, [])
        self.assertEqual(ids, [])
        self.assertEqual(desc, "全部窗口")
        ids, desc = ControlCenterBatchOpsMixin._resolve_batch_window_ids(host, ["bind-desktop"])
        self.assertEqual(ids, ["bind-desktop"])
        self.assertIn("指定窗口", desc)

    def _make_timer_host(self):
        class Host:
            _normalize_window_id_list = staticmethod(
                ControlCenterTimerMixin._normalize_window_id_list
            )
            _canonicalize_timer_window_ids = ControlCenterTimerMixin._canonicalize_timer_window_ids
            _retain_timer_window_ids = ControlCenterTimerMixin._retain_timer_window_ids
            _resolve_configured_window_filter = (
                ControlCenterTimerMixin._resolve_configured_window_filter
            )

            def __init__(self):
                self.scheduler = JobScheduler()
                self.sorted_windows = []
                self.bound_windows = []

            def _get_available_timer_window_options(self):
                return [("bind-desktop", "桌面")]

        host = Host()
        host.scheduler.sync_targets(
            [{"title": "桌面", "hwnd": 65548, "bind_id": "bind-desktop"}]
        )
        return host

    def test_retain_timer_ids_does_not_become_all(self):
        host = self._make_timer_host()
        self.assertEqual(
            ControlCenterTimerMixin._retain_timer_window_ids(host, ["65548"]),
            ["65548"],
        )
        self.assertEqual(
            ControlCenterTimerMixin._retain_timer_window_ids(host, ["bind-desktop", "65548"]),
            ["bind-desktop"],
        )
        self.assertEqual(ControlCenterTimerMixin._retain_timer_window_ids(host, []), [])

    def test_configured_filter_distinguishes_all_and_invalid(self):
        host = self._make_timer_host()
        self.assertEqual(
            ControlCenterTimerMixin._resolve_configured_window_filter(host, []),
            (None, True),
        )
        self.assertEqual(
            ControlCenterTimerMixin._resolve_configured_window_filter(host, ["65548"]),
            (None, False),
        )
        self.assertEqual(
            ControlCenterTimerMixin._resolve_configured_window_filter(host, ["bind-desktop"]),
            (["bind-desktop"], True),
        )

    def test_timer_summary_does_not_call_invalid_all(self):
        host = self._make_timer_host()
        self.assertEqual(
            ControlCenterTimerDialogMixin._format_target_windows_summary(host, ["65548"]),
            "目标窗口：无有效窗口",
        )
        self.assertEqual(
            ControlCenterTimerDialogMixin._format_target_windows_summary(host, []),
            "目标窗口：全部窗口",
        )
        self.assertEqual(
            ControlCenterTimerDialogMixin._format_target_windows_summary(host, ["bind-desktop"]),
            "目标窗口：桌面",
        )


if __name__ == "__main__":
    unittest.main()
