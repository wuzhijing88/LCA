from ..parameter_panel_support import *


class ParameterPanelRecordingCaptureStartStateMixin:
    def _begin_recording_start_transition(self):
        self._recording_state_changing = True
        QTimer.singleShot(3000, lambda: setattr(self, '_recording_state_changing', False))
