from ..parameter_panel_support import *


class ParameterPanelMediaMultiImagePathsFormatHelperMixin:

    def _get_multi_image_common_dir_for_display(self, file_paths):
        try:
            if len(file_paths) > 1:
                return os.path.commonpath(file_paths)
        except ValueError:
            return ""
        return ""

    def _format_paths_with_common_dir(self, file_paths, common_dir):
        formatted_lines = [f"# 共同目录: {common_dir}"]
        for file_path in file_paths:
            formatted_lines.append(os.path.basename(file_path))
        return formatted_lines

    def _format_paths_with_inline_directories(self, file_paths):
        formatted_lines = []
        for file_path in file_paths:
            if len(file_path) > 60:
                filename = os.path.basename(file_path)
                formatted_lines.append(f"{filename}  # {os.path.dirname(file_path)}")
            else:
                formatted_lines.append(file_path)
        return formatted_lines
