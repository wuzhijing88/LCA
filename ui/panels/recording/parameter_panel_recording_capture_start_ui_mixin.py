from ..parameter_panel_support import *


class ParameterPanelRecordingCaptureStartUiMixin:
    def _prepare_recording_widgets_for_active_state(self):
        control_widget = self.widgets.get('record_control')
        if control_widget:
            control_widget.setText('停止录制')
            control_widget.setProperty('class', 'danger')
            control_widget.setEnabled(True)

        replay_widget = self.widgets.get('replay_control')
        if replay_widget:
            replay_widget.setEnabled(False)
            logger.info('录制状态下已禁用回放按钮')

        edit_widget = self.widgets.get('edit_actions')
        if edit_widget:
            edit_widget.setEnabled(False)
            logger.info('录制状态下已禁用步骤编辑按钮')

    def _hide_windows_for_recording_capture(self):
        self._was_panel_visible = self.isVisible()
        if self._was_panel_visible:
            self.hide()
            logger.info('已隐藏参数面板')

        self._main_window = None
        if self.parent_window:
            self._main_window = self.parent_window
            self._was_main_window_visible = self._main_window.isVisible()
            if self._was_main_window_visible:
                self._main_window.hide()
                logger.info('已隐藏主窗口')

    def _show_recording_control_panel(self):
        try:
            from ui.recording_parts.recording_control_panel import RecordingControlPanel

            logger.info('准备创建录制控制浮窗...')
            self._recording_panel = RecordingControlPanel()
            self._recording_panel.stop_requested.connect(self._stop_recording)
            if hasattr(self._record_thread, 'step_count_updated'):
                self._record_thread.step_count_updated.connect(self._recording_panel.update_step_count)
            logger.info('浮窗已创建，准备启动...')
            self._recording_panel.start_recording()
            logger.info('录制控制浮窗已启动')
        except Exception as error:
            logger.error(f'创建录制控制浮窗失败: {error}', exc_info=True)
