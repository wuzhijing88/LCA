from ..parameter_panel_support import *


class ParameterPanelParameterCollectMixin:

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
