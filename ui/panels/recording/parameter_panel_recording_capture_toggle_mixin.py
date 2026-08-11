from ..parameter_panel_support import *


class ParameterPanelRecordingCaptureToggleMixin:
    def _toggle_recording(self):
            """切换录制状态（开始/停止） - 用于按钮点击"""
            if hasattr(self, '_recording_active') and self._recording_active:
                # 正在录制，点击停止 - 停止操作不受防抖限制
                logger.info("按钮点击: 停止录制")
                self._stop_recording()
            else:
                # 未录制，点击开始 - 开始操作需要防抖
                if hasattr(self, '_recording_state_changing') and self._recording_state_changing:
                    logger.warning("录制状态正在转换中，忽略开始录制请求")
                    return
                logger.info("按钮点击: 开始录制")
                self._start_recording()
