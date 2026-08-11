from ..parameter_panel_support import *


class ParameterPanelWidgetBasicSelectorHintWorkflowSelectorMixin:
    @staticmethod
    def _normalize_workflow_selector_value(value: Any):
        if value in (None, '', '当前工作流'):
            return None
        if value in ('全局变量', 'global'):
            return 'global'
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _get_workflow_selector_items(self):
        items = []
        current_task_id = None
        task_manager = None
        try:
            if self.main_window and hasattr(self.main_window, 'workflow_tab_widget') and self.main_window.workflow_tab_widget:
                current_task_id = self.main_window.workflow_tab_widget.get_current_task_id()
                task_manager = self.main_window.workflow_tab_widget.task_manager
            if task_manager is None and self.main_window and hasattr(self.main_window, 'task_manager'):
                task_manager = self.main_window.task_manager
        except Exception:
            task_manager = None

        if task_manager:
            for task in task_manager.get_all_tasks():
                if current_task_id is not None and task.task_id == current_task_id:
                    continue
                label = f'工作流 {task.task_id} {task.name}'
                items.append((label, task.task_id))
        return items

    def _on_workflow_selector_changed(self, index, widget: QComboBox, name: str):
        new_value = widget.itemData(index) if widget.itemData(index) is not None else widget.currentText()
        self._apply_live_parameter_changes({name: new_value})

    def _create_workflow_selector_widget(self, name: str, current_value: Any):
        widget = QComboBox(self)
        self._remove_combobox_shadow(widget)
        widget.addItem('当前工作流', None)
        widget.addItem('全局变量', 'global')
        for label, task_id in self._get_workflow_selector_items():
            widget.addItem(label, task_id)

        normalized_value = self._normalize_workflow_selector_value(current_value)
        if normalized_value is None:
            widget.setCurrentIndex(0)
            self.current_parameters[name] = None
        else:
            idx = widget.findData(normalized_value)
            if idx >= 0:
                widget.setCurrentIndex(idx)
            else:
                widget.setCurrentIndex(0)
                self.current_parameters[name] = None

        widget.currentIndexChanged.connect(
            lambda index, w=widget, n=name: self._on_workflow_selector_changed(index, w, n)
        )
        self._register_widget(name, widget)
        self._install_wheel_filter(widget, name)
        return widget
