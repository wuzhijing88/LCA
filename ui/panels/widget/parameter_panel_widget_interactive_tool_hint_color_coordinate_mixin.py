from ..parameter_panel_support import *


class ParameterPanelWidgetInteractiveToolHintColorCoordinateMixin:
    def _create_interactive_colorpicker_widget(self, name: str, current_value: Any):
        from themes import get_theme_manager
        from PySide6.QtWidgets import QListWidget

        theme_manager = get_theme_manager()
        color_widget = QWidget()
        color_layout = QVBoxLayout(color_widget)
        color_layout.setContentsMargins(0, 0, 0, 0)
        color_layout.setSpacing(6)

        color_list = QListWidget()
        color_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        color_list.setSpacing(2)

        border_color = theme_manager.get_color('border')
        bg_color = theme_manager.get_color('background')
        color_list.setStyleSheet(
            f'QListWidget {{ border: 1px solid {border_color}; background-color: {bg_color}; }}'
        )

        raw_value = str(current_value) if current_value else ''
        self._populate_color_list(color_list, raw_value)
        item_count = color_list.count()
        color_list.setFixedHeight(min(150, max(60, item_count * 30 + 10)))

        color_layout.addWidget(color_list)

        color_button = QPushButton('选择颜色')
        color_button.setProperty('class', 'primary')
        color_button.clicked.connect(lambda: self._select_color_rgb_list(color_list, name))
        color_layout.addWidget(color_button)

        self._register_widget(name, color_list)
        color_list.setProperty('raw_color_data', raw_value)
        return color_widget

    def _create_interactive_coordinate_widget(self, name: str, param_def: Dict[str, Any]):
        widget = ResponsiveButton(param_def.get('button_text', '点击获取坐标'))
        widget.setProperty('class', 'primary')
        widget.clicked.connect(lambda: self._select_coordinate(name))
        return widget

    def _create_interactive_coordinate_display_widget(self, name: str, param_def: Dict[str, Any]):
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(4)

        coord_button = ResponsiveButton(param_def.get('button_text', '点击获取坐标'))
        coord_button.setProperty('class', 'primary')
        container_layout.addWidget(coord_button)

        coord_edit = QLineEdit()
        coord_edit.setReadOnly(True)

        related_params = param_def.get('related_params', ['coordinate_x', 'coordinate_y'])
        x_param = related_params[0] if len(related_params) > 0 else 'coordinate_x'
        y_param = related_params[1] if len(related_params) > 1 else 'coordinate_y'

        x_value = self.current_parameters.get(x_param, 0)
        y_value = self.current_parameters.get(y_param, 0)
        coord_edit.setText(f'{x_value},{y_value}')
        container_layout.addWidget(coord_edit)

        coord_display_key = f'_coord_display_{name}'
        setattr(self, coord_display_key, coord_edit)
        coord_params_key = f'_coord_params_{name}'
        setattr(self, coord_params_key, (x_param, y_param, related_params))

        coord_button.clicked.connect(lambda: self._select_coordinate_with_display(name))
        self._register_widget(name, coord_button, stores_value=False)
        return container

    def _create_interactive_offset_widget(self, name: str, param_def: Dict[str, Any]):
        widget = ResponsiveButton(param_def.get('button_text', '拖拽选择偏移'))
        widget.setProperty('class', 'primary')
        widget.clicked.connect(lambda: self._select_offset(name))
        return widget
