from ..parameter_panel_support import *


class ParameterPanelMediaMultiImageSelectionDialogMixin:
    def _select_multiple_files(self, text_edit: QTextEdit, param_def: Dict[str, Any]):
        """Select multiple files."""
        try:
            file_paths = self._get_multi_image_selected_files(param_def)
            if not file_paths:
                return
            display_text = self._format_image_paths_display(file_paths)
            new_text = self._merge_multi_image_display_text(text_edit.toPlainText().strip(), display_text)
            self._sync_multi_image_text_edit(text_edit, new_text)
            self._update_current_parameter_from_widget(text_edit, new_text)
            logger.info(f"已选择 {len(file_paths)} 个文件")
        except Exception as e:
            logger.error(f"选择多个文件时发生错误: {e}")

    def _select_multiple_files_with_thumbnails(self, param_name: str, text_edit: QTextEdit, param_def: Dict[str, Any]):
        """Select multiple files with thumbnails."""
        try:
            file_paths = self._get_multi_image_selected_files(param_def)
            if not file_paths:
                return
            display_text = self._format_image_paths_display(file_paths)
            new_text = self._merge_multi_image_display_text(text_edit.toPlainText().strip(), display_text)
            self._sync_multi_image_text_edit(text_edit, new_text)
            self._sync_multi_image_parameter_value(param_name, new_text, emit_signal=True)
            logger.info(f"已选择 {len(file_paths)} 个文件")
        except Exception as e:
            logger.error(f"选择多个文件时发生错误: {e}")

    def _get_multi_image_selected_files(self, param_def: Dict[str, Any]):
        file_filter = param_def.get(
            'file_filter',
            '图片文件 (*.png *.jpg *.jpeg *.bmp *.gif);;所有文件 (*.*)',
        )
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            '选择多个图片文件',
            '',
            file_filter,
        )
        return file_paths

    def _merge_multi_image_display_text(self, current_text: str, display_text: str) -> str:
        if current_text:
            return current_text + "\n" + display_text
        return display_text
