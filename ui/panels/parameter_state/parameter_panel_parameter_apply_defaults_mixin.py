from ..parameter_panel_support import *


class ParameterPanelParameterApplyDefaultsMixin:
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
        coordinate_params = {'coordinate_x', 'coordinate_y'}
        for param_name, param_def in self.param_definitions.items():
            if param_name in new_parameters or 'default' not in param_def:
                continue
            if param_name in self.current_parameters and param_name not in ['', None]:
                current_value = self.current_parameters[param_name]
                if isinstance(current_value, bool):
                    new_parameters[param_name] = current_value
                    logger.debug(f'[APPLY] keep boolean parameter {param_name}: {current_value}')
                    continue
                if param_name in coordinate_params:
                    new_parameters[param_name] = current_value
                    logger.debug(f'[APPLY] keep coordinate parameter {param_name}: {current_value}')
                    continue
                if current_value not in [None, '', 0]:
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
