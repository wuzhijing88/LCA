import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock


def _load_module(module_name: str, relative_path: str):
    module_path = Path(__file__).resolve().parents[1] / relative_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


_main_window_lookup_module = _load_module(
    'tests._main_window_window_binding_lookup_mixin',
    'ui/main_window_parts/main_window_window_binding_lookup_mixin.py',
)
_global_settings_lookup_module = _load_module(
    'tests._global_settings_dialog_window_lookup_mixin',
    'ui/global_settings_parts/global_settings_dialog_window_lookup_mixin.py',
)

MainWindowWindowBindingLookupMixin = _main_window_lookup_module.MainWindowWindowBindingLookupMixin
GlobalSettingsDialogWindowLookupMixin = _global_settings_lookup_module.GlobalSettingsDialogWindowLookupMixin


class _DummyMainWindowLookup(MainWindowWindowBindingLookupMixin):
    def __init__(self):
        self.bound_windows = [{'title': '测试窗口', 'hwnd': 202}]


class _DummyGlobalSettingsLookup(GlobalSettingsDialogWindowLookupMixin):
    def __init__(self):
        self.bound_windows = [{'title': '测试窗口', 'hwnd': 101}]

class WindowLookupEntrypointsTests(unittest.TestCase):
    def test_main_window_lookup_reuses_shared_exact_match_resolver(self):
        host = _DummyMainWindowLookup()

        with mock.patch.object(
            _main_window_lookup_module,
            'PYWIN32_AVAILABLE',
            True,
        ):
            with mock.patch.object(
                _main_window_lookup_module,
                'win32gui',
                object(),
            ):
                with mock.patch.object(
                    _main_window_lookup_module,
                    'find_all_exact_window_hwnds',
                    return_value=[101, 202],
                ) as find_all_exact_window_hwnds:
                    with mock.patch.object(
                        _main_window_lookup_module,
                        'resolve_exact_window_match',
                        return_value=202,
                    ) as resolve_exact_window_match:
                        self.assertEqual(host._find_window_by_title('测试窗口'), 202)

        find_all_exact_window_hwnds.assert_called_once_with('测试窗口')
        resolve_exact_window_match.assert_called_once_with(
            '测试窗口',
            [101, 202],
            preferred_hwnds=[202],
            prefer_preferred=True,
        )

    def test_global_settings_lookup_falls_back_to_shared_child_search(self):
        host = _DummyGlobalSettingsLookup()

        with mock.patch.object(
            _global_settings_lookup_module,
            'find_all_exact_window_hwnds',
            return_value=[],
        ) as find_all_exact_window_hwnds:
            with mock.patch.object(
                _global_settings_lookup_module,
                'find_window_with_parent_info',
                return_value=(789, True, 456),
            ) as find_window_with_parent_info:
                self.assertEqual(host._find_window_handle('测试窗口'), 789)

        find_all_exact_window_hwnds.assert_called_once_with('测试窗口')
        find_window_with_parent_info.assert_called_once_with('测试窗口')

if __name__ == '__main__':
    unittest.main()
