from ..parameter_panel_support import *


class ParameterPanelMediaMultiImageThumbnailClearMixin:
            def _clear_thumbnails(self, param_name: str, text_edit: QTextEdit):



                """清空缩略图和路径"""



                text_edit.setPlainText("")



                self.current_parameters[param_name] = ""  # 同步更新参数







                # 立即同步到 TaskCard



                if self.current_card_id is not None:



                    self.parameters_changed.emit(self.current_card_id, {param_name: ""})







                self._update_thumbnail_grid(param_name, "")
