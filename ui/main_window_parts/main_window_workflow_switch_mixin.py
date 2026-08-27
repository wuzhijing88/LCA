import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

class MainWindowWorkflowSwitchMixin:

    def _on_current_workflow_changed(self, task_id: int):
        """切换画布到当前工作流标签。"""
        old_view = self.workflow_view
        if not self._is_qobject_alive(old_view):
            old_view = None
            self.workflow_view = None

        current_view = None
        if getattr(self, "workflow_tab_widget", None):
            current_view = self.workflow_tab_widget.get_current_workflow_view()
        self.workflow_view = current_view if self._is_qobject_alive(current_view) else None

        self._finish_current_workflow_view_switch(old_view)

    def _finish_current_workflow_view_switch(self, old_view):
        if self.workflow_view is None:
            return
        if old_view is not None and old_view is not self.workflow_view:
            self._disconnect_workflow_selection_signal(old_view)
        self.workflow_view.setEnabled(True)
        self.workflow_view.setVisible(True)

        from PySide6.QtWidgets import QGraphicsView
        self.workflow_view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        if self.workflow_view.scene.items():
            items_rect = self.workflow_view.scene.itemsBoundingRect()
            self.workflow_view.scene.setSceneRect(items_rect.adjusted(-500, -500, 500, 500))
            self.workflow_view.viewport().update()
        try:
            self.workflow_view.scene.selectionChanged.connect(self.update_status_bar_for_selection)
        except (TypeError, RuntimeError):
            pass
        # 新增卡片必须接上参数面板信号，否则双击卡片无法打开参数界面
        if not self.workflow_view.property("_mw_card_added_connected"):
            self.workflow_view.card_added.connect(self._on_card_added)
            self.workflow_view.setProperty("_mw_card_added_connected", True)
        self._connect_parameter_panel_signals()

    def _disconnect_workflow_selection_signal(self, workflow_view) -> None:
        if not self._is_qobject_alive(workflow_view):
            return
        try:
            scene = workflow_view.scene
            if callable(scene):
                scene = scene()
            if self._is_qobject_alive(scene):
                scene.selectionChanged.disconnect(self.update_status_bar_for_selection)
        except (TypeError, RuntimeError):
            pass
        if workflow_view.property("_mw_card_added_connected"):
            try:
                workflow_view.card_added.disconnect(self._on_card_added)
            except (TypeError, RuntimeError):
                pass
            workflow_view.setProperty("_mw_card_added_connected", False)

    def _show_welcome_hint(self):
        if self.task_manager.get_task_count() == 0:
            self.step_detail_label.setText("")

    def _is_qobject_alive(self, obj) -> bool:
        if obj is None:
            return False
        try:
            from shiboken6 import isValid
            return bool(isValid(obj))
        except ImportError:
            try:
                obj.metaObject()
                return True
            except RuntimeError:
                return False

    def _on_task_count_changed(self, task_id: int = None):
        if self.task_manager.get_task_count() == 0 and self.workflow_view is not None:
            self._disconnect_workflow_selection_signal(self.workflow_view)
            self.workflow_view = None
        if getattr(self, "executor", None) is None:
            self._update_status_bar()

    def load_workflow_file(self):

        """直接从文件加载工作流（原有功能）"""

        # 检查是否有工作流正在执行

        if self._is_any_workflow_running():

            # 在底部状态栏显示警告

            if hasattr(self, 'step_detail_label'):

                self.step_detail_label.setText("【警告】工作流正在执行中，无法导入新工作流")

                from themes import theme_color

                self._set_step_detail_style(text_color=theme_color("error", "#e81123"))

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

                from themes import theme_color

                self._set_step_detail_style(text_color=theme_color("error", "#e81123"))

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

    def _open_workflow_reference(self, filepath: str, switch_to_tab: bool = True) -> Optional[int]:
        workflow_ref = str(filepath or '').strip()
        if not workflow_ref:
            return None
        return self._find_or_import_workflow(workflow_ref, switch_to_tab=switch_to_tab)

    def _find_or_import_workflow(self, filepath: str, switch_to_tab: bool = True) -> Optional[int]:
        """查找已打开的工作流或导入新工作流，返回task_id"""
        abs_filepath = os.path.abspath(filepath)
        # 检查是否已打开
        for task in self.task_manager.get_all_tasks():
            if task.filepath and os.path.abspath(task.filepath) == abs_filepath:
                # 已打开，切换到对应标签页
                tab_index = self.workflow_tab_widget.task_to_tab.get(task.task_id)
                if switch_to_tab and tab_index is not None:
                    self.workflow_tab_widget.setCurrentIndex(tab_index)
                logger.info(f"工作流已打开，复用: {task.name}, task_id={task.task_id}")
                return task.task_id
        # 未打开，导入新工作流
        return self.workflow_tab_widget.import_workflow(filepath, activate_tab=switch_to_tab)
