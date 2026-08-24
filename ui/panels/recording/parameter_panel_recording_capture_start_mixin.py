from .parameter_panel_recording_capture_start_config_mixin import (
    ParameterPanelRecordingCaptureStartConfigMixin,
)
from .parameter_panel_recording_capture_start_main_mixin import (
    ParameterPanelRecordingCaptureStartMainMixin,
)
from .parameter_panel_recording_capture_start_thread_mixin import (
    ParameterPanelRecordingCaptureStartThreadMixin,
)
from .parameter_panel_recording_capture_start_ui_mixin import (
    ParameterPanelRecordingCaptureStartUiMixin,
)
from .parameter_panel_recording_capture_start_state_mixin import (
    ParameterPanelRecordingCaptureStartStateMixin,
)
from .parameter_panel_recording_window_target_mixin import (
    ParameterPanelRecordingWindowTargetMixin,
)


class ParameterPanelRecordingCaptureStartMixin(
    ParameterPanelRecordingWindowTargetMixin,
    ParameterPanelRecordingCaptureStartStateMixin,
    ParameterPanelRecordingCaptureStartConfigMixin,
    ParameterPanelRecordingCaptureStartUiMixin,
    ParameterPanelRecordingCaptureStartThreadMixin,
    ParameterPanelRecordingCaptureStartMainMixin,
):
    pass
