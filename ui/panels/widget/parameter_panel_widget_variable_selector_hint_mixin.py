from .parameter_panel_widget_variable_selector_hint_card_mixin import (
    ParameterPanelWidgetVariableSelectorHintCardMixin,
)
from .parameter_panel_widget_variable_selector_hint_dispatch_mixin import (
    ParameterPanelWidgetVariableSelectorHintDispatchMixin,
)
from .parameter_panel_widget_variable_selector_hint_name_mixin import (
    ParameterPanelWidgetVariableSelectorHintNameMixin,
)


class ParameterPanelWidgetVariableSelectorHintMixin(
    ParameterPanelWidgetVariableSelectorHintDispatchMixin,
    ParameterPanelWidgetVariableSelectorHintCardMixin,
    ParameterPanelWidgetVariableSelectorHintNameMixin,
):
    pass
