from .parameter_panel_recording_hotkey_control_mixin import (
    ParameterPanelRecordingHotkeyControlMixin,
)
from .parameter_panel_recording_hotkey_record_mixin import (
    ParameterPanelRecordingHotkeyRecordMixin,
)
from .parameter_panel_recording_hotkey_replay_mixin import (
    ParameterPanelRecordingHotkeyReplayMixin,
)


class ParameterPanelRecordingHotkeyMixin(
    ParameterPanelRecordingHotkeyControlMixin,
    ParameterPanelRecordingHotkeyRecordMixin,
    ParameterPanelRecordingHotkeyReplayMixin,
):
    pass
