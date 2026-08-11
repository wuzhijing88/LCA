from ..parameter_panel_support import *


class ParameterPanelWidgetBasicSelectorHintWorkflowCardMixin:
    def _create_workflow_card_selector_widget(self, param_def: Dict[str, Any], current_value: Any):
        widget = QComboBox(self)
        self._remove_combobox_shadow(widget)
        widget.addItem('使用线程默认起点', None)

        target_thread_value = self.current_parameters.get('target_thread')
        for card_id, task_type, custom_name in self._collect_workflow_cards_for_target_thread(target_thread_value):
            if custom_name:
                display_text = f'{custom_name} [{task_type}] (ID: {card_id})'
            else:
                display_text = f'{task_type} (ID: {card_id})'
            widget.addItem(display_text, int(card_id))

        selected_card_id = self._parse_card_id_from_value(current_value)
        if selected_card_id is None:
            selected_card_id = self._parse_card_id_from_value(param_def.get('default'))
        if selected_card_id is not None and selected_card_id >= 0:
            index = widget.findData(int(selected_card_id))
            if index >= 0:
                widget.setCurrentIndex(index)
        return widget
