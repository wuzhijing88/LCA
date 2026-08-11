from ..parameter_panel_support import *


class ParameterPanelParameterApplyCollectMixin:
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
                        f'Collect coordinates from selector: '
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
