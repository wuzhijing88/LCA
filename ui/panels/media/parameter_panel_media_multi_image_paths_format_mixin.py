from .parameter_panel_media_multi_image_paths_format_helper_mixin import (
    ParameterPanelMediaMultiImagePathsFormatHelperMixin,
)


class ParameterPanelMediaMultiImagePathsFormatMixin(
    ParameterPanelMediaMultiImagePathsFormatHelperMixin,
):

    def _format_image_paths_display(self, file_paths):
        if not file_paths:
            return ""
        if len(file_paths) == 1:
            return file_paths[0]

        common_dir = self._get_multi_image_common_dir_for_display(file_paths)
        if common_dir and len(common_dir) > 20:
            formatted_lines = self._format_paths_with_common_dir(file_paths, common_dir)
        else:
            formatted_lines = self._format_paths_with_inline_directories(file_paths)
        return "\n".join(formatted_lines)

    def _format_existing_paths_display(self, paths_text):
        if not paths_text or not paths_text.strip():
            return ""
        return paths_text
