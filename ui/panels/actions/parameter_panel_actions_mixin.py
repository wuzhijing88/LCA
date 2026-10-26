from functools import partial

from ..parameter_panel_support import *
from utils.window.window_binding_utils import get_active_bound_window_hwnd

class ParameterPanelActionsMixin:

    def _show_random_target_context_menu(self, target_card_id: int, widget: QWidget, pos):
        """显示随机跳转目标的右键菜单"""
        menu = self._create_panel_context_menu()
        set_weight_action = menu.addAction("设置权重")
        delete_action = menu.addAction("删除连线")
        action = menu.exec_(widget.mapToGlobal(pos))
        if action == set_weight_action:
            self._edit_random_branch_weight(target_card_id)
        elif action == delete_action:
            if self.current_card_id is not None:
                self.request_delete_random_connection.emit(self.current_card_id, target_card_id)

    def _edit_random_branch_weight(self, target_card_id: int):
        if self.current_card_id is None:
            return
        current_weight = get_branch_weight(
            self.current_parameters.get('random_weights'),
            target_card_id,
        )
        weight, ok = QInputDialog.getInt(
            self,
            "设置权重",
            f"目标卡片 {target_card_id} 的权重：",
            current_weight,
            1,
            999999,
            1,
        )
        if not ok:
            return
        updated_weights = set_branch_weight(
            self.current_parameters.get('random_weights'),
            target_card_id,
            weight,
        )
        self.current_parameters['random_weights'] = updated_weights
        self.parameters_changed.emit(self.current_card_id, {'random_weights': updated_weights})
        self._refresh_conditional_widgets()

    def _create_panel_context_menu(self) -> QMenu:
        """创建参数面板统一的右键菜单样式（与主窗口右键菜单保持一致）"""
        return apply_unified_menu_style(QMenu(self), frameless=True)

    def _handle_refresh_dynamic_options(self, param_def: Dict[str, Any]):
        """Refresh dynamic options."""
        try:
            target_params = self._resolve_dynamic_target_params(param_def)
            if not target_params:
                QMessageBox.warning(self, "错误", "未配置目标下拉框")
                return

            options_func_name = param_def.get('options_func', '')
            source_value = self._get_dynamic_source_value(param_def.get('source_param', ''))
            source_label = self._get_dynamic_source_label(param_def)
            if not source_value and options_func_name != 'list_map_options':
                QMessageBox.warning(self, "提示", f"请先设置{source_label}")
                return

            target_widgets, missing_targets = self._resolve_dynamic_target_widgets(target_params)
            if not target_widgets:
                QMessageBox.warning(self, "错误", f"未找到目标下拉框: {', '.join(missing_targets)}")
                return

            new_options = self._load_dynamic_options(source_value, options_func_name, param_def)
            changed_payload = self._apply_dynamic_options(target_widgets, new_options)
            self._emit_dynamic_options_changed(changed_payload)
            QMessageBox.information(
                self,
                "完成",
                f"已加载 {len(new_options)} 个选项，已更新 {len(target_widgets)} 个下拉框",
            )
        except Exception as e:
            logger.error(f"刷新动态选项失败: {e}", exc_info=True)

    def _resolve_dynamic_target_params(self, param_def: Dict[str, Any]) -> List[str]:
        target_params: List[str] = []
        raw_target_params = param_def.get('target_params')
        if isinstance(raw_target_params, (list, tuple, set)):
            for item in raw_target_params:
                text = str(item or '').strip()
                if text:
                    target_params.append(text)
        if target_params:
            return target_params

        target_param = str(param_def.get('target_param', '') or '').strip()
        if target_param:
            target_params.append(target_param)
        return target_params

    def _get_dynamic_source_value(self, source_param: str) -> str:
        source_widget = self._get_value_widget(source_param)
        if source_widget is None:
            return ''
        if isinstance(source_widget, QLineEdit):
            return source_widget.text()
        if isinstance(source_widget, QComboBox):
            return source_widget.currentText()
        if hasattr(source_widget, 'findChild'):
            line_edit = source_widget.findChild(QLineEdit)
            if line_edit:
                return line_edit.text()
        return ''

    def _resolve_dynamic_target_widgets(self, target_params: List[str]):
        target_widgets: Dict[str, QComboBox] = {}
        missing_targets: List[str] = []
        for target_param in target_params:
            target_widget = self._get_value_widget(target_param)
            if not isinstance(target_widget, QComboBox):
                target_widget = self._find_combo_box_by_name(target_param)
            if isinstance(target_widget, QComboBox):
                target_widgets[target_param] = target_widget
            else:
                missing_targets.append(target_param)
        return target_widgets, missing_targets

    def _find_combo_box_by_name(self, target_param: str):
        for combo in self.findChildren(QComboBox):
            if combo.objectName() == target_param:
                return combo
        return None

    def _get_dynamic_source_label(self, param_def: Dict[str, Any]) -> str:
        label = str(param_def.get("source_label", "") or "").strip()
        if label:
            return label
        source_param = str(param_def.get("source_param", "") or "").strip()
        if source_param and source_param in getattr(self, "param_definitions", {}):
            source_def = self.param_definitions.get(source_param, {}) or {}
            label = str(source_def.get("label", "") or "").strip()
            if label:
                return label
        return "源参数"

    def _load_dynamic_options(self, source_value: str, options_func_name: str, param_def: Dict[str, Any]) -> List[str]:
        func = self._resolve_dynamic_options_func(options_func_name)
        if func is None:
            raise ValueError(f"动态选项接口不存在：{options_func_name}")
        options = func(source_value or None) if options_func_name == 'list_map_options' else func(source_value)
        if not isinstance(options, (list, tuple, set)):
            raise TypeError(f"动态选项接口返回了无效结果：{options_func_name}")
        return [str(item).strip() for item in options if str(item).strip()]

    def _resolve_dynamic_options_func(self, options_func_name: str):
        if self.task_module is None:
            raise ValueError("当前卡片没有任务模块，无法读取动态选项")
        func = getattr(self.task_module, options_func_name, None)
        if not callable(func):
            raise ValueError(f"当前卡片不提供动态选项接口：{options_func_name}")
        return func

    def _initial_dynamic_options(self, name, param_def, current_value):
        options = list(self.current_parameters.get(f'_{name}_dynamic_options', param_def.get('options', [])))
        if current_value is not None and current_value not in options:
            options.append(current_value)
        return options

    def _schedule_dynamic_options(self, name, param_def, widget):
        source_param = param_def.get('source_param', '')
        source = str(self._get_dynamic_source_value(source_param) or self.current_parameters.get(source_param, '')).strip()
        if not source:
            return
        func = self._resolve_dynamic_options_func(param_def['options_func'])
        widget.setEnabled(False)
        widget.setProperty("dynamic_loading", True)
        widget.setProperty("dynamic_error", False)
        widget.setToolTip("正在读取选项…")

        def ready(options):
            widget.setProperty("dynamic_loading", False)
            current = self.current_parameters.get(name, param_def.get('default'))
            widget.blockSignals(True)
            try:
                widget.clear()
                widget.addItems(options)
                index = widget.findText(str(current)) if current is not None else -1
                widget.setCurrentIndex(index)
            finally:
                widget.blockSignals(False)
            widget.setEnabled(True)
            widget.setToolTip("当前值不在可选列表中，请重新选择" if index < 0 else "")
            self.param_definitions[name]['options'] = list(options)
            self.current_parameters[f'_{name}_dynamic_options'] = list(options)

        def failed(error):
            widget.setProperty("dynamic_loading", False)
            widget.setProperty("dynamic_error", True)
            widget.setEnabled(False)
            widget.setToolTip(f"读取选项失败：{error}")
            logger.error("读取参数 %s 的动态选项失败：%s", name, error)

        self._background_jobs.submit('options:' + name, partial(_read_dynamic_options, func, source), ready, failed)

    def _apply_dynamic_options(self, target_widgets: Dict[str, QComboBox], new_options: List[str]) -> Dict[str, Any]:
        changed_payload: Dict[str, Any] = {}
        for target_param, target_widget in target_widgets.items():
            self._update_dynamic_param_definition(target_param, new_options)
            self._store_dynamic_options_state(target_param, new_options, changed_payload)
            self._refresh_dynamic_combo_box(target_widget, new_options)
            current_value = target_widget.currentText()
            self.current_parameters[target_param] = current_value
            changed_payload[target_param] = current_value
        return changed_payload

    def _update_dynamic_param_definition(self, target_param: str, new_options: List[str]) -> None:
        if target_param in self.param_definitions:
            self.param_definitions[target_param]['options'] = new_options

    def _store_dynamic_options_state(self, target_param: str, new_options: List[str], changed_payload: Dict[str, Any]) -> None:
        hidden_options_key = f'_{target_param}_dynamic_options'
        self.current_parameters[hidden_options_key] = new_options
        changed_payload[hidden_options_key] = new_options
        logger.info(f"保存动态选项到 {hidden_options_key}: {new_options}")

    def _refresh_dynamic_combo_box(self, target_widget: QComboBox, new_options: List[str]) -> None:
        current_selection = target_widget.currentText()
        target_widget.blockSignals(True)
        target_widget.clear()
        target_widget.addItems(new_options)
        target_widget.blockSignals(False)
        index = target_widget.findText(current_selection)
        if index != -1:
            target_widget.setCurrentIndex(index)
        target_widget.update()
        target_widget.repaint()

    def _emit_dynamic_options_changed(self, changed_payload: Dict[str, Any]) -> None:
        if self.current_card_id is not None and changed_payload:
            self.parameters_changed.emit(self.current_card_id, changed_payload)

    def _refresh_selects_using_source(self, source_param):
        for name, definition in self.param_definitions.items():
            if definition.get('source_param') == source_param and definition.get('options_func'):
                widget = self._get_value_widget(name)
                if widget is not None:
                    self._schedule_dynamic_options(name, definition, widget)

    _BACKGROUND_ACTIONS = {
        'test_ocr_output',
        'test_dict_ocr_output',
        'preview_image_recognition',
        'preview_color_recognition',
    }

    _HIDE_WINDOW_ACTIONS = {'preview_image_recognition', 'preview_color_recognition'}

    def _handle_button_click(self, name, param_def):
        try:
            if param_def.get('widget_hint') == 'refresh_dynamic_options':
                self._handle_refresh_dynamic_options(param_def)
                return
            action = param_def.get('action')
            if not action:
                raise ValueError(f'参数按钮没有配置动作：{name}')
            action_func = self._resolve_button_action(action)
            current_params = self._collect_current_parameters()
            target_hwnd = self._get_button_action_target_hwnd()
            if self._should_run_action_in_background(action):
                self._start_background_action(action, action_func, current_params, target_hwnd)
                return
            result = self._invoke_button_action(action_func, current_params, target_hwnd)
            if action == "toggle_combo_key_sequence_record":
                self._resources.forget_cleanup("combo-recording")
                if getattr(self, "_combo_seq_recording_hook", None) is not None or getattr(self, "_combo_seq_recording_mouse_hooks", []):
                    import keyboard
                    import mouse
                    from tasks.keyboard_input import _cleanup_combo_sequence_recording
                    self._resources.bind_cleanup("combo-recording", partial(_cleanup_combo_sequence_recording, self, keyboard, mouse))
            if result is False:
                raise RuntimeError('按钮动作执行失败')
        except Exception as error:
            logger.error('参数按钮执行失败：%s', error, exc_info=True)
            QMessageBox.warning(self, '执行失败', str(error))

    def _resolve_button_action(self, action: str):
        from ui.panels.actions.ui_button_actions import resolve_ui_button_action

        ui_action = resolve_ui_button_action(action)
        if ui_action is not None:
            return ui_action
        if self.task_module is None:
            raise ValueError("当前卡片没有任务模块，无法执行按钮动作")
        action_func = getattr(self.task_module, action, None)
        if not callable(action_func):
            raise ValueError(f"当前卡片不提供按钮动作：{action}")
        return action_func

    def _get_button_action_target_hwnd(self):
        if not hasattr(self, 'main_window') or not self.main_window:
            return None
        if hasattr(self.main_window, 'bound_windows') and isinstance(self.main_window.bound_windows, list):
            for window_info in self.main_window.bound_windows:
                if not isinstance(window_info, dict):
                    continue
                if not window_info.get('enabled', True):
                    continue
                hwnd = window_info.get('hwnd')
                if hwnd:
                    return hwnd
        if hasattr(self.main_window, 'config') and isinstance(self.main_window.config, dict):
            return get_active_bound_window_hwnd(self.main_window.config)
        return None

    def _should_run_action_in_background(self, action: str) -> bool:
        return action in self._BACKGROUND_ACTIONS

    def _start_background_action(self, action: str, action_func, current_params: Dict[str, Any], target_hwnd):
        from copy import deepcopy
        from ui.panels.action_context import ActionWindowContext
        from task_workflow.resource_context import resource_dirs_from_mapping

        self._prepare_background_action_ui(action)
        directories = resource_dirs_from_mapping(self)
        panel_context = ActionWindowContext(self, directories, self.current_card_id, self)
        main_context = ActionWindowContext(self.main_window, directories, self.current_card_id, self)
        resource_key = f'action:{action}'
        self._cancel_background_actions()
        self._action_contexts = (panel_context, main_context)
        self._resources.bind_cleanup(resource_key, self._cancel_background_actions)
        values = deepcopy(current_params)

        def work(cancelled, progress):
            if cancelled.is_set() or panel_context._cancelled.is_set():
                return False
            return action_func(values, target_hwnd=target_hwnd, main_window=main_context, parameter_panel=panel_context)

        def failed(error):
            logger.error("按钮动作 %s 执行失败：%s", action, error)
            panel_context.show()
            main_context.show()
            QMessageBox.warning(self, "执行失败", f"按钮动作执行失败：{error}")

        self._background_jobs.submit(resource_key, work, lambda result: None, failed)

    def _cancel_background_actions(self):
        for context in getattr(self, '_action_contexts', ()):
            context.cancel()
            context.deleteLater()
        self._action_contexts = ()
        for key in list(self._resources.cleanups):
            if key.startswith('action:'):
                self._resources.forget_cleanup(key)

    def _prepare_background_action_ui(self, action: str):
        if action in self._HIDE_WINDOW_ACTIONS:
            self.hide()
            if self.main_window is not None:
                self.main_window.hide()

    def _invoke_button_action(self, action_func, current_params: Dict[str, Any], target_hwnd):
        return action_func(
            current_params,
            target_hwnd=target_hwnd,
            main_window=self.main_window,
            parameter_panel=self,
        )


def _read_dynamic_options(func, source, cancelled, progress):
    if cancelled.is_set():
        return []
    options = func(source)
    if not isinstance(options, (list, tuple, set)):
        raise TypeError("动态选项接口必须返回列表")
    return [str(item).strip() for item in options if str(item).strip()]
