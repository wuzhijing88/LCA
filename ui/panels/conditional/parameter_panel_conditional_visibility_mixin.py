from ..parameter_panel_support import *


class ParameterPanelConditionalVisibilityMixin:
    def _should_show_parameter(self, param_def: Dict[str, Any], param_name: str = None) -> bool:
        """检查参数是否应该显示（基于条件）"""
        try:
            if self._should_hide_click_related_parameter(param_name):
                return False

            condition = param_def.get('condition', param_def.get('conditions'))
            if not condition:
                return True

            # 确保current_parameters存在
            if not hasattr(self, 'current_parameters') or self.current_parameters is None:
                return True

            # 支持多条件（列表形式）和单条件（字典形式）
            if isinstance(condition, list):
                # 多条件：所有条件都必须满足（AND逻辑）
                for single_condition in condition:
                    if not self._check_single_condition(single_condition):
                        return False
                return True
            else:
                # 单条件 - 包含原有的特殊处理逻辑
                param_name = condition.get('param')
                expected_value = condition.get('value')

                if not param_name or expected_value is None:
                    return True

                # 获取当前参数值，如果不存在则使用参数定义中的默认值
                current_value = self.current_parameters.get(param_name)
                if current_value is None and hasattr(self, 'param_definitions') and self.param_definitions:
                    param_def = self.param_definitions.get(param_name, {})
                    current_value = param_def.get('default')

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

                # 检查是否有额外的AND条件
                and_condition = condition.get('and')
                if and_condition:
                    # 处理AND条件
                    if isinstance(and_condition, list):
                        # 多个AND条件
                        for and_cond in and_condition:
                            if not self._check_single_condition(and_cond):
                                return False
                    else:
                        # 单个AND条件
                        if not self._check_single_condition(and_condition):
                            return False

                # 特殊处理：对于依赖multi_image_mode的参数，需要额外检查operation_mode
                if param_name == 'multi_image_mode':
                    # 检查operation_mode是否为找图功能（兼容历史值）
                    operation_mode = self.current_parameters.get('operation_mode')
                    if operation_mode not in {'找图功能', '图片点击', '找图点击'}:
                        return False

                return True
        except Exception as e:
            logger.error(f"参数显示条件检查失败: {e}")
            return True  # 出错时默认显示
