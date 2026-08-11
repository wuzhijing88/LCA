from ..parameter_panel_support import *


class ParameterPanelFavoritesActionExecuteMixin:
        def _on_favorites_execute_single(self, filepath: str):

            """兼容旧入口：统一改为启动已勾选的工作流"""

            _ = filepath

            self._on_favorites_start_batch()

        def _on_favorites_start_batch(self):

            """启动批量执行"""

            from PySide6.QtWidgets import QMessageBox



            # 获取选中的工作流及其配置

            selected_favs = [f for f in self._favorites if f.get('checked', True)]



            if not selected_favs:

                QMessageBox.information(self, "提示", "请先选择要执行的工作流")

                return



            selected = [f['filepath'] for f in selected_favs]



            # 检查文件

            missing = [fp for fp in selected if not os.path.exists(fp)]

            if missing:

                QMessageBox.warning(self, "文件缺失", f"以下工作流文件不存在:\n" + "\n".join(missing))

                return



            logger.info(f"批量执行工作流: count={len(selected)}")

            self.batch_execute_requested.emit(selected)
