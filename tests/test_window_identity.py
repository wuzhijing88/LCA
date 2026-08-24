# -*- coding: utf-8 -*-
import unittest

from utils.window_identity import (
    _build_instance_key,
    hwnd_matches_identity,
    is_desktop_bound_window,
    is_wgc_with_desktop_target,
    match_bound_window,
    refresh_bound_windows,
    resolve_bound_window_hwnd,
    resolve_workflow_window_binding,
)


def _snap(hwnd, title, class_name="AppClass", process_name="game.exe", instance_key=""):
    return {
        "hwnd": hwnd,
        "title": title,
        "class_name": class_name,
        "process_name": process_name,
        "instance_key": instance_key,
    }


class WindowIdentityTests(unittest.TestCase):
    def test_keep_cached_hwnd_when_still_alive(self):
        window_info = {
            "title": "123123123-2",
            "class_name": "AppClass",
            "process_name": "game.exe",
            "hwnd": 100,
        }
        snapshots = [_snap(100, "123123123-2")]
        hwnd = resolve_bound_window_hwnd(
            window_info,
            snapshots=snapshots,
            hwnd_alive=lambda value: value == 100,
        )
        self.assertEqual(hwnd, 100)

    def test_reconnect_by_title_class_process_after_restart(self):
        window_info = {
            "title": "123123123-2",
            "class_name": "AppClass",
            "process_name": "game.exe",
            "hwnd": 100,
        }
        snapshots = [_snap(200, "123123123-2")]
        hwnd = resolve_bound_window_hwnd(
            window_info,
            snapshots=snapshots,
            hwnd_alive=lambda value: value == 200,
        )
        self.assertEqual(hwnd, 200)

    def test_allow_title_change_when_class_and_process_match(self):
        window_info = {
            "title": "旧标题",
            "class_name": "AppClass",
            "process_name": "game.exe",
            "hwnd": 100,
        }
        snapshots = [_snap(300, "新标题")]
        hwnd = resolve_bound_window_hwnd(
            window_info,
            snapshots=snapshots,
            hwnd_alive=lambda _value: False,
        )
        self.assertEqual(hwnd, 300)

    def test_refresh_matches_identical_windows_by_instance_key(self):
        windows = [
            {
                "title": "TheRender",
                "class_name": "Render",
                "process_name": "emu.exe",
                "instance_key": "index=0",
                "hwnd": 1,
                "enabled": True,
            },
            {
                "title": "TheRender",
                "class_name": "Render",
                "process_name": "emu.exe",
                "instance_key": "index=1",
                "hwnd": 2,
                "enabled": True,
            },
        ]
        snapshots = [
            _snap(11, "TheRender", "Render", "emu.exe", "index=1"),
            _snap(22, "TheRender", "Render", "emu.exe", "index=0"),
        ]
        changed = refresh_bound_windows(
            windows,
            snapshots=snapshots,
            hwnd_alive=lambda _value: False,
        )
        self.assertTrue(changed)
        self.assertEqual(windows[0]["hwnd"], 22)
        self.assertEqual(windows[1]["hwnd"], 11)

    def test_refresh_refuses_identical_windows_without_instance_key(self):
        windows = [
            {"title": "TheRender", "class_name": "Render", "process_name": "emu.exe", "hwnd": 1, "enabled": True},
            {"title": "TheRender", "class_name": "Render", "process_name": "emu.exe", "hwnd": 2, "enabled": True},
        ]
        snapshots = [
            _snap(11, "TheRender", "Render", "emu.exe"),
            _snap(22, "TheRender", "Render", "emu.exe"),
        ]
        changed = refresh_bound_windows(
            windows,
            snapshots=snapshots,
            hwnd_alive=lambda _value: False,
        )
        self.assertFalse(changed)
        self.assertEqual(windows[0]["hwnd"], 1)
        self.assertEqual(windows[1]["hwnd"], 2)

    def test_resolve_refuses_multiple_identical_candidates(self):
        window_info = {
            "title": "TheRender",
            "class_name": "Render",
            "process_name": "emu.exe",
            "hwnd": 1,
        }
        snapshots = [
            _snap(11, "TheRender", "Render", "emu.exe"),
            _snap(22, "TheRender", "Render", "emu.exe"),
        ]
        hwnd = resolve_bound_window_hwnd(
            window_info,
            snapshots=snapshots,
            hwnd_alive=lambda _value: False,
        )
        self.assertEqual(hwnd, 0)

    def test_refresh_keeps_record_when_window_is_offline(self):
        windows = [{"title": "离线窗口", "hwnd": 9, "enabled": True}]
        changed = refresh_bound_windows(
            windows,
            snapshots=[],
            hwnd_alive=lambda _value: False,
        )
        self.assertFalse(changed)
        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0]["title"], "离线窗口")

    def test_match_bound_window_by_title_after_hwnd_change(self):
        windows = [
            {"title": "123123123-2", "hwnd": 200, "enabled": True, "bind_id": "abc"},
        ]
        matched = match_bound_window(windows, hwnd=100, title="123123123-2")
        self.assertIsNotNone(matched)
        self.assertEqual(matched["hwnd"], 200)

    def test_workflow_binding_uses_current_hwnd_by_stable_id(self):
        workflow_binding = {
            "bound_window_id": "abc",
            "target_window_title": "123123123-2",
            "target_hwnd": 100,
        }
        windows = [
            {"title": "123123123-2", "hwnd": 200, "enabled": True, "bind_id": "abc"},
        ]
        resolved = resolve_workflow_window_binding(
            workflow_binding,
            windows,
            hwnd_alive=lambda value: value == 200,
        )
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved["target_hwnd"], 200)
        self.assertEqual(resolved["bound_window_id"], "abc")

    def test_workflow_binding_uses_unique_title_after_rebind_changes_id(self):
        workflow_binding = {
            "bound_window_id": "old-id",
            "target_window_title": "123123123-2",
            "target_hwnd": 100,
        }
        windows = [
            {"title": "123123123-2", "hwnd": 300, "enabled": True, "bind_id": "new-id"},
        ]
        resolved = resolve_workflow_window_binding(
            workflow_binding,
            windows,
            hwnd_alive=lambda value: value == 300,
        )
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved["target_hwnd"], 300)
        self.assertEqual(resolved["bound_window_id"], "new-id")

    def test_workflow_binding_refuses_unrelated_single_window_fallback(self):
        workflow_binding = {
            "bound_window_id": "old-id",
            "target_window_title": "目标窗口",
            "target_hwnd": 100,
        }
        windows = [
            {"title": "其他窗口", "hwnd": 400, "enabled": True, "bind_id": "other-id"},
        ]
        resolved = resolve_workflow_window_binding(
            workflow_binding,
            windows,
            hwnd_alive=lambda value: value == 400,
        )
        self.assertIsNone(resolved)

    def test_instance_key_uses_launch_args_not_exe_path(self):
        self.assertEqual(_build_instance_key([r"C:\emu\dnplayer.exe", "index=0"]), "index=0")
        self.assertEqual(
            _build_instance_key([r"D:\other\dnplayer.exe", "index=0"]),
            "index=0",
        )
        self.assertEqual(_build_instance_key([r"C:\game\game.exe"]), "")

    def test_hwnd_identity_rejects_recycled_handle(self):
        window_info = {
            "title": "目标",
            "class_name": "AppClass",
            "process_name": "game.exe",
        }
        self.assertFalse(hwnd_matches_identity(0, window_info))

    def test_wgc_desktop_combination_requires_engine_change(self):
        desktop = {"title": "桌面", "hwnd": 0}
        window = {"title": "123123123-2", "hwnd": 329608}
        self.assertTrue(is_desktop_bound_window(desktop))
        self.assertFalse(is_desktop_bound_window(window))
        self.assertTrue(is_wgc_with_desktop_target("wgc", [desktop]))
        self.assertFalse(is_wgc_with_desktop_target("printwindow", [desktop]))
        self.assertFalse(is_wgc_with_desktop_target("wgc", [window]))


if __name__ == "__main__":
    unittest.main()
