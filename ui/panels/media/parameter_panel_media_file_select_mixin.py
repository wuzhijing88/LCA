from ..parameter_panel_support import *


class ParameterPanelMediaFileSelectMixin:
    def _select_file(self, line_edit: QLineEdit, param_def: Dict[str, Any]):
        file_types = param_def.get('file_types')
        if file_types:
            if isinstance(file_types, list):
                file_filter = ';;'.join(file_types)
            else:
                file_filter = file_types
        else:
            file_filter = param_def.get('file_filter', 'All Files (*)')

        filename, _ = QFileDialog.getOpenFileName(self, "选择文件", "", file_filter)
        if filename:
            if self._is_yolo_model_param(param_def) and not filename.lower().endswith('.onnx'):
                ext = filename.rsplit('.', 1)[-1] if '.' in filename else ''
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(
                    self,
                    "模型格式提示",
                    f"检测到您选择的是 .{ext} 格式模型?\n\n"
                    f"本程序仅支持 ONNX 格式模型，请先将模型转换为 .onnx 格式?"
                )
                return

            param_name = self._get_registered_widget_name(line_edit)
            selected_value = self._normalize_single_image_parameter_value(param_name, filename)
            line_edit.setText(selected_value)
            self._update_current_parameter_from_widget(line_edit, selected_value)
            self._apply_parameters(auto_close=False)

    def _is_yolo_model_param(self, param_def: Dict[str, Any]) -> bool:
        file_types = param_def.get('file_types', [])
        if isinstance(file_types, list):
            for ft in file_types:
                if 'onnx' in ft.lower() or 'yolo' in ft.lower():
                    return True
        elif isinstance(file_types, str):
            if 'onnx' in file_types.lower() or 'yolo' in file_types.lower():
                return True
        return False
