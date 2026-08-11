from ..parameter_panel_support import *


class ParameterPanelWidgetMultilineTypeTemplatePresetMixin:
    def _create_multiline_template_preset_widget(self, name: str, param_def: Dict[str, Any], current_value: Any):
        template_widget = QWidget()
        template_layout = QVBoxLayout(template_widget)
        template_layout.setContentsMargins(0, 0, 0, 0)
        template_layout.setSpacing(6)

        text_edit = QPlainTextEdit()
        text_edit.setPlainText(str(current_value) if current_value is not None else '')
        custom_height = param_def.get('height', 80)
        text_edit.setMinimumHeight(custom_height)
        text_edit.setMaximumHeight(max(custom_height, 200))
        text_edit.setMinimumWidth(150)
        text_edit.setFixedHeight(custom_height)
        text_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        placeholder = param_def.get('placeholder', '')
        if placeholder:
            text_edit.setPlaceholderText(placeholder)
        if param_def.get('readonly', False):
            text_edit.setReadOnly(True)

        preset_combo = QComboBox(self)
        preset_combo.setObjectName('templatePresetCombo')
        self._remove_combobox_shadow(preset_combo)
        preset_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        preset_combo.setMinimumHeight(30)

        presets = param_def.get('template_presets', []) or []
        if not isinstance(presets, list):
            presets = []
        for item in presets:
            label_text = ''
            value_text = ''
            if isinstance(item, dict):
                label_text = str(item.get('label', '') or '').strip()
                value_text = str(item.get('value', '') or '').strip()
            else:
                value_text = str(item or '').strip()
                label_text = value_text
            if not label_text or not value_text:
                continue
            preset_combo.addItem(label_text, value_text)

        insert_button = ResponsiveButton('插入预设')
        insert_button.setObjectName('templatePresetInsertButton')
        insert_button.setProperty('class', 'primary')
        insert_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        insert_button.setMinimumHeight(30)
        insert_button.clicked.connect(lambda: self._insert_template_preset_text(text_edit, preset_combo))

        template_layout.addWidget(text_edit)
        template_layout.addWidget(preset_combo)
        template_layout.addWidget(insert_button)

        self._register_widget(name, text_edit)
        return template_widget

    @staticmethod
    def _insert_template_preset_text(text_edit, preset_combo):
        preset_value = preset_combo.currentData()
        if preset_value is None:
            preset_value = preset_combo.currentText()
        snippet = str(preset_value or '').strip()
        if not snippet:
            return
        if text_edit.toPlainText().strip():
            text_edit.appendPlainText(snippet)
        else:
            text_edit.setPlainText(snippet)
        text_edit.setFocus()
