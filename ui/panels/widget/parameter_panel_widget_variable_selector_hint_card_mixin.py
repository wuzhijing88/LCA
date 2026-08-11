from ..parameter_panel_support import *


class ParameterPanelWidgetVariableSelectorHintCardMixin:
    def _on_variable_card_selector_changed(self, index: int, widget: QComboBox, name: str) -> None:
        new_value = widget.itemData(index) if widget.itemData(index) is not None else widget.currentText()
        self._apply_live_parameter_changes({name: new_value})

    def _create_variable_card_selector_widget(self, name: str, param_def: Dict[str, Any], current_value: Any):
        widget = QComboBox(self)
        self._remove_combobox_shadow(widget)

        def _normalize_card_value(value):
            if value in (None, "", "全部"):
                return None
            try:
                return int(value)
            except (TypeError, ValueError):
                return None

        def _normalize_workflow_value(value):
            if value in (None, "", "当前工作流"):
                return None
            if value in ("全局变量", "global"):
                return "global"
            try:
                return int(value)
            except (TypeError, ValueError):
                return None

        def _get_card_label(card_id: int, task_type: str = None, custom_name: str = None) -> str:
            if custom_name:
                return f"卡片 {card_id} {custom_name}"
            if task_type:
                return f"卡片 {card_id} {task_type}"
            return f"卡片 {card_id}"

        def _get_cards_for_current() -> dict:
            labels = {}
            try:
                current_workflow_view = None
                if self.main_window and hasattr(self.main_window, "workflow_tab_widget") and self.main_window.workflow_tab_widget:
                    current_task_id = self.main_window.workflow_tab_widget.get_current_task_id()
                    if current_task_id is not None and current_task_id in self.main_window.workflow_tab_widget.task_views:
                        current_workflow_view = self.main_window.workflow_tab_widget.task_views[current_task_id]
                if current_workflow_view is None and self.main_window and hasattr(self.main_window, "workflow_view"):
                    current_workflow_view = self.main_window.workflow_view
                if current_workflow_view and hasattr(current_workflow_view, "cards"):
                    for card_id, card in current_workflow_view.cards.items():
                        labels[int(card_id)] = _get_card_label(
                            card_id,
                            task_type=getattr(card, "task_type", None),
                            custom_name=getattr(card, "custom_name", None),
                        )
            except Exception:
                pass

            if labels:
                return labels

            for _, (task_type, info_card_id) in (self.workflow_cards_info or {}).items():
                if isinstance(info_card_id, int):
                    labels[info_card_id] = _get_card_label(info_card_id, task_type=task_type)
            return labels

        def _get_cards_for_task(task_id: int) -> dict:
            labels = {}
            try:
                task_manager = None
                if self.main_window and hasattr(self.main_window, "workflow_tab_widget") and self.main_window.workflow_tab_widget:
                    task_manager = self.main_window.workflow_tab_widget.task_manager
                if task_manager is None and self.main_window and hasattr(self.main_window, "task_manager"):
                    task_manager = self.main_window.task_manager
                task = task_manager.get_task(task_id) if task_manager else None
                cards = task.workflow_data.get("cards", []) if task and isinstance(task.workflow_data, dict) else []
                for card in cards:
                    card_id = card.get("id")
                    if card_id is None:
                        continue
                    try:
                        card_id_int = int(card_id)
                    except (TypeError, ValueError):
                        continue
                    custom_name = card.get("custom_name") or card.get("customName")
                    task_type = card.get("task_type")
                    labels[card_id_int] = _get_card_label(card_id_int, task_type=task_type, custom_name=custom_name)
            except Exception:
                pass
            return labels

        workflow_filter_param = param_def.get("workflow_filter_param")
        workflow_filter_id = None
        if workflow_filter_param:
            workflow_filter_id = _normalize_workflow_value(self.current_parameters.get(workflow_filter_param))

        if workflow_filter_id is None:
            labels = _get_cards_for_current()
        elif workflow_filter_id == "global":
            labels = {}
        else:
            labels = _get_cards_for_task(workflow_filter_id)

        card_ids = sorted(labels.keys())
        widget.addItem("全部", None)
        for card_id in card_ids:
            widget.addItem(labels[card_id], card_id)

        current_value = _normalize_card_value(current_value)
        if current_value is None:
            widget.setCurrentIndex(0)
        else:
            idx = widget.findData(current_value)
            if idx >= 0:
                widget.setCurrentIndex(idx)
            else:
                widget.setCurrentIndex(0)
                self.current_parameters[name] = None

        widget.currentIndexChanged.connect(
            lambda index, w=widget, n=name: self._on_variable_card_selector_changed(index, w, n)
        )
        self._register_widget(name, widget)
        self._install_wheel_filter(widget, name)
        return widget
