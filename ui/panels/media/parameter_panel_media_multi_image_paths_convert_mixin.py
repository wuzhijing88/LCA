from .parameter_panel_media_multi_image_paths_common_mixin import (
    ParameterPanelMediaMultiImagePathsCommonMixin,
)


class ParameterPanelMediaMultiImagePathsConvertMixin(
    ParameterPanelMediaMultiImagePathsCommonMixin,
):

    def _convert_display_to_full_paths(self, display_text):
        lines = self._split_multi_image_path_lines(display_text)
        if not lines:
            return ""

        result_paths = []
        common_dir = None
        for line in lines:
            common_dir_candidate = self._extract_multi_image_common_dir(line)
            if common_dir_candidate is not None:
                common_dir = common_dir_candidate
                continue
            if self._is_multi_image_comment_line(line):
                continue
            full_path = self._convert_multi_image_line_to_full_path(line, common_dir)
            result_paths.append(full_path)
        return "\n".join(result_paths)
