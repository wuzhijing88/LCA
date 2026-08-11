from ..parameter_panel_support import *


class ParameterPanelMediaMultiImagePathsCommonMixin:

    _COMMON_DIR_PREFIXES = ("# 共同目录:", "#共同目录:")

    def _split_multi_image_path_lines(self, text):
        if not text or not text.strip():
            return []
        return [line.strip() for line in text.strip().split("\n") if line.strip()]

    def _extract_multi_image_common_dir(self, line):
        for prefix in self._COMMON_DIR_PREFIXES:
            if line.startswith(prefix):
                return line.split(":", 1)[1].strip() if ":" in line else None
        return None

    def _is_multi_image_comment_line(self, line):
        return line.startswith("#")

    def _parse_multi_image_annotated_line(self, line):
        if "  # " not in line:
            return None, None
        filename, directory = line.split("  # ", 1)
        filename = filename.strip()
        directory = directory.strip()
        if not filename or not directory:
            return None, None
        return filename, directory

    def _convert_multi_image_line_to_full_path(self, line, common_dir):
        filename, directory = self._parse_multi_image_annotated_line(line)
        if filename and directory:
            return os.path.join(directory, filename)
        if os.path.isabs(line):
            return line
        if common_dir:
            return os.path.join(common_dir, line)
        return line

    def _is_supported_multi_image_path(self, full_path):
        return full_path.lower().endswith(
            (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tiff", ".webp")
        )
