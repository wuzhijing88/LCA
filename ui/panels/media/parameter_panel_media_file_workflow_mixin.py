from ..parameter_panel_support import *


class ParameterPanelMediaFileWorkflowMixin:
    def _open_sub_workflow_for_edit(self, line_edit: QLineEdit):
        workflow_file = line_edit.text().strip()
        if not workflow_file:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "提示", "请先选择工作流文件")
            return

        try:
            if self.main_window and hasattr(self.main_window, 'workflow_tab_widget'):
                tab_widget = self.main_window.workflow_tab_widget
                parent_workflow_file = None
                if hasattr(tab_widget, "_get_current_workflow_filepath"):
                    parent_workflow_file = tab_widget._get_current_workflow_filepath()
                tab_widget.open_sub_workflow(
                    workflow_file,
                    parent_workflow_file=parent_workflow_file,
                )
                logger.info(f"[子工作流] 已请求打开: {workflow_file}")
            else:
                logger.warning("[子工作流] 无法找到主窗口或workflow_tab_widget")
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "错误", "无法打开子工作流编辑器")
        except Exception as e:
            logger.error(f"[子工作流] 打开失败: {e}", exc_info=True)
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "错误", f"打开子工作流失败:\n{e}")
