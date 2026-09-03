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

    _DEFAULT_DYNAMIC_OPTIONS = ["全部类别"]

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

    def _get_default_dynamic_options(self, param_def: Dict[str, Any]) -> List[str]:
        raw_options = param_def.get("default_options")
        if isinstance(raw_options, (list, tuple, set)):
            normalized = [str(item or "").strip() for item in raw_options if str(item or "").strip()]
            if normalized:
                return normalized
        return list(self._DEFAULT_DYNAMIC_OPTIONS)

    def _load_dynamic_options(self, source_value: str, options_func_name: str, param_def: Dict[str, Any]) -> List[str]:
        fallback_options = self._get_default_dynamic_options(param_def)
        func = self._resolve_dynamic_options_func(options_func_name)
        if func is None:
            return fallback_options
        try:
            if options_func_name == 'list_map_options':
                options = func(source_value or None)
            else:
                options = func(source_value)
            if isinstance(options, (list, tuple, set)):
                normalized = [str(item or "").strip() for item in options if str(item or "").strip()]
                if normalized or options_func_name == 'list_map_options':
                    return normalized
            return fallback_options
        except Exception as e:
            logger.error(f"调用 {options_func_name} 失败: {e}")
            return fallback_options

    def _resolve_dynamic_options_func(self, options_func_name: str):
        if hasattr(self, 'task_module') and self.task_module and hasattr(self.task_module, options_func_name):
            return getattr(self.task_module, options_func_name)
        try:
            from tasks import get_task_module
            if hasattr(self, 'current_task_type') and self.current_task_type:
                task_module = get_task_module(self.current_task_type)
                if task_module and hasattr(task_module, options_func_name):
                    return getattr(task_module, options_func_name)
        except Exception:
            pass
        return None

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

    _BACKGROUND_ACTIONS = {
        'test_ocr_output',
        'test_dict_ocr_output',
        'test_image_recognition',
        'test_color_recognition',
    }

    _HIDE_WINDOW_ACTIONS = {'test_image_recognition', 'test_color_recognition'}

    def _handle_button_click(self, name: str, param_def: Dict[str, Any]):
        """Handle button click."""
        widget_hint = param_def.get('widget_hint', '')
        action = param_def.get('action', '')

        if widget_hint == 'refresh_dynamic_options':
            self._handle_refresh_dynamic_options(param_def)
            return

        if not action:
            logger.warning(f"未处理的按钮点击: {name}, widget_hint: {widget_hint}")
            return

        logger.info(f"执行按钮action: {action}")
        action_func = self._resolve_button_action(action)
        if action_func is None:
            logger.debug(f"任务模块中未找到action函数: {action}")
            return

        try:
            current_params = self._collect_current_parameters()
            target_hwnd = self._get_button_action_target_hwnd()
            if self._should_run_action_in_background(action):
                self._start_background_action(action, action_func, current_params, target_hwnd)
                return

            result = self._invoke_button_action(action_func, current_params, target_hwnd)
            if result is False:
                logger.warning(f"执行action失败: {action}")
                return
            logger.info(f"成功执行action: {action}")
        except Exception as e:
            logger.error(f"执行action失败: {action}, 错误: {e}", exc_info=True)

    def _resolve_button_action(self, action: str):
        from ui.panels.actions.ui_button_actions import resolve_ui_button_action

        ui_action = resolve_ui_button_action(action)
        if ui_action is not None:
            return ui_action

        if hasattr(self, 'task_module') and self.task_module and hasattr(self.task_module, action):
            return getattr(self.task_module, action)

        if not hasattr(self, 'current_task_type') or not self.current_task_type:
            return None

        try:
            from tasks import get_task_module

            logger.debug(f"从 TASK_MODULES 查找 action: {action}，任务类型: {self.current_task_type}")
            task_module = get_task_module(self.current_task_type)
            if task_module is None:
                logger.debug(f"未找到任务类型 {self.current_task_type} 对应的模块")
                return None
            logger.debug(f"找到任务模块: {task_module}, 检查是否有 {action} 属性")
            if hasattr(task_module, action):
                logger.debug(f"成功找到 action 函数: {action}")
                return getattr(task_module, action)
        except Exception as e:
            logger.debug(f"从 TASK_MODULES 获取 action 时出错: {e}")
        return None

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

    def _start_background_action(self, action: str, action_func, current_params: Dict[str, Any], target_hwnd) -> None:
        import threading

        self._prepare_background_action_ui(action)

        def run_action_in_background():
            try:
                result = self._invoke_button_action(action_func, current_params, target_hwnd)
                if result is False:
                    logger.warning(f"后台执行action失败: {action}")
                    return
                logger.info(f"后台执行action成功: {action}")
            except Exception as e:
                logger.error(f"后台执行action失败: {action}, 错误: {e}", exc_info=True)

        thread = threading.Thread(target=run_action_in_background, daemon=True)
        thread.start()
        logger.info(f"已启动后台线程执行action: {action}")

    def _prepare_background_action_ui(self, action: str) -> None:
        if action not in self._HIDE_WINDOW_ACTIONS:
            return
        import time

        try:
            self.hide()
            if self.main_window:
                self.main_window.hide()
            time.sleep(0.2)
        except Exception as e:
            logger.warning(f"隐藏窗口失败: {e}")

    def _invoke_button_action(self, action_func, current_params: Dict[str, Any], target_hwnd):
        return action_func(
            current_params,
            target_hwnd=target_hwnd,
            main_window=self.main_window,
            parameter_panel=self,
        )
