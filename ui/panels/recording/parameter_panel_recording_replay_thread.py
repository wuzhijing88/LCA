from ..parameter_panel_support import *
from utils.replay_engine import ReplayEngine


class ParameterPanelReplayThread(QThread):
    finished_signal = Signal()
    result_signal = Signal(bool, str)
    step_changed = Signal(int)

    def __init__(
        self,
        actions_list,
        speed_val,
        loop_val,
        recording_area_val,
        offset_x,
        offset_y,
        recording_mode_val='绝对坐标',
    ):
        super().__init__()
        self.actions = actions_list
        self.speed = speed_val
        self.loop_count = loop_val
        self.recording_area = recording_area_val
        self.window_offset_x = offset_x
        self.window_offset_y = offset_y
        self.recording_mode = recording_mode_val
        self._replay_engine = ReplayEngine()

    def stop(self):
        self._replay_engine.stop()
        logger.info('[回放] 收到停止请求')

    def _emit_step_changed(self, index: int):
        self.step_changed.emit(index)

    def run(self):
        success = False
        result_message = '回放失败或被中断'
        try:
            logger.info('[回放] 使用统一回放引擎')
            success = self._replay_engine.replay(
                actions=self.actions,
                speed=self.speed,
                loop_count=self.loop_count,
                recording_area=self.recording_area,
                window_offset_x=self.window_offset_x,
                window_offset_y=self.window_offset_y,
                precise_timer=None,
                recording_mode=self.recording_mode,
                step_callback=self._emit_step_changed,
            )
            if success:
                logger.info('[回放] 回放完成')
                result_message = '回放完成'
            else:
                logger.warning('[回放] 回放失败或被中断')
                result_message = '回放失败或被中断'
        except Exception as e:
            logger.error(f"[\u56de\u653e] \u5f02\u5e38: {e}", exc_info=True)
            result_message = f'回放异常: {e}'
        finally:
            self.result_signal.emit(success, result_message)
            self.finished_signal.emit()
