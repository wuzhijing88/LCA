from .parameter_panel_recording_capture_mixin import ParameterPanelRecordingCaptureMixin
from .parameter_panel_recording_hotkey_mixin import ParameterPanelRecordingHotkeyMixin
from .parameter_panel_recording_replay_mixin import ParameterPanelRecordingReplayMixin


class ParameterPanelRecordingMixin(
    ParameterPanelRecordingHotkeyMixin,
    ParameterPanelRecordingCaptureMixin,
    ParameterPanelRecordingReplayMixin,
):
    pass
