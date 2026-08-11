from ..parameter_panel_support import *


class ParameterPanelWidgetNumericTypeLineEditMixin:
    def _create_numeric_int_widget(self, param_def: Dict[str, Any], current_value: Any):
        widget = QLineEdit()
        widget.setText(str(int(current_value) if current_value is not None else 0))
        widget.setPlaceholderText('请输入整数')
        from PySide6.QtGui import QIntValidator
        validator = QIntValidator()
        validator.setRange(param_def.get('min', -999999), param_def.get('max', 999999))
        widget.setValidator(validator)
        widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        return widget

    def _create_numeric_float_widget(self, param_def: Dict[str, Any], current_value: Any):
        widget = QLineEdit()
        widget.setText(str(float(current_value) if current_value is not None else 0.0))
        widget.setPlaceholderText('请输入小数')
        from PySide6.QtGui import QDoubleValidator
        validator = QDoubleValidator()
        validator.setRange(
            param_def.get('min', -999999.0),
            param_def.get('max', 999999.0),
            param_def.get('decimals', 2),
        )
        widget.setValidator(validator)
        widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        return widget
