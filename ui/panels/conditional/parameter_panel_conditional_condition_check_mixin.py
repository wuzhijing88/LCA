from ..parameter_panel_support import *


class ParameterPanelConditionalConditionCheckMixin:
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
