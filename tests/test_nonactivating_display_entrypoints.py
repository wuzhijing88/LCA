import unittest
from unittest import mock

import ui.system_parts.dpi_notification_widget as dpi_notification_module
import ui.widgets.custom_title_bar as custom_title_bar_module
import ui.widgets.custom_tooltip as custom_tooltip_module
import ui.widgets.custom_widgets as custom_widgets_module
import ui.widgets.floating_status_window as floating_status_module
import ui.panels.window.parameter_panel_window_activation_main_mixin as _main_activation_module
import ui.panels.window.parameter_panel_window_activation_panel_mixin as _panel_activation_module

ParameterPanelWindowActivationPanelMixin = _panel_activation_module.ParameterPanelWindowActivationPanelMixin
ParameterPanelWindowActivationMainMixin = _main_activation_module.ParameterPanelWindowActivationMainMixin


class _DummyTooltip:
    def __init__(self):
        self.moved_to = None
        self.text = None

    def setText(self, text):
        self.text = text

    def adjustSize(self):
        pass

    def move(self, pos):
        self.moved_to = pos


class _DummyTooltipManager:
    def __init__(self):
        self._tooltip = _DummyTooltip()

    def hide(self):
        pass

    def _clamp_to_screen(self, pos):
        return pos


class _DummyDropdown:
    def __init__(self):
        self._showing_popup = False
        self._items = ['a']
        self._max_visible_items = 5
        self._item_height = 24
        self.popup_frame = mock.Mock()
        self.list_widget = mock.Mock()
        self.display_button = mock.Mock()

    def isVisible(self):
        return True

    def isEnabled(self):
        return True

    def width(self):
        return 120

    def _normalize_popup_layout(self):
        pass

    def _sync_item_widths(self):
        pass


class _DummyActivationPanel(ParameterPanelWindowActivationPanelMixin):
    def __init__(self):
        self._input_focus_protection_active = False
        self._activation_in_progress = False

    def isActiveWindow(self):
        return False

    def _restore_widget_focus(self, widget):
        _ = widget


class _DummyMainActivation(ParameterPanelWindowActivationMainMixin):
    def __init__(self):
        self._snap_to_parent_enabled = True
        self._input_focus_protection_active = False
        self._activation_in_progress = False
        self.parent_window = mock.Mock()
        self.parent_window.isActiveWindow.return_value = False

    def _restore_widget_focus(self, widget):
        _ = widget


class _DummyDpiNotification:
    def __init__(self):
        self.detail_label = mock.Mock()
        self.auto_adjust_btn = mock.Mock()
        self.auto_hide_timer = mock.Mock()
        self.current_window_list = []
        self.current_old_dpi = None
        self.current_new_dpi = None
        self.reset_called = False

    def _reset_ui_state(self):
        self.reset_called = True


class _DummyFloatingWindow:
    def __init__(self):
        self.moves = []
        self.styles = []

    def setStyleSheet(self, style):
        self.styles.append(style)

    def width(self):
        return 100

    def move(self, x, y):
        self.moves.append((x, y))


class _DummyTopmostWindow:
    def __init__(self):
        self._flags = custom_title_bar_module.Qt.WindowType.Widget

    def windowFlags(self):
        return self._flags

    def setWindowFlags(self, flags):
        self._flags = flags


class _DummyTopmostButton:
    def __init__(self):
        self.tooltips = []

    def setToolTip(self, text):
        self.tooltips.append(text)


class _DummyTitleBar:
    def __init__(self):
        self._window_topmost = False
        self.parent_window = _DummyTopmostWindow()
        self.topmost_button = _DummyTopmostButton()


