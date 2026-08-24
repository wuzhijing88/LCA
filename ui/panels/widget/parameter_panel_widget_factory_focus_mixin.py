from ..parameter_panel_support import *


class ParameterPanelWidgetFactoryFocusMixin:
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
