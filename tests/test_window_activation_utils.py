import unittest
from unittest import mock

from utils.window_activation_utils import (
    ensure_overlay_ready_for_input,
    schedule_overlay_activation_boost,
    schedule_window_top_boost,
    show_and_activate_overlay,
    show_and_raise_widget,
)


class _DummyOverlay:
    def __init__(self, *, active=True, visible=True):
        self._closing = False
        self._activation_attempts = 0
        self._is_ready_for_input = False
        self._active = active
        self._visible = visible
        self.shown = False

    def show(self):
        self.shown = True
        self._visible = True

    def raise_(self):
        pass

    def activateWindow(self):
        pass

    def setFocus(self):
        pass

    def winId(self):
        return 123

    def isActiveWindow(self):
        return self._active

    def isVisible(self):
        return self._visible

    def _ensure_ready_for_input(self):
        pass


class WindowActivationUtilsTests(unittest.TestCase):
    def test_show_and_raise_widget_shows_then_raises(self):
        overlay = _DummyOverlay(active=True, visible=False)

        self.assertTrue(show_and_raise_widget(overlay, log_prefix='测试部件'))
        self.assertTrue(overlay.shown)

    def test_show_and_activate_overlay_shows_then_activates(self):
        overlay = _DummyOverlay(active=True, visible=False)

        with mock.patch(
            'utils.window_activation_utils.activate_overlay_widget',
            return_value=True,
        ) as activate_overlay_widget:
            self.assertTrue(
                show_and_activate_overlay(overlay, log_prefix='测试覆盖层', focus=True)
            )

        self.assertTrue(overlay.shown)
        activate_overlay_widget.assert_called_once_with(
            overlay,
            log_prefix='测试覆盖层',
            focus=True,
        )

    def test_ensure_overlay_ready_for_input_marks_ready_when_active(self):
        overlay = _DummyOverlay(active=True, visible=True)

        with mock.patch(
            'utils.window_activation_utils.activate_overlay_widget',
            return_value=True,
        ) as activate_overlay_widget:
            ensure_overlay_ready_for_input(
                overlay,
                log_prefix='测试覆盖层',
                ready_message='ready',
                retry_message='retry {attempt}/{max_attempts}',
                exhausted_message='exhausted',
            )

        self.assertTrue(overlay._is_ready_for_input)
        self.assertEqual(overlay._activation_attempts, 0)
        activate_overlay_widget.assert_called_once_with(
            overlay,
            log_prefix='测试覆盖层',
            focus=True,
        )

    def test_ensure_overlay_ready_for_input_schedules_retry_when_inactive(self):
        overlay = _DummyOverlay(active=False, visible=True)
        scheduled = []

        with mock.patch(
            'utils.window_activation_utils.activate_overlay_widget',
            return_value=True,
        ):
            with mock.patch(
                'PySide6.QtCore.QTimer.singleShot',
                side_effect=lambda delay, callback: scheduled.append((delay, callback)),
            ):
                ensure_overlay_ready_for_input(
                    overlay,
                    log_prefix='测试覆盖层',
                    ready_message='ready',
                    retry_message='retry {attempt}/{max_attempts}',
                    exhausted_message='exhausted',
                    retry_delay_ms=321,
                )

        self.assertFalse(overlay._is_ready_for_input)
        self.assertEqual(overlay._activation_attempts, 1)
        self.assertEqual(len(scheduled), 1)
        self.assertEqual(scheduled[0][0], 321)
        self.assertIs(scheduled[0][1].__self__, overlay)
        self.assertIs(scheduled[0][1].__func__, overlay._ensure_ready_for_input.__func__)

    def test_schedule_overlay_activation_boost_schedules_all_intervals(self):
        overlay = _DummyOverlay(active=True, visible=True)
        scheduled = []

        with mock.patch(
            'PySide6.QtCore.QTimer.singleShot',
            side_effect=lambda delay, callback: scheduled.append(delay),
        ):
            schedule_overlay_activation_boost(
                overlay,
                log_prefix='测试覆盖层',
                intervals_ms=(10, 20, 30),
            )

        self.assertEqual(scheduled, [10, 20, 30])

    def test_schedule_window_top_boost_schedules_all_intervals(self):
        scheduled = []

        with mock.patch(
            'PySide6.QtCore.QTimer.singleShot',
            side_effect=lambda delay, callback: scheduled.append(delay),
        ):
            schedule_window_top_boost(123, log_prefix='测试窗口', intervals_ms=(10, 20, 30))

        self.assertEqual(scheduled, [10, 20, 30])


if __name__ == '__main__':
    unittest.main()
