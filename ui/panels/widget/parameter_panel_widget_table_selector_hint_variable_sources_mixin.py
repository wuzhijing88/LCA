from ..parameter_panel_support import *


class ParameterPanelWidgetTableSelectorHintVariableSourcesMixin:
    def _create_variable_sources_table_widget(self, name: str, param_def: Dict[str, Any], current_value: Any):
        import json as json_module
        from ui.dialogs.variable_sources_dialog import VariableSourcesDialog

        table_widget, summary_label, edit_button, hidden_edit = self._create_table_selector_container(
            '已配置 0 个来源',
            '编辑来源',
        )

        sources_cache = self._load_variable_sources_table_value(
            current_value if current_value is not None else param_def.get('default', '[]')
        )
        hidden_edit.setPlainText(json_module.dumps(sources_cache, ensure_ascii=True))
        self.current_parameters[name] = hidden_edit.toPlainText()
        self._update_variable_sources_summary(summary_label, len(sources_cache))

        def _open_sources_dialog():
            nonlocal sources_cache
            card_filter_id = self._get_table_selector_card_filter_id(param_def)
            workflow_filter_id = self._get_table_selector_workflow_filter_id(param_def)
            dialog = VariableSourcesDialog(
                sources_cache,
                self,
                card_id=card_filter_id,
                workflow_id=workflow_filter_id,
            )
            if dialog.exec() == QDialog.DialogCode.Accepted:
                sources_cache = dialog.get_sources()
                hidden_edit.setPlainText(json_module.dumps(sources_cache, ensure_ascii=True))
                self.current_parameters[name] = hidden_edit.toPlainText()
                self._update_variable_sources_summary(summary_label, len(sources_cache))

        edit_button.clicked.connect(_open_sources_dialog)
        self._register_widget(name, hidden_edit)
        return table_widget

    @staticmethod
    def _parse_variable_sources_text(text: str) -> list:
        names = []
        for part in text.replace(';', ',').replace('|', ',').split(','):
            chunk = part.strip()
            if not chunk:
                continue
            for line in chunk.splitlines():
                name = line.strip()
                if name:
                    names.append(name)
        return names

    def _load_variable_sources_table_value(self, value) -> list:
        import json as json_module

        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            try:
                parsed = json_module.loads(value)
                if isinstance(parsed, list):
                    return [str(item).strip() for item in parsed if str(item).strip()]
            except Exception:
                pass
            return self._parse_variable_sources_text(value)
        return []

    @staticmethod
    def _update_variable_sources_summary(summary_label, count: int):
        summary_label.setText(f'已配置 {count} 个来源')
