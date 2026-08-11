from ..parameter_panel_support import *


class ParameterPanelWidgetMultilineTypeDefaultMixin:
    def _create_multiline_plain_text_widget(self, param_def: Dict[str, Any], current_value: Any):
        widget = QPlainTextEdit()
        widget.setPlainText(str(current_value) if current_value is not None else '')
        custom_height = param_def.get('height', 80)
        widget.setMinimumHeight(custom_height)
        widget.setMaximumHeight(max(custom_height, 200))
        widget.setMinimumWidth(150)
        widget.setFixedHeight(custom_height)
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        placeholder = param_def.get('placeholder', '')
        if placeholder:
            widget.setPlaceholderText(placeholder)
        if param_def.get('readonly', False):
            widget.setReadOnly(True)
        return widget
