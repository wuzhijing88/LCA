from ..parameter_panel_support import *


class ParameterPanelRecordingCaptureStopMixin:
    def _stop_recording(self):
            """停止录制"""
            try:
                logger.info("按钮/快捷键触发:停止录制")
    
                if self._record_thread and self._record_thread.isRunning():
                    self._record_thread.stop()
                    # 注意：_recording_active 会在 _on_recording_finished 回调中设置为 False
                else:
                    # 录制线程不存在或已停止，直接清理状态
                    self._recording_active = False
                    self._recording_state_changing = False
    
            except Exception as e:
                # 发生异常时也要清除状态标志
                self._recording_state_changing = False
                self._recording_active = False
                logger.error(f"停止录制失败: {e}", exc_info=True)
