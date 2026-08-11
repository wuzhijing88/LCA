from ..parameter_panel_support import *


class ParameterPanelWidgetNumericTypeSelectionMixin:
    def _create_numeric_radio_widget(self, param_def: Dict[str, Any], current_value: Any):
        from PySide6.QtWidgets import QButtonGroup, QRadioButton

        radio_widget = QWidget()
        radio_layout = QVBoxLayout(radio_widget)
        radio_layout.setContentsMargins(0, 0, 0, 0)
        radio_layout.setSpacing(4)

        button_group = QButtonGroup(radio_widget)
        options = param_def.get('options', {})
        if isinstance(options, dict):
            for key, display_text in options.items():
                radio_button = QRadioButton(str(display_text))
                radio_button.setProperty('value', key)
                button_group.addButton(radio_button)
                radio_layout.addWidget(radio_button)
                if key == current_value:
                    radio_button.setChecked(True)
        else:
            for option in options:
                radio_button = QRadioButton(str(option))
                radio_button.setProperty('value', option)
                button_group.addButton(radio_button)
                radio_layout.addWidget(radio_button)
                if option == current_value:
                    radio_button.setChecked(True)

        radio_widget.button_group = button_group
        return radio_widget

    def _create_numeric_choice_widget(self, name: str, param_def: Dict[str, Any], current_value: Any):
        widget = QComboBox(self)
        self._remove_combobox_shadow(widget)
        choices = param_def.get('choices', param_def.get('options', []))
        if isinstance(choices, dict):
            for key, value in choices.items():
                widget.addItem(str(value), key)
            index = widget.findData(current_value)
            if index >= 0:
                widget.setCurrentIndex(index)
        else:
            for i, choice in enumerate(choices):
                choice_str = str(choice)
                widget.addItem(choice_str)
                if choice_str.startswith('=== ') and choice_str.endswith(' ==='):
                    item = widget.model().item(i)
                    if item:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                        font = item.font()
                        font.setBold(True)
                        item.setFont(font)
                        item.setBackground(QColor(240, 240, 240))
                        item.setForeground(QColor(100, 100, 100))
            if current_value is not None:
                index = widget.findText(str(current_value))
                if index >= 0:
                    widget.setCurrentIndex(index)

        widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._apply_force_down_popup(widget)
        widget.currentIndexChanged.connect(
            lambda index, w=widget, n=name: self._handle_numeric_select_changed(index, w, n)
        )
        return widget

    def _handle_numeric_select_changed(self, index: int, widget, name: str):
        new_value = widget.itemData(index) if widget.itemData(index) is not None else widget.currentText()
        if name == 'operation_mode':
            new_value = self._normalize_operation_mode_value(
                new_value,
                fallback_task_type=self.current_task_type or '',
            )
        self._apply_live_parameter_changes({name: new_value})
