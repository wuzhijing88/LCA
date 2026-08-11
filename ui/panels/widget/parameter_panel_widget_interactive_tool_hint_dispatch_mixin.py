from ..parameter_panel_support import *


class ParameterPanelWidgetInteractiveToolHintDispatchMixin:
    def _create_interactive_tool_widget_by_hint(self, name: str, param_def: Dict[str, Any], current_value: Any, label_text: str):
        _ = label_text
        widget_hint = param_def.get('widget_hint', '')
        if widget_hint == 'element_picker':
            return self._create_interactive_element_picker_widget(param_def)
        if widget_hint == 'enable_browser_accessibility':
            return self._create_interactive_browser_accessibility_widget(param_def)
        if widget_hint == 'colorpicker':
            return self._create_interactive_colorpicker_widget(name, current_value)
        if widget_hint == 'ocr_region_selector':
            return self._create_interactive_ocr_region_widget(name, param_def)
        if widget_hint == 'coordinate_selector':
            return self._create_interactive_coordinate_widget(name, param_def)
        if widget_hint == 'coordinate_selector_with_display':
            return self._create_interactive_coordinate_display_widget(name, param_def)
        if widget_hint == 'offset_selector':
            return self._create_interactive_offset_widget(name, param_def)
        if widget_hint == 'motion_region_selector':
            return self._create_interactive_motion_region_widget(name, param_def)
        if widget_hint == 'image_region_selector':
            return self._create_interactive_image_region_widget(name, param_def)
        if widget_hint == 'multi_image_region_selector':
            return self._create_interactive_multi_image_region_widget(name, param_def)
        if widget_hint == 'yolo_realtime_preview':
            return self._create_interactive_yolo_preview_widget(param_def)
        if widget_hint == 'color_region_selector':
            return self._create_interactive_color_region_widget(name, param_def)
        return None
