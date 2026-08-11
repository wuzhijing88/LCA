from ..parameter_panel_support import *


class ParameterPanelWidgetRegistryMixin:

    def _set_footer_buttons_visible(self, visible: bool):
        if hasattr(self, 'apply_button') and self.apply_button is not None:
            self.apply_button.setVisible(visible)
        if hasattr(self, 'reset_button') and self.reset_button is not None:
            self.reset_button.setVisible(visible)

    def _register_widget(self, name: str, widget: QWidget, *, stores_value: bool = True) -> None:
        """统一注册面板控件，区分真实参数控件与辅助控件。"""
        self.widgets[name] = widget
        if stores_value:
            self.value_widgets[name] = widget
        else:
            self.value_widgets.pop(name, None)

    def _should_register_value_widget(self, param_def: Dict[str, Any]) -> bool:
        """判断控件是否承载实际参数值。"""
        param_type = str(param_def.get('type', '') or '').strip().lower()
        widget_hint = str(param_def.get('widget_hint', '') or '').strip()

        non_value_widget_hints = {
            'element_picker',
            'ocr_region_selector',
            'coordinate_selector',
            'coordinate_selector_with_display',
            'offset_selector',
            'motion_region_selector',
            'image_region_selector',
            'multi_image_region_selector',
            'yolo_realtime_preview',
            'record_control',
            'replay_control',
            'action_editor',
        }

        if param_type == 'button':
            return False
        return widget_hint not in non_value_widget_hints

    def _get_value_widget(self, name: str) -> Optional[QWidget]:
        return self.value_widgets.get(name)

    def _iter_value_widgets(self):
        return self.value_widgets.items()

    def _get_registered_widget_name(self, target_widget: QWidget) -> Optional[str]:
        for name, widget in self.value_widgets.items():
            if widget is target_widget:
                return name
        return None

    @staticmethod
    def _is_single_image_parameter_name(name: Optional[str]) -> bool:
        return bool(name) and (name == "image_path" or str(name).endswith("_image_path"))

    def _normalize_single_image_parameter_value(self, name: Optional[str], value: Any) -> Any:
        if not self._is_single_image_parameter_name(name):
            return value
        return normalize_workflow_image_path(value)

    def _update_current_parameter_from_widget(self, target_widget: QWidget, value: Any) -> Optional[str]:
        name = self._get_registered_widget_name(target_widget)
        if name is None:
            return None
        self.current_parameters[name] = self._normalize_single_image_parameter_value(name, value)
        return name

    def _clear_content(self):
        """清除内容区域的所有控件"""
        logger.debug(f"清除参数面板内容 - card_id: {self.current_card_id}")
        self._stop_combo_key_sequence_recording()
        self._clear_favorites_runtime_refs()

        # 【修复】先断开所有文件输入框的信号连接，防止图片预览混入其他任务
        for name, widget in list(self.value_widgets.items()):
            if isinstance(widget, QLineEdit):
                try:
                    # 尝试断开所有信号连接
                    widget.textChanged.disconnect()
                    logger.debug(f"已断开 {name} 的textChanged信号")
                except:
                    pass  # 如果没有连接，忽略错误

        while self.content_layout.count():
            child = self.content_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
            elif child.layout():
                # 清理嵌套布局（如图片预览的QHBoxLayout）
                nested_layout = child.layout()
                while nested_layout.count():
                    nested_child = nested_layout.takeAt(0)
                    if nested_child.widget():
                        nested_child.widget().deleteLater()
                nested_layout.deleteLater()
        self.widgets.clear()
        self.value_widgets.clear()
        self.conditional_widgets.clear()

