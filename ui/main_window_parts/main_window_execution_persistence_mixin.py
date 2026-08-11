import logging

logger = logging.getLogger(__name__)


class MainWindowExecutionPersistenceMixin:

    def _sync_task_runtime_context(self, task, variables_payload) -> None:

        """运行变量落盘后，同步主进程中的任务变量上下文。"""

        if task is None or not isinstance(variables_payload, dict):

            return

        try:

            from task_workflow.workflow_vars import update_context_from_variables

            update_context_from_variables(getattr(task, "task_id", None), variables_payload)

        except Exception as exc:

            logger.warning(

                f"同步任务变量上下文失败: task_id={getattr(task, 'task_id', None)}, error={exc}"

            )

    def _refresh_open_variable_pool_dialogs(self, task_id) -> None:

        """刷新已打开的变量池对话框，保证工作流完成后立即可见最新变量。"""

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

                if not isinstance(widget, VariablePoolDialog):

                    continue

                try:

                    widget.handle_runtime_variables_persisted(normalized_task_id)

                except Exception as exc:

                    logger.debug("刷新变量池对话框失败: %s", exc)

        except Exception as exc:

            logger.debug("查找变量池对话框失败: %s", exc)

    def _persist_task_runtime_variables(self, task, runtime_variables):

        """将运行期变量写回任务并落盘。"""

        if task is None or not isinstance(runtime_variables, dict):

            return

        try:

            persist_stats = getattr(self, "_runtime_var_persist_stats", None)

            if isinstance(persist_stats, dict):

                persist_stats["calls"] = int(persist_stats.get("calls", 0) or 0) + 1

                persist_stats["last_task_id"] = getattr(task, "task_id", None)

            variables_payload = None

            try:

                from task_workflow.runtime_var_store import (

                    build_task_key,

                    save_runtime_snapshot,

                )

                task_key = build_task_key(

                    filepath=getattr(task, "filepath", None),

                    task_id=getattr(task, "task_id", None),

                    task_name=getattr(task, "name", None),

                )

                variables_payload = save_runtime_snapshot(task_key, runtime_variables)

            except Exception as storage_err:

                logger.warning(f"变量持久化到外部存储失败，已跳过本次变量回写: {storage_err}")

                return

            if not isinstance(variables_payload, dict):

                logger.warning("变量持久化结果无效，已跳过本次变量回写")

                return

            if not isinstance(task.workflow_data, dict):

                task.workflow_data = {}

            task.workflow_data["variables"] = variables_payload
            self._sync_task_runtime_context(task, variables_payload)
            self._refresh_open_variable_pool_dialogs(getattr(task, "task_id", None))

            workflow_data_to_save = None

            workflow_view = None

            if hasattr(self, "workflow_tab_widget") and self.workflow_tab_widget:

                workflow_view = self.workflow_tab_widget.task_views.get(task.task_id)

            # 内存优化：运行期间高频持久化优先复用内存中的 workflow_data，

            # 仅在任务存在未保存编辑时才执行全量 serialize_workflow。

            should_serialize = bool(workflow_view and getattr(task, "modified", False))

            if should_serialize:

                if isinstance(persist_stats, dict):

                    persist_stats["serialize_calls"] = int(

                        persist_stats.get("serialize_calls", 0) or 0

                    ) + 1

                workflow_data_to_save = workflow_view.serialize_workflow(

                    variables_override=variables_payload

                )

            if not isinstance(workflow_data_to_save, dict):

                workflow_data_to_save = (

                    dict(task.workflow_data)

                    if isinstance(task.workflow_data, dict)

                    else {}

                )

                workflow_data_to_save["variables"] = variables_payload

            # 兜底：若结构异常导致缺失必要字段，再做一次全量序列化。

            if workflow_view and (

                "cards" not in workflow_data_to_save

                or "connections" not in workflow_data_to_save

            ):

                if isinstance(persist_stats, dict):

                    persist_stats["serialize_calls"] = int(

                        persist_stats.get("serialize_calls", 0) or 0

                    ) + 1

                workflow_data_to_save = workflow_view.serialize_workflow(

                    variables_override=variables_payload

                )

            if not task.save(workflow_data=workflow_data_to_save):

                if isinstance(persist_stats, dict):

                    persist_stats["save_failed"] = int(

                        persist_stats.get("save_failed", 0) or 0

                    ) + 1

                logger.warning(f"任务运行变量落盘失败: task_id={task.task_id}, name={task.name}")

        except Exception as exc:

            logger.warning(f"写回运行变量失败: task_id={getattr(task, 'task_id', None)}, error={exc}")

    def _persist_execution_runtime_variables(self, executor_obj=None, task_id=None):

        """将单工作流执行器的运行变量快照持久化到任务。"""

        if executor_obj is None:

            executor_obj = getattr(self, "executor", None)

        runtime_variables = getattr(executor_obj, "_final_runtime_variables", None)

        if not isinstance(runtime_variables, dict):

            return None

        resolved_task_id = task_id

        if resolved_task_id is None:

            resolved_task_id = getattr(self, "_active_execution_task_id", None)

        if resolved_task_id is None and executor_obj is not None:

            try:

                workflow_id_text = str(getattr(executor_obj, "workflow_id", "") or "").strip()

                if workflow_id_text.startswith("workflow_"):

                    resolved_task_id = int(workflow_id_text.split("_", 1)[1])

            except Exception:

                resolved_task_id = None

        if (

            resolved_task_id is None

            and hasattr(self, "workflow_tab_widget")

            and self.workflow_tab_widget

        ):

            resolved_task_id = self.workflow_tab_widget.get_current_task_id()

        if resolved_task_id is None:

            return None

        task = None

        if hasattr(self, "task_manager") and self.task_manager:

            task = self.task_manager.get_task(resolved_task_id)

        if task is None:

            return None

        self._persist_task_runtime_variables(task, runtime_variables)

        try:

            executor_obj._final_runtime_variables = None

        except Exception:

            pass

        return resolved_task_id

    def _convert_status_message_to_user_friendly(self, status_message: str) -> str:

        """将内部状态消息转换为用户友好的消息"""

        try:

            # 处理包含内部标识符的消息

            if "STOP_WORKFLOW" in status_message:

                return "工作流执行已停止"

            elif "被用户停止" in status_message:

                return "工作流被用户停止"

            elif "成功停止" in status_message:

                return "工作流执行成功完成"

            elif "执行完成" in status_message:

                return "工作流执行完成"

            elif "执行成功" in status_message:

                return "工作流执行成功"

            elif "执行失败" in status_message:

                return "工作流执行失败"

            elif "错误" in status_message or "异常" in status_message:

                return f"工作流执行出错：{status_message}"

            else:

                # 如果消息已经是用户友好的，直接返回

                return status_message

        except Exception as e:

            logger.warning(f"转换状态消息时出错: {e}")

            return "工作流执行完成"
