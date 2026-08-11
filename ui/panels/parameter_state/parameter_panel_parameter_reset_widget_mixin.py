from ..parameter_panel_support import *


class ParameterPanelParameterResetWidgetMixin:

    def _reset_widget_to_default(self, widget, default_value, param_def):
        if isinstance(widget, QCheckBox):
            widget.setChecked(bool(default_value) if default_value is not None else False)
        elif isinstance(widget, QSpinBox):
            widget.setValue(int(default_value) if default_value is not None else 0)
        elif isinstance(widget, QDoubleSpinBox):
            widget.setValue(float(default_value) if default_value is not None else 0.0)
        elif isinstance(widget, QLineEdit):
            widget.clear() if (default_value is None or default_value == "") else widget.setText(str(default_value))
        elif isinstance(widget, (QPlainTextEdit, QTextEdit)):
            widget.clear() if (default_value is None or default_value == "") else widget.setPlainText(str(default_value))
        elif isinstance(widget, QComboBox):
            self._reset_combobox_to_default(widget, default_value, param_def)
        elif isinstance(widget, QSlider):
            widget.setValue(int(default_value) if default_value is not None else 0)
        elif isinstance(widget, QListWidget):
            widget.clear()
            if widget.property("raw_color_data") is not None:
                widget.setProperty("raw_color_data", "")
        elif hasattr(widget, 'button_group'):
            if default_value is not None:
                for button in widget.button_group.buttons():
                    if button.text() == str(default_value):
                        button.setChecked(True)
                        break
        elif hasattr(widget, 'clear_colors'):
            widget.clear_colors()
        elif hasattr(widget, 'clear'):
            try:
                widget.clear()
            except Exception:
                pass

    def _reset_combobox_to_default(self, combo_widget, default_value, param_def):
        current_count = combo_widget.count()
        initial_options = param_def.get('options', [])
        if initial_options and current_count != len(initial_options):
            combo_widget.clear()
            combo_widget.addItems(initial_options)

        if default_value is not None:
            index = combo_widget.findData(default_value)
            if index >= 0:
                combo_widget.setCurrentIndex(index)
            else:
                idx = combo_widget.findText(str(default_value))
                combo_widget.setCurrentIndex(idx if idx >= 0 else 0)
        else:
            combo_widget.setCurrentIndex(0)
