from ..parameter_panel_support import *
from ..thread_target_selector import ThreadTargetSelector
from task_workflow.thread_start import validate_thread_target

class ParameterPanelWorkflowSelectorMixin:

    def _collect_workflow_cards_for_selector(self) -> List[tuple[int, str, str]]:
        """收集当前工作流卡片信息: (card_id, task_type, custom_name)?"""
        workflow_view = self._get_active_workflow_view()
        custom_name_map: Dict[int, str] = {}
        if workflow_view and hasattr(workflow_view, 'cards'):
            try:
                for card_id, card_obj in workflow_view.cards.items():
                    custom_name_map[int(card_id)] = str(
                        getattr(card_obj, 'custom_name', '') or ''
                    ).strip()
            except Exception:
                custom_name_map = {}

        results: List[tuple[int, str, str]] = []
        seen = set()
        for _, info in sorted((self.workflow_cards_info or {}).items(), key=lambda kv: kv[0]):
            if not isinstance(info, (tuple, list)) or len(info) < 2:
                continue
            task_type = str(info[0] or '未知任务')
            try:
                card_id = int(info[1])
            except Exception:
                continue
            if card_id in seen:
                continue
            seen.add(card_id)
            results.append((card_id, task_type, custom_name_map.get(card_id, '')))

        if not results and workflow_view and hasattr(workflow_view, 'cards'):
            try:
                for card_id, card_obj in workflow_view.cards.items():
                    cid = int(card_id)
                    task_type = str(getattr(card_obj, 'task_type', '') or '未知任务')
                    custom_name = str(getattr(card_obj, 'custom_name', '') or '').strip()
                    results.append((cid, task_type, custom_name))
            except Exception:
                pass

        results.sort(key=lambda item: item[0])
        return results

    def _collect_workflow_connections_for_selector(self) -> List[tuple[int, int]]:
        """收集当前工作流连接关系: (start_card_id, end_card_id)?"""
        workflow_view = self._get_active_workflow_view()
        if not workflow_view or not hasattr(workflow_view, 'connections'):
            return []

        connections: List[tuple[int, int]] = []
        for conn in list(getattr(workflow_view, 'connections', []) or []):
            try:
                start_item = getattr(conn, 'start_item', None)
                end_item = getattr(conn, 'end_item', None)
                if start_item is None or end_item is None:
                    continue
                start_id = int(getattr(start_item, 'card_id'))
                end_id = int(getattr(end_item, 'card_id'))
            except Exception:
                continue
            connections.append((start_id, end_id))
        return connections

    def _build_workflow_adjacency_for_selector(self) -> Dict[int, Set[int]]:
        adjacency: Dict[int, Set[int]] = {}
        for start_id, end_id in self._collect_workflow_connections_for_selector():
            adjacency.setdefault(start_id, set()).add(end_id)
        return adjacency

    @staticmethod
    def _collect_reachable_card_ids(start_card_id: int, adjacency: Dict[int, Set[int]]) -> Set[int]:
        visited: Set[int] = set()
        stack: List[int] = [int(start_card_id)]
        while stack:
            current_id = stack.pop()
            if current_id in visited:
                continue
            visited.add(current_id)
            for next_id in adjacency.get(current_id, set()):
                if next_id not in visited:
                    stack.append(next_id)
        return visited

    @staticmethod
    def _parse_thread_start_id_from_target(target_value: Any) -> Optional[int]:
        validate_thread_target(target_value)
        if isinstance(target_value, list) or target_value in {'当前线程', '全部线程'}:
            return None
        return int(target_value)

    @staticmethod
    def _parse_card_id_from_value(value: Any) -> Optional[int]:
        if value is None:
            return None
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
        raise ValueError('指定卡片必须是非负整数编号或空值')

    def _resolve_current_thread_start_card_id(
        self,
        start_card_ids: List[int],
        adjacency: Dict[int, Set[int]],
    ) -> Optional[int]:
        current_card_id = self.current_card_id
        if current_card_id is None:
            return None

        owner_start_ids: List[int] = []
        for start_id in start_card_ids:
            reachable = self._collect_reachable_card_ids(start_id, adjacency)
            if int(current_card_id) in reachable:
                owner_start_ids.append(start_id)

        if len(owner_start_ids) == 1:
            return owner_start_ids[0]
        return None

    def _collect_workflow_cards_for_target_thread(self, target_value: Any) -> List[tuple[int, str, str]]:
        all_cards = self._collect_workflow_cards_for_selector()
        if not all_cards:
            return []

        start_card_ids = [
            card_id for card_id, task_type, _ in all_cards if is_thread_start_task_type(task_type)
        ]
        if not start_card_ids:
            return []

        if isinstance(target_value, list):
            if not target_value:
                return []
            validate_thread_target(target_value)
            adjacency = self._build_workflow_adjacency_for_selector()
            allowed_ids = {item[0] for item in all_cards}
            for target in target_value:
                start_id = int(target)
                if start_id not in start_card_ids:
                    return []
                allowed_ids.intersection_update(self._collect_reachable_card_ids(start_id, adjacency))
            return [item for item in all_cards if item[0] in allowed_ids]

        target_text = '' if target_value is None else str(target_value).strip()
        if target_text == '全部线程':
            return all_cards

        adjacency = self._build_workflow_adjacency_for_selector()
        selected_start_id = self._parse_thread_start_id_from_target(target_value)
        if selected_start_id is not None and selected_start_id not in start_card_ids:
            selected_start_id = None

        if selected_start_id is None and target_text == '当前线程':
            selected_start_id = self._resolve_current_thread_start_card_id(start_card_ids, adjacency)

        if selected_start_id is None:
            return []

        allowed_ids = self._collect_reachable_card_ids(selected_start_id, adjacency)
        filtered_cards = [item for item in all_cards if item[0] in allowed_ids]
        return filtered_cards

    def _refresh_workflow_card_selector_options(self) -> None:
        target_value: Any = self.current_parameters.get('target_thread')
        target_widget = self._get_value_widget('target_thread')
        if isinstance(target_widget, ThreadTargetSelector):
            target_value = target_widget.value()
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
                widget.addItem('请选择指定卡片', None)
                widget.setProperty('invalid_value', None)
                for card_id, task_type, custom_name in card_options:
                    if custom_name:
                        display_text = f'{custom_name} [{task_type}] (ID: {card_id})'
                    else:
                        display_text = f'{task_type} (ID: {card_id})'
                    widget.addItem(display_text, int(card_id))

                if selected_card_id is not None and selected_card_id >= 0:
                    index = widget.findData(int(selected_card_id))
                    if index < 0:
                        widget.addItem(f'指定卡片不可用 (ID: {selected_card_id})', selected_card_id)
                        widget.setProperty('invalid_value', selected_card_id)
                        index = widget.count() - 1
                    widget.setCurrentIndex(index)
            finally:
                widget.blockSignals(False)

    def _on_thread_target_selection_changed(self, param_name: str, widget: ThreadTargetSelector) -> None:
        selected_value = widget.value()
        self._apply_live_parameter_changes(
            {param_name: selected_value},
            refresh_conditional=False,
        )
        self._refresh_workflow_card_selector_options()

    def _get_active_workflow_view(self):
        """获取当前活动的 workflow_view。"""
        try:
            if self.main_window and hasattr(self.main_window, "workflow_tab_widget") and self.main_window.workflow_tab_widget:
                current_task_id = self.main_window.workflow_tab_widget.get_current_task_id()
                if (
                    current_task_id is not None
                    and current_task_id in self.main_window.workflow_tab_widget.task_views
                ):
                    return self.main_window.workflow_tab_widget.task_views[current_task_id]
            if self.main_window and hasattr(self.main_window, "workflow_view"):
                return self.main_window.workflow_view
        except Exception:
            pass
        return None

    @staticmethod
    def _sanitize_workflow_name_token(value: Optional[object], max_len: int = 64) -> str:
        """将工作流名称转换为可用于文件名的安全 token。"""
        raw = str(value or "").strip()
        if not raw:
            return ""

        invalid_chars = set('<>:"/\\|?*')
        chars = []
        for ch in raw:
            if ch in invalid_chars or ord(ch) < 32:
                chars.append("_")
            elif ch.isspace():
                chars.append("_")
            else:
                chars.append(ch)

        token = "".join(chars).strip("._ ")
        while "__" in token:
            token = token.replace("__", "_")
        return token[:max_len]



    def _get_active_workflow_file_token(self) -> Optional[str]:
        if self.main_window is None:
            return None
        tabs = self.main_window.workflow_tab_widget
        path = tabs._get_current_workflow_filepath()
        if path:
            return self._sanitize_workflow_name_token(os.path.splitext(os.path.basename(path))[0]) or None
        task_id = tabs.get_current_task_id()
        return self._sanitize_workflow_name_token(f'workflow_{task_id}') if task_id is not None else None

    def _normalize_operation_mode_parameter(self, param_definitions=None, *, parameters=None) -> None:
        """只接受参数定义中的现行操作模式；缺省值由统一填充流程提供。"""
        definitions = self.param_definitions if param_definitions is None else param_definitions
        values = self.current_parameters if parameters is None else parameters
        if "operation_mode" not in definitions or "operation_mode" not in values:
            return
        value = values["operation_mode"]
        if value not in definitions["operation_mode"]["options"]:
            raise ValueError(f"无效的鼠标操作模式: {value!r}，请先转换为现行工程格式")
