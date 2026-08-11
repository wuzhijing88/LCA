from .parameter_panel_recording_capture_start_mixin import (
    ParameterPanelRecordingCaptureStartMixin,
)
from .parameter_panel_recording_capture_stop_mixin import (
    ParameterPanelRecordingCaptureStopMixin,
)
from .parameter_panel_recording_capture_toggle_mixin import (
    ParameterPanelRecordingCaptureToggleMixin,
)


class ParameterPanelRecordingCaptureRuntimeMixin(
    ParameterPanelRecordingCaptureToggleMixin,
    ParameterPanelRecordingCaptureStartMixin,
    ParameterPanelRecordingCaptureStopMixin,
):
    pass
