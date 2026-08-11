from ..parameter_panel_support import *


class ParameterPanelConditionalDisplayMixin:

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
