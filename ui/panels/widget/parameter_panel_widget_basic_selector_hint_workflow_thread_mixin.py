from ..parameter_panel_support import *


class ParameterPanelWidgetBasicSelectorHintWorkflowThreadMixin:
    def _create_thread_target_selector_widget(self, name: str, param_def: Dict[str, Any], current_value: Any):
        widget = QComboBox(self)
        self._remove_combobox_shadow(widget)
        widget.addItem('当前线程', '当前线程')
        widget.addItem('全部线程', '全部线程')

        start_cards = [
            item for item in self._collect_workflow_cards_for_selector() if is_thread_start_task_type(item[1])
        ]
        for idx, (card_id, _task_type, custom_name) in enumerate(start_cards, 1):
            thread_label = custom_name.strip() if custom_name else ''
            if not thread_label or thread_label == THREAD_START_TASK_TYPE:
                thread_label = f'线程起点{idx}'
            widget.addItem(f'{thread_label} (ID: {card_id})', str(card_id))

        desired_value = str(current_value or param_def.get('default') or '').strip()
        if desired_value:
            index = widget.findData(desired_value)
            if index < 0:
                index = widget.findText(desired_value)
            if index < 0 and not desired_value.isdigit():
                for i in range(widget.count()):
                    if widget.itemText(i).startswith(f'{desired_value} (ID:'):
                        index = i
                        break
            if index >= 0:
                widget.setCurrentIndex(index)

        selected_value = widget.currentData()
        if selected_value is None:
            selected_value = widget.currentText()
        self.current_parameters[name] = selected_value
        widget.currentIndexChanged.connect(
            lambda _index, n=name, w=widget: self._on_thread_target_selection_changed(n, w)
        )
        return widget
