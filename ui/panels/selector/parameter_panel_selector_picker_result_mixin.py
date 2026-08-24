from ..parameter_panel_support import *
from utils.window_activation_utils import show_and_activate_overlay


class ParameterPanelSelectorPickerResultMixin:
    _CONTROL_TYPE_EN_TO_CN = {
        "ButtonControl": "按钮",
        "EditControl": "编辑框",
        "TextControl": "文本",
        "CheckBoxControl": "复选框",
        "RadioButtonControl": "单选按钮",
        "ComboBoxControl": "下拉框",
        "ListControl": "列表",
        "ListItemControl": "列表项",
        "MenuControl": "菜单",
        "MenuItemControl": "菜单项",
        "TreeControl": "树",
        "TreeItemControl": "树节点",
        "TabControl": "选项卡",
        "TabItemControl": "选项卡项",
        "HyperlinkControl": "超链接",
        "WindowControl": "窗口",
        "PaneControl": "面板",
        "GroupControl": "分组",
        "DataGridControl": "数据表格",
        "TableControl": "表格",
    }

    @Slot()
    def _close_picker_overlay(self):
        """Close picker overlay."""
        try:
            if hasattr(self, '_picker_overlay') and self._picker_overlay:
                self._picker_overlay.close()
                self._picker_overlay = None
        except Exception:
            pass

    @Slot()
    def _on_picking_cancelled(self):
        """Handle picking cancelled."""
        self._close_picker_overlay()
        self._restore_picker_ui_state()

    @Slot()
    def _on_element_picked(self):
        """Handle element picked."""
        self._close_picker_overlay()
        self._restore_picker_ui_state()

        info = self._get_picked_info_or_warn()
        if info is None:
            return

        self._clear_picked_element_fields()
        control_type_cn = self._translate_control_type(info.control_type)
        element_fields = self._build_picked_element_fields(info, control_type_cn)
        filled_count = self._apply_picked_element_fields(element_fields)
        self._show_picked_element_result(info, control_type_cn, filled_count)

    def _restore_picker_ui_state(self) -> None:
        if hasattr(self, 'main_window') and self.main_window:
            self.main_window.showNormal()
            show_and_activate_overlay(self.main_window, log_prefix='元素拾取主窗口恢复', focus=True)
        self._set_element_picker_button_state(False)

    def _get_picked_info_or_warn(self):
        info = getattr(self, '_picked_info', None)
        if info is not None:
            return info
        QMessageBox.warning(
            self,
            "拾取失败",
            "未能获取到元素信息，请确保鼠标在目标元素上",
        )
        return None

    def _clear_picked_element_fields(self) -> None:
        for field_name in ['element_name', 'element_automation_id', 'element_class_name', 'element_control_type']:
            if field_name not in self.widgets:
                continue
            widget = self.widgets[field_name]
            if isinstance(widget, QLineEdit):
                widget.setText("")
                self.current_parameters[field_name] = ""
            elif isinstance(widget, QComboBox):
                widget.setCurrentIndex(0)
                self.current_parameters[field_name] = ""

    def _translate_control_type(self, control_type: str) -> str:
        if not control_type:
            return ""
        return self._CONTROL_TYPE_EN_TO_CN.get(control_type, control_type)

    def _build_picked_element_fields(self, info, control_type_cn: str) -> Dict[str, str]:
        return {
            'element_name': info.name,
            'element_automation_id': info.automation_id,
            'element_class_name': info.class_name,
            'element_control_type': control_type_cn,
        }

    def _apply_picked_element_fields(self, element_fields: Dict[str, str]) -> int:
        filled_count = 0
        for field_name, value in element_fields.items():
            if not value or field_name not in self.widgets:
                continue
            widget = self.widgets[field_name]
            if isinstance(widget, QLineEdit):
                widget.setText(value)
                self.current_parameters[field_name] = value
                filled_count += 1
            elif isinstance(widget, QComboBox):
                filled_count += self._apply_picked_combo_value(widget, field_name, value)
        return filled_count

    def _apply_picked_combo_value(self, widget: QComboBox, field_name: str, value: str) -> int:
        index = widget.findText(value)
        if index >= 0:
            widget.setCurrentIndex(index)
            self.current_parameters[field_name] = value
            return 1
        if value.endswith('Control'):
            return 0
        value_with_suffix = value + 'Control'
        index = widget.findText(value_with_suffix)
        if index < 0:
            return 0
        widget.setCurrentIndex(index)
        self.current_parameters[field_name] = value_with_suffix
        return 1

    def _show_picked_element_result(self, info, control_type_cn: str, filled_count: int) -> None:
        if filled_count <= 0:
            QMessageBox.warning(self, "拾取结果", "元素没有可用的属性信息")
            return

        msg = f"已填充 {filled_count} 个属性:\n"
        if info.name:
            msg += f"  名称: {info.name}\n"
        if info.automation_id:
            msg += f"  自动化标识: {info.automation_id}\n"
        if info.class_name:
            msg += f"  类名: {info.class_name}\n"
        if control_type_cn:
            msg += f"  控件类型: {control_type_cn}"
        QMessageBox.information(self, "拾取成功", msg)
