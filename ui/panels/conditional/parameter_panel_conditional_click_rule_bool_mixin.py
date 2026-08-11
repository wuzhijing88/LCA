from ..parameter_panel_support import *


class ParameterPanelConditionalClickRuleBoolMixin:
    @staticmethod
    def _click_rule_to_bool(value, default=True):
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        if isinstance(value, (int, float)):
            return value != 0
        text = str(value).strip().lower()
        if text in {'true', '1', 'yes', 'on', '是', '启用'}:
            return True
        if text in {'false', '0', 'no', 'off', '否', '禁用'}:
            return False
        return default
