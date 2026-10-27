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
        if old_view is not self.workflow_view or self.workflow_view is None:
            panel = getattr(self, "parameter_panel", None)
            if panel is not None and not panel._favorites_mode:
                panel.discard_workflow_context()
                self._parameter_panel_visible = False
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
        self._bind_current_workflow_resource_dirs()

    def _bind_current_workflow_resource_dirs(self, task=None) -> None:
        from task_workflow.resource_context import bind_resource_dirs, resource_dirs_from_mapping

        current_task = task
        if current_task is None and getattr(self, "workflow_tab_widget", None):
            task_id = self.workflow_tab_widget.get_current_task_id()
            manager = getattr(self.workflow_tab_widget, "task_manager", None)
            if manager is not None and task_id is not None:
                current_task = manager.get_task(task_id)
        dirs = resource_dirs_from_mapping(current_task)
        bind_resource_dirs(dirs)
        images_dir = dirs.get("images_dir") or ""
        sounds_dir = dirs.get("sounds_dir") or ""
        if hasattr(self, "parameter_panel") and self.parameter_panel:
            self.parameter_panel.images_dir = images_dir
            self.parameter_panel.sounds_dir = sounds_dir
            self.parameter_panel.dicts_dir = dirs.get("dicts_dir") or ""
            self.parameter_panel.yolo_dir = dirs.get("yolo_dir") or ""
            self.parameter_panel.replays_dir = dirs.get("replays_dir") or ""
            self.parameter_panel.plugins_dir = dirs.get("plugins_dir") or ""

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
        from shiboken6 import isValid
        return bool(isValid(obj))

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

                self._set_step_detail_style(text_color=theme_color("error"))

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

                self._set_step_detail_style(text_color=theme_color("error"))

                from PySide6.QtCore import QTimer

                QTimer.singleShot(3000, lambda: self.step_detail_label.setText("任务执行中..."))

            logger.warning("工作流正在执行，禁止创建新工作流")

            return

        try:
            workspace_dir = self._prompt_workspace_for_new_workflow()
        except Exception as exc:
            from PySide6.QtWidgets import QMessageBox

            logger.exception("选择新建工作流的工作区失败")
            QMessageBox.critical(self, "创建失败", f"无法确定新建工作流的工作区：\n{exc}")
            return
        if workspace_dir is None:
            logger.info("已取消新建工作流")
            return
        task_id = self.workflow_tab_widget.create_blank_workflow(workspace_dir=workspace_dir)

        if task_id is not None:

            logger.info(f"空白工作流创建成功，任务ID: {task_id}")

            # 空白工作流标记为未保存（已由task_manager处理）

        else:

            logger.info("空白工作流创建失败")

    def _configured_user_workspace_dirs(self) -> list:
        from task_workflow.workspace import is_default_app_workspace
        from ui.export_parts.export_scripts import workspace_dirs_from_main

        return [path for path in workspace_dirs_from_main(self) if not is_default_app_workspace(path)]

    def _prompt_workspace_for_new_workflow(self) -> Optional[str]:
        """跟随当前工作流所属工作区；归属不明时明确选择，取消返回 None。"""
        from PySide6.QtWidgets import QDialog, QFileDialog, QInputDialog, QMessageBox
        from task_workflow.workspace import resolve_favorite_workspace_dir
        from themes import apply_rounded_popup

        existing = self._configured_user_workspace_dirs()
        if existing:
            workspace_dir = ""
            task_id = self.workflow_tab_widget.get_current_task_id()
            if task_id is not None:
                task = self.workflow_tab_widget.task_manager.get_task(task_id)
                if task is None:
                    raise ValueError("当前工作流不存在")
                workspace_dir = resolve_favorite_workspace_dir(task.filepath, existing)
            if not workspace_dir:
                if len(existing) == 1:
                    workspace_dir = existing[0]
                else:
                    picker = QInputDialog(self)
                    try:
                        picker.setWindowTitle("选择工作区")
                        picker.setLabelText("请选择新建工作流的保存工作区：")
                        picker.setComboBoxItems(existing)
                        picker.setComboBoxEditable(False)
                        picker.setOption(QInputDialog.InputDialogOption.UseListViewForComboBoxItems)
                        picker.setMinimumWidth(min(
                            max(picker.fontMetrics().horizontalAdvance(path) for path in existing) + 64,
                            picker.screen().availableGeometry().width() - 48,
                        ))
                        picker.setOkButtonText("确定")
                        picker.setCancelButtonText("取消")
                        apply_rounded_popup(picker, frameless=False)
                        if picker.exec() != QDialog.DialogCode.Accepted or not self._is_qobject_alive(picker):
                            return None
                        workspace_dir = picker.textValue()
                        if workspace_dir not in existing:
                            raise ValueError("所选目录不在当前工作区列表中")
                    finally:
                        if self._is_qobject_alive(picker):
                            picker.deleteLater()
            if not os.path.isdir(workspace_dir):
                raise ValueError(f"工作区目录不存在：{workspace_dir}")
            return workspace_dir
        box = QMessageBox(self)
        try:
            box.setIcon(QMessageBox.Icon.Question)
            box.setWindowTitle("添加工作区")
            box.setText(
                "还没有工作区。新建的工作流会保存在软件默认目录，之后可能不好找。\n\n是否现在添加工作区？"
            )
            box.setStandardButtons(QMessageBox.StandardButton.NoButton)
            add_button = box.addButton("添加", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("暂不添加", QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(add_button)
            apply_rounded_popup(box, frameless=False)
            box.exec()
            if not self._is_qobject_alive(box):
                return None
            # 全局事件过滤后按钮的 Python 引用可能失效，按当前按钮角色识别动作。
            clicked_role = box.buttonRole(box.clickedButton())
            if clicked_role == QMessageBox.ButtonRole.RejectRole:
                return ""
            if clicked_role != QMessageBox.ButtonRole.AcceptRole:
                return None
        finally:
            if self._is_qobject_alive(box):
                box.close()
                box.deleteLater()
        panel = self.parameter_panel
        folder = QFileDialog.getExistingDirectory(self, "选择工作区目录", "")
        if not folder:
            return None
        if not self._is_qobject_alive(self):
            return None
        added = panel._add_favorite_workspace_dir(folder)
        if not added:
            raise ValueError(f"添加工作区失败：{folder}")
        panel.show_favorites()
        self._parameter_panel_visible = True
        return added

    def _offer_workspace_if_missing(self) -> None:
        if self._configured_user_workspace_dirs():
            return
        tab = getattr(self, "workflow_tab_widget", None)
        manager = getattr(tab, "task_manager", None) if tab is not None else None
        if manager is not None and manager.get_all_tasks():
            return
        self._prompt_workspace_for_new_workflow()

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

        from ui.control_center_parts.control_center_shutdown import shutdown_blocks_execution

        if shutdown_blocks_execution(getattr(self, "_control_center_shutdown", None)):
            logger.debug("检测到中控仍在关闭收尾")
            return True

        return False

    def _open_workflow_reference(self, filepath: str, switch_to_tab: bool = True) -> Optional[int]:
        workflow_ref = str(filepath or '').strip()
        if not workflow_ref:
            return None
        return self._find_or_import_workflow(workflow_ref, switch_to_tab=switch_to_tab)

    def _find_or_import_workflow(self, filepath: str, switch_to_tab: bool = True) -> Optional[int]:
        """查找已打开的工作流或导入新工作流，返回task_id"""
        from task_workflow.workspace import (
            favorite_path_key,
            resolve_existing_workflow_path,
            workflow_path_keys,
        )

        resolved_path = resolve_existing_workflow_path(filepath)
        abs_filepath = os.path.abspath(resolved_path or filepath)
        candidates = set(workflow_path_keys(abs_filepath))
        # 检查是否已打开
        for task in self.task_manager.get_all_tasks():
            task_paths = []
            if task.filepath:
                task_paths.append(task.filepath)
            source_ref = str(getattr(task, 'source_ref', '') or '')
            if source_ref:
                task_paths.append(source_ref)
            if candidates and any(favorite_path_key(path) in candidates for path in task_paths):
                # 已打开，切换到对应标签页
                tab_index = self.workflow_tab_widget.task_to_tab.get(task.task_id)
                if switch_to_tab and tab_index is not None:
                    self.workflow_tab_widget.setCurrentIndex(tab_index)
                logger.info(f"工作流已打开，复用: {task.name}, task_id={task.task_id}")
                return task.task_id
        # 未打开，导入新工作流
        return self.workflow_tab_widget.import_workflow(abs_filepath, activate_tab=switch_to_tab)
