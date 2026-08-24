from ..parameter_panel_support import *


class ParameterPanelWidgetFactoryBuildMixin:
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
