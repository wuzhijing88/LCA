from .parameter_panel_conditional_click_rule_bool_mixin import (
    ParameterPanelConditionalClickRuleBoolMixin,
)
from .parameter_panel_conditional_click_rule_dispatch_mixin import (
    ParameterPanelConditionalClickRuleDispatchMixin,
)
from .parameter_panel_conditional_click_rule_params_mixin import (
    ParameterPanelConditionalClickRuleParamsMixin,
)


class ParameterPanelConditionalClickRuleMixin(
    ParameterPanelConditionalClickRuleBoolMixin,
    ParameterPanelConditionalClickRuleParamsMixin,
    ParameterPanelConditionalClickRuleDispatchMixin,
):
    pass
