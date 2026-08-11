from ..parameter_panel_support import *
from .parameter_panel_recording_replay_thread import ParameterPanelReplayThread


class ParameterPanelRecordingReplayStartExecutionMixin:
    def _start_replay(self):
        logger.info('开始回放操作')
        if not self._can_start_replay():
            return

        try:
            payload = self._get_recorded_actions_payload_or_warn()
            if payload is None:
                return

            window_offset_x, window_offset_y = self._resolve_replay_window_offsets(payload['recording_area'])
            if window_offset_x is None or window_offset_y is None:
                self._show_replay_message(
                    QMessageBox.Icon.Warning,
                    '提示',
                    '无法进行窗口回放，请检查绑定窗口配置或目标窗口状态',
                )
                return

            speed, loop_count = self._resolve_replay_runtime_options()
            self._set_replay_button_running_state()
            self._start_replay_thread(
                payload['actions'],
                speed,
                loop_count,
                payload['recording_area'],
                window_offset_x,
                window_offset_y,
                payload['recording_mode'],
            )
        except Exception as e:
            logger.error(f"启动回放失败: {e}", exc_info=True)
            self._show_replay_message(QMessageBox.Icon.Critical, '错误', f"启动回放失败: {e}")
            self._replay_active = False
            self._restore_replay_button_default_state()

    def _can_start_replay(self) -> bool:
        if getattr(self, '_replay_active', False):
            logger.warning('回放正在进行中，禁止重复调用')
            return False
        if getattr(self, '_recording_active', False):
            logger.warning('录制过程中不能使用回放功能')
            return False
        return True

    def _resolve_replay_runtime_options(self):
        speed = float(self.current_parameters.get('speed', 1.0))
        loop_count_raw = self.current_parameters.get('loop_count', 1)
        loop_count = int(loop_count_raw) if loop_count_raw is not None else 1
        if loop_count <= 0:
            loop_count = 1
        logger.info(
            f"[测试回放] 回放参数: speed={speed}, loop_count={loop_count}, raw={loop_count_raw}"
        )
        return speed, loop_count

    def _start_replay_thread(
        self,
        actions,
        speed,
        loop_count,
        recording_area,
        window_offset_x,
        window_offset_y,
        recording_mode,
    ):
        self._replay_thread = ParameterPanelReplayThread(
            actions,
            speed,
            loop_count,
            recording_area,
            window_offset_x,
            window_offset_y,
            recording_mode,
        )
        self._replay_thread.finished_signal.connect(self._on_replay_finished)
        self._replay_thread.finished.connect(self._on_replay_thread_finished)
        self._replay_active = True
        self._replay_thread.start()
        logger.info('回放线程已启动，回放状态标志已设置')
