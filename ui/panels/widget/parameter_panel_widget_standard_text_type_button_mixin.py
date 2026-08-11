from ..parameter_panel_support import *


class ParameterPanelWidgetStandardTextTypeButtonMixin:
    def _create_standard_text_button_widget(self, name: str, param_def: Dict[str, Any], label_text: str, widget_hint: str):
        # 按钮类型
        logger.debug(f"[DEBUG] 创建按钮控件: name={name}, button_text={param_def.get('button_text', label_text)}, action={param_def.get('action', '')}")
        widget = QPushButton(param_def.get('button_text', label_text))
        widget.setProperty("class", "primary")
        # 按钮点击事件
        if name == 'refresh_apps':
            widget.clicked.connect(lambda: self._handle_refresh_apps_click())
        elif widget_hint == 'pc_app_manager':
            widget.clicked.connect(lambda: self._handle_pc_app_manager_click())
        else:
            widget.clicked.connect(lambda: self._handle_button_click(name, param_def))
        logger.debug(f"[DEBUG] 按钮控件创建成功: name={name}")
        return widget
