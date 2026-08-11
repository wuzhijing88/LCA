from .parameter_panel_recording_window_target_mixin import (
    ParameterPanelRecordingWindowTargetMixin,
)
from ..parameter_panel_support import *
from utils.window_activation_utils import resolve_replay_window_offsets_from_config


class ParameterPanelRecordingReplayStartWindowMixin(ParameterPanelRecordingWindowTargetMixin):
    _REPLAY_WINDOW_LOG_PREFIX = '回放'

    def _resolve_replay_window_offsets(self, recording_area: str):
        return resolve_replay_window_offsets_from_config(
            recording_area,
            log_prefix=self._REPLAY_WINDOW_LOG_PREFIX,
        )
