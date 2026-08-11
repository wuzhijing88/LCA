from ..parameter_panel_support import *


class ParameterPanelWidgetVariableSelectorHintNameMixin:
    def _create_variable_name_selector_widget(self, name: str, param_def: Dict[str, Any], current_value: Any):
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

        def _sort_key(name: str) -> tuple:
            import re
            text = str(name)
            match = re.match(r'^卡片(\d+)结果(?:[\._](.*))?$', text)
            if match:
                return (0, int(match.group(1)), match.group(2) or "")
            match = re.match(r'^card_(\d+)_result(?:[\._](.*))?$', text, flags=re.IGNORECASE)
            if match:
                return (0, int(match.group(1)), match.group(2) or "")
            return (1, text)

        def _is_system_var(name: str) -> bool:
            return str(name).startswith((
                "latest_ocr_",
                "latest_yolo_",
            ))

        def _get_task_type_for_card(card_id: Optional[int], workflow_task_id: Optional[int]) -> Optional[str]:
            if card_id is None:
                return None
            try:
                if workflow_task_id is None:
                    current_workflow_view = None
                    if self.main_window and hasattr(self.main_window, "workflow_tab_widget") and self.main_window.workflow_tab_widget:
                        current_task_id = self.main_window.workflow_tab_widget.get_current_task_id()
                        if current_task_id is not None and current_task_id in self.main_window.workflow_tab_widget.task_views:
                            current_workflow_view = self.main_window.workflow_tab_widget.task_views[current_task_id]
                    if current_workflow_view is None and self.main_window and hasattr(self.main_window, "workflow_view"):
                        current_workflow_view = self.main_window.workflow_view
                    if current_workflow_view and hasattr(current_workflow_view, "cards"):
                        card = current_workflow_view.cards.get(card_id)
                        if card:
                            return getattr(card, "task_type", None)
                elif workflow_task_id == "global":
                    return None
                else:
                    task_manager = None
                    if self.main_window and hasattr(self.main_window, "workflow_tab_widget") and self.main_window.workflow_tab_widget:
                        task_manager = self.main_window.workflow_tab_widget.task_manager
                    if task_manager is None and self.main_window and hasattr(self.main_window, "task_manager"):
                        task_manager = self.main_window.task_manager
                    task = task_manager.get_task(workflow_task_id) if task_manager else None
                    cards = task.workflow_data.get("cards", []) if task and isinstance(task.workflow_data, dict) else []
                    for card in cards:
                        card_id_value = card.get("id")
                        if card_id_value is None:
                            continue
                        try:
                            card_id_int = int(card_id_value)
                        except (TypeError, ValueError):
                            continue
                        if card_id_int == card_id:
                            return card.get("task_type")
            except Exception:
                return None
            for _, (task_type, info_card_id) in (self.workflow_cards_info or {}).items():
                if info_card_id == card_id:
                    return task_type
            return None

        def _get_variable_names(card_id: Optional[int], workflow_task_id: Optional[int]) -> list:
            try:
                if workflow_task_id is None:
                    from task_workflow.workflow_context import get_workflow_context
                    context = get_workflow_context()
                else:
                    from task_workflow.workflow_vars import get_context_for_task
                    context = get_context_for_task(workflow_task_id)
                if not context:
                    return []
                if hasattr(context, "snapshot_variable_state"):
                    state = context.snapshot_variable_state()
                    global_vars = dict((state or {}).get("global_vars", {}) or {})
                    source_map = dict((state or {}).get("var_sources", {}) or {})
                else:
                    global_vars = getattr(context, "global_vars", {}) or {}
                    source_map = getattr(context, "var_sources", {}) or {}
                if workflow_task_id == "global":
                    names = [str(var_name) for var_name in global_vars.keys() if not _is_system_var(var_name)]
                    return sorted(names, key=_sort_key)
                names = []
                allowed_task_types = param_def.get("allowed_task_types")
                if allowed_task_types and not isinstance(allowed_task_types, (list, tuple, set)):
                    allowed_task_types = [allowed_task_types]
                allowed_task_types = [str(item) for item in (allowed_task_types or []) if str(item)]

                for var_name in global_vars.keys():
                    if _is_system_var(var_name):
                        continue
                    source_id = source_map.get(var_name)
                    if card_id is None:
                        if source_id is None:
                            continue
                        if allowed_task_types:
                            task_type = _get_task_type_for_card(source_id, workflow_task_id)
                            if task_type not in allowed_task_types:
                                continue
                        names.append(str(var_name))
                    else:
                        if source_id == card_id:
                            if allowed_task_types:
                                task_type = _get_task_type_for_card(source_id, workflow_task_id)
                                if task_type not in allowed_task_types:
                                    continue
                            names.append(str(var_name))
                return sorted(names, key=_sort_key)
            except Exception:
                return []

        card_filter_param = param_def.get("card_filter_param") or "variable_card_id"
        filter_card_id = _normalize_card_value(self.current_parameters.get(card_filter_param))
        workflow_filter_param = param_def.get("workflow_filter_param")
        workflow_filter_id = None
        if workflow_filter_param:
            workflow_filter_id = _normalize_workflow_value(self.current_parameters.get(workflow_filter_param))
        global_only = bool(param_def.get("global_only"))
        if global_only:
            workflow_filter_id = "global"
            filter_card_id = None
            try:
                from task_workflow.global_var_store import ensure_global_context_loaded
                ensure_global_context_loaded()
            except Exception:
                pass
        names = _get_variable_names(filter_card_id, workflow_filter_id)

        placeholder_label = "请选择变量" if global_only else "当前工作流"
        widget.addItem(placeholder_label, "")
        for var_name in names:
            widget.addItem(var_name)

        if current_value in names:
            widget.setCurrentText(str(current_value))
        else:
            widget.setCurrentIndex(0)
            self.current_parameters[name] = ""

        def on_select_changed(index, w=widget, n=name):
            new_value = w.itemData(index) if w.itemData(index) is not None else w.currentText()
            self.current_parameters[n] = new_value

        widget.currentIndexChanged.connect(on_select_changed)
        self._register_widget(name, widget)
        self._install_wheel_filter(widget, name)
        return widget
