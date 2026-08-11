from ..parameter_panel_support import *


class ParameterPanelWidgetInteractiveToolHintRegionMixin:
    def _create_interactive_ocr_region_widget(self, name: str, param_def: Dict[str, Any]):
        widget = ResponsiveButton(param_def.get('button_text', '框选区域'))
        widget.setProperty('class', 'primary')
        widget.clicked.connect(lambda: self._select_ocr_region(name))
        return widget

    def _create_interactive_motion_region_widget(self, name: str, param_def: Dict[str, Any]):
        widget = ResponsiveButton(param_def.get('button_text', '选择检测区域'))
        widget.setProperty('class', 'primary')
        widget.clicked.connect(lambda: self._select_motion_region(name))
        return widget

    def _create_interactive_image_region_widget(self, name: str, param_def: Dict[str, Any]):
        widget = ResponsiveButton(param_def.get('button_text', '点击框选识别区域'))
        widget.setProperty('class', 'primary')
        param_prefix = param_def.get('param_prefix', 'recognition_region')
        initial_x = self.current_parameters.get(f'{param_prefix}_x', 0)
        initial_y = self.current_parameters.get(f'{param_prefix}_y', 0)
        initial_width = self.current_parameters.get(f'{param_prefix}_width', 0)
        initial_height = self.current_parameters.get(f'{param_prefix}_height', 0)
        if initial_width > 0 and initial_height > 0:
            widget.setText(f'区域: X={initial_x}, Y={initial_y}, {initial_width}x{initial_height}')
        widget.clicked.connect(lambda: self._select_image_region(name))
        return widget

    def _create_interactive_multi_image_region_widget(self, name: str, param_def: Dict[str, Any]):
        widget = ResponsiveButton(param_def.get('button_text', '点击框选识别区域'))
        widget.setProperty('class', 'primary')
        initial_x = self.current_parameters.get('multi_recognition_region_x', 0)
        initial_y = self.current_parameters.get('multi_recognition_region_y', 0)
        initial_width = self.current_parameters.get('multi_recognition_region_width', 0)
        initial_height = self.current_parameters.get('multi_recognition_region_height', 0)
        if initial_width > 0 and initial_height > 0:
            widget.setText(f'区域: X={initial_x}, Y={initial_y}, {initial_width}x{initial_height}')
        widget.clicked.connect(lambda: self._select_multi_image_region(name))
        return widget

    def _create_interactive_color_region_widget(self, name: str, param_def: Dict[str, Any]):
        widget = ResponsiveButton(param_def.get('button_text', '点击框选识别区域'))
        widget.setProperty('class', 'primary')
        search_region_enabled = self.current_parameters.get('search_region_enabled', False)
        if search_region_enabled:
            initial_x = int(self.current_parameters.get('search_region_x', 0) or 0)
            initial_y = int(self.current_parameters.get('search_region_y', 0) or 0)
            initial_width = int(self.current_parameters.get('search_region_width', 0) or 0)
            initial_height = int(self.current_parameters.get('search_region_height', 0) or 0)
            if initial_width > 0 and initial_height > 0:
                widget.setText(f'区域: X={initial_x}, Y={initial_y}, {initial_width}x{initial_height}')
        widget.clicked.connect(lambda: self._select_color_search_region(name))
        return widget
