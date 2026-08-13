import logging

logger = logging.getLogger(__name__)


class MainWindowExecutionPersistenceMixin:
    def _refresh_open_variable_pool_dialogs(self, task_id) -> None:
        try:
            normalized_task_id = int(task_id)
        except (TypeError, ValueError):
            return
        try:
            from PySide6.QtWidgets import QApplication
            from ui.dialogs.variable_pool_dialog import VariablePoolDialog

            app = QApplication.instance()
            if app is None:
                return
            for widget in app.topLevelWidgets():
                if isinstance(widget, VariablePoolDialog):
                    widget.handle_runtime_variables_persisted(normalized_task_id)
        except Exception:
            logger.exception("刷新变量池失败: task_id=%s", normalized_task_id)

    def _persist_task_runtime_variables(self, task, runtime_variables):
        """将运行变量直接持久化到工作流路径对应的 SQLite 空间。"""
        if task is None or not isinstance(runtime_variables, dict):
            return False
        try:
            from task_workflow.runtime_var_store import build_task_key, save_runtime_snapshot

            task_key = build_task_key(task.filepath, task.task_id, task.name)
            save_runtime_snapshot(task_key, runtime_variables)
            if isinstance(task.workflow_data, dict):
                task.workflow_data.pop("variables", None)
            self._refresh_open_variable_pool_dialogs(task.task_id)
            return True
        except Exception:
            logger.exception("运行变量写入 SQLite 失败: task_id=%s", getattr(task, "task_id", None))
            return False

    def _persist_execution_runtime_variables(self, executor_obj=None, task_id=None):
        """将单工作流执行器的变量快照写入对应 SQLite 空间。"""
        executor_obj = executor_obj or getattr(self, "executor", None)
        runtime_variables = getattr(executor_obj, "_final_runtime_variables", None)
        if not isinstance(runtime_variables, dict):
            return None

        resolved_task_id = task_id or getattr(self, "_active_execution_task_id", None)
        if resolved_task_id is None:
            workflow_id = str(getattr(executor_obj, "workflow_id", "") or "")
            if workflow_id.startswith("workflow_"):
                try:
                    resolved_task_id = int(workflow_id.split("_", 1)[1])
                except ValueError:
                    resolved_task_id = None
        if resolved_task_id is None and getattr(self, "workflow_tab_widget", None):
            resolved_task_id = self.workflow_tab_widget.get_current_task_id()
        if resolved_task_id is None or not getattr(self, "task_manager", None):
            return None

        task = self.task_manager.get_task(resolved_task_id)
        if task is None or not self._persist_task_runtime_variables(task, runtime_variables):
            return None
        executor_obj._final_runtime_variables = None
        return resolved_task_id

    def _convert_status_message_to_user_friendly(self, status_message: str) -> str:
        text = str(status_message or "")
        if "STOP_WORKFLOW" in text:
            return "工作流执行已停止"
        if "用户手动停止" in text:
            return "工作流已被用户停止"
        if "正常停止" in text:
            return "工作流执行正常结束"
        if "执行完成" in text:
            return "工作流执行完成"
        if "执行成功" in text:
            return "工作流执行成功"
        if "执行失败" in text:
            return "工作流执行失败"
        if "错误" in text or "异常" in text:
            return f"工作流执行出现问题：{text}"
        return text
