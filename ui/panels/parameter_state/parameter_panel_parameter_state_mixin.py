import copy

import math

from ..parameter_panel_support import *
from ..thread_target_selector import ThreadTargetSelector

class ParameterPanelParameterStateMixin:

    _DATA_COMBO_WIDGET_HINTS = {
        'card_selector',
        'jump_target_selector',
        'thread_target_selector',
        'workflow_card_selector',
        'bound_window_selector',
    }

    def _extract_combobox_parameter_value(
        self,
        name: str,
        widget: QComboBox,
        for_submission: bool,
    ):
        if for_submission and widget.property("dynamic_loading"):
            raise ValueError(f"参数 {name} 的可选值尚未加载完成")
        if for_submission and widget.property("dynamic_error"):
            raise ValueError(f"参数 {name} 的可选值读取失败，请修正资源后重试")
        if for_submission and widget.currentIndex() < 0:
            raise ValueError(f"参数 {name} 没有有效的选项")
        if for_submission and widget.property("invalid_value") is not None and widget.currentData() == widget.property("invalid_value"):
            raise ValueError(f"参数 {name} 的当前选项无效")
        current_data = widget.currentData()
        param_def = self.param_definitions.get(name, {})
        widget_hint = param_def.get('widget_hint', '')
        if widget_hint in self._DATA_COMBO_WIDGET_HINTS:
            return current_data

        selected_value = current_data if current_data is not None else widget.currentText()
        return selected_value

    def _extract_line_edit_parameter_value(
        self,
        name: str,
        widget: QLineEdit,
        for_submission: bool,
    ):
        text_value = widget.text()
        param_def = self.param_definitions.get(name, {})
        param_type = param_def.get('type', 'text')

        if param_type in ['int', 'integer', 'float', 'double']:
            label = param_def.get('label', name)
            text = text_value.strip()
            if not text and not for_submission:
                return text_value
            if not text:
                raise ValueError(f"{label}不能为空")
            if re.search(r"\{\{[^{}]+\}\}", text):
                remainder = re.sub(r"\{\{[^{}]+\}\}", "", text)
                if "{{" in remainder or "}}" in remainder:
                    raise ValueError(f"{label}的变量表达式无效")
                return text_value
            try:
                value = int(text) if param_type in ['int', 'integer'] else float(text)
            except ValueError as exc:
                if not for_submission:
                    return text_value
                raise ValueError(f"{label}必须填写有效数字或变量表达式") from exc
            if not math.isfinite(value) and not for_submission:
                return text_value
            if not math.isfinite(value):
                raise ValueError(f"{label}必须是有限数字")
            if 'min' in param_def and value < param_def['min'] and for_submission:
                raise ValueError(f"{label}不能小于{param_def['min']}")
            if 'max' in param_def and value > param_def['max'] and for_submission:
                raise ValueError(f"{label}不能大于{param_def['max']}")
            return value

        return self._normalize_single_image_parameter_value(name, text_value)

    def _extract_list_widget_parameter_value(
        self,
        name: str,
        widget: QListWidget,
        restore_property: bool,
    ):
        raw_data = widget.property('raw_color_data')
        if raw_data:
            return raw_data

        existing_value = self.current_parameters.get(name)
        if existing_value and str(existing_value).strip():
            logger.debug(f'[COLOR_PARAM] keep current_parameters value for {name}: {existing_value}')
            if restore_property:
                widget.setProperty('raw_color_data', existing_value)
            return existing_value

        param_def = self.param_definitions.get(name, {})
        return param_def.get('default', '')

    def _extract_button_group_parameter_value(
        self,
        name: str,
        widget,
        prefer_existing_when_unchecked: bool,
    ):
        checked_button = widget.button_group.checkedButton()
        if checked_button:
            return checked_button.property('value')

        if prefer_existing_when_unchecked and name in self.current_parameters:
            return self.current_parameters.get(name)

        param_def = self.param_definitions.get(name, {})
        return param_def.get('default')

    @staticmethod
    def _extract_layout_parameter_value(widget):
        layout = widget.layout()
        if not layout or layout.count() <= 0:
            return None
        line_edit = layout.itemAt(0).widget()
        if not hasattr(line_edit, 'text'):
            return None
        return line_edit.text()

    def _extract_parameter_value_from_widget(
        self,
        name: str,
        widget,
        *,
        convert_image_paths: bool,
        prefer_existing_on_empty: bool,
        prefer_existing_on_invalid: bool,
        prefer_existing_when_unchecked: bool,
        allow_layout_widget: bool,
        allow_coordinate_selector: bool,
        restore_list_widget_property: bool,
        log_invalid_numeric: bool,
    ):
        if isinstance(widget, ThreadTargetSelector):
            return True, widget.value(for_submission=not prefer_existing_on_invalid)
        if isinstance(widget, QCheckBox):
            return True, widget.isChecked()
        if isinstance(widget, QSpinBox):
            return True, widget.value()
        if isinstance(widget, QDoubleSpinBox):
            return True, widget.value()
        if isinstance(widget, QComboBox):
            return True, self._extract_combobox_parameter_value(
                name,
                widget,
                for_submission=not prefer_existing_on_invalid,
            )
        if isinstance(widget, QPlainTextEdit):
            return True, widget.toPlainText()
        if isinstance(widget, QTextEdit):
            text_value = widget.toPlainText()
            if convert_image_paths and name == 'image_paths':
                text_value = self._convert_display_to_full_paths(text_value)
            return True, text_value
        if isinstance(widget, QLineEdit):
            return True, self._extract_line_edit_parameter_value(
                name,
                widget,
                for_submission=not prefer_existing_on_invalid,
            )
        if hasattr(widget, 'button_group'):
            return True, self._extract_button_group_parameter_value(
                name,
                widget,
                prefer_existing_when_unchecked=prefer_existing_when_unchecked,
            )
        if isinstance(widget, QListWidget):
            return True, self._extract_list_widget_parameter_value(
                name,
                widget,
                restore_property=restore_list_widget_property,
            )
        if allow_layout_widget and hasattr(widget, 'layout'):
            layout_value = self._extract_layout_parameter_value(widget)
            if layout_value is not None:
                return True, layout_value
        if allow_coordinate_selector:
            param_def = self.param_definitions.get(name, {})
            if (
                param_def.get('widget_hint', '') == 'coordinate_selector'
                and hasattr(widget, 'get_coordinate')
            ):
                coord_x, coord_y = widget.get_coordinate()
                return True, {'coordinate_x': coord_x, 'coordinate_y': coord_y}
        return False, None

    def _collect_hidden_apply_parameters(self, real_time_params: Dict[str, Any]) -> Dict[str, Any]:
        hidden_parameters = {}
        tracked_names = {
            'success_jump_target_id',
            'failure_jump_target_id',
            'recognition_region_x',
            'recognition_region_y',
            'recognition_region_width',
            'recognition_region_height',
        }
        for name, param_def in self.param_definitions.items():
            is_hidden = param_def.get('type') == 'hidden' or param_def.get('hidden')
            if not is_hidden and self._should_show_parameter(param_def, name):
                continue

            if name in self.current_parameters:
                current_value = self.current_parameters[name]
            elif name in real_time_params:
                current_value = real_time_params[name]
            else:
                current_value = param_def.get('default')
            hidden_parameters[name] = current_value
            if name in tracked_names:
                logger.info(f'[APPLY] collect hidden parameter {name} = {current_value}')
        return hidden_parameters

    def _collect_visible_apply_parameters(self) -> Dict[str, Any]:
        visible_parameters = {}
        for name, widget in self._iter_value_widgets():
            try:
                handled, value = self._extract_parameter_value_from_widget(
                    name,
                    widget,
                    convert_image_paths=True,
                    prefer_existing_on_empty=False,
                    prefer_existing_on_invalid=False,
                    prefer_existing_when_unchecked=False,
                    allow_layout_widget=False,
                    allow_coordinate_selector=True,
                    restore_list_widget_property=True,
                    log_invalid_numeric=True,
                )
                if not handled:
                    logger.warning(f'Unknown widget type: {type(widget)} for parameter {name}')
                    continue
                if isinstance(value, dict):
                    visible_parameters.update(value)
                    logger.info(
                        'Collect coordinates from selector: '
                        f'coordinate_x={value.get("coordinate_x")}, '
                        f'coordinate_y={value.get("coordinate_y")}'
                    )
                    continue
                visible_parameters[name] = value
                if name in ['success_jump_target_id', 'failure_jump_target_id']:
                    logger.info(f'[APPLY] collect selector parameter {name} = {value}')
            except Exception as error:
                logger.error(f'读取参数失败 {name}：{error}')
                raise
        return visible_parameters

    def _collect_condition_affecting_parameter_names(self) -> Set[str]:
        condition_affecting_params = set()
        for param_def in self.param_definitions.values():
            condition = param_def.get('condition', param_def.get('conditions'))
            if not condition:
                continue
            if isinstance(condition, list):
                for single_condition in condition:
                    if single_condition.get('param'):
                        condition_affecting_params.add(single_condition['param'])
                continue
            if condition.get('param'):
                condition_affecting_params.add(condition['param'])
            and_condition = condition.get('and')
            if not and_condition:
                continue
            if isinstance(and_condition, list):
                for and_cond in and_condition:
                    if and_cond.get('param'):
                        condition_affecting_params.add(and_cond['param'])
            elif and_condition.get('param'):
                condition_affecting_params.add(and_condition['param'])
        return condition_affecting_params

    def _has_conditional_parameter_changes(self, new_parameters: Dict[str, Any]) -> bool:
        for param_name in self._collect_condition_affecting_parameter_names():
            if (
                param_name in new_parameters
                and new_parameters[param_name] != self.current_parameters.get(param_name)
            ):
                return True
        return False

    def _apply_operation_mode_change_defaults(self, new_parameters: Dict[str, Any]) -> None:
        if 'operation_mode' not in new_parameters:
            return
        self._normalize_operation_mode_parameter(parameters=new_parameters)
        old_operation_mode = self.current_parameters.get('operation_mode')
        new_operation_mode = new_parameters['operation_mode']
        if old_operation_mode == new_operation_mode:
            return
        logger.info(
            f'Operation mode changed from {old_operation_mode} to '
            f'{new_operation_mode}, reset dependent parameters'
        )
        if 'multi_image_mode' in self.param_definitions:
            default_multi_mode = self.param_definitions['multi_image_mode']['default']
            new_parameters['multi_image_mode'] = default_multi_mode
            logger.info(f'Reset multi_image_mode to default: {default_multi_mode}')

    def _fill_missing_apply_defaults(self, new_parameters: Dict[str, Any]) -> None:
        for param_name, param_def in self.param_definitions.items():
            if param_name in new_parameters or 'default' not in param_def:
                continue
            if param_name in self.current_parameters:
                current_value = self.current_parameters[param_name]
                new_parameters[param_name] = current_value
                logger.debug(f'[APPLY] keep existing parameter {param_name}: {current_value}')
                continue
            default_value = param_def['default']
            new_parameters[param_name] = default_value
            logger.debug(f'[APPLY] fill default parameter {param_name}: {default_value}')

    def _preserve_internal_apply_parameters(self, new_parameters: Dict[str, Any]) -> None:
        for key, value in self.current_parameters.items():
            if key.startswith('_') and key not in new_parameters:
                new_parameters[key] = value
                logger.debug(f'[APPLY] preserve internal parameter: {key}')

    def _apply_live_parameter_changes(
        self,
        changes: Dict[str, Any],
        *,
        refresh_conditional: bool = True,
    ) -> None:
        if not changes:
            return
        from ui.panels.parameter_compare import collect_changed_parameters

        changes = dict(changes)
        self._apply_operation_mode_change_defaults(changes)
        real_changes = collect_changed_parameters(self.current_parameters, changes)
        self.current_parameters.update(changes)
        if getattr(self, "_loading_parameter_panel", False):
            return
        if not real_changes:
            return
        if self.current_card_id is not None:
            self.parameters_changed.emit(self.current_card_id, dict(real_changes))
        if refresh_conditional:
            self._refresh_conditional_widgets(changes)

    def _apply_parameters(self, auto_close=True):
        if self.current_task_type == "脚本卡片":
            self._plugin_parameter_controller.apply(auto_close)
            return
        if self._apply_favorites_parameters(auto_close):
            return

        if self.current_card_id is None:
            logger.warning('Current card id is empty, cannot apply parameters')
            return

        real_time_params = self._get_real_time_card_parameters()
        new_parameters = self._collect_hidden_apply_parameters(real_time_params)
        new_parameters.update(self._collect_visible_apply_parameters())

        needs_update = self._has_conditional_parameter_changes(new_parameters)
        self._apply_operation_mode_change_defaults(new_parameters)
        self._fill_missing_apply_defaults(new_parameters)
        self._preserve_internal_apply_parameters(new_parameters)
        if not self._validate_script_parameters(new_parameters):
            return

        self.current_parameters.update(new_parameters)
        if needs_update:
            self._update_conditional_display()

        if not getattr(self, "_loading_parameter_panel", False):
            from ui.panels.parameter_compare import collect_changed_parameters

            if collect_changed_parameters(real_time_params, new_parameters):
                self.parameters_changed.emit(self.current_card_id, new_parameters)
        if auto_close:
            self._finish_hiding_panel()

    def _validate_script_parameters(self, parameters: Dict[str, Any]) -> bool:
        if str(getattr(self, "current_task_type", "") or "").strip() != "自定义脚本":
            return True
        source = str((parameters or {}).get("script_source") or "").strip()
        if not source:
            return True
        try:
            from tasks.script_task import validate_script_source

            validate_script_source(source)
            return True
        except Exception as exc:
            QMessageBox.warning(self, "语法检查", str(exc))
            return False

    def _apply_favorites_parameters(self, auto_close: bool) -> bool:
        if not getattr(self, '_favorites_mode', False):
            return False
        self._save_favorites_config()
        self._sync_favorites_tabs()
        if auto_close:
            self.hide_panel()
        return True

    def _get_real_time_card_parameters(self) -> dict:
        """独立面板使用自身状态；挂接主窗口时只从现行标签页读取卡片。"""
        if self.main_window is None or self.current_card_id is None:
            return self.current_parameters.copy()
        tab_widget = self.main_window.workflow_tab_widget
        task_id = tab_widget.get_current_task_id()
        view = tab_widget.task_views.get(task_id)
        if view is None or self.current_card_id not in view.cards:
            raise ValueError(f"当前工作流中不存在卡片 {self.current_card_id}，无法读取参数")
        if self._runtime_workflow_identity != (id(self.main_window), task_id):
            raise ValueError("参数面板所属工作流已切换，请重新打开卡片")
        return view.cards[self.current_card_id].parameters.copy()

    def cache_runtime_parameter(self, card_id: int, param_name: str, value: Any) -> None:
        """缓存运行时参数值（仅用于显示，不写入工作流文件）。"""
        if card_id is None or not param_name:
            return
        key = (card_id, param_name)
        self.runtime_parameters.pop(key, None)
        self.runtime_parameters[key] = value
        while len(self.runtime_parameters) > 512:
            self.runtime_parameters.pop(next(iter(self.runtime_parameters)))

    def _get_runtime_parameter(self, card_id: int, param_name: str) -> Any:
        """从当前任务模块读取运行时显示值。"""
        runtime_value = None
        if self.task_module and hasattr(self.task_module, 'get_runtime_parameter'):
            try:
                runtime_value = self.task_module.get_runtime_parameter(card_id, param_name)
            except Exception as exc:
                logger.debug(f"[运行时参数] 获取失败: {exc}")
        return runtime_value

    def update_parameter_value(self, param_name: str, value: Any) -> None:
        """更新指定参数的显示值（不写回工作流文件）。"""
        if not param_name:
            return
        text_value = "" if value is None else str(value)
        self.current_parameters[param_name] = value
        widget = self._get_value_widget(param_name)
        if not widget:
            return
        try:
            widget.blockSignals(True)
            if hasattr(widget, "setPlainText"):
                widget.setPlainText(text_value)
            elif hasattr(widget, "setText"):
                widget.setText(text_value)
        finally:
            widget.blockSignals(False)

    def refresh_runtime_parameters(self, card_id: Optional[int] = None) -> None:
        """从任务模块刷新运行时参数显示。"""
        if not self.task_module or not hasattr(self.task_module, 'get_runtime_parameter'):
            return
        if card_id is None:
            card_id = self.current_card_id
        if card_id is None:
            return
        for param_name, param_def in self.param_definitions.items():
            if param_def.get('save_to_workflow', True):
                continue
            runtime_value = self._get_runtime_parameter(card_id, param_name)
            if runtime_value is None:
                continue
            self.cache_runtime_parameter(card_id, param_name, runtime_value)
            if self.current_card_id == card_id:
                self.update_parameter_value(param_name, runtime_value)

    def _reset_parameters(self):
        if self.current_task_type == "脚本卡片":
            from ui.panels.card_plugin_state import reset_card_plugin_parameters
            reset_card_plugin_parameters(self)
            return
        if not self.param_definitions:
            return
        self._release_panel_runtime()
        values = {
            name: copy.deepcopy(definition['default'])
            for name, definition in self.param_definitions.items()
            if 'default' in definition and definition.get('save_to_workflow', True)
        }
        for name, definition in self.param_definitions.items():
            if definition.get('type') == 'hidden' and 'default' not in definition and name in self.current_parameters:
                values[name] = copy.deepcopy(self.current_parameters[name])
        if '_random_connections' in self.current_parameters:
            values['_random_connections'] = copy.deepcopy(self.current_parameters['_random_connections'])
        self.current_parameters = values
        self.runtime_parameters = {key: value for key, value in self.runtime_parameters.items() if key[0] != self.current_card_id}
        self._rebuild_parameter_widgets(preserve_scroll=False)
        self._check_and_register_record_hotkey()
        if self.current_card_id is not None:
            self.parameters_changed.emit(self.current_card_id, copy.deepcopy(self.current_parameters))

    def _collect_current_parameters(self) -> Dict[str, Any]:
        if self.current_task_type == "脚本卡片":
            return self._plugin_parameter_controller.collect()
        parameters = {}
        self._collect_hidden_saved_parameters(parameters)
        self._collect_visible_workflow_parameters(parameters)
        self._fill_missing_workflow_parameters(parameters)
        self._normalize_operation_mode_parameter(parameters=parameters)
        return parameters

    def _collect_hidden_saved_parameters(self, parameters: Dict[str, Any]) -> None:
        for name, param_def in self.param_definitions.items():
            if param_def.get('type') == 'hidden':
                parameters[name] = self.current_parameters.get(name, param_def.get('default'))

    def _collect_visible_workflow_parameters(self, parameters: Dict[str, Any]) -> None:
        for name, widget in self._iter_value_widgets():
            try:
                param_def = self.param_definitions.get(name, {})
                if not param_def.get('save_to_workflow', True):
                    continue
                handled, value = self._extract_parameter_value_from_widget(
                    name,
                    widget,
                    convert_image_paths=False,
                    prefer_existing_on_empty=True,
                    prefer_existing_on_invalid=True,
                    prefer_existing_when_unchecked=True,
                    allow_layout_widget=True,
                    allow_coordinate_selector=False,
                    restore_list_widget_property=False,
                    log_invalid_numeric=False,
                )
                if not handled:
                    logger.debug(f"Unhandled widget type: {name} - {type(widget)}")
                    continue
                if isinstance(value, dict):
                    parameters.update(value)
                else:
                    parameters[name] = value
            except Exception as e:
                logger.error(f"收集参数失败 {name}：{e}")
                raise

    def _fill_missing_workflow_parameters(self, parameters: Dict[str, Any]) -> None:
        for name, param_def in self.param_definitions.items():
            if name in parameters:
                continue
            if not param_def.get('save_to_workflow', True):
                continue
            if name in self.current_parameters:
                parameters[name] = self.current_parameters[name]
            else:
                parameters[name] = param_def.get('default')

    def _apply_parameters_from_ui(self):
        try:
            self._apply_parameters(auto_close=True)
        except (ValueError, TypeError) as error:
            QMessageBox.warning(self, "参数无效", str(error))

    def _reset_parameters_from_ui(self):
        try:
            self._reset_parameters()
        except Exception as error:
            logger.error("重置参数失败：%s", error, exc_info=True)
            QMessageBox.warning(self, "重置失败", str(error))
