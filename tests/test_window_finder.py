import unittest
from unittest import mock

from utils.window_finder import (
    WindowFinder,
    find_all_exact_window_hwnds,
    find_unique_exact_window_hwnd,
    find_window_with_parent_info,
    list_all_windows,
    resolve_exact_window_match,
    resolve_unique_window_hwnd,
    sanitize_window_lookup_title,
)


class WindowFinderTests(unittest.TestCase):
    def test_resolve_unique_window_hwnd_normalizes_exact_match(self):
        with mock.patch(
            'utils.window_finder.find_unique_exact_window_hwnd',
            return_value=123,
        ) as find_unique_exact_window_hwnd:
            with mock.patch(
                'utils.window_finder.normalize_window_hwnd',
                return_value=(456, '测试窗口'),
            ) as normalize_window_hwnd:
                self.assertEqual(resolve_unique_window_hwnd('测试窗口'), 456)

        find_unique_exact_window_hwnd.assert_called_once_with('测试窗口')
        normalize_window_hwnd.assert_called_once_with(123, title_hint='测试窗口')

    def test_resolve_unique_window_hwnd_returns_none_when_unavailable(self):
        with mock.patch(
            'utils.window_finder.find_unique_exact_window_hwnd',
            return_value=None,
        ):
            with mock.patch(
                'utils.window_finder.normalize_window_hwnd',
                return_value=(None, ''),
            ):
                self.assertIsNone(resolve_unique_window_hwnd('不存在窗口'))

    def test_find_all_exact_window_hwnds_enumerates_visible_exact_matches(self):
        def _enum_windows(callback, windows):
            callback(101, windows)
            callback(202, windows)

        with mock.patch('utils.window_finder.win32gui.IsWindowVisible', return_value=True):
            with mock.patch(
                'utils.window_finder.win32gui.GetWindowText',
                side_effect=lambda hwnd: '测试窗口' if hwnd == 101 else '其他窗口',
            ):
                with mock.patch(
                    'utils.window_finder.win32gui.EnumWindows',
                    side_effect=_enum_windows,
                ):
                    self.assertEqual(find_all_exact_window_hwnds('测试窗口'), [101])

    def test_find_unique_exact_window_hwnd_returns_unique_match(self):
        with mock.patch(
            'utils.window_finder.find_all_exact_window_hwnds',
            return_value=[303],
        ):
            self.assertEqual(find_unique_exact_window_hwnd('测试窗口'), 303)

    def test_window_finder_compat_wrapper_reuses_top_level_helpers(self):
        with mock.patch(
            'utils.window_finder.find_unique_exact_window_hwnd',
            return_value=303,
        ) as find_unique_exact_window_hwnd:
            with mock.patch(
                'utils.window_finder.find_all_exact_window_hwnds',
                return_value=[101, 202],
            ) as find_all_exact_window_hwnds:
                with mock.patch(
                    'utils.window_finder.list_all_windows',
                    return_value=[{'hwnd': 1, 'title': '测试窗口'}],
                ) as list_all_windows:
                    self.assertEqual(WindowFinder.find_window('测试窗口'), 303)
                    self.assertEqual(WindowFinder.find_all_windows('测试窗口'), [101, 202])
                    self.assertEqual(
                        WindowFinder.list_all_windows(),
                        [{'hwnd': 1, 'title': '测试窗口'}],
                    )

        find_unique_exact_window_hwnd.assert_called_once_with('测试窗口')
        find_all_exact_window_hwnds.assert_called_once_with('测试窗口')
        list_all_windows.assert_called_once_with()

    def test_resolve_exact_window_match_prefers_unique_preferred_hwnd(self):
        hwnd = resolve_exact_window_match(
            '测试窗口',
            [101, 202],
            preferred_hwnds=[202],
            prefer_preferred=True,
        )

        self.assertEqual(hwnd, 202)

    def test_resolve_exact_window_match_prefers_unique_unbound_hwnd(self):
        hwnd = resolve_exact_window_match(
            '测试窗口',
            [101, 202],
            preferred_hwnds=[101],
            prefer_unpreferred=True,
        )

        self.assertEqual(hwnd, 202)

    def test_find_window_with_parent_info_does_not_fallback_when_exact_matches_ambiguous(self):
        with mock.patch(
            'utils.window_finder.find_all_exact_window_hwnds',
            return_value=[101, 202],
        ):
            with mock.patch(
                'utils.window_finder.win32gui.EnumWindows',
            ) as enum_windows:
                self.assertEqual(
                    find_window_with_parent_info('测试窗口'),
                    (None, False, None),
                )

        enum_windows.assert_not_called()

    def test_sanitize_window_lookup_title_strips_known_annotations(self):
        self.assertEqual(
            sanitize_window_lookup_title('测试窗口 [RenderWindow] (HWND: 123456)'),
            '测试窗口',
        )


if __name__ == '__main__':
    unittest.main()
