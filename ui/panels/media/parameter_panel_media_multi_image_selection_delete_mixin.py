from ..parameter_panel_support import *


class ParameterPanelMediaMultiImageSelectionDeleteMixin:
    def _delete_single_image(self, param_name: str, image_path: str):
        """Delete single image."""
        try:
            text_edit = self._get_multi_image_text_edit(param_name)
            if text_edit is None:
                return
            current_text = text_edit.toPlainText()
            if not current_text:
                return
            new_text = self._remove_path_from_multi_image_text(current_text, image_path)
            self._sync_multi_image_text_edit(text_edit, new_text)
            self._sync_multi_image_parameter_value(param_name, new_text, emit_signal=True)
            logger.info(f"已删除图片: {os.path.basename(image_path)}")
        except Exception as e:
            logger.error(f"删除图片失败: {e}", exc_info=True)

    def _get_multi_image_text_edit(self, param_name: str):
        text_edit = self.widgets.get(param_name)
        if isinstance(text_edit, QTextEdit):
            return text_edit
        return None

    def _remove_path_from_multi_image_text(self, current_text: str, image_path: str) -> str:
        all_paths = self._parse_image_paths(current_text)
        new_paths = [path for path in all_paths if path != image_path]
        if len(new_paths) == len(all_paths):
            image_filename = os.path.basename(image_path)
            new_paths = [path for path in all_paths if os.path.basename(path) != image_filename]
        if not new_paths:
            return ''
        return self._format_image_paths_display(new_paths)
