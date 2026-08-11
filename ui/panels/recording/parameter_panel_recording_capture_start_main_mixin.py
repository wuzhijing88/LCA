from ..parameter_panel_support import *


class ParameterPanelRecordingCaptureStartMainMixin:
    def _start_recording(self):
        """启动录制"""
        try:
            self._begin_recording_start_transition()
            logger.info('快捷键触发:开始录制')

            options = self._get_capture_recording_options()
            recording_area, window_rect, abort_start = self._resolve_capture_window_context(
                options['recording_area']
            )
            if abort_start:
                return

            options['recording_area'] = recording_area
            self._prepare_recording_widgets_for_active_state()
            self._start_recording_capture_thread(options, window_rect)
            self._hide_windows_for_recording_capture()
            self._show_recording_control_panel()
        except Exception as error:
            logger.error(f'启动录制失败: {error}', exc_info=True)
            QMessageBox.critical(self, '错误', f'启动录制失败: {error}')
        finally:
            self._recording_state_changing = False
