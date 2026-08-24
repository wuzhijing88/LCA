from ..parameter_panel_support import *


class ParameterPanelRecordingReplayRuntimeMixin:
    _REPLAY_BUTTON_DEFAULT = '测试回放'
    _REPLAY_BUTTON_RUNNING = '停止回放'
    _REPLAY_BUTTON_STOPPING = '正在停止...'

    def _toggle_replay(self):
        if getattr(self, '_replay_active', False):
            self._stop_replay()
        else:
            self._start_replay()

    def _stop_replay(self):
        logger.info('用户请求停止回放')
        thread = getattr(self, '_replay_thread', None)
        if not thread or not thread.isRunning():
            return
        thread.stop()
        logger.info('已发送回放停止信号')
        self._set_replay_button_stopping_state()

    def _set_replay_button_running_state(self):
        replay_widget = self.widgets.get('replay_control')
        if replay_widget:
            replay_widget.setText(self._REPLAY_BUTTON_RUNNING)
            replay_widget.setProperty('class', 'danger')
            replay_widget.setEnabled(True)

    def _set_replay_button_stopping_state(self):
        replay_widget = self.widgets.get('replay_control')
        if replay_widget:
            replay_widget.setText(self._REPLAY_BUTTON_STOPPING)
            replay_widget.setEnabled(False)

    def _restore_replay_button_default_state(self):
        replay_widget = self.widgets.get('replay_control')
        if not replay_widget:
            return
        replay_widget.setProperty('class', 'primary')
        action_count = self._get_recorded_action_count()
        if action_count > 0:
            replay_widget.setText(f"测试回放 ({action_count}个操作)")
        else:
            replay_widget.setText(self._REPLAY_BUTTON_DEFAULT)
        replay_widget.setEnabled(True)

    @Slot()
    def _on_replay_finished(self):
        try:
            self._replay_active = False
            self._restore_replay_button_default_state()
            logger.info('回放完成，状态标志已清除')
        except Exception as e:
            logger.error(f"处理回放完成失败: {e}", exc_info=True)
            self._replay_active = False

    @Slot()
    def _on_replay_thread_finished(self):
        thread = getattr(self, '_replay_thread', None)
        if not thread:
            return
        self._replay_thread = None
        try:
            thread.deleteLater()
        except RuntimeError:
            pass
