from ..parameter_panel_support import *


class ParameterPanelWidgetTableSelectorHintSharedMixin:
    @staticmethod
    def _normalize_table_selector_card_id(value):
        if value in (None, '', '全部'):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _get_table_selector_card_filter_id(self, param_def: Dict[str, Any]):
        card_param = param_def.get('card_filter_param')
        if not card_param:
            return None
        return self._normalize_table_selector_card_id(self.current_parameters.get(card_param))

    def _get_table_selector_workflow_filter_id(self, param_def: Dict[str, Any]):
        workflow_param = param_def.get('workflow_filter_param')
        if not workflow_param:
            return None
        value = self.current_parameters.get(workflow_param)
        if value in (None, '', '当前工作流'):
            return None
        if value in ('全局变量', 'global'):
            return 'global'
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _create_table_selector_container(summary_text: str, button_text: str):
        table_widget = QWidget()
        table_layout = QHBoxLayout(table_widget)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(8)

        summary_label = QLabel(summary_text)
        edit_button = ResponsiveButton(button_text)
        edit_button.setProperty('class', 'primary')

        hidden_edit = QPlainTextEdit()
        hidden_edit.setVisible(False)

        table_layout.addWidget(summary_label, 1)
        table_layout.addWidget(edit_button, 0)
        table_layout.addWidget(hidden_edit)
        return table_widget, summary_label, edit_button, hidden_edit
