# -*- coding: utf-8 -*-
import os
import tempfile
import unittest

from utils.instance_runtime import (
    apply_instance_window_offset,
    claim_instance_slot,
    extract_bound_hwnds,
    get_instance_slot,
    get_instance_title_suffix,
    get_instance_window_offset,
    get_qsettings_application_name,
    release_instance_slot,
    reset_instance_runtime_for_tests,
    should_handle_hotkey,
)


class InstanceRuntimeTests(unittest.TestCase):
    def setUp(self):
        reset_instance_runtime_for_tests()
        self._temp = tempfile.TemporaryDirectory()
        self.instances_dir = os.path.join(self._temp.name, "instances")
        os.makedirs(self.instances_dir, exist_ok=True)
        self.alive = {1001, 1002, 1003}

    def tearDown(self):
        reset_instance_runtime_for_tests()
        self._temp.cleanup()

    def _pid_is_running(self, pid):
        return int(pid) in self.alive

    def test_first_claim_uses_primary_slot(self):
        slot = claim_instance_slot(
            instances_dir=self.instances_dir,
            pid=1001,
            pid_is_running=self._pid_is_running,
        )
        self.assertEqual(slot, 1)
        self.assertEqual(get_instance_slot(), 1)
        self.assertEqual(get_instance_title_suffix(), "")
        self.assertTrue(os.path.exists(os.path.join(self.instances_dir, "slot-1.lock")))

    def test_second_claim_gets_next_slot(self):
        claim_instance_slot(
            instances_dir=self.instances_dir,
            pid=1001,
            pid_is_running=self._pid_is_running,
        )
        reset_instance_runtime_for_tests()
        slot = claim_instance_slot(
            instances_dir=self.instances_dir,
            pid=1002,
            pid_is_running=self._pid_is_running,
        )
        self.assertEqual(slot, 2)
        self.assertEqual(get_instance_title_suffix(), " #2")

    def test_stale_lock_is_reused(self):
        claim_instance_slot(
            instances_dir=self.instances_dir,
            pid=1001,
            pid_is_running=self._pid_is_running,
        )
        self.alive.discard(1001)
        reset_instance_runtime_for_tests()
        slot = claim_instance_slot(
            instances_dir=self.instances_dir,
            pid=1002,
            pid_is_running=self._pid_is_running,
        )
        self.assertEqual(slot, 1)

    def test_single_instance_keeps_global_hotkeys(self):
        self.assertTrue(
            should_handle_hotkey(
                [{"hwnd": 11, "enabled": True}],
                foreground_hwnd=99,
                current_pid=1001,
                current_slot=1,
                peer_records=[],
                window_pid=lambda hwnd: 0,
                hwnd_ancestry=lambda hwnd: [hwnd],
            )
        )

    def test_hotkey_goes_to_instance_owning_foreground_ui(self):
        self.assertTrue(
            should_handle_hotkey(
                [],
                foreground_hwnd=501,
                current_pid=1002,
                current_slot=2,
                peer_records=[{"slot": 1, "pid": 1001, "bound_hwnds": [11], "last_ui_focus_ts": 1}],
                window_pid=lambda hwnd: 1002 if hwnd == 501 else 0,
                hwnd_ancestry=lambda hwnd: [hwnd],
            )
        )
        self.assertFalse(
            should_handle_hotkey(
                [{"hwnd": 11, "enabled": True}],
                foreground_hwnd=501,
                current_pid=1001,
                current_slot=1,
                peer_records=[{"slot": 2, "pid": 1002, "bound_hwnds": [], "last_ui_focus_ts": 9}],
                window_pid=lambda hwnd: 1002 if hwnd == 501 else 0,
                hwnd_ancestry=lambda hwnd: [hwnd],
            )
        )

    def test_hotkey_routes_to_bound_window_owner(self):
        peers = [{"slot": 2, "pid": 1002, "bound_hwnds": [22], "last_ui_focus_ts": 1}]
        self.assertTrue(
            should_handle_hotkey(
                [{"hwnd": 11, "enabled": True}],
                foreground_hwnd=11,
                current_pid=1001,
                current_slot=1,
                peer_records=peers,
                window_pid=lambda hwnd: 0,
                hwnd_ancestry=lambda hwnd: [hwnd],
            )
        )
        self.assertFalse(
            should_handle_hotkey(
                [{"hwnd": 11, "enabled": True}],
                foreground_hwnd=22,
                current_pid=1001,
                current_slot=1,
                peer_records=peers,
                window_pid=lambda hwnd: 0,
                hwnd_ancestry=lambda hwnd: [hwnd],
            )
        )

    def test_shared_binding_uses_last_focused_instance(self):
        self.assertTrue(
            should_handle_hotkey(
                [{"hwnd": 11, "enabled": True}],
                foreground_hwnd=11,
                current_pid=1002,
                current_slot=2,
                own_last_ui_focus_ts=9,
                peer_records=[{"slot": 1, "pid": 1001, "bound_hwnds": [11], "last_ui_focus_ts": 1}],
                window_pid=lambda hwnd: 0,
                hwnd_ancestry=lambda hwnd: [hwnd],
            )
        )
        self.assertFalse(
            should_handle_hotkey(
                [{"hwnd": 11, "enabled": True}],
                foreground_hwnd=11,
                current_pid=1001,
                current_slot=1,
                own_last_ui_focus_ts=1,
                peer_records=[{"slot": 2, "pid": 1002, "bound_hwnds": [11], "last_ui_focus_ts": 9}],
                window_pid=lambda hwnd: 0,
                hwnd_ancestry=lambda hwnd: [hwnd],
            )
        )

    def test_unrelated_foreground_goes_to_last_focused_instance(self):
        self.assertTrue(
            should_handle_hotkey(
                [{"hwnd": 11, "enabled": True}],
                foreground_hwnd=99,
                current_pid=1002,
                current_slot=2,
                own_last_ui_focus_ts=9,
                peer_records=[{"slot": 1, "pid": 1001, "bound_hwnds": [11], "last_ui_focus_ts": 1}],
                window_pid=lambda hwnd: 0,
                hwnd_ancestry=lambda hwnd: [hwnd],
            )
        )
        self.assertFalse(
            should_handle_hotkey(
                [{"hwnd": 11, "enabled": True}],
                foreground_hwnd=99,
                current_pid=1001,
                current_slot=1,
                own_last_ui_focus_ts=1,
                peer_records=[{"slot": 2, "pid": 1002, "bound_hwnds": [22], "last_ui_focus_ts": 9}],
                window_pid=lambda hwnd: 0,
                hwnd_ancestry=lambda hwnd: [hwnd],
            )
        )

    def test_extract_bound_hwnds_skips_disabled(self):
        hwnds = extract_bound_hwnds(
            [
                {"hwnd": 11, "enabled": True},
                {"hwnd": 22, "enabled": False},
                {"hwnd": 11, "enabled": True},
            ]
        )
        self.assertEqual(hwnds, [11])

    def test_release_removes_owned_lock(self):
        claim_instance_slot(
            instances_dir=self.instances_dir,
            pid=1001,
            pid_is_running=self._pid_is_running,
        )
        release_instance_slot(instances_dir=self.instances_dir)
        self.assertFalse(os.path.exists(os.path.join(self.instances_dir, "slot-1.lock")))

    def test_primary_instance_keeps_default_settings_and_position(self):
        self.assertEqual(get_qsettings_application_name(), "LCA")
        self.assertEqual(get_instance_window_offset(), (0, 0))
        self.assertEqual(
            apply_instance_window_offset(100, 80, 1000, 700, (0, 0, 1919, 1079)),
            (100, 80),
        )

    def test_secondary_instance_offsets_window_and_settings_name(self):
        claim_instance_slot(
            instances_dir=self.instances_dir,
            pid=1001,
            pid_is_running=self._pid_is_running,
        )
        reset_instance_runtime_for_tests()
        claim_instance_slot(
            instances_dir=self.instances_dir,
            pid=1002,
            pid_is_running=self._pid_is_running,
        )
        self.assertEqual(get_qsettings_application_name(), "LCA-2")
        self.assertEqual(get_instance_window_offset(), (40, 40))
        self.assertEqual(
            apply_instance_window_offset(100, 80, 1000, 700, (0, 0, 1919, 1079)),
            (140, 120),
        )
        self.assertEqual(
            apply_instance_window_offset(1880, 1040, 1000, 700, (0, 0, 1919, 1079)),
            (920, 380),
        )


if __name__ == "__main__":
    unittest.main()
