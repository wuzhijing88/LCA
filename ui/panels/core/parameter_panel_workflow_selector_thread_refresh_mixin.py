from ..parameter_panel_support import *


class ParameterPanelWorkflowSelectorThreadRefreshMixin:
    def _refresh_workflow_card_selector_options(self) -> None:
        target_value: Any = self.current_parameters.get('target_thread')
        target_widget = self._get_value_widget('target_thread')
        if isinstance(target_widget, QComboBox):
            current_data = target_widget.currentData()
            target_value = current_data if current_data is not None else target_widget.currentText()
            self.current_parameters['target_thread'] = target_value

        card_options = self._collect_workflow_cards_for_target_thread(target_value)
        for param_name, widget in self._iter_value_widgets():
            param_def = self.param_definitions.get(param_name, {})
            if param_def.get('widget_hint') != 'workflow_card_selector':
                continue
            if not isinstance(widget, QComboBox):
                continue

            selected_card_id = self._parse_card_id_from_value(widget.currentData())
            widget.blockSignals(True)
            try:
                widget.clear()
                widget.addItem('使用线程默认起点', None)
                for card_id, task_type, custom_name in card_options:
                    if custom_name:
                        display_text = f'{custom_name} [{task_type}] (ID: {card_id})'
                    else:
                        display_text = f'{task_type} (ID: {card_id})'
                    widget.addItem(display_text, int(card_id))

                if selected_card_id is not None and selected_card_id >= 0:
                    index = widget.findData(int(selected_card_id))
                    if index >= 0:
                        widget.setCurrentIndex(index)
            finally:
                widget.blockSignals(False)

    def _on_thread_target_selection_changed(self, param_name: str, widget: QComboBox) -> None:
        selected_value = widget.currentData()
        if selected_value is None:
            selected_value = widget.currentText()
        self._apply_live_parameter_changes(
            {param_name: selected_value},
            refresh_conditional=False,
        )
        self._refresh_workflow_card_selector_options()
