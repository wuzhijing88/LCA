import hashlib
import logging
import os
from typing import Tuple

from ..control_center_parts.control_center_runtime import TaskState, WindowTaskRunner

logger = logging.getLogger(__name__)


class ControlCenterWindowTaskCompletionMixin:
    def on_workflow_completed(self, window_id: str, success: bool, workflow_index: int):
        logger.info(f"窗口{window_id}的工作流{workflow_index + 1}已完成，成功={success}")
        runners = self._get_window_runner_list(window_id)
        runner = runners[workflow_index] if 0 <= workflow_index < len(runners) else None
        workflow_name = ""
        failure_message = ""
        window_title = ""
        window_hwnd = None

        try:
            if runner is not None:
                workflow_name = str(runner.property("workflow_name") or "").strip()
                failure_message = str(getattr(runner, "_last_execution_message", "") or "").strip()
                window_info = getattr(runner, "window_info", {}) or {}
                if isinstance(window_info, dict):
                    window_title = str(window_info.get("title") or "").strip()
                    window_hwnd = window_info.get("hwnd")
        except Exception:
            workflow_name = workflow_name

        if not workflow_name:
            workflows = self.window_workflows.get(window_id)
            if isinstance(workflows, list) and 0 <= workflow_index < len(workflows):
                workflow_item = workflows[workflow_index]
                if isinstance(workflow_item, dict):
                    workflow_name = str(workflow_item.get("name") or "").strip()

        result_map = self._window_workflow_results.setdefault(window_id, {})
        result_map[workflow_index] = bool(success)
        self._persist_workflow_runtime_snapshot(window_id, workflow_index)
        self._try_finalize_window_workflows(window_id)
        self._dispatch_pending_runner_starts()

    def _persist_workflow_runtime_snapshot(self, window_id: str, workflow_index: int):
        try:
            runners = self._get_window_runner_list(window_id)
            workflows = self.window_workflows.get(window_id)
            if not (
                isinstance(workflows, list)
                and 0 <= workflow_index < len(workflows)
                and 0 <= workflow_index < len(runners)
                and isinstance(workflows[workflow_index], dict)
                and isinstance(workflows[workflow_index].get("data"), dict)
            ):
                return

            runtime_vars = getattr(runners[workflow_index], "_last_runtime_variables", None)
            if not isinstance(runtime_vars, dict):
                return

            variables_payload = None
            try:
                from task_workflow.runtime_var_store import save_runtime_snapshot

                workflow_item = workflows[workflow_index]
                workflow_path = str(workflow_item.get("file_path") or "").strip()
                if workflow_path:
                    normalized_path = os.path.normcase(os.path.abspath(workflow_path)).replace("\\", "/")
                else:
                    normalized_path = f"memory:{window_id}:{workflow_index}"
                path_digest = hashlib.sha1(normalized_path.encode("utf-8")).hexdigest()[:12]
                task_key = f"cc:{window_id}:{workflow_index}:{path_digest}"
                variables_payload = save_runtime_snapshot(task_key, runtime_vars)
            except Exception as storage_err:
                logger.warning(
                    f"窗口{window_id}工作流{workflow_index + 1}变量外部持久化失败: {storage_err}"
                )
                variables_payload = None

            if not isinstance(variables_payload, dict):
                logger.warning(
                    "窗口%s工作流%d变量持久化结果无效，已跳过回写",
                    window_id,
                    workflow_index + 1,
                )
                return

            workflows[workflow_index]["data"]["variables"] = variables_payload
            logger.info(
                "窗口%s工作流%d变量快照已回写，变量数=%d",
                window_id,
                workflow_index + 1,
                WindowTaskRunner._count_runtime_vars(runtime_vars),
            )
        except Exception as exc:
            logger.warning(
                f"回写窗口{window_id}工作流{workflow_index + 1}变量快照失败: {exc}"
            )

    def on_workflow_thread_finished(self, window_id: str, workflow_index: int):
        logger.info(f"窗口{window_id}的工作流线程{workflow_index + 1}已退出")
        self._try_finalize_window_workflows(window_id)
        self._dispatch_pending_runner_starts()

    def _try_finalize_window_workflows(self, window_id: str):
        runners = self._get_window_runner_list(window_id)
        if not runners:
            return

        any_pending = any(getattr(runner, "has_pending_work", False) for runner in runners)
        if any_pending:
            return

        result_map = self._window_workflow_results.setdefault(window_id, {})
        workflow_total = len(runners)
        success_count = sum(1 for value in result_map.values() if value is True)
        failed_count = sum(1 for value in result_map.values() if value is False)
        unknown_count = max(0, workflow_total - success_count - failed_count)
        final_success = failed_count == 0 and unknown_count == 0 and workflow_total > 0

        logger.info(
            "窗口%s结果汇总: total=%d, success=%d, failed=%d, unknown=%d, final_success=%s",
            window_id,
            workflow_total,
            success_count,
            failed_count,
            unknown_count,
            final_success,
        )
        self.on_window_task_completed(window_id, final_success)

    def on_window_task_completed(self, window_id, success):
        row = self.find_window_row(window_id)
        self._update_window_completion_status(row, success)
        self._cleanup_window_task_runners(window_id)
        self._window_workflow_results.pop(window_id, None)
        self._refresh_multi_window_mode_env()
        self.on_selection_changed()
        self._refresh_overview_metrics()

        window_title, workflow_name, result = self._build_window_completion_log_context(row, success)
        self.log_message(
            f"窗口工作流完成：窗口={window_title}，工作流={workflow_name}，结果={result}"
        )
        self._check_cleanup_ocr_after_window_completion()

    def _update_window_completion_status(self, row: int, success: bool):
        if row < 0:
            return
        current_status = self._get_window_status_text(row)
        if current_status == "已中断":
            return
        status_text = TaskState.COMPLETED.value if success else TaskState.FAILED.value
        step_text = "工作流已完成" if success else "工作流执行失败"
        self._set_status_cell(row, status_text)
        self._set_step_cell(row, step_text)

    def _cleanup_window_task_runners(self, window_id: str):
        if window_id not in self.window_runners:
            return
        try:
            for runner in self._get_window_runner_list(window_id):
                try:
                    self._remove_runner_from_start_queue(runner)
                    runner.status_updated.disconnect()
                    runner.step_updated.disconnect()
                    runner.task_completed.disconnect()
                except Exception as disconnect_error:
                    logger.debug(f"Disconnect runner signal ignored: {disconnect_error}")
            del self.window_runners[window_id]
            logger.info(f"Window runners cleaned: {window_id}")
        except Exception as e:
            logger.error(f"运行器清理失败：window_id={window_id}, error={e}")

    def _build_window_completion_log_context(self, row: int, success: bool) -> Tuple[str, str, str]:
        window_title = "Unknown"
        workflow_name = "Workflow"
        if row >= 0:
            title_item = self.window_table.item(row, 0)
            workflow_item = self.window_table.item(row, 2)
            if title_item:
                window_title = title_item.text()
            if workflow_item:
                workflow_name = workflow_item.text()

        if row >= 0:
            final_status = self._get_window_status_text(row)
            if final_status == "已中断":
                result = "interrupted"
            elif final_status in {TaskState.COMPLETED.value, "完成"}:
                result = "success"
            else:
                result = "failed"
        else:
            result = "success" if success else "failed"
        return window_title, workflow_name, result

    def _check_cleanup_ocr_after_window_completion(self):
        try:
            if not self.window_runners:
                logger.info("All window runners finished; checking OCR cleanup")
                self._check_and_cleanup_ocr_if_all_done()
        except Exception as e:
            logger.error(f"OCR 清理检查失败：{e}")
