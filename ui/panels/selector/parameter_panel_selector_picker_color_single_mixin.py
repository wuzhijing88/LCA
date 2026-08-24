from ..parameter_panel_support import *

from .parameter_panel_selector_picker_color_coordinate_dialog_mixin import (
    ParameterPanelSelectorPickerColorCoordinateDialogMixin,
)


class ParameterPanelSelectorPickerColorSingleMixin(
    ParameterPanelSelectorPickerColorCoordinateDialogMixin,
):

    def _select_color_rgb(self, line_edit: QLineEdit):
        try:
            from PySide6.QtWidgets import QMessageBox

            dialog, color_picker = self._create_color_coordinate_dialog()
            self._apply_initial_color_string_to_picker(color_picker, line_edit.text())

            def on_dialog_accepted():
                logger.info("确定按钮被点击（对话框accepted）")
                color_string = color_picker.get_color_string()
                logger.info(f"获取到颜色字符串: '{color_string}'")
                if not color_string:
                    logger.warning("颜色字符串为空")
                    QMessageBox.warning(self, "提示", "未选择任何颜色")
                    dialog.close()
                    return

                line_edit.setText(color_string)
                param_name = self._update_current_parameter_from_widget(line_edit, color_string)
                if param_name:
                    updates = {param_name: color_string}
                    self._store_color_picker_base_point(color_picker, updates)
                    self._emit_color_picker_updates(updates)
                logger.info(f"颜色选择完成: {color_string}")
                dialog.close()

            def on_dialog_rejected():
                logger.info("对话框被取消（rejected）")
                dialog.close()

            dialog.accepted.connect(on_dialog_accepted)
            dialog.rejected.connect(on_dialog_rejected)
            self._show_color_coordinate_dialog(dialog)
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            import traceback

            logger.error(f"颜色选择器启动失败: {e}")
            logger.error(traceback.format_exc())
            QMessageBox.critical(self, "错误", f"颜色选择器启动失败: {e}")
