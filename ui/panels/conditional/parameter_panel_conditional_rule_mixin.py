from .parameter_panel_conditional_click_rule_mixin import ParameterPanelConditionalClickRuleMixin
from .parameter_panel_conditional_evaluator_mixin import ParameterPanelConditionalEvaluatorMixin


class ParameterPanelConditionalRuleMixin(
    ParameterPanelConditionalClickRuleMixin,
    ParameterPanelConditionalEvaluatorMixin,
):
    pass
