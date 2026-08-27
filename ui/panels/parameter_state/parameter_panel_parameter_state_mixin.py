from ..parameter_panel_support import *

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
        normalize_operation_mode: bool = False,
    ):
        current_data = widget.currentData()
        param_def = self.param_definitions.get(name, {})
        widget_hint = param_def.get('widget_hint', '')
        if widget_hint in self._DATA_COMBO_WIDGET_HINTS:
            return current_data

        selected_value = current_data if current_data is not None else widget.currentText()
        if normalize_operation_mode and name == 'operation_mode':
            selected_value = self._normalize_operation_mode_value(
                selected_value,
                fallback_task_type=self.current_task_type or '',
            )
        return selected_value

    def _extract_line_edit_parameter_value(
        self,
        name: str,
        widget: QLineEdit,
        prefer_existing_on_empty: bool,
        prefer_existing_on_invalid: bool,
        log_invalid: bool,
    ):
        text_value = widget.text()
        param_def = self.param_definitions.get(name, {})
        param_type = param_def.get('type', 'text')

        if param_type in ['int', 'integer']:
            existing_value = self.current_parameters.get(name, param_def.get('default', 0))
            if not text_value:
                return existing_value if prefer_existing_on_empty else 0
            try:
                return int(text_value)
            except ValueError:
                if log_invalid:
                    logger.warning(f'Invalid int value for {name}: {text_value}')
                return existing_value if prefer_existing_on_invalid else param_def.get('default', 0)

        if param_type in ['float', 'double']:
            existing_value = self.current_parameters.get(name, param_def.get('default', 0.0))
            if not text_value:
                return existing_value if prefer_existing_on_empty else 0.0
            try:
                return float(text_value)
            except ValueError:
                if log_invalid:
                    logger.warning(f'Invalid float value for {name}: {text_value}')
                return existing_value if prefer_existing_on_invalid else param_def.get('default', 0.0)

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
        normalize_operation_mode: bool,
        convert_image_paths: bool,
        prefer_existing_on_empty: bool,
        prefer_existing_on_invalid: bool,
        prefer_existing_when_unchecked: bool,
        allow_layout_widget: bool,
        allow_coordinate_selector: bool,
        restore_list_widget_property: bool,
        log_invalid_numeric: bool,
    ):
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
                normalize_operation_mode,
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
                prefer_existing_on_empty=prefer_existing_on_empty,
                prefer_existing_on_invalid=prefer_existing_on_invalid,
                log_invalid=log_invalid_numeric,
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
                    normalize_operation_mode=True,
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
        old_operation_mode = self._normalize_operation_mode_value(
            self.current_parameters.get('operation_mode'),
            fallback_task_type=self.current_task_type or '',
        )
        new_operation_mode = self._normalize_operation_mode_value(
            new_parameters['operation_mode'],
            fallback_task_type=self.current_task_type or '',
        )
        new_parameters['operation_mode'] = new_operation_mode
        if old_operation_mode == new_operation_mode:
            return
        logger.info(
            f'Operation mode changed from {old_operation_mode} to '
            f'{new_operation_mode}, reset dependent parameters'
        )
        if 'multi_image_mode' in self.param_definitions:
            default_multi_mode = self.param_definitions['multi_image_mode'].get(
                'default',
                '单图识别',
            )
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

        real_changes = collect_changed_parameters(self.current_parameters, changes)
        self.current_parameters.update(changes)
        if getattr(self, "_loading_parameter_panel", False):
            return
        if not real_changes:
            return
        if self.current_card_id is not None:
            self.parameters_changed.emit(self.current_card_id, dict(real_changes))
        if refresh_conditional:
            self._refresh_conditional_widgets()

    def _apply_parameters(self, auto_close=True):
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
            self.hide_panel()

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
        """
        从卡片实时读取最新参数

        这个方法确保获取卡片的实时参数，而不是使用缓存的 current_parameters
        这样可以捕获在参数面板打开期间，通过其他方式（如删除连线）修改的参数

        Returns:
            dict: 卡片的实时参数，如果无法获取则返回缓存的参数
        """
        try:
            # 首先尝试从主窗口获取当前的workflow_view
            current_workflow_view = None
            if hasattr(self, 'main_window') and self.main_window:
                # 尝试从标签页系统获取
                if hasattr(self.main_window, 'workflow_tab_widget') and self.main_window.workflow_tab_widget:
                    current_task_id = self.main_window.workflow_tab_widget.get_current_task_id()
                    if current_task_id is not None and current_task_id in self.main_window.workflow_tab_widget.task_views:
                        current_workflow_view = self.main_window.workflow_tab_widget.task_views[current_task_id]
                        logger.debug("[实时参数] 从主窗口标签页获取workflow_view")

                # 回退到旧系统
                if current_workflow_view is None and hasattr(self.main_window, 'workflow_view'):
                    current_workflow_view = self.main_window.workflow_view
                    logger.debug("[实时参数] 从主窗口旧系统获取workflow_view")

            # 在获取的workflow_view中查找卡片
            if current_workflow_view and hasattr(current_workflow_view, 'cards'):
                if self.current_card_id in current_workflow_view.cards:
                    card = current_workflow_view.cards[self.current_card_id]
                    if hasattr(card, 'parameters'):
                        logger.debug(f"[实时参数] 从卡片 {self.current_card_id} 读取实时参数成功")
                        return card.parameters.copy()

            # 如果无法获取实时参数，回退到缓存参数
            logger.debug(f"[实时参数] 无法读取卡片 {self.current_card_id} 的实时参数，使用缓存参数")
            return self.current_parameters.copy()

        except Exception as e:
            logger.warning(f"[实时参数] 读取实时参数失败: {e}，使用缓存参数")
            return self.current_parameters.copy()

    def cache_runtime_parameter(self, card_id: int, param_name: str, value: Any) -> None:
        """缓存运行时参数值（仅用于显示，不写入工作流文件）。"""
        if card_id is None or not param_name:
            return
        self.runtime_parameters[(card_id, param_name)] = value

    def _get_runtime_parameter(self, card_id: int, param_name: str) -> Any:
        """获取运行时参数值，优先使用任务模块，必要时回退到模块缓存。"""
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

    def _reset_widget_to_default(self, widget, default_value, param_def):
        if isinstance(widget, QCheckBox):
            widget.setChecked(bool(default_value) if default_value is not None else False)
        elif isinstance(widget, QSpinBox):
            widget.setValue(int(default_value) if default_value is not None else 0)
        elif isinstance(widget, QDoubleSpinBox):
            widget.setValue(float(default_value) if default_value is not None else 0.0)
        elif isinstance(widget, QLineEdit):
            widget.clear() if (default_value is None or default_value == "") else widget.setText(str(default_value))
        elif isinstance(widget, (QPlainTextEdit, QTextEdit)):
            widget.clear() if (default_value is None or default_value == "") else widget.setPlainText(str(default_value))
        elif isinstance(widget, QComboBox):
            self._reset_combobox_to_default(widget, default_value, param_def)
        elif isinstance(widget, QSlider):
            widget.setValue(int(default_value) if default_value is not None else 0)
        elif isinstance(widget, QListWidget):
            widget.clear()
            if widget.property("raw_color_data") is not None:
                widget.setProperty("raw_color_data", "")
        elif hasattr(widget, 'button_group'):
            if default_value is not None:
                for button in widget.button_group.buttons():
                    if button.text() == str(default_value):
                        button.setChecked(True)
                        break
        elif hasattr(widget, 'clear_colors'):
            widget.clear_colors()
        elif hasattr(widget, 'clear'):
            try:
                widget.clear()
            except Exception:
                pass

    def _reset_combobox_to_default(self, combo_widget, default_value, param_def):
        current_count = combo_widget.count()
        initial_options = param_def.get('options', [])
        if initial_options and current_count != len(initial_options):
            combo_widget.clear()
            combo_widget.addItems(initial_options)

        if default_value is not None:
            index = combo_widget.findData(default_value)
            if index >= 0:
                combo_widget.setCurrentIndex(index)
            else:
                idx = combo_widget.findText(str(default_value))
                combo_widget.setCurrentIndex(idx if idx >= 0 else 0)
        else:
            combo_widget.setCurrentIndex(0)

    def _reset_parameters(self):
        if not self.param_definitions:
            return

        logger.info("Start resetting parameters")
        tool_position_params = self._get_reset_tool_position_params()
        extra_hidden_params = self._get_reset_extra_hidden_params()

        self._reinitialize_reset_parameter_values(tool_position_params)
        reset_count = self._reset_parameter_widgets(tool_position_params)
        logger.info(f"Reset {reset_count} UI widgets")

        self._run_reset_cleanup_pipeline(tool_position_params, extra_hidden_params)
        self._emit_reset_parameter_state()
        logger.info("Parameter reset finished")

    def _get_reset_tool_position_params(self) -> Set[str]:
        return {
            'scroll_start_position',
            'drag_start_position', 'drag_end_position',
            'move_start_position', 'move_end_position',
        }

    def _get_reset_extra_hidden_params(self) -> List[str]:
        return [
            'recorded_actions',
            'minimap_x', 'minimap_y', 'minimap_width', 'minimap_height',
            'region_x', 'region_y', 'region_width', 'region_height',
            'region_hwnd', 'region_window_title', 'region_window_class', 'region_client_width', 'region_client_height',
            'region_x1', 'region_y1', 'region_x2', 'region_y2',
            'target_supports_counter',
            'recognition_region_x', 'recognition_region_y', 'recognition_region_width', 'recognition_region_height',
            'search_region_x', 'search_region_y', 'search_region_width', 'search_region_height',
            'connected_targets',
            'motion_detection_region',
            'region_coordinates',
            'combo_mouse_x', 'combo_mouse_y',
            'combo_seq_mouse_x', 'combo_seq_mouse_y',
            'anchor_point',
        ]

    def _reinitialize_reset_parameter_values(self, tool_position_params: Set[str]) -> None:
        self.current_parameters.clear()
        for name, param_def in self.param_definitions.items():
            param_type = param_def.get('type', 'text')
            if param_type in ('hidden', 'separator'):
                continue
            if name in tool_position_params:
                self.current_parameters[name] = ""
            else:
                self.current_parameters[name] = param_def.get('default')

    def _reset_parameter_widgets(self, tool_position_params: Set[str]) -> int:
        reset_count = 0
        for name, param_def in self.param_definitions.items():
            param_type = param_def.get('type', 'text')
            if param_type in ('hidden', 'separator'):
                continue
            if name not in self.widgets:
                continue

            widget = self.widgets[name]
            default_value = param_def.get('default')
            try:
                if name in tool_position_params:
                    if isinstance(widget, QLineEdit):
                        widget.clear()
                    reset_count += 1
                    continue
                self._reset_widget_to_default(widget, default_value, param_def)
                reset_count += 1
            except Exception as e:
                logger.error(f"重置控件失败 {name}：{e}")
        return reset_count

    def _run_reset_cleanup_pipeline(self, tool_position_params: Set[str], extra_hidden_params: List[str]) -> None:
        self._clear_image_previews()
        self._cleanup_keyboard_parameters()
        self._cleanup_extra_hidden_params(extra_hidden_params)
        self._cleanup_all_card_parameters()
        self._ensure_tool_position_params_cleared(tool_position_params)
        self._cleanup_workflow_context()
        self._reset_action_control_buttons()

    def _ensure_tool_position_params_cleared(self, tool_position_params: Set[str]) -> None:
        for param_name in tool_position_params:
            if param_name in self.current_parameters and self.current_parameters[param_name] != "":
                self.current_parameters[param_name] = ""
                logger.debug(f"Tool position parameter cleared: {param_name}")

    def _emit_reset_parameter_state(self) -> None:
        if self.current_card_id is not None:
            logger.info(f"Emit reset parameter signal: card_id={self.current_card_id}")
            self.parameters_changed.emit(self.current_card_id, self.current_parameters.copy())
        QTimer.singleShot(100, self._refresh_conditional_widgets)

    def _clear_image_previews(self):
        for widget_name, widget in list(self.widgets.items()):
            if widget_name.endswith('_preview') and isinstance(widget, QLabel):
                widget.setText("未选择图片")
                widget.setPixmap(QPixmap())
                widget.setProperty("image_path", "")

    def _cleanup_keyboard_parameters(self):
        keyboard_params = [
            'key', 'hotkey', 'key_combination', 'combo_keys', 'combo_seq_keys',
            'record_hotkey', 'replay_hotkey', 'trigger_key', 'stop_key',
        ]
        cleared_count = 0
        for param_name in keyboard_params:
            if param_name in self.current_parameters:
                self.current_parameters[param_name] = ""
                cleared_count += 1
            if param_name in self.widgets:
                widget = self.widgets[param_name]
                try:
                    self._reset_widget_to_default(widget, self.param_definitions.get(param_name, {}).get('default'), self.param_definitions.get(param_name, {}))
                except Exception as e:
                    logger.debug(f"重置键盘控件失败 {param_name}：{e}")
        if cleared_count > 0:
            logger.info(f"Cleared {cleared_count} keyboard-related parameters")

    def _cleanup_extra_hidden_params(self, extra_hidden_params):
        cleared_count = 0
        for param_name in extra_hidden_params:
            if param_name in self.current_parameters:
                del self.current_parameters[param_name]
                cleared_count += 1
            if param_name in self.widgets:
                widget = self.widgets[param_name]
                if isinstance(widget, QLineEdit):
                    widget.clear()
        if cleared_count > 0:
            logger.info(f"Cleared {cleared_count} extra hidden parameters")

    def _cleanup_all_card_parameters(self):
        if self.current_card_id is None:
            return
        try:
            main_window = None
            current_widget = self.parent()
            level = 0
            while current_widget and level < 10:
                if hasattr(current_widget, 'cards') or hasattr(current_widget, 'workflow_data'):
                    main_window = current_widget
                    break
                current_widget = current_widget.parent()
                level += 1
            if not main_window:
                logger.debug("未找到主窗口，跳过卡片参数清理")
                return
            card_id = self.current_card_id
            if hasattr(main_window, 'workflow_data') and isinstance(main_window.workflow_data, dict):
                if 'cards' in main_window.workflow_data:
                    cards = main_window.workflow_data['cards']
                    if isinstance(cards, list):
                        for card in cards:
                            if isinstance(card, dict) and card.get('id') == card_id:
                                if 'parameters' in card:
                                    old_param_count = len(card['parameters'])
                                    card['parameters'].clear()
                                    logger.info(f"Cleared {old_param_count} stored parameters for card {card_id}")
                                break
            elif hasattr(main_window, 'cards') and isinstance(main_window.cards, dict):
                if card_id in main_window.cards:
                    card = main_window.cards[card_id]
                    if 'parameters' in card:
                        old_param_count = len(card['parameters'])
                        card['parameters'].clear()
                        logger.info(f"Cleared {old_param_count} stored parameters for card {card_id}")
        except Exception as e:
            logger.debug(f"Non-fatal error during stored parameter cleanup: {e}")

    def _cleanup_workflow_context(self):
        if self.current_card_id is None:
            return
        try:
            from task_workflow.workflow_context import get_workflow_context
            context = get_workflow_context()
            card_id = self.current_card_id
            logger.info(f"Start clearing workflow context for card {card_id}")

            cleared_stats = {
                'card_data_keys': 0,
                'ocr_results': 0,
                'image_results': False,
            }

            self._cleanup_context_card_data(context, card_id, cleared_stats)
            self._cleanup_context_ocr_results(context, card_id, cleared_stats)
            self._cleanup_context_image_results(context, card_id, cleared_stats)
            self._log_context_cleanup_result(context, card_id, cleared_stats)
        except Exception as e:
            logger.error(f"工作流上下文清理失败：{e}", exc_info=True)

    def _cleanup_context_card_data(self, context, card_id: int, cleared_stats: Dict[str, Any]) -> None:
        if card_id not in context.card_data:
            return
        card_data = context.card_data[card_id]
        cleared_stats['card_data_keys'] = len(card_data)
        card_data_keys = list(card_data.keys())
        logger.info(f"Card {card_id} card_data keys: {card_data_keys}")
        function_related_keys = [k for k in card_data_keys if any(kw in k.lower() for kw in ['multi', 'group', 'function', 'state', 'index'])]
        if function_related_keys:
            logger.info(f"Detected multi-function related keys: {function_related_keys}")
        del context.card_data[card_id]
        logger.info(f"Removed context.card_data for card {card_id}, total keys: {len(card_data_keys)}")

    def _cleanup_context_ocr_results(self, context, card_id: int, cleared_stats: Dict[str, Any]) -> None:
        if card_id not in context.ocr_results:
            return
        cleared_stats['ocr_results'] = len(context.ocr_results[card_id])
        del context.ocr_results[card_id]
        logger.info(f"Removed context.ocr_results for card {card_id}, count: {cleared_stats['ocr_results']}")

    def _cleanup_context_image_results(self, context, card_id: int, cleared_stats: Dict[str, Any]) -> None:
        if card_id not in context.image_results:
            return
        cleared_stats['image_results'] = True
        del context.image_results[card_id]
        logger.info(f"Removed context.image_results for card {card_id}")

    def _log_context_cleanup_result(self, context, card_id: int, cleared_stats: Dict[str, Any]) -> None:
        all_cleared = (
            card_id not in context.card_data and
            card_id not in context.ocr_results and
            card_id not in context.image_results
        )
        if all_cleared:
            cleared_summary = []
            if cleared_stats['card_data_keys'] > 0:
                cleared_summary.append(f"card_data({cleared_stats['card_data_keys']} keys)")
            if cleared_stats['ocr_results'] > 0:
                cleared_summary.append(f"ocr_results({cleared_stats['ocr_results']} items)")
            if cleared_stats['image_results']:
                cleared_summary.append("image_results")
            if cleared_summary:
                logger.info(f"Context cleanup verified for card {card_id}: {', '.join(cleared_summary)}")
            else:
                logger.info(f"Card {card_id} has no context data to clear")
            return
        remaining = []
        if card_id in context.card_data:
            remaining_keys = list(context.card_data[card_id].keys())
            remaining.append(f"card_data({remaining_keys})")
        if card_id in context.ocr_results:
            remaining.append(f"ocr_results({len(context.ocr_results[card_id])})")
        if card_id in context.image_results:
            remaining.append("image_results")
        logger.warning(f"Context cleanup incomplete for card {card_id}: {remaining}")

    def _collect_current_parameters(self) -> Dict[str, Any]:
        parameters = {}
        self._collect_hidden_saved_parameters(parameters)
        self._collect_visible_workflow_parameters(parameters)
        self._fill_missing_workflow_parameters(parameters)
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
                    normalize_operation_mode=False,
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
                param_def = self.param_definitions.get(name, {})
                parameters[name] = param_def.get('default')

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
