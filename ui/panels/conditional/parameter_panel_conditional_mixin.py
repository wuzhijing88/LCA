from ..parameter_panel_support import *

class ParameterPanelConditionalMixin:

    def _refresh_conditional_widgets(self):
        """刷新条件控件的显示/隐藏状态"""
        # 保存当前滚动位置
        scroll_pos = 0
        if hasattr(self, 'scroll_area') and self.scroll_area.verticalScrollBar():
            scroll_pos = self.scroll_area.verticalScrollBar().value()

        # 先从卡片实时读取最新参数，确保不丢失未显示的参数值（如跳转目标）
        real_time_params = self._get_real_time_card_parameters()

        # 收集当前控件的值
        collected_params = self._collect_current_parameters()

        # 合并参数到current_parameters
        # 优先级：控件值 > 实时参数 > 当前缓存
        # 但对于card_selector，优先使用实时参数，避免刚创建的控件覆盖正确值

        # 1. 先用实时参数更新current_parameters（保底，确保所有参数都有值）
        for name, value in real_time_params.items():
            if value is not None:
                self.current_parameters[name] = value
                if name in ['success_jump_target_id', 'failure_jump_target_id']:
                    logger.info(f"[REFRESH] 从实时参数更新 {name} = {value}")

        # 2. 再用控件值更新（用户在界面上的修改优先）
        for name, value in collected_params.items():
            param_def = self.param_definitions.get(name, {})
            widget_hint = param_def.get('widget_hint', '')
            # 对于card_selector，只在控件值非None时更新，避免覆盖实时参数
            if widget_hint in ['card_selector', 'jump_target_selector']:
                if value is not None:
                    self.current_parameters[name] = value
                    if name in ['success_jump_target_id', 'failure_jump_target_id']:
                        logger.info(f"[REFRESH] 从控件更新 {name} = {value}")
            else:
                # 其他类型的参数直接更新
                self.current_parameters[name] = value

        # 先清除现有的控件
        self._clear_content()

        # 重新创建参数控件；重建时禁止把初始化信号当成用户改参
        was_loading = getattr(self, "_loading_parameter_panel", False)
        self._loading_parameter_panel = True
        try:
            self._create_parameter_widgets()
        finally:
            self._loading_parameter_panel = was_loading

        # 恢复滚动位置
        if hasattr(self, 'scroll_area') and self.scroll_area.verticalScrollBar():
            QTimer.singleShot(10, lambda: self.scroll_area.verticalScrollBar().setValue(scroll_pos))

    def _rebuild_parameter_widgets(self, preserve_scroll: bool = True):
        """仅重建参数控件（不回收/合并参数值）"""
        scroll_pos = 0
        if preserve_scroll and hasattr(self, 'scroll_area') and self.scroll_area.verticalScrollBar():
            scroll_pos = self.scroll_area.verticalScrollBar().value()

        self._clear_content()
        was_loading = getattr(self, "_loading_parameter_panel", False)
        self._loading_parameter_panel = True
        try:
            self._create_parameter_widgets()
        finally:
            self._loading_parameter_panel = was_loading

        if preserve_scroll and hasattr(self, 'scroll_area') and self.scroll_area.verticalScrollBar():
            QTimer.singleShot(10, lambda: self.scroll_area.verticalScrollBar().setValue(scroll_pos))

    @staticmethod
    def _click_rule_to_bool(value, default=True):
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        if isinstance(value, (int, float)):
            return value != 0
        text = str(value).strip().lower()
        if text in {'true', '1', 'yes', 'on', '是', '启用'}:
            return True
        if text in {'false', '0', 'no', 'off', '否', '禁用'}:
            return False
        return default

    _MOUSE_IMAGE_CLICK_PARAMS = {
        '---common_click_params---',
        'button',
        'clicks',
        'interval',
        'image_position_mode',
        'image_offset_selector_tool',
        'image_fixed_offset_x',
        'image_fixed_offset_y',
        'image_random_offset_x',
        'image_random_offset_y',
        'image_click_action',
        'image_enable_auto_release',
        'image_hold_mode',
        'image_hold_duration',
        'image_hold_duration_min',
        'image_hold_duration_max',
    }

    _MOUSE_COLOR_CLICK_PARAMS = {
        'click_position_mode',
        'color_offset_selector_tool',
        'color_fixed_offset_x',
        'color_fixed_offset_y',
        'color_random_offset_x',
        'color_random_offset_y',
        'color_click_button',
        'color_click_clicks',
        'color_click_interval',
        'color_click_action',
        'color_enable_auto_release',
        'color_hold_mode',
        'color_hold_duration',
        'color_hold_duration_min',
        'color_hold_duration_max',
    }

    _MOUSE_TEXT_CLICK_PARAMS = {
        '---common_click_params---',
        'button',
        'clicks',
        'interval',
        'text_position_mode',
        'text_offset_selector_tool',
        'text_fixed_offset_x',
        'text_fixed_offset_y',
        'text_random_offset_x',
        'text_random_offset_y',
        'text_click_action',
        'text_enable_auto_release',
        'text_hold_mode',
        'text_hold_duration',
        'text_hold_duration_min',
        'text_hold_duration_max',
    }

    _MOUSE_COORDINATE_CLICK_PARAMS = {
        '---common_click_params---',
        'button',
        'clicks',
        'interval',
        'coordinate_position_mode',
        'coordinate_offset_selector_tool',
        'coordinate_fixed_offset_x',
        'coordinate_fixed_offset_y',
        'coordinate_random_offset_x',
        'coordinate_random_offset_y',
        'coordinate_click_action',
        'coordinate_enable_auto_release',
        'coordinate_hold_mode',
        'coordinate_hold_duration',
        'coordinate_hold_duration_min',
        'coordinate_hold_duration_max',
    }

    _MOUSE_ELEMENT_CLICK_PARAMS = {
        'element_use_invoke',
        'element_button',
    }

    _FIND_IMAGE_CLICK_PARAMS = {
        '---click_offset---',
        'button',
        'click_action',
        'enable_auto_release',
        'hold_duration',
        'clicks',
        'interval',
        'offset_selector_tool',
        'image_position_mode',
        'fixed_offset_x',
        'fixed_offset_y',
        'random_offset_x',
        'random_offset_y',
    }

    _COORDINATE_CLICK_TASK_PARAMS = {
        '---click_settings---',
        'button',
        'click_action',
        'hold_duration',
        'clicks',
        'interval',
        '---click_offset---',
        'offset_selector_tool',
        'position_mode',
        'fixed_offset_x',
        'fixed_offset_y',
        'random_offset_x',
        'random_offset_y',
    }

    def _should_hide_click_related_parameter(self, param_name: str) -> bool:
        """根据找图/找色点击开关，隐藏点击相关参数。"""
        if not param_name:
            return False

        current_task_type = str(getattr(self, 'current_task_type', '') or '').strip()
        current_params = getattr(self, 'current_parameters', {}) or {}

        if current_task_type == '模拟鼠标操作':
            return self._should_hide_mouse_operation_click_parameter(param_name, current_task_type, current_params)

        if current_task_type in {'图片点击', '查找图片并点击'}:
            return self._should_hide_simple_click_task_parameter(
                param_name,
                current_params,
                self._FIND_IMAGE_CLICK_PARAMS,
            )

        if current_task_type in {'点击指定坐标', '坐标点击', '点击坐标'}:
            return self._should_hide_simple_click_task_parameter(
                param_name,
                current_params,
                self._COORDINATE_CLICK_TASK_PARAMS,
            )

        return False

    def _should_hide_mouse_operation_click_parameter(
        self,
        param_name: str,
        current_task_type: str,
        current_params: Dict[str, Any],
    ) -> bool:
        operation_mode = self._normalize_operation_mode_value(
            current_params.get('operation_mode', ''),
            fallback_task_type=current_task_type,
        )
        rule_mapping = {
            '找图功能': ('image_enable_click', self._MOUSE_IMAGE_CLICK_PARAMS),
            '找色功能': ('color_enable_click', self._MOUSE_COLOR_CLICK_PARAMS),
            '文字点击': ('text_enable_click', self._MOUSE_TEXT_CLICK_PARAMS),
            '坐标点击': ('coordinate_enable_click', self._MOUSE_COORDINATE_CLICK_PARAMS),
            '元素点击': ('element_enable_click', self._MOUSE_ELEMENT_CLICK_PARAMS),
        }
        toggle_name, hidden_params = rule_mapping.get(operation_mode, (None, None))
        if not toggle_name or hidden_params is None:
            return False
        if self._click_rule_to_bool(current_params.get(toggle_name, True), True):
            return False
        return param_name in hidden_params

    def _should_hide_simple_click_task_parameter(
        self,
        param_name: str,
        current_params: Dict[str, Any],
        hidden_params: Set[str],
    ) -> bool:
        if self._click_rule_to_bool(current_params.get('enable_click', True), True):
            return False
        return param_name in hidden_params

    def _should_show_parameter(self, param_def: Dict[str, Any], param_name: str = None) -> bool:
        """检查参数是否应该显示（基于条件）"""
        try:
            if self._should_hide_click_related_parameter(param_name):
                return False

            condition = param_def.get('condition', param_def.get('conditions'))
            if not condition:
                return True

            # 确保current_parameters存在
            if not hasattr(self, 'current_parameters') or self.current_parameters is None:
                return True

            # 支持多条件（列表形式）和单条件（字典形式）
            if isinstance(condition, list):
                # 多条件：所有条件都必须满足（AND逻辑）
                for single_condition in condition:
                    if not self._check_single_condition(single_condition):
                        return False
                return True
            else:
                # 单条件 - 包含原有的特殊处理逻辑
                param_name = condition.get('param')
                expected_value = condition.get('value')

                if not param_name or expected_value is None:
                    return True

                # 获取当前参数值，如果不存在则使用参数定义中的默认值
                current_value = self.current_parameters.get(param_name)
                if current_value is None and hasattr(self, 'param_definitions') and self.param_definitions:
                    param_def = self.param_definitions.get(param_name, {})
                    current_value = param_def.get('default')

                # 获取操作符，支持显式定义或自动推导
                operator = condition.get('operator')
                if operator is None:
                    # 自动推导：根据expected_value类型判断
                    operator = 'in' if isinstance(expected_value, list) else '=='

                # 检查主条件
                main_condition_met = self._apply_condition_operator(current_value, expected_value, operator)

                # 如果主条件不满足，直接返回False
                if not main_condition_met:
                    return False

                # 检查是否有额外的AND条件
                and_condition = condition.get('and')
                if and_condition:
                    # 处理AND条件
                    if isinstance(and_condition, list):
                        # 多个AND条件
                        for and_cond in and_condition:
                            if not self._check_single_condition(and_cond):
                                return False
                    else:
                        # 单个AND条件
                        if not self._check_single_condition(and_condition):
                            return False

                # 特殊处理：对于依赖multi_image_mode的参数，需要额外检查operation_mode
                if param_name == 'multi_image_mode':
                    # 检查operation_mode是否为找图功能（兼容历史值）
                    operation_mode = self.current_parameters.get('operation_mode')
                    if operation_mode not in {'找图功能', '图片点击', '找图点击'}:
                        return False

                return True
        except Exception as e:
            logger.error(f"参数显示条件检查失败: {e}")
            return True  # 出错时默认显示

    def _check_single_condition(self, condition: Dict[str, Any]) -> bool:
        """检查单个条件是否满足"""
        try:
            if not isinstance(condition, dict):
                return True

            param_name = condition.get('param')
            expected_value = condition.get('value')

            if not param_name or expected_value is None:
                return True

            # 确保current_parameters存在
            if not hasattr(self, 'current_parameters') or self.current_parameters is None:
                return True

            # 获取当前参数值，如果不存在则使用参数定义中的默认值
            current_value = self.current_parameters.get(param_name)
            if current_value is None and hasattr(self, 'param_definitions') and self.param_definitions:
                param_def_lookup = self.param_definitions.get(param_name, {})
                current_value = param_def_lookup.get('default')

            # 操作模式兼容：统一旧值与新值，避免历史流程参数导致条件失效
            if param_name == 'operation_mode':
                current_value = self._normalize_operation_mode_value(current_value)
                if isinstance(expected_value, list):
                    expected_value = [self._normalize_operation_mode_value(v) for v in expected_value]
                else:
                    expected_value = self._normalize_operation_mode_value(expected_value)

            # 获取操作符，支持显式定义或自动推导
            operator = condition.get('operator')
            if operator is None:
                # 自动推导：根据expected_value类型判断
                operator = 'in' if isinstance(expected_value, list) else '=='

            # 检查主条件
            main_condition_met = self._apply_condition_operator(current_value, expected_value, operator)

            # 如果主条件不满足，直接返回False
            if not main_condition_met:
                return False

            # 检查是否有嵌套的AND条件
            and_condition = condition.get('and')
            if and_condition:
                if isinstance(and_condition, list):
                    # 多个AND条件
                    for and_cond in and_condition:
                        if not self._check_single_condition(and_cond):
                            return False
                else:
                    # 单个AND条件，递归检查
                    if not self._check_single_condition(and_condition):
                        return False

            return True
        except Exception as e:
            logger.error(f"条件检查失败: {e}")
            return True  # 出错时默认显示

    def _apply_condition_operator(self, current_value: Any, expected_value: Any, operator: str) -> bool:
        """应用条件操作符"""
        try:
            if operator == '==' or operator == 'eq':
                return current_value == expected_value
            elif operator == '!=' or operator == 'ne':
                return current_value != expected_value
            elif operator == 'in':
                if isinstance(expected_value, (list, tuple)):
                    return current_value in expected_value
                else:
                    return current_value == expected_value
            elif operator == 'not_in' or operator == 'notin':
                if isinstance(expected_value, (list, tuple)):
                    return current_value not in expected_value
                else:
                    return current_value != expected_value
            elif operator == '>' or operator == 'gt':
                try:
                    return float(current_value) > float(expected_value)
                except (TypeError, ValueError):
                    return False
            elif operator == '<' or operator == 'lt':
                try:
                    return float(current_value) < float(expected_value)
                except (TypeError, ValueError):
                    return False
            elif operator == '>=' or operator == 'ge':
                try:
                    return float(current_value) >= float(expected_value)
                except (TypeError, ValueError):
                    return False
            elif operator == '<=' or operator == 'le':
                try:
                    return float(current_value) <= float(expected_value)
                except (TypeError, ValueError):
                    return False
            elif operator == 'contains':
                if isinstance(current_value, str) and isinstance(expected_value, str):
                    return expected_value in current_value
                return False
            elif operator == 'startswith':
                if isinstance(current_value, str) and isinstance(expected_value, str):
                    return current_value.startswith(expected_value)
                return False
            elif operator == 'endswith':
                if isinstance(current_value, str) and isinstance(expected_value, str):
                    return current_value.endswith(expected_value)
                return False
            else:
                logger.warning(f"未知的条件操作符: {operator}，使用默认的==操作符")
                return current_value == expected_value
        except Exception as e:
            logger.error(f"应用条件操作符失败: operator={operator}, current={current_value}, expected={expected_value}, error={e}")
            return True  # 出错时默认显示

    def _connect_conditional_signals(self, param_name: str, widget: QWidget):
        """为影响条件显示的参数连接信号"""
        # 检查是否有其他参数依赖于这个参数
        is_conditional_param = False
        for other_param_def in self.param_definitions.values():
            condition = other_param_def.get('condition', other_param_def.get('conditions'))
            if condition:
                # 支持多条件和单条件
                if isinstance(condition, list):
                    # 多条件：检查是否有任何条件依赖于这个参数
                    for single_condition in condition:
                        if single_condition.get('param') == param_name:
                            is_conditional_param = True
                            break
                else:
                    # 单条件 - 检查主条件和AND条件
                    if condition.get('param') == param_name:
                        is_conditional_param = True
                    else:
                        # 检查AND条件
                        and_condition = condition.get('and')
                        if and_condition:
                            if isinstance(and_condition, list):
                                # 多个AND条件
                                for and_cond in and_condition:
                                    if and_cond.get('param') == param_name:
                                        is_conditional_param = True
                                        break
                            else:
                                # 单个AND条件
                                if and_condition.get('param') == param_name:
                                    is_conditional_param = True
            if is_conditional_param:
                break

        if not is_conditional_param:
            return

        # 根据控件类型连接相应的信号
        if isinstance(widget, QComboBox):
            widget.currentTextChanged.connect(self._on_conditional_param_changed)
        elif isinstance(widget, QCheckBox):
            widget.toggled.connect(self._on_conditional_param_changed)
        elif isinstance(widget, QSpinBox):
            widget.valueChanged.connect(self._on_conditional_param_changed)
        elif isinstance(widget, QDoubleSpinBox):
            widget.valueChanged.connect(self._on_conditional_param_changed)
        elif isinstance(widget, QLineEdit):
            widget.textChanged.connect(self._on_conditional_param_changed)
        elif isinstance(widget, QPlainTextEdit):
            widget.textChanged.connect(self._on_conditional_param_changed)
        elif hasattr(widget, 'button_group'):
            # 单选按钮组
            widget.button_group.buttonToggled.connect(self._on_conditional_param_changed)

    def _on_conditional_param_changed(self):
        """条件参数值发生变化时的处理"""
        logger.debug("条件参数变化，准备更新参数面板显示")

        # 延迟更新以避免频繁重建界面
        if not hasattr(self, '_update_timer'):
            from PySide6.QtCore import QTimer
            self._update_timer = QTimer(self)
            self._update_timer.setSingleShot(True)
            self._update_timer.timeout.connect(self._update_conditional_display)

        self._update_timer.start(100)  # 100ms延迟

    def _update_conditional_display(self):
        current_values = self._collect_current_parameters()
        if 'delay_mode' in current_values:
            logger.debug(f"Conditional update debug: delay_mode={current_values['delay_mode']}")

        self.current_parameters.update(current_values)
        needs_global_config_refresh = False
        self._sync_changed_conditional_parameters(current_values)

        saved_values, focused_widget_name, cursor_position = self._capture_conditional_widget_state()
        self._merge_saved_conditional_values(saved_values)
        self._rebuild_conditional_widgets()
        self._restore_conditional_widget_state(saved_values, focused_widget_name, cursor_position)
        self._schedule_global_config_refresh_if_needed(needs_global_config_refresh)

    def _sync_changed_conditional_parameters(self, current_values: Dict[str, Any]) -> None:
        condition_affecting_params = set()
        if hasattr(self, '_collect_condition_affecting_parameter_names'):
            condition_affecting_params = self._collect_condition_affecting_parameter_names()
        changed_conditional_params = {
            param_name: current_values[param_name]
            for param_name in condition_affecting_params
            if param_name in current_values
        }
        if changed_conditional_params and self.current_card_id is not None:
            logger.info(f"Sync changed conditional parameters to TaskCard: {changed_conditional_params}")
            self.parameters_changed.emit(self.current_card_id, changed_conditional_params)

    def _capture_conditional_widget_state(self) -> tuple[Dict[str, Any], Optional[str], int]:
        saved_values: Dict[str, Any] = {}
        focused_widget_name = None
        cursor_position = 0

        for name, widget in self._iter_value_widgets():
            try:
                if isinstance(widget, QLineEdit):
                    saved_values[name] = widget.text()
                    if widget.hasFocus():
                        focused_widget_name = name
                        cursor_position = widget.cursorPosition()
                elif isinstance(widget, QSpinBox):
                    saved_values[name] = widget.value()
                    if widget.hasFocus():
                        focused_widget_name = name
                elif isinstance(widget, QDoubleSpinBox):
                    saved_values[name] = widget.value()
                    if widget.hasFocus():
                        focused_widget_name = name
                elif isinstance(widget, QComboBox):
                    current_data = widget.currentData()
                    saved_values[name] = current_data if current_data is not None else widget.currentText()
                elif isinstance(widget, QCheckBox):
                    saved_values[name] = widget.isChecked()
                elif isinstance(widget, QPlainTextEdit):
                    saved_values[name] = widget.toPlainText()
                    if widget.hasFocus():
                        focused_widget_name = name
                        cursor_position = widget.textCursor().position()
                elif isinstance(widget, QTextEdit):
                    saved_values[name] = widget.toPlainText()
                    if widget.hasFocus():
                        focused_widget_name = name
                        cursor_position = widget.textCursor().position()
                elif isinstance(widget, QListWidget):
                    raw_data = widget.property("raw_color_data")
                    if raw_data:
                        saved_values[name] = raw_data
                    else:
                        existing_value = self.current_parameters.get(name)
                        if existing_value and str(existing_value).strip():
                            saved_values[name] = existing_value
                elif hasattr(widget, 'button_group'):
                    checked_button = widget.button_group.checkedButton()
                    if checked_button:
                        saved_values[name] = checked_button.property('value')
            except Exception as e:
                logger.debug(f"恢复控件状态失败 {name}：{e}")

        return saved_values, focused_widget_name, cursor_position

    def _merge_saved_conditional_values(self, saved_values: Dict[str, Any]) -> None:
        for name, value in saved_values.items():
            self.current_parameters[name] = value
            logger.debug(f"Update current_parameters[{name}] = {value}")

    def _rebuild_conditional_widgets(self) -> None:
        self._clear_content()
        self._create_parameter_widgets()

    def _restore_conditional_widget_state(self, saved_values: Dict[str, Any], focused_widget_name: Optional[str], cursor_position: int) -> None:
        for name, value in saved_values.items():
            if name not in self.value_widgets:
                continue
            widget = self.value_widgets[name]
            try:
                if isinstance(widget, QLineEdit):
                    widget.setText(str(value))
                    if name == focused_widget_name:
                        QTimer.singleShot(10, lambda w=widget, pos=cursor_position: self._restore_focus(w, pos))
                elif isinstance(widget, QSpinBox):
                    widget.setValue(int(value))
                    if name == focused_widget_name:
                        QTimer.singleShot(10, lambda w=widget: w.setFocus())
                elif isinstance(widget, QDoubleSpinBox):
                    widget.setValue(float(value))
                    if name == focused_widget_name:
                        QTimer.singleShot(10, lambda w=widget: w.setFocus())
                elif isinstance(widget, QComboBox):
                    index = widget.findData(value)
                    if index >= 0:
                        widget.setCurrentIndex(index)
                    else:
                        widget.setCurrentText(str(value))
                elif isinstance(widget, QCheckBox):
                    widget.setChecked(bool(value))
                elif isinstance(widget, QPlainTextEdit):
                    widget.setPlainText(str(value))
                    if name == focused_widget_name:
                        QTimer.singleShot(10, lambda w=widget, pos=cursor_position: self._restore_text_focus(w, pos))
                elif isinstance(widget, QTextEdit):
                    widget.setPlainText(str(value))
                    if name == focused_widget_name:
                        QTimer.singleShot(10, lambda w=widget, pos=cursor_position: self._restore_text_focus(w, pos))
            except Exception as e:
                logger.debug(f"恢复控件状态失败 {name}：{e}")

    def _schedule_global_config_refresh_if_needed(self, needs_global_config_refresh: bool) -> None:
        if not needs_global_config_refresh:
            return
        logger.info("Detected global_config condition, schedule refresh after 150ms")
        QTimer.singleShot(150, self._force_refresh_for_global_config)
