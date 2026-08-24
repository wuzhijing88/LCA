import logging

logger = logging.getLogger(__name__)


class MainWindowWorkflowSwitchLoadingMixin:

    def load_workflow_file(self):

        """直接从文件加载工作流（原有功能）"""

        # 检查是否有工作流正在执行

        if self._is_any_workflow_running():

            # 在底部状态栏显示警告

            if hasattr(self, 'step_detail_label'):

                self.step_detail_label.setText("【警告】工作流正在执行中，无法导入新工作流")

                self._set_step_detail_style(text_color="#FF0000")

                from PySide6.QtCore import QTimer

                QTimer.singleShot(3000, lambda: self.step_detail_label.setText("任务执行中..."))

            logger.warning("工作流正在执行，禁止导入新工作流")

            return

        # 使用标签页控件的导入功能

        task_id = self.workflow_tab_widget.import_workflow()

        if task_id is not None:

            logger.info(f"工作流导入成功，任务ID: {task_id}")

            # 不需要设置 unsaved_changes，因为新导入的任务不算未保存

        else:

            logger.info("工作流导入已取消或失败")

    def create_blank_workflow(self):

        """创建新的空白工作流"""

        # 检查是否有工作流正在执行

        if self._is_any_workflow_running():

            # 在底部状态栏显示警告

            if hasattr(self, 'step_detail_label'):

                self.step_detail_label.setText("【警告】工作流正在执行中，无法创建新工作流")

                self._set_step_detail_style(text_color="#FF0000")

                from PySide6.QtCore import QTimer

                QTimer.singleShot(3000, lambda: self.step_detail_label.setText("任务执行中..."))

            logger.warning("工作流正在执行，禁止创建新工作流")

            return

        # 使用标签页控件的创建功能

        task_id = self.workflow_tab_widget.create_blank_workflow()

        if task_id is not None:

            logger.info(f"空白工作流创建成功，任务ID: {task_id}")

            # 空白工作流标记为未保存（已由task_manager处理）

        else:

            logger.info("空白工作流创建失败")

    def _ensure_current_workflow(self, show_warning: bool = True) -> bool:

        """

        确保有当前工作流，如果没有则提示用户

        Args:

            show_warning: 是否显示警告对话框

        Returns:

            是否有可用的工作流

        """

        from PySide6.QtWidgets import QMessageBox

        if self.workflow_view and hasattr(self.workflow_view, 'cards'):

            return True

        if show_warning:

            QMessageBox.information(

                self,

                "提示",

                "请先导入工作流任务\n\n点击标签栏的 '+' 按钮或使用菜单'加载配置'"

            )

        return False

    def _is_any_workflow_running(self) -> bool:

        """检查是否有任何工作流正在执行

        Returns:

            True if any workflow is running, False otherwise

        """

        # 检查单窗口执行器

        if self.executor_thread and self.executor_thread.isRunning():

            logger.debug("检测到单窗口执行器正在运行")

            return True

        # 检查多窗口执行器

        if hasattr(self, 'multi_executor') and self.multi_executor and self.multi_executor.is_running:

            logger.debug("检测到多窗口执行器正在运行")

            return True

        # 检查任务管理器中的运行状态

        running_tasks = [task for task in self.task_manager.get_all_tasks() if task.status == 'running']

        if running_tasks:

            logger.debug(f"检测到 {len(running_tasks)} 个任务状态为running")

            return True

        return False
