from ..parameter_panel_support import *


class ParameterPanelMediaMultiImagePathsDisplayCountMixin:
    def _update_path_count_label(self, label, text_content):
        if not text_content or not text_content.strip():
            label.setText("")
            return

        lines = [line.strip() for line in text_content.splitlines() if line.strip()]
        valid_paths = [line for line in lines if not line.startswith('#')]
        count = len(valid_paths)
        if count == 0:
            label.setText("")
        elif count == 1:
            label.setText("1个文件")
        else:
            label.setText(f"{count}个文件")
