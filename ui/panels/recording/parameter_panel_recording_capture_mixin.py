from .parameter_panel_recording_capture_editor_mixin import (
    ParameterPanelRecordingCaptureEditorMixin,
)
from .parameter_panel_recording_capture_finish_mixin import (
    ParameterPanelRecordingCaptureFinishMixin,
)
from .parameter_panel_recording_capture_runtime_mixin import (
    ParameterPanelRecordingCaptureRuntimeMixin,
)


class ParameterPanelRecordingCaptureMixin(
    ParameterPanelRecordingCaptureRuntimeMixin,
    ParameterPanelRecordingCaptureEditorMixin,
    ParameterPanelRecordingCaptureFinishMixin,
):
    pass
