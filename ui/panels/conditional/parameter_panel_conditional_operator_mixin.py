from ..parameter_panel_support import *


class ParameterPanelConditionalOperatorMixin:
    def _apply_condition_operator(self, current_value: Any, expected_value: Any, operator: str) -> bool:
        """应用条件操作符"""
        try:
            if operator == '==' or operator == 'eq':
                return current_value == expected_value
            elif operator == '!=' or operator == 'ne':
                return current_value != expected_value
            elif operator == 'in':
                if isinstance(expected_value, (list, tuple)):
                    return current_value in expected_value
                else:
                    return current_value == expected_value
            elif operator == 'not_in' or operator == 'notin':
                if isinstance(expected_value, (list, tuple)):
                    return current_value not in expected_value
                else:
                    return current_value != expected_value
            elif operator == '>' or operator == 'gt':
                try:
                    return float(current_value) > float(expected_value)
                except (TypeError, ValueError):
                    return False
            elif operator == '<' or operator == 'lt':
                try:
                    return float(current_value) < float(expected_value)
                except (TypeError, ValueError):
                    return False
            elif operator == '>=' or operator == 'ge':
                try:
                    return float(current_value) >= float(expected_value)
                except (TypeError, ValueError):
                    return False
            elif operator == '<=' or operator == 'le':
                try:
                    return float(current_value) <= float(expected_value)
                except (TypeError, ValueError):
                    return False
            elif operator == 'contains':
                if isinstance(current_value, str) and isinstance(expected_value, str):
                    return expected_value in current_value
                return False
            elif operator == 'startswith':
                if isinstance(current_value, str) and isinstance(expected_value, str):
                    return current_value.startswith(expected_value)
                return False
            elif operator == 'endswith':
                if isinstance(current_value, str) and isinstance(expected_value, str):
                    return current_value.endswith(expected_value)
                return False
            else:
                logger.warning(f"未知的条件操作符: {operator}，使用默认的==操作符")
                return current_value == expected_value
        except Exception as e:
            logger.error(f"应用条件操作符失败: operator={operator}, current={current_value}, expected={expected_value}, error={e}")
            return True  # 出错时默认显示
