import sys
import unittest
from unittest import mock

from tasks.task_utils import get_recorded_region_binding_mismatch_detail
from ui.selectors.ocr_region_selector import OCRRegionSelectorWidget
from utils.window_coordinate_common import (
    find_region_binding_equivalent_descendant,
    normalize_region_binding_hwnd,
)


class _FakeWin32Gui:
    def __init__(self, windows):
        self._windows = {
            int(hwnd): dict(data)
            for hwnd, data in windows.items()
        }
        self._children = {}
        for hwnd, data in self._windows.items():
            parent_hwnd = int(data.get("parent", 0) or 0)
            if parent_hwnd > 0:
                self._children.setdefault(parent_hwnd, []).append(hwnd)

    def IsWindow(self, hwnd):
        return int(hwnd) in self._windows

    def GetWindowText(self, hwnd):
        return str(self._windows[int(hwnd)].get("title", ""))

    def GetClassName(self, hwnd):
        return str(self._windows[int(hwnd)].get("class", ""))

    def GetClientRect(self, hwnd):
        width, height = self._windows[int(hwnd)].get("client_size", (0, 0))
        return 0, 0, int(width), int(height)

    def ClientToScreen(self, hwnd, point):
        origin_x, origin_y = self._windows[int(hwnd)].get("client_origin", (0, 0))
        return int(origin_x) + int(point[0]), int(origin_y) + int(point[1])

    def GetParent(self, hwnd):
        return int(self._windows[int(hwnd)].get("parent", 0) or 0)

    def EnumChildWindows(self, hwnd, callback, extra):
        for child_hwnd in list(self._children.get(int(hwnd), [])):
            if callback(child_hwnd, extra) is False:
                return
            self.EnumChildWindows(child_hwnd, callback, extra)


def _build_fake_win32(*, include_old_child=True, include_new_child=False, include_other_window=False):
    windows = {
        100: {
            "title": "QQ",
            "class": "Chrome_WidgetWin_1",
            "client_size": (1280, 720),
            "client_origin": (30, 40),
            "parent": 0,
        },
    }
    if include_old_child:
        windows[110] = {
            "title": "Chrome Legacy Window",
            "class": "Chrome_RenderWidgetHostHWND",
            "client_size": (1280, 720),
            "client_origin": (30, 40),
            "parent": 100,
        }
    if include_new_child:
        windows[111] = {
            "title": "Chrome Legacy Window",
            "class": "Chrome_RenderWidgetHostHWND",
            "client_size": (1280, 720),
            "client_origin": (30, 40),
            "parent": 100,
        }
    if include_other_window:
        windows[200] = {
            "title": "Notepad",
            "class": "Notepad",
            "client_size": (900, 600),
            "client_origin": (300, 200),
            "parent": 0,
        }
    return _FakeWin32Gui(windows)


class RegionBindingNormalizationTests(unittest.TestCase):
    def test_normalize_region_binding_promotes_equivalent_parent(self):
        fake_win32 = _build_fake_win32(include_old_child=True)

        with mock.patch.dict(sys.modules, {"win32gui": fake_win32}):
            normalized = normalize_region_binding_hwnd(110)

        self.assertEqual(normalized, (100, "QQ", "Chrome_WidgetWin_1", 1280, 720))

    def test_find_region_binding_equivalent_descendant_matches_recreated_child(self):
        fake_win32 = _build_fake_win32(include_old_child=False, include_new_child=True)

        with mock.patch.dict(sys.modules, {"win32gui": fake_win32}):
            matched_hwnd = find_region_binding_equivalent_descendant(
                100,
                title_hint="Chrome Legacy Window",
                class_hint="Chrome_RenderWidgetHostHWND",
                client_width=1280,
                client_height=720,
            )

        self.assertEqual(matched_hwnd, 111)

    def test_ocr_selector_build_region_binding_info_uses_normalized_hwnd(self):
        fake_win32 = _build_fake_win32(include_old_child=True)

        with mock.patch.dict(sys.modules, {"win32gui": fake_win32}):
            info = OCRRegionSelectorWidget._build_region_binding_info(None, 110)

        self.assertEqual(
            info,
            {
                "region_hwnd": 100,
                "region_window_title": "QQ",
                "region_window_class": "Chrome_WidgetWin_1",
                "region_client_width": 1280,
                "region_client_height": 720,
            },
        )

    def test_task_utils_accepts_equivalent_parent_and_child_binding(self):
        fake_win32 = _build_fake_win32(include_old_child=True)
        params = {
            "region_hwnd": 110,
            "region_window_title": "Chrome Legacy Window",
            "region_window_class": "Chrome_RenderWidgetHostHWND",
            "region_client_width": 1280,
            "region_client_height": 720,
        }

        with mock.patch.dict(sys.modules, {"win32gui": fake_win32}):
            detail = get_recorded_region_binding_mismatch_detail(params, 100)

        self.assertIsNone(detail)

    def test_task_utils_accepts_recreated_child_binding_under_same_parent(self):
        fake_win32 = _build_fake_win32(include_old_child=False, include_new_child=True)
        params = {
            "region_hwnd": 110,
            "region_window_title": "Chrome Legacy Window",
            "region_window_class": "Chrome_RenderWidgetHostHWND",
            "region_client_width": 1280,
            "region_client_height": 720,
        }

        with mock.patch.dict(sys.modules, {"win32gui": fake_win32}):
            detail = get_recorded_region_binding_mismatch_detail(params, 100)

        self.assertIsNone(detail)

    def test_task_utils_still_reports_real_binding_mismatch(self):
        fake_win32 = _build_fake_win32(include_old_child=True, include_other_window=True)
        params = {
            "region_hwnd": 110,
            "region_window_title": "Chrome Legacy Window",
            "region_window_class": "Chrome_RenderWidgetHostHWND",
            "region_client_width": 1280,
            "region_client_height": 720,
        }

        with mock.patch.dict(sys.modules, {"win32gui": fake_win32}):
            detail = get_recorded_region_binding_mismatch_detail(params, 200)

        self.assertIsNotNone(detail)
        self.assertIn("HWND", detail)


if __name__ == "__main__":
    unittest.main()
