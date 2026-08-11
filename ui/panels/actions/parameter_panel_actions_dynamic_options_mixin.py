from ..parameter_panel_support import *


class ParameterPanelActionsDynamicOptionsMixin:
    _DEFAULT_DYNAMIC_OPTIONS = ["全部类别"]

    def _handle_refresh_dynamic_options(self, param_def: Dict[str, Any]):
        """Refresh dynamic options."""
        try:
            target_params = self._resolve_dynamic_target_params(param_def)
            if not target_params:
                QMessageBox.warning(self, "错误", "未配置目标下拉框")
                return

            source_value = self._get_dynamic_source_value(param_def.get('source_param', ''))
            source_label = self._get_dynamic_source_label(param_def)
            if not source_value:
                QMessageBox.warning(self, "提示", f"请先设置{source_label}")
                return

            target_widgets, missing_targets = self._resolve_dynamic_target_widgets(target_params)
            if not target_widgets:
                QMessageBox.warning(self, "错误", f"未找到目标下拉框: {', '.join(missing_targets)}")
                return

            options_func_name = param_def.get('options_func', '')
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
            options = func(source_value)
            if isinstance(options, (list, tuple, set)):
                normalized = [str(item or "").strip() for item in options if str(item or "").strip()]
                if normalized:
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
