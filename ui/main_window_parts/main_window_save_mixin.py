import logging
import os

from PySide6.QtWidgets import QMessageBox

from app_core.lca_format.constants import LCA_SAVE_FILTER
from task_workflow.workflow_payload import save_workflow_file

logger = logging.getLogger(__name__)


class MainWindowSaveMixin:
    def _handle_save_action(self):
        """保存并备份所有标签页的工作流，处理同名冲突"""
        if not hasattr(self, 'workflow_tab_widget') or not self.workflow_tab_widget:
            QMessageBox.warning(self, "保存失败", "工作流标签页未初始化，无法保存")
            return
        if not hasattr(self, 'task_manager') or not self.task_manager:
            QMessageBox.warning(self, "保存失败", "任务管理器未初始化，无法保存")
            return
        all_tasks = self.task_manager.get_all_tasks()
        if not all_tasks:
            QMessageBox.information(self, "保存", "没有可保存的工作流")
            return
        logger.info(f"开始保存并备份所有工作流，共 {len(all_tasks)} 个")
        # 收集所有需要保存的任务信息，并获取最新工作流数据
        tasks_to_save = []
        failed_tasks = []
        for task in all_tasks:
            task_id = task.task_id
            task.last_save_error = ""
            task.last_save_file_written = False
            try:
                if task_id not in self.workflow_tab_widget.task_views:
                    raise RuntimeError("工作流画布未初始化，无法读取当前编辑内容")
                workflow_view = self.workflow_tab_widget.task_views[task_id]
                workflow_data = workflow_view.serialize_workflow()
                task.update_workflow_data(workflow_data)
                tasks_to_save.append((task, workflow_data))
            except Exception as exc:
                task.record_save_failure("读取画布数据", exc)
                failed_tasks.append(f"工作流：{task.name}\n{task.last_save_error}")

        # 子工作流先写回父工程，父工程随后从最新会话封装子包。
        # 否则父工程会先封装旧的子包，子工作流新增资源会在随后写回时丢失。
        tasks_to_save.sort(
            key=lambda item: 0
            if str(item[0].filepath).startswith("memory://")
            else 1
        )
        # 处理没有保存路径的任务
        tasks_without_path = [(t, d) for t, d in tasks_to_save if not t.filepath]
        if tasks_without_path:
            # 让用户选择保存目录
            from PySide6.QtWidgets import QFileDialog
            save_dir = QFileDialog.getExistingDirectory(
                self,
                "选择保存目录（用于保存未命名的工作流）",
                ""
            )
            if not save_dir:
                QMessageBox.warning(self, "保存取消", "未选择保存目录，保存已取消")
                return
            from task_workflow.workspace import prepare_exclusive_workflow_save
            prepared_tasks = []
            for task, workflow_data in tasks_to_save:
                if task.filepath:
                    prepared_tasks.append((task, workflow_data))
                    continue
                base_name = task.name if task.name else "工作流"
                base_name = os.path.splitext(base_name)[0]
                filepath = os.path.join(save_dir, f"{base_name}.lca")
                try:
                    filepath = prepare_exclusive_workflow_save(
                        workflow_data, filepath, source_filepath=str(task.filepath or ""),
                    )
                    task.update_workflow_data(workflow_data)
                    task.filepath = filepath
                    task.name = os.path.splitext(os.path.basename(filepath))[0]
                    prepared_tasks.append((task, workflow_data))
                except Exception as exc:
                    task.record_save_failure("准备保存路径", exc, filepath=filepath)
                    failed_tasks.append(f"工作流：{task.name}\n{task.last_save_error}")
            tasks_to_save = prepared_tasks
        # 检测同名冲突并处理
        filepath_count = {}
        for task, workflow_data in tasks_to_save:
            filepath = task.filepath
            if str(filepath).startswith("memory://"):
                identity = (
                    os.path.normcase(os.path.abspath(task.host_workflow_filepath)),
                    task.host_logical_path,
                )
            else:
                identity = filepath
            if identity in filepath_count:
                filepath_count[identity].append((task, workflow_data))
            else:
                filepath_count[identity] = [(task, workflow_data)]
        # 处理冲突
        conflicting_tasks = set()
        for task_list in filepath_count.values():
            if len(task_list) > 1:
                filepath = task_list[0][0].filepath
                if str(filepath).startswith("memory://"):
                    for task, _ in task_list:
                        task.record_save_failure("校验保存目标", "同一父工程中的子工作流被重复打开，无法保存")
                        failed_tasks.append(f"工作流：{task.name}\n{task.last_save_error}")
                        conflicting_tasks.add(task.task_id)
                    continue
                # 有冲突，重命名
                base_path = os.path.splitext(filepath)[0]
                for i, (task, _) in enumerate(task_list):
                    if i == 0:
                        # 第一个保持原名
                        pass
                    else:
                        # 后续的添加序号
                        new_filepath = f"{base_path}({i}).lca"
                        task.filepath = new_filepath
                        task.name = os.path.basename(new_filepath)
                        logger.info(f"同名冲突，重命名任务: {filepath} -> {new_filepath}")
        # 执行保存和备份
        saved_count = 0
        for task, workflow_data in tasks_to_save:
            if task.task_id in conflicting_tasks:
                continue
            old_filepath = task.filepath
            stage = "保存并备份工程"
            try:
                if not task.save_and_backup(workflow_data=workflow_data):
                    failed_tasks.append(f"工作流：{task.name}\n{task.last_save_error}")
                    continue
                stage = "同步保存后的界面与资源"
                self._sync_favorite_path_after_save(old_filepath, task)
                self._sync_saved_task_resources(task, workflow_data)
                self.workflow_tab_widget._update_tab_status(task.task_id)
                saved_count += 1
                logger.info(f"已保存并备份: {task.filepath}")
            except Exception as exc:
                task.record_save_failure(stage, exc)
                failed_tasks.append(f"工作流：{task.name}\n{task.last_save_error}")
        # 显示结果
        if failed_tasks:
            QMessageBox.warning(
                self,
                "保存完成",
                f"已保存并备份 {saved_count} 个工作流，{len(failed_tasks)} 个未完成\n\n"
                + "\n\n".join(failed_tasks)
            )
        else:
            QMessageBox.information(
                self,
                "保存成功",
                f"已保存并备份所有 {saved_count} 个工作流"
            )
    def perform_save(self, filepath: str):
        """Gathers data and writes it to the specified file path."""
        # 检查是否有当前工作流
        if not self.workflow_view:
            QMessageBox.warning(self, "无法保存", "没有打开的工作流")
            return False
        logger.info(f"Gathering workflow data for saving to {filepath}...")
        # BUG FIX: 保存前清理无效连接
        try:
            invalid_count = self.workflow_view.validate_connections()
            if invalid_count > 0:
                logger.error("连线状态存在 %d 项错误，拒绝保存工作流", invalid_count)
                self._show_error_message("保存失败", f"连线状态存在 {invalid_count} 项错误，请先修正")
                return False
        except Exception as e:
            logger.error("保存前连线校验失败: %s", e, exc_info=True)
            self._show_error_message("保存失败", f"连线校验失败：{e}")
            return False
        try:
            workflow_data = self.workflow_view.serialize_workflow()
        except Exception as e:
            logger.error(f"Error serializing workflow: {e}", exc_info=True)
            self._show_error_message("保存失败", f"序列化工作流时发生错误: {e}")
            return False
        # BUG FIX: 验证数据完整性
        if not workflow_data.get('cards'):
            logger.warning("工作流不包含任何卡片")
            # 询问用户是否继续保存空工作流
            reply = QMessageBox.question(
                self, '确认保存',
                '当前工作流不包含任何卡片，是否继续保存？',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return False
        # --- ADDED: Log the data JUST BEFORE writing ---
        logger.debug(f"[SAVE_DEBUG] Data to be written to LCA: {workflow_data}")
        from task_workflow.workflow_sanitize import sanitize_workflow_data

        sanitize_workflow_data(workflow_data)
        # --- END ADDED ---
        try:
            if os.path.isfile(filepath):
                from task_workflow.workspace import backup_workflow_file

                backup_workflow_file(filepath)
            filepath = str(save_workflow_file(filepath, workflow_data))
        except Exception as e:
            logger.error(f"写入文件失败: {e}", exc_info=True)
            self._show_error_message("保存失败", f"写入文件时发生错误: {e}")
            return False
        logger.info(f"工作流已保存到: {filepath}")
        self.setWindowTitle(f"自动化工作流 - {os.path.basename(filepath)}") # Update title
        filename_only = os.path.basename(filepath)
        self._update_step_details(f"任务配置文件 '{filename_only}' 保存成功。")
        self.current_save_path = filepath # Update current save path
        self.unsaved_changes = False
        self._update_main_window_title()
        return True
    def save_workflow_as(self):
        """Saves the current workflow to a new file chosen by the user."""
        from PySide6.QtWidgets import QFileDialog
        from task_workflow.workspace import default_new_workflow_filepath, exclusive_workflow_filepath
        default_filename = default_new_workflow_filepath("workflow")
        current_path = self.current_save_path or default_filename
        current_path = os.path.splitext(current_path)[0] + ".lca"
        filepath, filetype = QFileDialog.getSaveFileName(
            self,
            "保存工作流",
            current_path,
            LCA_SAVE_FILTER
        )
        if not filepath:
            return # User cancelled
        if not filepath.lower().endswith(".lca"):
            filepath += ".lca"
        filepath = exclusive_workflow_filepath(filepath)
        # 保存为普通工作流文件
        self.current_save_path = filepath # Remember path for next time

        return True
    def _mark_unsaved_changes(self, *args):
        """Sets the unsaved changes flag and updates the window title."""
        # <<< ADDED: Debugging log >>>
        # Try to get the sender object name if available
        sender_info = "Unknown Source"
        sender = self.sender() # Get the object that emitted the signal
        if sender:
            sender_info = f"Sender: {type(sender).__name__} {getattr(sender, 'objectName', lambda: '')()}"

        logger.debug(f"_mark_unsaved_changes called ({sender_info}, Args: {args})")
        # <<< END ADDED >>>
        if not self.unsaved_changes:
            logger.debug("_mark_unsaved_changes: Marking changes as unsaved.")
            self.unsaved_changes = True
            self._update_main_window_title()
        tab_widget = getattr(self, "workflow_tab_widget", None)
        if tab_widget is None or not hasattr(tab_widget, "get_current_task_id"):
            return
        task_id = tab_widget.get_current_task_id()
        if task_id is not None:
            tab_widget._mark_task_modified(task_id)
