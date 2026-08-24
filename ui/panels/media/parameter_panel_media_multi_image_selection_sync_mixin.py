from ..parameter_panel_support import *


class ParameterPanelMediaMultiImageSelectionSyncMixin:
    def _sync_multi_image_text_edit(self, text_edit: QTextEdit, new_text: str) -> None:
        text_edit.setPlainText(new_text)

    def _sync_multi_image_parameter_value(self, param_name: str, new_text: str, emit_signal: bool = False) -> None:
        self.current_parameters[param_name] = new_text
        if emit_signal and self.current_card_id is not None:
            self.parameters_changed.emit(self.current_card_id, {param_name: new_text})
