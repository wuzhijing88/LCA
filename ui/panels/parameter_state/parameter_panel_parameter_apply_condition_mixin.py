from ..parameter_panel_support import *


class ParameterPanelParameterApplyConditionMixin:
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
