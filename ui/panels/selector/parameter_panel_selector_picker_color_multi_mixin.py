from .parameter_panel_selector_picker_color_coordinate_dialog_mixin import (
    ParameterPanelSelectorPickerColorCoordinateDialogMixin,
)
from ..parameter_panel_support import logger


class ParameterPanelSelectorPickerColorMultiMixin(
    ParameterPanelSelectorPickerColorCoordinateDialogMixin,
):

    def _restore_multi_color_raw_data(self, color_list, param_name: str):
        current_raw = color_list.property("raw_color_data")
        if current_raw:
            return current_raw
        current_raw = self.current_parameters.get(param_name, "")
        if current_raw and str(current_raw).strip():
            color_list.setProperty("raw_color_data", current_raw)
            logger.debug(f"[颜色选择器] 从 current_parameters 恢复颜色数据: {current_raw}")
        return current_raw

    def _apply_multi_color_string(self, color_list, param_name: str, color_string, color_picker):
        self._populate_color_list(color_list, color_string)
        item_count = color_list.count()
        color_list.setFixedHeight(min(150, max(60, item_count * 30 + 10)))
        color_list.setProperty("raw_color_data", color_string)

        updates = {param_name: color_string}
        self.current_parameters[param_name] = color_string
        self._store_color_picker_base_point(color_picker, updates)
        self._emit_color_picker_updates(updates)
        if hasattr(self, "_refresh_arrow_preview"):
            self._refresh_arrow_preview(param_name)

    def _select_color_rgb_list(self, color_list, param_name: str):
        try:
            from PySide6.QtWidgets import QMessageBox

            dialog, color_picker = self._create_color_coordinate_dialog()
            current_raw = self._restore_multi_color_raw_data(color_list, param_name)
            self._apply_initial_color_string_to_picker(color_picker, current_raw)

            def on_dialog_accepted():
                color_string = color_picker.get_color_string()
                if not color_string:
                    QMessageBox.warning(self, "提示", "未选择任何颜色")
                    dialog.close()
                    return

                self._apply_multi_color_string(color_list, param_name, color_string, color_picker)
                logger.info(f"颜色选择完成: {color_string}")
                dialog.close()

            dialog.accepted.connect(on_dialog_accepted)
            dialog.rejected.connect(dialog.close)
            self._show_color_coordinate_dialog(dialog)
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            import traceback

            logger.error(f"颜色选择器启动失败: {e}")
            logger.error(traceback.format_exc())
            QMessageBox.critical(self, "错误", f"颜色选择器启动失败: {e}")
