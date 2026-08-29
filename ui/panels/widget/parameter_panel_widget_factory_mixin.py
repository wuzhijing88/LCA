from ..parameter_panel_support import *
from ...selectors.multi_coordinate_text import (
    MULTI_COORDINATE_BUTTON_TEXT,
    MULTI_COORDINATE_PLACEHOLDER,
)

class ParameterPanelWidgetFactoryMixin:

    def _create_widget_by_hint(self, name: str, param_def: Dict[str, Any], current_value: Any, label_text: str):
        widget = self._create_selector_widget_by_hint(name, param_def, current_value, label_text)
        if widget is not None:
            return widget
        return self._create_tool_widget_by_hint(name, param_def, current_value, label_text)

    def _create_selector_widget_by_hint(self, name: str, param_def: Dict[str, Any], current_value: Any, label_text: str):
        return self._create_basic_selector_widget_by_hint(name, param_def, current_value, label_text)

    def _create_basic_selector_widget_by_hint(self, name: str, param_def: Dict[str, Any], current_value: Any, label_text: str):
        _ = label_text
        widget_hint = param_def.get('widget_hint', '')
        if widget_hint in {'jump_target_selector', 'card_selector'}:
            return self._create_jump_target_selector_widget(name, current_value)
        if widget_hint == 'thread_target_selector':
            return self._create_thread_target_selector_widget(name, param_def, current_value)
        if widget_hint == 'bound_window_selector':
            return self._create_bound_window_selector_widget(current_value)
        if widget_hint == 'workflow_card_selector':
            return self._create_workflow_card_selector_widget(param_def, current_value)
        if widget_hint == 'package_selector':
            return self._create_package_selector_widget(name, current_value)
        if widget_hint == 'file_selector':
            return self._create_file_selector_widget(name, param_def, current_value)
        if widget_hint == 'color_selector':
            return self._create_color_selector_widget(name, current_value)
        if widget_hint == 'workflow_selector':
            return self._create_workflow_selector_widget(name, current_value)
        return None

    def _create_jump_target_selector_widget(self, name: str, current_value: Any):
        widget = QComboBox(self)
        self._remove_combobox_shadow(widget)
        widget.addItem('无跳转', None)

        sorted_cards = sorted(self.workflow_cards_info.items())
        for _seq_id, (task_type, card_id) in sorted_cards:
            if card_id != self.current_card_id:
                widget.addItem(f'{task_type} (ID: {card_id})', card_id)

        actual_value = current_value
        if actual_value is None:
            real_time_params = self._get_real_time_card_parameters()
            if name in real_time_params and real_time_params[name] is not None:
                actual_value = real_time_params[name]
                logger.info(f'[CARD_SELECTOR] {name} 从实时参数获取值: {actual_value}')

        if actual_value is not None:
            index = widget.findData(actual_value)
            if index >= 0:
                widget.setCurrentIndex(index)
                logger.info(f'[CARD_SELECTOR] 设置 {name} 的初始值为: {actual_value}, 索引: {index}')
            else:
                logger.warning(f'[CARD_SELECTOR] 未找到 {name} 的值 {actual_value} 对应的选项')
        return widget

    def _create_thread_target_selector_widget(self, name: str, param_def: Dict[str, Any], current_value: Any):
        widget = QComboBox(self)
        self._remove_combobox_shadow(widget)
        widget.addItem('当前线程', '当前线程')
        widget.addItem('全部线程', '全部线程')

        start_cards = [
            item for item in self._collect_workflow_cards_for_selector() if is_thread_start_task_type(item[1])
        ]
        for idx, (card_id, _task_type, custom_name) in enumerate(start_cards, 1):
            thread_label = custom_name.strip() if custom_name else ''
            if not thread_label or thread_label == THREAD_START_TASK_TYPE:
                thread_label = f'线程起点{idx}'
            widget.addItem(f'{thread_label} (ID: {card_id})', str(card_id))

        if current_value is None or isinstance(current_value, bool) or current_value == '':
            desired_source = param_def.get('default')
        else:
            desired_source = current_value
        desired_value = '' if desired_source is None else str(desired_source).strip()
        if desired_value:
            index = widget.findData(desired_value)
            if index < 0:
                index = widget.findText(desired_value)
            if index < 0 and not desired_value.isdigit():
                for i in range(widget.count()):
                    if widget.itemText(i).startswith(f'{desired_value} (ID:'):
                        index = i
                        break
            if index >= 0:
                widget.setCurrentIndex(index)

        selected_value = widget.currentData()
        if selected_value is None:
            selected_value = widget.currentText()
        self.current_parameters[name] = selected_value
        widget.currentIndexChanged.connect(
            lambda _index, n=name, w=widget: self._on_thread_target_selection_changed(n, w)
        )
        return widget

    def _create_bound_window_selector_widget(self, current_value: Any):
        widget = QComboBox(self)
        self._remove_combobox_shadow(widget)
        widget.addItem('使用默认窗口', None)

        enabled_windows = self._get_enabled_bound_windows_for_selector()
        for idx, window_info in enumerate(enabled_windows, 1):
            window_title = str(window_info.get('title') or f'窗口{idx}').strip()
            widget.addItem(f'窗口{idx}: {window_title}', idx)

        selected_index = None
        try:
            if current_value not in (None, '', 'None', 'none', 0, '0'):
                selected_index = int(current_value)
        except Exception:
            selected_index = None
        if selected_index is not None and selected_index > 0:
            combo_index = widget.findData(selected_index)
            if combo_index >= 0:
                widget.setCurrentIndex(combo_index)
        return widget

    def _create_workflow_card_selector_widget(self, param_def: Dict[str, Any], current_value: Any):
        widget = QComboBox(self)
        self._remove_combobox_shadow(widget)
        widget.addItem('使用线程默认起点', None)

        target_thread_value = self.current_parameters.get('target_thread')
        for card_id, task_type, custom_name in self._collect_workflow_cards_for_target_thread(target_thread_value):
            if custom_name:
                display_text = f'{custom_name} [{task_type}] (ID: {card_id})'
            else:
                display_text = f'{task_type} (ID: {card_id})'
            widget.addItem(display_text, int(card_id))

        selected_card_id = self._parse_card_id_from_value(current_value)
        if selected_card_id is None:
            selected_card_id = self._parse_card_id_from_value(param_def.get('default'))
        if selected_card_id is not None and selected_card_id >= 0:
            index = widget.findData(int(selected_card_id))
            if index >= 0:
                widget.setCurrentIndex(index)
        return widget

    @staticmethod
    def _normalize_workflow_selector_value(value: Any):
        from task_workflow.workflow_vars import normalize_workflow_task_id

        return normalize_workflow_task_id(value)

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
        new_value = widget.itemData(index)
        self._apply_live_parameter_changes({name: new_value}, refresh_conditional=False)
        self._refresh_workflow_dependents(name)

    def _create_workflow_selector_widget(self, name: str, current_value: Any):
        widget = QComboBox(self)
        self._remove_combobox_shadow(widget)
        widget.addItem('当前工作流', None)
        for label, task_id in self._get_workflow_selector_items():
            widget.addItem(label, task_id)

        try:
            normalized_value = self._normalize_workflow_selector_value(current_value)
            selector_is_valid = True
        except (TypeError, ValueError):
            normalized_value = current_value
            selector_is_valid = False

        if selector_is_valid and normalized_value is None:
            widget.setCurrentIndex(0)
        else:
            idx = widget.findData(normalized_value) if selector_is_valid else -1
            if idx >= 0:
                widget.setCurrentIndex(idx)
            else:
                widget.addItem(f'无效工作流（已保存）: {current_value!s}', current_value)
                widget.setCurrentIndex(widget.count() - 1)

        widget.currentIndexChanged.connect(
            lambda index, w=widget, n=name: self._on_workflow_selector_changed(index, w, n)
        )
        self._register_widget(name, widget)
        self._install_wheel_filter(widget, name)
        return widget

    def _create_package_selector_widget(self, name: str, current_value: Any):
        package_widget = QWidget()
        package_layout = QHBoxLayout(package_widget)
        package_layout.setContentsMargins(0, 0, 0, 0)

        package_combo = QComboBox(package_widget)
        self._remove_combobox_shadow(package_combo)
        if current_value:
            package_combo.addItem(str(current_value))
            package_combo.setCurrentText(str(current_value))

        refresh_button = ResponsiveButton("刷新")
        refresh_button.setMinimumWidth(60)
        refresh_button.setProperty("class", "primary")
        refresh_button.clicked.connect(lambda: self._refresh_package_list(package_combo))

        package_layout.addWidget(package_combo, 1)
        package_layout.addWidget(refresh_button)

        self._register_widget(name, package_combo)
        self._install_wheel_filter(package_combo, name)
        return package_widget

    def _create_file_selector_widget(self, name: str, param_def: Dict[str, Any], current_value: Any):
        file_widget = QWidget()
        file_layout = QHBoxLayout(file_widget)
        file_layout.setContentsMargins(0, 0, 0, 0)

        file_edit = QLineEdit(str(current_value) if current_value else "")
        file_button = QPushButton("浏览...")
        file_button.clicked.connect(lambda: self._select_file(file_edit, param_def))

        file_layout.addWidget(file_edit)
        file_layout.addWidget(file_button)
        self._register_widget(name, file_edit)
        return file_widget

    def _create_color_selector_widget(self, name: str, current_value: Any):
        color_widget = QWidget()
        color_layout = QHBoxLayout(color_widget)
        color_layout.setContentsMargins(0, 0, 0, 0)

        color_edit = QLineEdit(str(current_value) if current_value else "#000000")
        color_button = QPushButton("选择颜色")
        color_button.clicked.connect(lambda: self._select_color(color_edit))

        color_layout.addWidget(color_edit)
        color_layout.addWidget(color_button)
        self._register_widget(name, color_edit)
        return color_widget

    def _create_tool_widget_by_hint(self, name: str, param_def: Dict[str, Any], current_value: Any, label_text: str):
        widget = self._create_interactive_tool_widget_by_hint(name, param_def, current_value, label_text)
        if widget is not None:
            return widget
        return self._create_recording_tool_widget_by_hint(name, param_def, current_value, label_text)

    def _create_interactive_tool_widget_by_hint(self, name: str, param_def: Dict[str, Any], current_value: Any, label_text: str):
        _ = label_text
        widget_hint = param_def.get('widget_hint', '')
        if widget_hint == 'element_picker':
            return self._create_interactive_element_picker_widget(param_def)
        if widget_hint == 'enable_browser_accessibility':
            return self._create_interactive_browser_accessibility_widget(param_def)
        if widget_hint == 'colorpicker':
            return self._create_interactive_colorpicker_widget(name, current_value)
        if widget_hint == 'ocr_region_selector':
            return self._create_interactive_ocr_region_widget(name, param_def)
        if widget_hint == 'coordinate_selector':
            return self._create_interactive_coordinate_widget(name, param_def)
        if widget_hint == 'coordinate_selector_with_display':
            return self._create_interactive_coordinate_display_widget(name, param_def)
        if widget_hint == 'offset_selector':
            return self._create_interactive_offset_widget(name, param_def)
        if widget_hint == 'motion_region_selector':
            return self._create_interactive_motion_region_widget(name, param_def)
        if widget_hint == 'image_region_selector':
            return self._create_interactive_image_region_widget(name, param_def)
        if widget_hint == 'multi_image_region_selector':
            return self._create_interactive_multi_image_region_widget(name, param_def)
        if widget_hint == 'yolo_realtime_preview':
            return self._create_interactive_yolo_preview_widget(param_def)
        if widget_hint == 'color_region_selector':
            return self._create_interactive_color_region_widget(name, param_def)
        return None

    def _create_interactive_element_picker_widget(self, param_def: Dict[str, Any]):
        picker_button = QPushButton(param_def.get('button_text', '拾取元素'))
        picker_button.setToolTip(
            param_def.get('tooltip', '点击后移动鼠标到目标元素，右键确认拾取')
        )
        from themes import theme_color

        picker_button.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {theme_color("accent", "#0078d4")};
                color: white;
                border: none;
                padding: 6px 16px;
                border-radius: 4px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {theme_color("accent_hover", "#1084d8")};
            }}
            QPushButton:pressed {{
                background-color: {theme_color("accent_pressed", "#006cbe")};
            }}
            QPushButton:disabled {{
                background-color: {theme_color("surface", "#f5f5f5")};
                color: {theme_color("text_disabled", "#999999")};
            }}
            """
        )
        picker_button.clicked.connect(self._start_element_picking)
        self._element_picker_button = picker_button
        return picker_button

    def _create_interactive_browser_accessibility_widget(self, param_def: Dict[str, Any]):
        acc_button = QPushButton(param_def.get('button_text', '启用浏览器辅助功能'))
        acc_button.setToolTip(param_def.get('tooltip', ''))
        from themes import theme_color

        acc_button.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {theme_color("success", "#107c10")};
                color: white;
                border: none;
                padding: 6px 16px;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: {theme_color("success", "#107c10")};
            }}
            QPushButton:pressed {{
                background-color: {theme_color("success", "#107c10")};
            }}
            """
        )
        acc_button.clicked.connect(self._enable_browser_accessibility)
        return acc_button

    def _create_interactive_yolo_preview_widget(self, param_def: Dict[str, Any]):
        widget = ResponsiveButton(param_def.get('button_text', '启动实时预览'))
        widget.setProperty('class', 'primary')
        widget.clicked.connect(self._start_yolo_realtime_preview)
        return widget

    def _create_interactive_colorpicker_widget(self, name: str, current_value: Any):
        from themes import get_theme_manager
        from PySide6.QtWidgets import QListWidget

        theme_manager = get_theme_manager()
        color_widget = QWidget()
        color_layout = QVBoxLayout(color_widget)
        color_layout.setContentsMargins(0, 0, 0, 0)
        color_layout.setSpacing(6)

        color_list = QListWidget()
        color_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        color_list.setSpacing(2)

        border_color = theme_manager.get_color('border')
        bg_color = theme_manager.get_color('background')
        color_list.setStyleSheet(
            f'QListWidget {{ border: 1px solid {border_color}; background-color: {bg_color}; }}'
        )

        raw_value = str(current_value) if current_value else ''
        self._populate_color_list(color_list, raw_value)
        item_count = color_list.count()
        color_list.setFixedHeight(min(150, max(60, item_count * 30 + 10)))

        color_layout.addWidget(color_list)

        color_button = QPushButton('选择颜色')
        color_button.setProperty('class', 'primary')
        color_button.clicked.connect(lambda: self._select_color_rgb_list(color_list, name))
        color_layout.addWidget(color_button)

        self._register_widget(name, color_list)
        color_list.setProperty('raw_color_data', raw_value)
        return color_widget

    def _create_interactive_coordinate_widget(self, name: str, param_def: Dict[str, Any]):
        widget = ResponsiveButton(param_def.get('button_text', '点击获取坐标'))
        widget.setProperty('class', 'primary')
        widget.clicked.connect(lambda: self._select_coordinate(name))
        return widget

    def _create_interactive_coordinate_display_widget(self, name: str, param_def: Dict[str, Any]):
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(4)

        coord_button = ResponsiveButton(param_def.get('button_text', '点击获取坐标'))
        coord_button.setProperty('class', 'primary')
        container_layout.addWidget(coord_button)

        coord_edit = QLineEdit()
        coord_edit.setReadOnly(True)

        related_params = param_def.get('related_params', ['coordinate_x', 'coordinate_y'])
        x_param = related_params[0] if len(related_params) > 0 else 'coordinate_x'
        y_param = related_params[1] if len(related_params) > 1 else 'coordinate_y'

        x_value = self.current_parameters.get(x_param, 0)
        y_value = self.current_parameters.get(y_param, 0)
        coord_edit.setText(f'{x_value},{y_value}')
        container_layout.addWidget(coord_edit)

        coord_display_key = f'_coord_display_{name}'
        setattr(self, coord_display_key, coord_edit)
        coord_params_key = f'_coord_params_{name}'
        setattr(self, coord_params_key, (x_param, y_param, related_params))

        coord_button.clicked.connect(lambda: self._select_coordinate_with_display(name))
        self._register_widget(name, coord_button, stores_value=False)
        return container

    def _create_interactive_offset_widget(self, name: str, param_def: Dict[str, Any]):
        widget = ResponsiveButton(param_def.get('button_text', '拖拽选择偏移'))
        widget.setProperty('class', 'primary')
        widget.clicked.connect(lambda: self._select_offset(name))
        return widget

    def _create_interactive_ocr_region_widget(self, name: str, param_def: Dict[str, Any]):
        widget = ResponsiveButton(param_def.get('button_text', '框选区域'))
        widget.setProperty('class', 'primary')
        widget.clicked.connect(lambda: self._select_ocr_region(name))
        return widget

    def _create_interactive_motion_region_widget(self, name: str, param_def: Dict[str, Any]):
        widget = ResponsiveButton(param_def.get('button_text', '选择检测区域'))
        widget.setProperty('class', 'primary')
        widget.clicked.connect(lambda: self._select_motion_region(name))
        return widget

    def _create_interactive_image_region_widget(self, name: str, param_def: Dict[str, Any]):
        widget = ResponsiveButton(param_def.get('button_text', '点击框选识别区域'))
        widget.setProperty('class', 'primary')
        param_prefix = param_def.get('param_prefix', 'recognition_region')
        initial_x = self.current_parameters.get(f'{param_prefix}_x', 0)
        initial_y = self.current_parameters.get(f'{param_prefix}_y', 0)
        initial_width = self.current_parameters.get(f'{param_prefix}_width', 0)
        initial_height = self.current_parameters.get(f'{param_prefix}_height', 0)
        if initial_width > 0 and initial_height > 0:
            widget.setText(f'区域: X={initial_x}, Y={initial_y}, {initial_width}x{initial_height}')
        widget.clicked.connect(lambda: self._select_image_region(name))
        return widget

    def _create_interactive_multi_image_region_widget(self, name: str, param_def: Dict[str, Any]):
        widget = ResponsiveButton(param_def.get('button_text', '点击框选识别区域'))
        widget.setProperty('class', 'primary')
        initial_x = self.current_parameters.get('multi_recognition_region_x', 0)
        initial_y = self.current_parameters.get('multi_recognition_region_y', 0)
        initial_width = self.current_parameters.get('multi_recognition_region_width', 0)
        initial_height = self.current_parameters.get('multi_recognition_region_height', 0)
        if initial_width > 0 and initial_height > 0:
            widget.setText(f'区域: X={initial_x}, Y={initial_y}, {initial_width}x{initial_height}')
        widget.clicked.connect(lambda: self._select_multi_image_region(name))
        return widget

    def _create_interactive_color_region_widget(self, name: str, param_def: Dict[str, Any]):
        widget = ResponsiveButton(param_def.get('button_text', '点击框选识别区域'))
        widget.setProperty('class', 'primary')
        search_region_enabled = self.current_parameters.get('search_region_enabled', False)
        if search_region_enabled:
            initial_x = int(self.current_parameters.get('search_region_x', 0) or 0)
            initial_y = int(self.current_parameters.get('search_region_y', 0) or 0)
            initial_width = int(self.current_parameters.get('search_region_width', 0) or 0)
            initial_height = int(self.current_parameters.get('search_region_height', 0) or 0)
            if initial_width > 0 and initial_height > 0:
                widget.setText(f'区域: X={initial_x}, Y={initial_y}, {initial_width}x{initial_height}')
        widget.clicked.connect(lambda: self._select_color_search_region(name))
        return widget

    def _create_recording_tool_widget_by_hint(self, name: str, param_def: Dict[str, Any], current_value: Any, label_text: str):
        widget_hint = param_def.get('widget_hint', '')
        widget = None
        if widget_hint == 'record_control':
            widget = ResponsiveButton("开始录制")
            widget.setProperty("class", "primary")
            widget.clicked.connect(lambda: self._toggle_recording())
            self._register_widget(name, widget, stores_value=False)

        elif widget_hint == 'replay_control':
            action_count = self._get_recorded_action_count()
            widget = ResponsiveButton(
                f"测试回放 ({action_count}个操作)" if action_count else "测试回放"
            )
            widget.setProperty("class", "primary")
            widget.clicked.connect(lambda: self._toggle_replay())
            self._register_widget(name, widget, stores_value=False)

        elif widget_hint == 'action_editor':
            action_count = self._get_recorded_action_count()
            widget = ResponsiveButton(
                f"编辑步骤 ({action_count}个)" if action_count else "编辑步骤"
            )
            widget.setProperty("class", "secondary")
            widget.clicked.connect(lambda: self._open_action_editor())
            self._register_widget(name, widget, stores_value=False)

        return widget

    def _create_widget_by_param_type(self, name: str, param_def: Dict[str, Any], current_value: Any, label_text: str):
        widget = self._create_numeric_widget_by_type(name, param_def, current_value, label_text)
        if widget is not None:
            return widget
        return self._create_textual_widget_by_type(name, param_def, current_value, label_text)

    def _create_numeric_widget_by_type(self, name: str, param_def: Dict[str, Any], current_value: Any, label_text: str):
        _ = label_text
        param_type = param_def.get('type', 'text')
        if param_type in ('bool', 'checkbox'):
            return self._create_numeric_checkbox_widget(name, current_value)
        if param_type in ('int', 'integer'):
            return self._create_numeric_int_widget(param_def, current_value)
        if param_type in ('float', 'double'):
            return self._create_numeric_float_widget(param_def, current_value)
        if param_type == 'radio':
            return self._create_numeric_radio_widget(param_def, current_value)
        if param_type in ('choice', 'select', 'combo'):
            return self._create_numeric_choice_widget(name, param_def, current_value)
        return None

    def _create_numeric_checkbox_widget(self, name: str, current_value: Any):
        widget = QCheckBox()
        widget.setChecked(bool(current_value))
        widget.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, False)
        widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        widget.stateChanged.connect(lambda state: self._handle_numeric_checkbox_state_changed(name, state))
        widget.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, False)
        widget.setMouseTracking(False)

        event_filter = self._create_numeric_checkbox_event_filter(widget, name)
        widget.installEventFilter(event_filter)
        if not hasattr(self, '_event_filters'):
            self._event_filters = []
        self._event_filters.append(event_filter)
        return widget

    def _handle_numeric_checkbox_state_changed(self, name: str, state):
        checked = state == 2
        changed_parameters = {name: checked}
        if name == 'search_region_enabled' and not checked:
            changed_parameters.update(
                {
                    'search_region_x': 0,
                    'search_region_y': 0,
                    'search_region_width': 0,
                    'search_region_height': 0,
                }
            )
            logger.info('已清除识别区域坐标参数')
        self._apply_live_parameter_changes(changed_parameters)

    @staticmethod
    def _create_numeric_checkbox_event_filter(widget, name: str):
        class CheckboxEventFilter(QObject):
            def __init__(self, checkbox_widget, checkbox_name):
                super().__init__()
                self.checkbox_widget = checkbox_widget
                self.checkbox_name = checkbox_name

            def eventFilter(self, obj, event):
                if event.type() == event.Type.MouseButtonPress:
                    logger.debug(f'复选框 {self.checkbox_name} 接收到鼠标按下事件')
                    current_state = self.checkbox_widget.isChecked()
                    new_state = not current_state
                    self.checkbox_widget.setChecked(new_state)
                    logger.debug(f'复选框 {self.checkbox_name} 状态从 {current_state} 切换到 {new_state}')
                    self.checkbox_widget.clicked.emit()
                    self.checkbox_widget.toggled.emit(new_state)
                    return True
                return False

        return CheckboxEventFilter(widget, name)

    def _create_numeric_int_widget(self, param_def: Dict[str, Any], current_value: Any):
        widget = QLineEdit()
        text = "" if current_value is None else str(current_value)
        try:
            widget.setText(str(int(current_value) if current_value is not None else 0))
        except (TypeError, ValueError):
            widget.setText(text or "0")
        widget.setPlaceholderText("请输入整数")
        from PySide6.QtGui import QIntValidator
        validator = QIntValidator()
        validator.setRange(param_def.get("min", -999999), param_def.get("max", 999999))
        widget.setValidator(validator)
        widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        return widget

    def _create_numeric_float_widget(self, param_def: Dict[str, Any], current_value: Any):
        widget = QLineEdit()
        text = "" if current_value is None else str(current_value)
        try:
            widget.setText(str(float(current_value) if current_value is not None else 0.0))
        except (TypeError, ValueError):
            widget.setText(text or "0.0")
        widget.setPlaceholderText("请输入小数")
        from PySide6.QtGui import QDoubleValidator
        validator = QDoubleValidator()
        validator.setRange(
            param_def.get("min", -999999.0),
            param_def.get("max", 999999.0),
            param_def.get("decimals", 2),
        )
        widget.setValidator(validator)
        widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        return widget

    def _create_numeric_radio_widget(self, param_def: Dict[str, Any], current_value: Any):
        from PySide6.QtWidgets import QButtonGroup, QRadioButton

        radio_widget = QWidget()
        radio_layout = QVBoxLayout(radio_widget)
        radio_layout.setContentsMargins(0, 0, 0, 0)
        radio_layout.setSpacing(4)

        button_group = QButtonGroup(radio_widget)
        options = param_def.get('options', {})
        if isinstance(options, dict):
            for key, display_text in options.items():
                radio_button = QRadioButton(str(display_text))
                radio_button.setProperty('value', key)
                button_group.addButton(radio_button)
                radio_layout.addWidget(radio_button)
                if key == current_value:
                    radio_button.setChecked(True)
        else:
            for option in options:
                radio_button = QRadioButton(str(option))
                radio_button.setProperty('value', option)
                button_group.addButton(radio_button)
                radio_layout.addWidget(radio_button)
                if option == current_value:
                    radio_button.setChecked(True)

        radio_widget.button_group = button_group
        return radio_widget

    def _create_numeric_choice_widget(self, name: str, param_def: Dict[str, Any], current_value: Any):
        widget = QComboBox(self)
        self._remove_combobox_shadow(widget)
        choices = param_def.get('choices', param_def.get('options', []))
        if isinstance(choices, dict):
            for key, value in choices.items():
                widget.addItem(str(value), key)
            index = widget.findData(current_value)
            if index >= 0:
                widget.setCurrentIndex(index)
        else:
            for i, choice in enumerate(choices):
                choice_str = str(choice)
                widget.addItem(choice_str)
                if choice_str.startswith('=== ') and choice_str.endswith(' ==='):
                    item = widget.model().item(i)
                    if item:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                        font = item.font()
                        font.setBold(True)
                        item.setFont(font)
                        from themes import theme_color

                        item.setBackground(QColor(theme_color("surface", "#f5f5f5")))
                        item.setForeground(QColor(theme_color("text_secondary", "#666666")))
            if current_value is not None:
                index = widget.findText(str(current_value))
                if index >= 0:
                    widget.setCurrentIndex(index)

        widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._apply_force_down_popup(widget)
        widget.currentIndexChanged.connect(
            lambda index, w=widget, n=name: self._handle_numeric_select_changed(index, w, n)
        )
        return widget

    def _handle_numeric_select_changed(self, index: int, widget, name: str):
        new_value = widget.itemData(index) if widget.itemData(index) is not None else widget.currentText()
        if name == 'operation_mode':
            new_value = self._normalize_operation_mode_value(
                new_value,
                fallback_task_type=self.current_task_type or '',
            )
        self._apply_live_parameter_changes({name: new_value})

    def _create_textual_widget_by_type(self, name: str, param_def: Dict[str, Any], current_value: Any, label_text: str):
        widget = self._create_multiline_widget_by_type(name, param_def, current_value, label_text)
        if widget is not None:
            return widget
        return self._create_standard_text_widget_by_type(name, param_def, current_value, label_text)

    def _create_multiline_widget_by_type(self, name: str, param_def: Dict[str, Any], current_value: Any, label_text: str):
        _ = label_text
        param_type = param_def.get('type', 'text')
        widget_hint = param_def.get('widget_hint', '')
        if param_type not in ('textarea', 'multiline'):
            return None
        if param_def.get('readonly', False) and name == 'connected_targets':
            return self._create_multiline_connected_targets_widget()
        if name == 'path_points':
            return self._create_multiline_path_points_widget(name, current_value)
        if widget_hint == 'template_preset_editor':
            return self._create_multiline_template_preset_widget(name, param_def, current_value)
        return self._create_multiline_plain_text_widget(param_def, current_value)

    def _create_multiline_connected_targets_widget(self):
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(6)

        connections = self.current_parameters.get('_random_connections', [])
        if connections:
            for conn in connections:
                conn_task_type = conn.get('task_type', '')
                conn_card_id = conn.get('card_id', '')
                conn_weight = get_branch_weight(
                    self.current_parameters.get('random_weights'),
                    conn_card_id,
                )
                display_text = f"{conn_task_type} (ID: {conn_card_id})  权重: {conn_weight}"

                from themes import theme_color

                card_label = QLabel(display_text)
                card_label.setStyleSheet(
                    f"""
                    QLabel {{
                        color: {theme_color('text', '#333333')};
                        background-color: {theme_color('surface', '#f5f5f5')};
                        border: 1px solid {theme_color('border', '#e0e0e0')};
                        border-radius: 4px;
                        padding: 6px 10px;
                    }}
                    """
                )
                card_label.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                card_label.customContextMenuRequested.connect(
                    partial(self._show_random_target_context_menu, conn_card_id, card_label)
                )
                container_layout.addWidget(card_label)
        else:
            hint_frame = QFrame()
            hint_frame.setObjectName('randomTargetCard')
            hint_layout = QHBoxLayout(hint_frame)
            hint_layout.setContentsMargins(8, 6, 8, 6)

            hint_label = QLabel('未连接任何目标卡片，请从右侧紫色端口拖拽连线')
            hint_label.setWordWrap(True)
            hint_layout.addWidget(hint_label)

            container_layout.addWidget(hint_frame)

        return container

    def _create_multiline_path_points_widget(self, name: str, current_value: Any):
        path_widget = QWidget()
        path_layout = QVBoxLayout(path_widget)
        path_layout.setContentsMargins(0, 0, 0, 0)
        path_layout.setSpacing(4)

        text_edit = QPlainTextEdit()
        text_edit.setPlainText(str(current_value) if current_value is not None else '')
        text_edit.setMaximumHeight(100)
        text_edit.setPlaceholderText(MULTI_COORDINATE_PLACEHOLDER)

        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 0, 0, 0)

        coord_button = ResponsiveButton(MULTI_COORDINATE_BUTTON_TEXT)
        coord_button.setProperty('class', 'primary')
        coord_button.clicked.connect(lambda: self._select_multi_coordinates(name))

        clear_button = ResponsiveButton('清空')
        clear_button.setProperty('class', 'danger')
        clear_button.clicked.connect(text_edit.clear)

        button_layout.addWidget(coord_button)
        button_layout.addWidget(clear_button)
        button_layout.addStretch()

        path_layout.addWidget(text_edit)
        path_layout.addLayout(button_layout)

        self._register_widget(name, text_edit)
        return path_widget

    def _create_multiline_template_preset_widget(self, name: str, param_def: Dict[str, Any], current_value: Any):
        template_widget = QWidget()
        template_layout = QVBoxLayout(template_widget)
        template_layout.setContentsMargins(0, 0, 0, 0)
        template_layout.setSpacing(6)

        text_edit = QPlainTextEdit()
        text_edit.setPlainText(str(current_value) if current_value is not None else '')
        custom_height = param_def.get('height', 80)
        text_edit.setMinimumHeight(custom_height)
        text_edit.setMaximumHeight(max(custom_height, 200))
        text_edit.setMinimumWidth(150)
        text_edit.setFixedHeight(custom_height)
        text_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        placeholder = param_def.get('placeholder', '')
        if placeholder:
            text_edit.setPlaceholderText(placeholder)
        if param_def.get('readonly', False):
            text_edit.setReadOnly(True)

        preset_combo = QComboBox(self)
        preset_combo.setObjectName('templatePresetCombo')
        self._remove_combobox_shadow(preset_combo)
        preset_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        preset_combo.setMinimumHeight(30)

        presets = param_def.get('template_presets', []) or []
        if not isinstance(presets, list):
            presets = []
        for item in presets:
            label_text = ''
            value_text = ''
            if isinstance(item, dict):
                label_text = str(item.get('label', '') or '').strip()
                value_text = str(item.get('value', '') or '').strip()
            else:
                value_text = str(item or '').strip()
                label_text = value_text
            if not label_text or not value_text:
                continue
            preset_combo.addItem(label_text, value_text)

        insert_button = ResponsiveButton('插入预设')
        insert_button.setObjectName('templatePresetInsertButton')
        insert_button.setProperty('class', 'primary')
        insert_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        insert_button.setMinimumHeight(30)
        insert_button.clicked.connect(lambda: self._insert_template_preset_text(text_edit, preset_combo))

        template_layout.addWidget(text_edit)
        template_layout.addWidget(preset_combo)
        template_layout.addWidget(insert_button)

        self._register_widget(name, text_edit)
        return template_widget

    @staticmethod
    def _insert_template_preset_text(text_edit, preset_combo):
        preset_value = preset_combo.currentData()
        if preset_value is None:
            preset_value = preset_combo.currentText()
        snippet = str(preset_value or '').strip()
        if not snippet:
            return
        if text_edit.toPlainText().strip():
            text_edit.appendPlainText(snippet)
        else:
            text_edit.setPlainText(snippet)
        text_edit.setFocus()

    def _create_multiline_plain_text_widget(self, param_def: Dict[str, Any], current_value: Any):
        widget = QPlainTextEdit()
        widget.setPlainText(str(current_value) if current_value is not None else '')
        custom_height = param_def.get('height', 80)
        widget.setMinimumHeight(custom_height)
        widget.setMaximumHeight(max(custom_height, 200))
        widget.setMinimumWidth(150)
        widget.setFixedHeight(custom_height)
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        placeholder = param_def.get('placeholder', '')
        if placeholder:
            widget.setPlaceholderText(placeholder)
        if param_def.get('readonly', False):
            widget.setReadOnly(True)
        return widget

    def _create_standard_text_widget_by_type(self, name: str, param_def: Dict[str, Any], current_value: Any, label_text: str):
        param_type = param_def.get('type', 'text')
        widget_hint = param_def.get('widget_hint', '')
        if param_type == 'button':
            return self._create_standard_text_button_widget(name, param_def, label_text, widget_hint)
        if param_type == 'file':
            return self._create_standard_text_file_widget(name, param_def, current_value)
        if param_type == 'coordinate':
            return self._create_standard_text_coordinate_widget(name, current_value)
        return self._create_standard_text_default_widget(name, param_def, current_value)

    def _create_standard_text_button_widget(self, name: str, param_def: Dict[str, Any], label_text: str, widget_hint: str):
        # 按钮类型
        logger.debug(
            f"[DEBUG] 创建按钮控件: name={name}, hint={widget_hint}, "
            f"button_text={param_def.get('button_text', label_text)}, action={param_def.get('action', '')}"
        )
        widget = QPushButton(param_def.get('button_text', label_text))
        widget.setProperty("class", "primary")
        widget.clicked.connect(lambda: self._handle_button_click(name, param_def))
        logger.debug(f"[DEBUG] 按钮控件创建成功: name={name}")
        return widget

    def _create_standard_text_file_widget(self, name: str, param_def: Dict[str, Any], current_value: Any):
        # 文件选择器类型
        file_widget = QWidget()
        file_layout = QHBoxLayout(file_widget)
        file_layout.setContentsMargins(0, 0, 0, 0)

        file_edit = QLineEdit(str(current_value) if current_value else "")
        file_edit.setPlaceholderText("点击选择文件或手动输入路径...")

        # 为子工作流任务添加"编辑子流程"按钮
        if self.current_task_type == '子工作流' and name == 'workflow_file':
            # 浏览按钮
            browse_button = QPushButton("浏览...")
            browse_button.clicked.connect(lambda: self._select_file(file_edit, param_def))

            # 编辑子流程按钮
            edit_button = QPushButton("编辑子流程")
            edit_button.setProperty("class", "primary")
            edit_button.setToolTip("在新标签页中打开并编辑子工作流")
            edit_button.clicked.connect(lambda: self._open_sub_workflow_for_edit(file_edit))

            file_layout.addWidget(file_edit)
            file_layout.addWidget(browse_button)
            file_layout.addWidget(edit_button)

        # 为找图功能和拖拽图片参数添加截图工具按钮
        # 判断是否需要截图工具：
        # 1. 模拟鼠标操作任务的操作模式为找图功能时的 image_path
        # 2. 模拟鼠标操作任务的操作模式为鼠标拖拽时的 drag_start_image_path 和 drag_end_image_path
        elif name == 'image_path' or name in ['drag_start_image_path', 'drag_end_image_path'] or (
            self.current_task_type == 'A*寻路' and name in ['arrow_template_path', 'death_image_paths']
        ):
            should_show_screenshot = False
            if name == 'image_path':
                if self.current_task_type == '模拟鼠标操作':
                    # 检查操作模式是否为找图功能（兼容历史值）
                    operation_mode = self._normalize_operation_mode_value(
                        self.current_parameters.get('operation_mode', ''),
                        fallback_task_type=self.current_task_type or "",
                    )
                    if operation_mode == '找图功能':
                        should_show_screenshot = True
            elif name in ['drag_start_image_path', 'drag_end_image_path']:
                if self.current_task_type == '模拟鼠标操作':
                    operation_mode = self.current_parameters.get('operation_mode', '')
                    if operation_mode == '鼠标拖拽':
                        should_show_screenshot = True
            elif self.current_task_type == 'A*寻路':
                should_show_screenshot = True

            if should_show_screenshot:
                # 添加浏览按钮
                browse_button = QPushButton("浏览...")
                browse_button.clicked.connect(lambda: self._select_file(file_edit, param_def))

                # 创建截图工具按钮
                screenshot_button = QPushButton("截图工具")
                screenshot_button.setProperty("class", "primary")
                screenshot_button.setToolTip("点击后拖动鼠标选择区域截图\n截图将自动保存并填充路径")
                # 修复闭包问题：使用默认参数捕获当前的file_edit引用
                screenshot_button.clicked.connect(lambda checked=False, edit=file_edit: self._start_screenshot_for_param(edit))

                file_layout.addWidget(file_edit)
                file_layout.addWidget(browse_button)
                file_layout.addWidget(screenshot_button)
            else:
                # 其他文件类型只使用浏览按钮
                file_button = QPushButton("浏览...")
                file_button.clicked.connect(lambda: self._select_file(file_edit, param_def))

                file_layout.addWidget(file_edit)
                file_layout.addWidget(file_button)
        else:
            # 其他文件类型只使用浏览按钮
            file_button = QPushButton("浏览...")
            file_button.clicked.connect(lambda: self._select_file(file_edit, param_def))

            file_layout.addWidget(file_edit)
            file_layout.addWidget(file_button)

        widget = file_widget
        self._register_widget(name, file_edit)  # 存储编辑框用于获取值
        return widget

    def _create_standard_text_coordinate_widget(self, name: str, current_value: Any):
        # 坐标输入类型 - 带坐标选择工具
        coord_widget = QWidget()
        coord_layout = QHBoxLayout(coord_widget)
        coord_layout.setContentsMargins(0, 0, 0, 0)

        coord_edit = QLineEdit(str(current_value) if current_value else "0,0")
        coord_edit.setPlaceholderText("X,Y")
        # 设置基本属性确保输入功能
        coord_edit.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        coord_button = ResponsiveButton("选择坐标")
        coord_button.setProperty("class", "primary")
        coord_button.clicked.connect(lambda: self._select_coordinate(name))

        coord_layout.addWidget(coord_edit)
        coord_layout.addWidget(coord_button)

        widget = coord_widget
        self._register_widget(name, coord_edit)  # 存储编辑框用于获取值
        return widget

    def _create_standard_text_default_widget(self, name: str, param_def: Dict[str, Any], current_value: Any):
        # 检查是否为多图片路径参数
        if name in ['image_paths'] and param_def.get('multiline', False):
            # 多图片路径选择器 - 使用缩略图网格显示
            multi_file_widget = QWidget()
            multi_file_layout = QVBoxLayout(multi_file_widget)
            multi_file_layout.setContentsMargins(0, 0, 0, 0)
            multi_file_layout.setSpacing(4)

            # 隐藏的文本编辑区域（用于存储路径数据）
            text_edit = QTextEdit()
            text_edit.setVisible(False)  # 隐藏文本编辑框

            # 格式化显示当前值
            if current_value:
                display_text = self._format_existing_paths_display(str(current_value))
                text_edit.setPlainText(display_text)
            else:
                text_edit.setPlainText("")

            # 缩略图网格容器
            thumbnail_scroll = QScrollArea()
            thumbnail_scroll.setWidgetResizable(True)
            thumbnail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            thumbnail_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            # 固定高度，避免重建控件时高度变化
            thumbnail_scroll.setFixedHeight(160)
            # 添加边框样式
            from themes import theme_color

            thumbnail_scroll.setStyleSheet(
                f"QScrollArea {{ border: 1px solid {theme_color('border', '#e0e0e0')}; }}"
            )

            # 缩略图网格内容
            thumbnail_container = QWidget()
            thumbnail_container.setObjectName(f"{name}_thumbnail_container")
            thumbnail_grid = FlowLayout(thumbnail_container)  # 使用流式布局
            thumbnail_grid.setSpacing(20)
            thumbnail_grid.setContentsMargins(8, 8, 8, 8)

            thumbnail_scroll.setWidget(thumbnail_container)

            # 保存缩略图容器引用
            self.widgets[f"{name}_thumbnail_container"] = thumbnail_container

            # 初始化缩略图显示
            self._update_thumbnail_grid(name, text_edit.toPlainText())

            # 按钮区域
            button_layout = QHBoxLayout()
            button_layout.setContentsMargins(0, 0, 0, 0)

            select_button = QPushButton("选择多个图片...")
            select_button.setToolTip("打开文件选择对话框，选择多个图片文件")
            select_button.setProperty("class", "primary")
            select_button.clicked.connect(lambda: self._select_multiple_files_with_thumbnails(name, text_edit, param_def))

            clear_button = QPushButton("清空")
            clear_button.setToolTip("清空所有图片路径")
            clear_button.setProperty("class", "danger")
            clear_button.clicked.connect(lambda: self._clear_thumbnails(name, text_edit))

            # 统计信息标签
            count_label = QLabel()
            count_label.setObjectName(f"{name}_count_label")
            count_label
            self._update_path_count_label(count_label, text_edit.toPlainText())

            # 连接文本变化事件以更新统计和缩略图
            text_edit.textChanged.connect(lambda: self._update_path_count_label(count_label, text_edit.toPlainText()))
            text_edit.textChanged.connect(lambda: self._update_thumbnail_grid(name, text_edit.toPlainText()))

            button_layout.addWidget(select_button)
            button_layout.addWidget(clear_button)
            button_layout.addWidget(count_label)
            button_layout.addStretch()

            multi_file_layout.addWidget(thumbnail_scroll)
            multi_file_layout.addLayout(button_layout)
            multi_file_layout.addWidget(text_edit)  # 隐藏的文本编辑框

            widget = multi_file_widget
            self._register_widget(name, text_edit)  # 存储文本编辑框用于获取值

        elif param_def.get('multiline', False):
            # 多行文本输入
            widget = QTextEdit()
            widget.setPlainText(str(current_value) if current_value is not None else "")
            widget.setMaximumHeight(100)  # 限制高度

        else:
            # 默认单行文本输入
            widget = QLineEdit(str(current_value) if current_value is not None else "")
            # 设置基本属性确保输入功能
            widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            widget.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            widget.setCursorPosition(0)

            # 设置占位符文本
            placeholder = param_def.get('placeholder', '')
            if placeholder:
                widget.setPlaceholderText(placeholder)

            # 检查是否为只读
            if param_def.get('readonly', False):
                widget.setReadOnly(True)
                # 只读样式由全局主题管理器控制

        return widget

    def _finalize_created_widget(
        self,
        name: str,
        param_def: Dict[str, Any],
        param_type: str,
        layout: QVBoxLayout,
        row_widget: QWidget,
        row_layout: QHBoxLayout,
        widget: Optional[QWidget],
        current_value: Any,
    ) -> None:
        self._register_created_widget(name, param_def, widget)
        self._attach_created_widget_row(
            name,
            param_type,
            layout,
            row_widget,
            row_layout,
            widget,
            param_def=param_def,
        )
        self._append_image_preview_row(name, param_type, layout, current_value)
        self._append_help_text(param_def, layout)

    def _register_created_widget(self, name: str, param_def: Dict[str, Any], widget: Optional[QWidget]):
        if widget and name not in self.widgets:
            self._register_widget(name, widget, stores_value=self._should_register_value_widget(param_def))

            # 确保所有输入控件都能接收焦点和输入事件
            if hasattr(widget, 'setFocusPolicy'):
                widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

            # 为可能响应滚轮的控件安装滚轮事件过滤器
            self._install_wheel_filter(widget, name)

            # 确保输入控件能正常工作
            if isinstance(widget, (QLineEdit, QSpinBox, QDoubleSpinBox)):
                # 设置基本属性确保输入功能
                widget.setEnabled(True)
                widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

                # 强制设置更多属性
                widget.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, True)
                widget.setReadOnly(False) if hasattr(widget, 'setReadOnly') else None

                # 简化调试信息
                logger.debug(f"创建输入控件 {name}: 类型={type(widget).__name__}")

                # 为输入框添加文本变化监听（保持原有功能）
                if isinstance(widget, QLineEdit):
                    def on_text_changed(text, widget_name=name):
                        logger.debug(f"输入框 {widget_name} 文本变化: {text}")
                    widget.textChanged.connect(on_text_changed)

                    # 重写事件方法，添加焦点保护机制
                    original_focus_in = widget.focusInEvent
                    original_focus_out = widget.focusOutEvent

                    def new_focus_in(event, widget_name=name):
                        logger.debug(f"输入框 {widget_name} 获得焦点，启用焦点保护")
                        # 启用焦点保护，暂时禁用窗口激活同步
                        self._input_focus_protection_active = True
                        original_focus_in(event)

                    def new_focus_out(event, widget_name=name):
                        logger.debug(f"输入框 {widget_name} 失去焦点，延迟禁用焦点保护")
                        original_focus_out(event)
                        # 延迟禁用焦点保护，给用户切换到其他输入框的时间
                        QTimer.singleShot(500, lambda: setattr(self, '_input_focus_protection_active', False))

                    widget.focusInEvent = new_focus_in
                    widget.focusOutEvent = new_focus_out

            # 设置工具提示
            tooltip = param_def.get('tooltip', '')
            if tooltip:
                # 确保tooltip能正确显示，特别是包含换行符的长文本
                widget.setToolTip(tooltip)
                # 设置tooltip的显示时间更长一些，便于阅读
                widget.setToolTipDuration(10000)  # 10秒

            # 检查是否是影响条件显示的参数，如果是则连接信号
            self._connect_conditional_signals(name, widget)

    def _attach_created_widget_row(
        self,
        name: str,
        param_type: str,
        layout: QVBoxLayout,
        row_widget: QWidget,
        row_layout: QHBoxLayout,
        widget: Optional[QWidget],
        param_def: Optional[Dict[str, Any]] = None,
    ):
        if widget:
            logger.debug(
                f"[DEBUG] Attach widget row: name={name}, type={param_type}, widget_type={type(widget).__name__}"
            )
            widget.setFixedWidth(240)
            row_layout.addWidget(widget)
            row_layout.addStretch()
            if param_type == 'textarea' or param_type == 'multiline':
                row_widget.setMinimumHeight(70)
            layout.addWidget(row_widget)
            return

        logger.warning(
            f"[DEBUG] Widget creation returned None: name={name}, type={param_type}"
        )

    IMAGE_PREVIEW_PARAM_NAMES = {
        'image_path',
        'target_image_path',
        'drag_start_image_path',
        'drag_end_image_path',
        'arrow_template_path',
        'death_image_paths',
    }

    IMAGE_PREVIEW_TASK_TYPES = {'\u6a21\u62df\u9f20\u6807\u64cd\u4f5c', 'A*寻路'}

    def _should_append_image_preview(self, name: str, param_type: str) -> bool:
        return (
            param_type == 'file'
            and name in self.IMAGE_PREVIEW_PARAM_NAMES
            and self.current_task_type in self.IMAGE_PREVIEW_TASK_TYPES
        )

    def _append_image_preview_row(
        self,
        name: str,
        param_type: str,
        layout: QVBoxLayout,
        current_value: Any,
    ) -> None:
        if not self._should_append_image_preview(name, param_type):
            return

        logger.debug(
            f"Create image preview for task '{self.current_task_type}' param '{name}'"
        )

        preview_row_widget = QWidget()
        preview_row_layout = QHBoxLayout(preview_row_widget)
        preview_row_layout.setContentsMargins(0, 0, 0, 0)
        preview_row_layout.setSpacing(8)

        preview_text_label = QLabel('图片预览：')
        preview_text_label.setFixedWidth(140)
        preview_text_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        preview_row_layout.addWidget(preview_text_label)

        preview_label = QLabel()
        preview_label.setObjectName(f"{name}_preview")
        preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_label.setFixedHeight(80)
        preview_label.setMinimumWidth(150)
        from themes import theme_color

        preview_label.setStyleSheet(f"QLabel {{ border: 1px solid {theme_color('border', '#e0e0e0')}; }}")
        preview_label.setText('未选择图片')
        preview_label.setWordWrap(True)
        preview_label.setMouseTracking(True)
        preview_label.setProperty('image_path', '')
        preview_row_layout.addWidget(preview_label, 1)
        layout.addWidget(preview_row_widget)

        preview_key = f"{name}_preview"
        self._register_widget(preview_key, preview_label, stores_value=False)

        def on_double_click(event, path_getter=lambda: preview_label.property('image_path')):
            image_path = path_getter()
            if image_path and os.path.exists(image_path):
                self._show_image_viewer(image_path)

        preview_label.mouseDoubleClickEvent = on_double_click

        file_input = self._get_value_widget(name)
        if isinstance(file_input, QLineEdit):
            file_input.setProperty('preview_key', preview_key)

            def update_preview_handler(text, input_widget=file_input):
                current_preview_key = input_widget.property('preview_key')
                if current_preview_key and current_preview_key in self.widgets:
                    self._update_image_preview(text, self.widgets[current_preview_key])

            file_input.textChanged.connect(update_preview_handler)

            if current_value:
                self._update_image_preview(str(current_value), preview_label)

    def _append_help_text(self, param_def: Dict[str, Any], layout: QVBoxLayout) -> None:
        help_text = param_def.get('help', '')
        if not help_text:
            return

        help_label = QLabel(help_text)
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

    def _create_parameter_widgets(self):
        if not self.param_definitions:
            no_params_label = QLabel("No configurable parameters")
            no_params_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.content_layout.addWidget(no_params_label)
            return

        for name, param_def in self.param_definitions.items():
            if name.startswith('---') and name.endswith('---'):
                if self._should_show_parameter(param_def, name):
                    separator_label = param_def.get('label', '')
                    if separator_label:
                        separator = QLabel(separator_label)
                        self.content_layout.addWidget(separator)
                        self.conditional_widgets[name] = separator
                continue

            if param_def.get('type') == 'separator':
                continue
            if param_def.get('type') == 'hidden':
                continue
            if param_def.get('hidden'):
                continue
            if not self._should_show_parameter(param_def, name):
                continue

            self._create_single_parameter_widget(name, param_def, self.content_layout)

        self.content_layout.addStretch()

    def _prepare_current_parameter_value(self, name: str, param_def: Dict[str, Any]) -> Any:
        widget_hint = param_def.get('widget_hint', '')
        if widget_hint in ['card_selector', 'jump_target_selector']:
            if name not in self.current_parameters or self.current_parameters[name] is None:
                real_time_params = self._get_real_time_card_parameters()
                if name in real_time_params and real_time_params[name] is not None:
                    self.current_parameters[name] = real_time_params[name]
                    logger.info(f"[CREATE_WIDGET] {name} synced from runtime params: {real_time_params[name]}")

        current_value = self.current_parameters.get(name, param_def.get('default'))
        if name == 'operation_mode':
            normalized_mode = self._normalize_operation_mode_value(
                current_value,
                fallback_task_type=self.current_task_type or "",
            )
            if normalized_mode:
                current_value = normalized_mode
                self.current_parameters[name] = normalized_mode
        return current_value

    def _create_parameter_row(self, name: str, param_def: Dict[str, Any]) -> tuple[QWidget, QHBoxLayout]:
        label_text = param_def.get('label', name)
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        label = QLabel(f"{label_text}:")
        label.setFixedWidth(140)
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        label.setWordWrap(True)

        tooltip = param_def.get('tooltip', '')
        if tooltip:
            label.setToolTip(tooltip)
            label.setToolTipDuration(10000)

        row_layout.addWidget(label)
        return row_widget, row_layout

    def _create_single_parameter_widget(self, name: str, param_def: Dict[str, Any], layout: QVBoxLayout):
        param_type = param_def.get('type', 'text')
        label_text = param_def.get('label', name)
        current_value = self._prepare_current_parameter_value(name, param_def)
        row_widget, row_layout = self._create_parameter_row(name, param_def)

        widget = self._create_widget_by_hint(name, param_def, current_value, label_text)
        if widget is None:
            widget = self._create_widget_by_param_type(name, param_def, current_value, label_text)

        self._finalize_created_widget(
            name=name,
            param_def=param_def,
            param_type=param_type,
            layout=layout,
            row_widget=row_widget,
            row_layout=row_layout,
            widget=widget,
            current_value=current_value,
        )

    def _setup_status_display(self, widget: QWidget, param_name: str, param_def: Dict[str, Any]):
        try:
            label = param_def.get('label', param_name)
            tooltip = param_def.get('tooltip', '')
            param_type = param_def.get('type', 'text')
            status_text = f"{label}"
            if tooltip:
                status_text += f" - {tooltip}"
            else:
                status_text += f" ({param_type})"
            _ = (widget, status_text)
        except Exception as e:
            logger.warning(f"设置状态显示失败: {e}")

    def _restore_focus(self, widget, cursor_position):
        try:
            widget.setFocus()
            widget.setCursorPosition(cursor_position)
        except Exception as e:
            logger.debug(f"恢复焦点失败: {e}")

    def _restore_text_focus(self, widget, cursor_position):
        try:
            widget.setFocus()
            cursor = widget.textCursor()
            cursor.setPosition(cursor_position)
            widget.setTextCursor(cursor)
        except Exception as e:
            logger.debug(f"恢复文本焦点失败: {e}")

    def _force_refresh_for_global_config(self):
        logger.info("执行global_config条件的强制刷新")
        saved_values = self._collect_current_parameters()

        for name, value in saved_values.items():
            self.current_parameters[name] = value

        self._clear_content()
        self._create_parameter_widgets()

        for name, value in saved_values.items():
            if name in self.widgets:
                widget = self.widgets[name]
                try:
                    if isinstance(widget, QLineEdit):
                        widget.setText(str(value))
                    elif isinstance(widget, QSpinBox):
                        widget.setValue(int(value))
                    elif isinstance(widget, QDoubleSpinBox):
                        widget.setValue(float(value))
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
                    elif isinstance(widget, QTextEdit):
                        widget.setPlainText(str(value))
                except Exception as e:
                    logger.debug(f"恢复参数 {name} 值失败: {e}")

        logger.info("global_config条件强制刷新完成")
