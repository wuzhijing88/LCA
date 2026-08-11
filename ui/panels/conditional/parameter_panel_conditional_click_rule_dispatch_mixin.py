from ..parameter_panel_support import *


class ParameterPanelConditionalClickRuleDispatchMixin:
    def _should_hide_click_related_parameter(self, param_name: str) -> bool:
        """根据找图/找色点击开关，隐藏点击相关参数。"""
        if not param_name:
            return False

        current_task_type = str(getattr(self, 'current_task_type', '') or '').strip()
        current_params = getattr(self, 'current_parameters', {}) or {}

        if current_task_type == '模拟鼠标操作':
            return self._should_hide_mouse_operation_click_parameter(param_name, current_task_type, current_params)

        if current_task_type in {'图片点击', '查找图片并点击'}:
            return self._should_hide_simple_click_task_parameter(
                param_name,
                current_params,
                self._FIND_IMAGE_CLICK_PARAMS,
            )

        if current_task_type in {'点击指定坐标', '坐标点击', '点击坐标'}:
            return self._should_hide_simple_click_task_parameter(
                param_name,
                current_params,
                self._COORDINATE_CLICK_TASK_PARAMS,
            )

        return False

    def _should_hide_mouse_operation_click_parameter(
        self,
        param_name: str,
        current_task_type: str,
        current_params: Dict[str, Any],
    ) -> bool:
        operation_mode = self._normalize_operation_mode_value(
            current_params.get('operation_mode', ''),
            fallback_task_type=current_task_type,
        )
        rule_mapping = {
            '找图功能': ('image_enable_click', self._MOUSE_IMAGE_CLICK_PARAMS),
            '找色功能': ('color_enable_click', self._MOUSE_COLOR_CLICK_PARAMS),
            '文字点击': ('text_enable_click', self._MOUSE_TEXT_CLICK_PARAMS),
            '坐标点击': ('coordinate_enable_click', self._MOUSE_COORDINATE_CLICK_PARAMS),
            '元素点击': ('element_enable_click', self._MOUSE_ELEMENT_CLICK_PARAMS),
        }
        toggle_name, hidden_params = rule_mapping.get(operation_mode, (None, None))
        if not toggle_name or hidden_params is None:
            return False
        if self._click_rule_to_bool(current_params.get(toggle_name, True), True):
            return False
        return param_name in hidden_params

    def _should_hide_simple_click_task_parameter(
        self,
        param_name: str,
        current_params: Dict[str, Any],
        hidden_params: Set[str],
    ) -> bool:
        if self._click_rule_to_bool(current_params.get('enable_click', True), True):
            return False
        return param_name in hidden_params