class NonActivatingDisplayEntrypointsTests(unittest.TestCase):
    def test_custom_tooltip_reuses_shared_raise_helper(self):
        manager = _DummyTooltipManager()

        with mock.patch.object(
            custom_tooltip_module,
            'show_and_raise_widget',
        ) as show_and_raise_widget:
            custom_tooltip_module.CustomTooltipManager.show_text(
                manager,
                '提示',
                custom_tooltip_module.QPoint(10, 20),
            )

        show_and_raise_widget.assert_called_once_with(
            manager._tooltip,
            log_prefix='自定义提示',
        )

    def test_custom_dropdown_reuses_shared_raise_helper(self):
        dropdown = _DummyDropdown()
        button_rect = mock.Mock()
        button_rect.bottomLeft.return_value = mock.Mock()
        dropdown.display_button.rect.return_value = button_rect
        dropdown.display_button.mapToGlobal.return_value = mock.Mock()
        dropdown.display_button.width.return_value = 100
        dropdown.list_widget.count.return_value = 1
        dropdown.list_widget.sizeHintForRow.return_value = 20
        dropdown.list_widget.spacing.return_value = 0
        dropdown.list_widget.contentsMargins.return_value = custom_widgets_module.QMargins(0, 0, 0, 0)
        dropdown.list_widget.viewportMargins.return_value = custom_widgets_module.QMargins(0, 0, 0, 0)
        dropdown.list_widget.viewport.return_value.geometry.return_value = mock.Mock()
        dropdown.list_widget.geometry.return_value = mock.Mock()
        dropdown.popup_frame.geometry.return_value = mock.Mock()

        with mock.patch.object(
            custom_widgets_module,
            'show_and_raise_widget',
        ) as show_and_raise_widget:
            custom_widgets_module.CustomDropdown._show_popup(dropdown)

        show_and_raise_widget.assert_called_once_with(
            dropdown.popup_frame,
            log_prefix='自定义下拉弹层',
        )

    def test_parameter_panel_activation_reuses_shared_raise_helper(self):
        panel = _DummyActivationPanel()

        with mock.patch.object(
            _panel_activation_module.QApplication,
            'focusWidget',
            return_value=None,
        ):
            with mock.patch.object(
                _panel_activation_module,
                'show_and_raise_widget',
            ) as show_and_raise_widget:
                panel._smart_activate_parameter_panel()

        show_and_raise_widget.assert_called_once_with(
            panel,
            log_prefix='参数面板激活同步',
        )

    def test_main_window_activation_reuses_shared_raise_helper(self):
        panel = _DummyMainActivation()

        with mock.patch.object(
            _main_activation_module.QApplication,
            'focusWidget',
            return_value=None,
        ):
            with mock.patch.object(
                _main_activation_module,
                'show_and_raise_widget',
            ) as show_and_raise_widget:
                panel._smart_activate_main_window()

        show_and_raise_widget.assert_called_once_with(
            panel.parent_window,
            log_prefix='主窗口激活同步',
        )

    def test_dpi_notification_reuses_shared_raise_helper(self):
        notification = _DummyDpiNotification()

        with mock.patch.object(
            dpi_notification_module,
            'show_and_raise_widget',
        ) as show_and_raise_widget:
            dpi_notification_module.DPINotificationWidget.show_notification(
                notification,
                96,
                144,
                window_list=[{'hwnd': 1}],
                auto_hide_seconds=15,
            )

        self.assertTrue(notification.reset_called)
        show_and_raise_widget.assert_called_once_with(
            notification,
            log_prefix='DPI变化通知',
        )
        notification.auto_hide_timer.start.assert_called_once_with(15000)

    def test_floating_window_reuses_shared_raise_helper(self):
        floating = _DummyFloatingWindow()
        geometry = mock.Mock()
        geometry.isEmpty.return_value = False
        geometry.left.return_value = 10
        geometry.width.return_value = 200
        geometry.top.return_value = 5

        with mock.patch.object(
            floating_status_module,
            'show_and_raise_widget',
        ) as show_and_raise_widget:
            with mock.patch.object(
                floating_status_module,
                'get_available_geometry_for_widget',
                return_value=geometry,
            ):
                floating_status_module.FloatingStatusWindow.show_at_top_center(floating)

        self.assertEqual(floating.moves, [(60, 15)])
        show_and_raise_widget.assert_called_once_with(
            floating,
            log_prefix='浮动状态窗口',
        )

    def test_custom_title_bar_topmost_toggle_reuses_shared_raise_helper(self):
        title_bar = _DummyTitleBar()

        with mock.patch.object(
            custom_title_bar_module,
            'show_and_raise_widget',
        ) as show_and_raise_widget:
            custom_title_bar_module.CustomTitleBar._toggle_topmost(title_bar)

        self.assertTrue(title_bar._window_topmost)
        self.assertIn(
            custom_title_bar_module.Qt.WindowType.WindowStaysOnTopHint,
            title_bar.parent_window.windowFlags(),
        )
        self.assertEqual(title_bar.topmost_button.tooltips, ['取消置顶'])
        show_and_raise_widget.assert_called_once_with(
            title_bar.parent_window,
            log_prefix='标题栏置顶切换',
        )


if __name__ == '__main__':
    unittest.main()
