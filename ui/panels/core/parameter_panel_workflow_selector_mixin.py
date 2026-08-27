from ..parameter_panel_support import *

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
        if target_value is None or isinstance(target_value, bool):
            return None
        if isinstance(target_value, int):
            return target_value if target_value >= 0 else None

        text = str(target_value).strip()
        if not text or text in {'当前线程', '全部线程'}:
            return None

        try:
            value = int(text)
            return value if value >= 0 else None
        except Exception:
            pass

        match = re.search(r'ID\s*[:?]\s*(-?\d+)', text)
        if not match:
            match = re.search(r'\(\s*ID\s*[:?]\s*(-?\d+)\s*\)', text)
        if not match:
            return None
        try:
            value = int(match.group(1))
            return value if value >= 0 else None
        except Exception:
            return None

    @staticmethod
    def _parse_card_id_from_value(value: Any) -> Optional[int]:
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value

        text = str(value).strip()
        if not text:
            return None
        if text in {'使用线程默认起点', '默认起点', 'None', 'none', '-1'}:
            return None

        try:
            return int(text)
        except Exception:
            match = re.search(r'ID\s*[:?]\s*(-?\d+)', text)
            if not match:
                match = re.search(r'\(\s*ID\s*[:?]\s*(-?\d+)\s*\)', text)
            if match:
                try:
                    return int(match.group(1))
                except Exception:
                    return None
        return None

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
            return all_cards

        target_text = '' if target_value is None else str(target_value).strip()
        if not target_text or target_text == '全部线程':
            return all_cards

        adjacency = self._build_workflow_adjacency_for_selector()
        selected_start_id = self._parse_thread_start_id_from_target(target_value)
        if selected_start_id is not None and selected_start_id not in start_card_ids:
            selected_start_id = None

        if selected_start_id is None and target_text == '当前线程':
            selected_start_id = self._resolve_current_thread_start_card_id(start_card_ids, adjacency)

        if selected_start_id is None:
            return all_cards

        allowed_ids = self._collect_reachable_card_ids(selected_start_id, adjacency)
        filtered_cards = [item for item in all_cards if item[0] in allowed_ids]
        return filtered_cards if filtered_cards else all_cards

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

    def _extract_workflow_name_token_from_task(self, task_obj: Optional[object]) -> str:
        """优先从工作流文件名提取 token，失败时回退任务显示名。"""
        if task_obj is None:
            return ""

        try:
            filepath = str(getattr(task_obj, "filepath", "") or "").strip()
            if filepath:
                stem = os.path.splitext(os.path.basename(filepath))[0]
                token = self._sanitize_workflow_name_token(stem)
                if token:
                    return token
        except Exception:
            pass

        try:
            task_name = str(getattr(task_obj, "name", "") or "").strip()
            token = self._sanitize_workflow_name_token(task_name)
            if token:
                return token
        except Exception:
            pass

        return ""

    def _get_active_workflow_file_token(self) -> Optional[str]:
        """获取当前工作流名称标识，用于截图命名。"""
        tab_widget = None
        try:
            if self.main_window and hasattr(self.main_window, "workflow_tab_widget"):
                tab_widget = self.main_window.workflow_tab_widget
        except Exception:
            tab_widget = None

        if tab_widget:
            current_task_id = None
            try:
                current_task_id = tab_widget.get_current_task_id()
            except Exception:
                current_task_id = None

            if current_task_id is not None:
                try:
                    task_manager = getattr(tab_widget, "task_manager", None)
                    task_obj = task_manager.get_task(current_task_id) if task_manager else None
                except Exception:
                    task_obj = None

                token = self._extract_workflow_name_token_from_task(task_obj)
                if token:
                    return token

                try:
                    if hasattr(tab_widget, "_get_current_workflow_filepath"):
                        workflow_path = tab_widget._get_current_workflow_filepath()
                        path_token = self._sanitize_workflow_name_token(
                            os.path.splitext(os.path.basename(str(workflow_path or "").strip()))[0]
                        )
                        if path_token:
                            return path_token
                except Exception:
                    pass

                fallback_token = self._sanitize_workflow_name_token(f"workflow_{int(current_task_id)}")
                if fallback_token:
                    return fallback_token

        workflow_view = self._get_active_workflow_view()
        if workflow_view is None:
            return None

        try:
            fallback_task_id = getattr(workflow_view, "task_id", None)
            if fallback_task_id is None:
                return None
            return self._sanitize_workflow_name_token(f"workflow_{int(fallback_task_id)}") or None
        except Exception:
            return None

    _LEGACY_OPERATION_MODE_BY_INDEX = [
        "找图功能",
        "坐标点击",
        "文字点击",
        "找色功能",
        "元素点击",
        "鼠标滚轮",
        "鼠标拖拽",
        "鼠标移动",
    ]

    _OPERATION_MODE_ALIAS = {
        "图片点击": "找图功能",
        "找图点击": "找图功能",
        "找色点击": "找色功能",
    }

    _LEGACY_IMAGE_TASK_TYPES = {"图片点击", "查找图片并点击", "找图点击", "找图功能"}

    def _normalize_operation_mode_value(self, value: Any, fallback_task_type: str = "") -> str:
        """归一化 operation_mode，兼容旧文案和旧索引值。"""
        mode = ""

        if isinstance(value, (int, float)) and not isinstance(value, bool):
            idx = int(value)
            if 0 <= idx < len(self._LEGACY_OPERATION_MODE_BY_INDEX):
                mode = self._LEGACY_OPERATION_MODE_BY_INDEX[idx]
            else:
                mode = str(value).strip()
        else:
            mode = str(value or "").strip()
            if mode.isdigit():
                idx = int(mode)
                if 0 <= idx < len(self._LEGACY_OPERATION_MODE_BY_INDEX):
                    mode = self._LEGACY_OPERATION_MODE_BY_INDEX[idx]

        mode = self._OPERATION_MODE_ALIAS.get(mode, mode)
        if mode:
            return mode

        task_type_candidates = [
            str(fallback_task_type or "").strip(),
            str(self.current_task_type or "").strip(),
            str(self.current_parameters.get("task_type", "") or "").strip(),
        ]
        if any(task_type in self._LEGACY_IMAGE_TASK_TYPES for task_type in task_type_candidates if task_type):
            return "找图功能"
        return ""

    def _normalize_operation_mode_parameter(self, param_definitions: Optional[Dict[str, Dict[str, Any]]] = None) -> None:
        """在参数面板初始化阶段统一修正 operation_mode。"""
        definitions = param_definitions or self.param_definitions
        if "operation_mode" not in definitions:
            return

        raw_value = self.current_parameters.get("operation_mode")
        normalized = self._normalize_operation_mode_value(raw_value, fallback_task_type=self.current_task_type or "")
        if normalized:
            self.current_parameters["operation_mode"] = normalized

    def _prune_obsolete_params_in_workflow(self, obsolete_params: list) -> None:
        if getattr(self, "_loading_parameter_panel", False):
            return
        if not obsolete_params or self.current_card_id is None:
            return

        current_workflow_view = None
        try:
            if self.main_window and hasattr(self.main_window, "workflow_tab_widget") and self.main_window.workflow_tab_widget:
                current_task_id = self.main_window.workflow_tab_widget.get_current_task_id()
                if current_task_id is not None and current_task_id in self.main_window.workflow_tab_widget.task_views:
                    current_workflow_view = self.main_window.workflow_tab_widget.task_views[current_task_id]
            if current_workflow_view is None and self.main_window and hasattr(self.main_window, "workflow_view"):
                current_workflow_view = self.main_window.workflow_view
        except Exception as exc:
            logger.debug(f"[废弃参数] 解析 workflow_view 失败：{exc}")
            return

        if not current_workflow_view or not hasattr(current_workflow_view, "cards"):
            return

        card = current_workflow_view.cards.get(self.current_card_id)
        if not card or not hasattr(card, "parameters"):
            return

        removed = []
        for name in obsolete_params:
            if name in card.parameters:
                removed.append(name)
                card.parameters.pop(name, None)

        if not removed:
            return

        try:
            card.parameters = card.parameters.copy()
        except Exception:
            pass
        try:
            card.update()
        except Exception:
            pass
        if getattr(self, "_loading_parameter_panel", False):
            logger.debug(f"[obsolete params] removed from workflow during panel load: {removed}")
            return
        if self.main_window and hasattr(self.main_window, "_mark_unsaved_changes"):
            self.main_window._mark_unsaved_changes()
        logger.debug(f"[obsolete params] removed from workflow: {removed}")
