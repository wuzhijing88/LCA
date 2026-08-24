from ..parameter_panel_support import *


class ParameterPanelWidgetMultilineTypeDispatchMixin:
    def _create_multiline_widget_by_type(self, name: str, param_def: Dict[str, Any], current_value: Any, label_text: str):
        _ = label_text
        param_type = param_def.get('type', 'text')
        widget_hint = param_def.get('widget_hint', '')
        if param_type not in ('textarea', 'multiline'):
            return None
        if param_def.get('readonly', False) and name == 'connected_targets':
            return self._create_multiline_connected_targets_widget()
        if name == 'path_points':
            return self._create_multiline_path_points_widget(name, current_value)
        if widget_hint == 'template_preset_editor':
            return self._create_multiline_template_preset_widget(name, param_def, current_value)
        return self._create_multiline_plain_text_widget(param_def, current_value)
