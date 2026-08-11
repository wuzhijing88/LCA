from ..parameter_panel_support import *


class ParameterPanelWidgetBasicSelectorHintDispatchMixin:
    def _create_basic_selector_widget_by_hint(self, name: str, param_def: Dict[str, Any], current_value: Any, label_text: str):
        _ = label_text
        widget_hint = param_def.get('widget_hint', '')
        if widget_hint in {'jump_target_selector', 'card_selector'}:
            return self._create_jump_target_selector_widget(name, current_value)
        if widget_hint == 'thread_target_selector':
            return self._create_thread_target_selector_widget(name, param_def, current_value)
        if widget_hint == 'bound_window_selector':
            return self._create_bound_window_selector_widget(current_value)
        if widget_hint == 'workflow_card_selector':
            return self._create_workflow_card_selector_widget(param_def, current_value)
        if widget_hint == 'package_selector':
            return self._create_package_selector_widget(name, current_value)
        if widget_hint == 'pc_app_selector':
            return self._create_pc_app_selector_widget(name, current_value)
        if widget_hint == 'file_selector':
            return self._create_file_selector_widget(name, param_def, current_value)
        if widget_hint == 'color_selector':
            return self._create_color_selector_widget(name, current_value)
        if widget_hint == 'workflow_selector':
            return self._create_workflow_selector_widget(name, current_value)
        return None
