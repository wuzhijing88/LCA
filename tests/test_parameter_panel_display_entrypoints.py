import unittest
from unittest import mock

import ui.panels.core.parameter_panel_presentation_mixin as presentation_module
import ui.panels.favorites.parameter_panel_favorites_view_entry_mixin as favorites_module
import ui.panels.media.parameter_panel_media_screenshot_result_mixin as media_result_module
import ui.panels.recording.parameter_panel_recording_capture_finish_mixin as recording_finish_module
import ui.panels.selector.parameter_panel_selector_picker_result_mixin as picker_result_module


ParameterPanelPresentationMixin = presentation_module.ParameterPanelPresentationMixin
ParameterPanelMediaScreenshotResultMixin = media_result_module.ParameterPanelMediaScreenshotResultMixin
ParameterPanelFavoritesViewEntryMixin = favorites_module.ParameterPanelFavoritesViewEntryMixin
ParameterPanelRecordingCaptureFinishMixin = recording_finish_module.ParameterPanelRecordingCaptureFinishMixin
ParameterPanelSelectorPickerResultMixin = picker_result_module.ParameterPanelSelectorPickerResultMixin


class _DummyCloseButton:
    def resetStyle(self):
        pass


class _DummySignal:
    def __init__(self):
        self.calls = []

    def emit(self, value):
        self.calls.append(value)


class _DummyPresentationPanel(ParameterPanelPresentationMixin):
    def __init__(self):
        self.title_input = mock.Mock()
        self.close_button = _DummyCloseButton()
        self.current_card_id = 1
        self.current_task_type = '任务'
        self.current_custom_name = None
        self.runtime_parameters = {}

    def _clear_content(self):
        pass

    def _create_parameter_widgets(self):
        pass

    def refresh_runtime_parameters(self, card_id):
        _ = card_id

    def _position_panel(self):
        pass


class _DummyMediaPanel(ParameterPanelMediaScreenshotResultMixin):
    def __init__(self):
        self.main_window = object()


class _DummyFavoritesPanel(ParameterPanelFavoritesViewEntryMixin):
    def __init__(self):
        self._favorites = [{'filepath': 'a.json', 'checked': True}]
        self.favorites_opened = _DummySignal()
        self.title_input = mock.Mock()
        self._favorites_mode = False

    def _set_footer_buttons_visible(self, visible):
        _ = visible

    def _clear_content(self):
        pass

    def _load_favorites_data(self):
        pass

    def _create_favorites_ui(self):
        pass

    def _update_favorites_title(self):
        pass

    def _position_panel(self):
        pass


class _DummyRecordingFinishPanel(ParameterPanelRecordingCaptureFinishMixin):
    def __init__(self):
        self._recording_panel = mock.Mock()
        self._was_panel_visible = True
        self._main_window = mock.Mock()
        self._was_main_window_visible = True
        self._recording_active = True
        self._recording_state_changing = True
        self.current_parameters = {}
        self.widgets = {}
        self.parameters_changed = mock.Mock()
        self.current_card_id = 1


class _DummyPickerResultPanel(ParameterPanelSelectorPickerResultMixin):
    def __init__(self):
        self.main_window = mock.Mock()
        self.button_state = None

    def _set_element_picker_button_state(self, state):
        self.button_state = state


class ParameterPanelDisplayEntrypointsTests(unittest.TestCase):
    def test_show_parameter_panel_window_reuses_shared_raise_helper(self):
        panel = _DummyPresentationPanel()

        with mock.patch.object(
            presentation_module,
            'show_and_raise_widget',
        ) as show_and_raise_widget:
            panel._show_parameter_panel_window(1, '任务', None)

        show_and_raise_widget.assert_called_once_with(
            panel,
            log_prefix='参数面板展示',
        )

    def test_restore_windows_after_screenshot_reuses_shared_helpers(self):
        panel = _DummyMediaPanel()

        with mock.patch.object(
            media_result_module,
            'show_and_raise_widget',
        ) as show_and_raise_widget:
            with mock.patch.object(
                media_result_module,
                'show_and_activate_overlay',
            ) as show_and_activate_overlay:
                panel._restore_windows_after_screenshot()

        show_and_raise_widget.assert_called_once_with(
            panel.main_window,
            log_prefix='主窗口恢复',
        )
        show_and_activate_overlay.assert_called_once_with(
            panel,
            log_prefix='参数面板恢复',
            focus=True,
        )

    def test_show_favorites_reuses_shared_raise_helper(self):
        panel = _DummyFavoritesPanel()

        with mock.patch.object(
            favorites_module,
            'show_and_raise_widget',
        ) as show_and_raise_widget:
            with mock.patch.object(
                favorites_module.QTimer,
                'singleShot',
            ) as single_shot:
                panel.show_favorites()

        show_and_raise_widget.assert_called_once_with(
            panel,
            log_prefix='收藏面板展示',
        )
        self.assertEqual(single_shot.call_count, 1)

    def test_recording_finish_restores_windows_via_shared_helpers(self):
        panel = _DummyRecordingFinishPanel()

        with mock.patch.object(
            recording_finish_module,
            'show_and_activate_overlay',
        ) as show_and_activate_overlay:
            with mock.patch.object(
                recording_finish_module,
                'show_and_raise_widget',
            ) as show_and_raise_widget:
                panel._on_recording_finished([])

        panel._recording_panel.stop_recording.assert_called_once_with()
        show_and_activate_overlay.assert_called_once_with(
            panel,
            log_prefix='参数面板恢复',
            focus=True,
        )
        show_and_raise_widget.assert_called_once_with(
            panel._main_window,
            log_prefix='主窗口恢复',
        )

    def test_picker_restore_reuses_shared_window_launcher(self):
        panel = _DummyPickerResultPanel()

        with mock.patch.object(
            picker_result_module,
            'show_and_activate_overlay',
        ) as show_and_activate_overlay:
            panel._restore_picker_ui_state()

        panel.main_window.showNormal.assert_called_once_with()
        show_and_activate_overlay.assert_called_once_with(
            panel.main_window,
            log_prefix='元素拾取主窗口恢复',
            focus=True,
        )
        self.assertFalse(panel.button_state)


if __name__ == '__main__':
    unittest.main()
