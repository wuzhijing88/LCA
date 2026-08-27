import logging
from typing import List
from functools import partial
from typing import Dict, List, Optional
from PySide6.QtWidgets import QMessageBox
from app_core.control_plane import JobState
from ..main_window_parts.main_window_support import normalize_execution_mode_setting
from ..control_center_parts.control_center_runtime import WindowTaskRunner
from typing import Tuple
from ..control_center_parts.control_center_runtime import TaskState

logger = logging.getLogger(__name__)

class ControlCenterWindowTaskMixin:

    def _get_window_runner_list(self, window_id) -> List:
        runners = self.window_runners.get(str(window_id), [])
        if not isinstance(runners, list):
            runners = [runners]
        return [runner for runner in runners if self._is_qt_runner_valid(runner)]

    def stop_window_task(self, row):
        window_info = self.sorted_windows[row]
        window_id = self._window_runtime_id(window_info, row)
        window_title = str(window_info.get("title", "未知窗口"))

        try:
            logger.info(f"停止窗口工作流：{window_id}")
            scheduler = getattr(self, "scheduler", None)
            if scheduler is not None:
                scheduler.request_stop(window_id)
            stop_requested = self._direct_stop_window_task(window_id)
        except Exception as e:
            logger.error(f"停止窗口失败：window_id={window_id}, error={e}")
            self.log_message(f"停止窗口失败：{window_id} -> {e}")
            return False

        if not stop_requested:
            scheduler = getattr(self, "scheduler", None)
            if scheduler is not None and not self._get_window_runner_list(window_id):
                scheduler.finalize_orphaned_stop(window_id)
                self._paint_job_snapshot(window_id)
            self.log_message(f"窗口未在运行或停止请求未发送：{window_title}")
            return False

        self.on_selection_changed()
        self._sync_job_from_runners(window_id)
        self.log_message(f"已请求停止窗口：{window_title}")
        return True

    def _direct_stop_window_task(self, window_id):
        runners = self._get_window_runner_list(window_id)
        if not runners:
            return False

        stop_requested = False
        previous_dispatch_state = self._runner_dispatch_suspended
        self._runner_dispatch_suspended = True
        try:
            for runner in runners:
                try:
                    self._remove_runner_from_start_queue(runner)
                    if not self._can_request_stop_runner(runner):
                        continue
                    runner.stop()
                    stop_requested = True
                except Exception as e:
                    logger.error(f"停止窗口{window_id}的工作流时出错: {e}")
            if stop_requested:
                logger.info(f"已直接停止窗口{window_id}的所有工作流")
        finally:
            self._runner_dispatch_suspended = previous_dispatch_state
            self._dispatch_pending_runner_starts()
        return stop_requested

    def on_window_status_updated(self, window_id, status):
        snapshot = self._sync_job_from_runners(window_id)
        if snapshot is not None:
            return
        row = self.find_window_row(window_id)
        if row >= 0:
            self._set_status_cell(row, status)
            self._refresh_overview_metrics()

    def on_window_step_updated(self, window_id, step_info):
        from app_core.control_plane import JobState

        scheduler = getattr(self, "scheduler", None)
        job = scheduler.get_job(window_id) if scheduler is not None else None
        if job is not None and job.state not in {JobState.STARTING, JobState.RUNNING, JobState.PAUSED}:
            return
        snapshot = self._sync_job_from_runners(window_id)
        if snapshot is not None:
            return
        row = self.find_window_row(window_id)
        if row >= 0:
            self._set_step_cell(row, step_info)

    def start_window_task(self, row):
        self._refresh_bound_window_handles()
        window_info = self.sorted_windows[row]
        window_id = self._window_runtime_id(window_info, row)
        workflows = self._prepare_window_workflows_for_start(window_info, window_id)
        if workflows is None:
            return False

        scheduler = getattr(self, "scheduler", None)
        start_accepted = False
        if scheduler is not None:
            command = scheduler.request_start(window_id)
            if not command.ok:
                logger.info("调度器拒绝启动作业 %s: %s", window_id, command.reason)
                return False
            start_accepted = True

        try:
            configured_execution_mode = self._get_configured_execution_mode()
            runners = self._build_window_task_runners(
                window_info,
                window_id,
                workflows,
                configured_execution_mode,
            )
            self._register_window_task_runners(window_id, runners)
            if self._is_start_aborted(window_id):
                self._abort_registered_window_start(window_id, window_info)
                return False
            self._schedule_window_task_runners(window_id, runners)
            if self._is_start_aborted(window_id):
                self._abort_registered_window_start(window_id, window_info)
                return False
        except Exception as e:
            logger.error("创建窗口运行器失败：window_id=%s, error=%s", window_id, e)
            if start_accepted and scheduler is not None and not self._get_window_runner_list(window_id):
                scheduler.revert_unstarted(window_id)
                self._paint_job_snapshot(window_id)
            self.log_message(f"启动窗口失败：{window_info.get('title') or window_id} -> {e}")
            return False

        self.on_selection_changed()

        workflow_count = len(workflows)
        window_title = window_info.get("title") or "\u672a\u77e5\u7a97\u53e3"
        self.log_message(
            f"\u542f\u52a8\u7a97\u53e3\u5de5\u4f5c\u6d41: {window_title} - {workflow_count}\u4e2a\u5de5\u4f5c\u6d41\u5df2\u52a0\u5165\u8c03\u5ea6"
        )
        return True

    def _is_start_aborted(self, window_id: str) -> bool:
        scheduler = getattr(self, "scheduler", None)
        if scheduler is None:
            return False
        job = scheduler.get_job(window_id)
        return bool(job and job.state in {JobState.STOPPED, JobState.STOPPING})

    def _abort_registered_window_start(self, window_id: str, window_info: Dict) -> None:
        self._direct_stop_window_task(window_id)
        if not self._get_window_runner_list(window_id):
            scheduler = getattr(self, "scheduler", None)
            if scheduler is not None:
                scheduler.finalize_orphaned_stop(window_id)
        self._sync_job_from_runners(window_id)
        self.log_message(f"启动窗口已取消：{window_info.get('title') or window_id}")

    def _prepare_window_workflows_for_start(self, window_info: Dict, window_id: str) -> Optional[List[Dict]]:
        if self._is_parent_window_busy():
            logger.warning("\u4e3b\u7a97\u53e3\u6709\u4efb\u52a1\u6b63\u5728\u8fd0\u884c\uff0c\u4e2d\u63a7\u62d2\u7edd\u542f\u52a8\u65b0\u4efb\u52a1")
            QMessageBox.warning(
                self,
                "\u65e0\u6cd5\u542f\u52a8",
                "\u4e3b\u7a97\u53e3\u6b63\u5728\u6267\u884c\u4efb\u52a1\uff0c\u8bf7\u7b49\u5f85\u4e3b\u7a97\u53e3\u4efb\u52a1\u5b8c\u6210\u6216\u505c\u6b62\u540e\u518d\u4ece\u4e2d\u63a7\u542f\u52a8\u3002\n\n"
                "\u4e2d\u63a7\u548c\u4e3b\u7a97\u53e3\u7684\u6267\u884c\u5668\u4e0d\u80fd\u540c\u65f6\u8fd0\u884c\uff0c\u5426\u5219\u53ef\u80fd\u5bfc\u81f4\u7a0b\u5e8f\u5361\u6b7b\u3002"
            )
            return None

        pending_count = self._count_pending_window_runner_work(window_id)
        if pending_count > 0:
            logger.info(f"\u7a97\u53e3{window_id}\u5df2\u6709{pending_count}\u4e2a\u5de5\u4f5c\u6d41\u4ecd\u5728\u5904\u7406\u4e2d")
            return None

        workflows = self._get_normalized_window_workflows(window_id)
        if not workflows:
            QMessageBox.warning(self, "\u8b66\u544a", "\u8bf7\u5148\u4e3a\u8be5\u7a97\u53e3\u5206\u914d\u5de5\u4f5c\u6d41")
            return None

        blocked_workflows = self._collect_yolo_workflow_names(workflows)
        if blocked_workflows:
            self._show_yolo_workflow_block_warning(window_info, window_id, blocked_workflows)
            return None
        return workflows

    def _is_parent_window_busy(self) -> bool:
        if not self.parent_window or not hasattr(self.parent_window, "_is_any_workflow_running"):
            return False
        try:
            return bool(self.parent_window._is_any_workflow_running())
        except Exception:
            return False

    def _count_pending_window_runner_work(self, window_id: str) -> int:
        pending_count = 0
        for runner in self._get_window_runner_list(window_id):
            try:
                if runner.has_pending_work:
                    pending_count += 1
            except Exception:
                continue
        return pending_count

    def _get_normalized_window_workflows(self, window_id: str) -> List[Dict]:
        workflows = self.window_workflows.get(window_id)
        if workflows is None:
            return []
        if isinstance(workflows, dict):
            workflows = [workflows]
            self.window_workflows[window_id] = workflows
        if not isinstance(workflows, list):
            logger.warning("\u7a97\u53e3%s\u5de5\u4f5c\u6d41\u914d\u7f6e\u683c\u5f0f\u65e0\u6548: %s", window_id, type(workflows).__name__)
            return []
        return workflows

    def _show_yolo_workflow_block_warning(self, window_info: Dict, window_id: str, blocked_workflows: List[str]):
        window_title = str(window_info.get("title", "\u672a\u77e5\u7a97\u53e3"))
        preview_lines = [f"  - {name}" for name in blocked_workflows[:6]]
        if len(blocked_workflows) > 6:
            preview_lines.append(f"  - \u5176\u4f59 {len(blocked_workflows) - 6} \u4e2a\u5de5\u4f5c\u6d41")
        warning_message = (
            "\u4e2d\u63a7\u591a\u5f00\u4e0d\u652f\u6301\u6267\u884c YOLO \u4efb\u52a1\u3002\n"
            "\u8bf7\u5728\u4e3b\u7a97\u53e3\u5355\u5f00\u6267\u884c\u4ee5\u4e0b\u5de5\u4f5c\u6d41\uff1a\n\n"
            f"\u7a97\u53e3\uff1a{window_title}\n"
            "\u5de5\u4f5c\u6d41\uff1a\n"
            + "\n".join(preview_lines)
        )
        QMessageBox.warning(self, "\u542f\u52a8\u5df2\u62e6\u622a", warning_message)
        self.log_message(f"\u5df2\u62e6\u622a\uff1a\u7a97\u53e3 {window_title} \u5305\u542b YOLO \u5de5\u4f5c\u6d41")
        logger.warning(
            "\u4e2d\u63a7\u542f\u52a8\u62e6\u622a\uff1a\u7a97\u53e3%s(%s)\u5305\u542bYOLO\u5de5\u4f5c\u6d41: %s",
            window_title,
            window_id,
            blocked_workflows,
        )

    def _get_configured_execution_mode(self) -> Optional[str]:
        try:
            get_parent_config = getattr(self, "_get_parent_config", None)
            if callable(get_parent_config):
                config = get_parent_config()
            else:
                config = getattr(self.parent_window, "config", None) if self.parent_window else None
            if not isinstance(config, dict):
                return None
            configured_mode = str(config.get("execution_mode") or "").strip()
            if not configured_mode:
                return None
            return normalize_execution_mode_setting(configured_mode)
        except Exception:
            return None
        return None

    def _build_window_task_runners(
        self,
        window_info: Dict,
        window_id: str,
        workflows: List[Dict],
        configured_execution_mode: Optional[str],
    ) -> List[WindowTaskRunner]:
        runners = []
        workflow_total = len(workflows)
        for workflow_index, workflow_info in enumerate(workflows):
            runner = self._create_window_task_runner(
                window_info,
                window_id,
                workflow_info,
                workflow_index,
                workflow_total,
                configured_execution_mode,
            )
            runners.append(runner)
        return runners

    def _create_window_task_runner(
        self,
        window_info: Dict,
        window_id: str,
        workflow_info: Dict,
        workflow_index: int,
        workflow_total: int,
        configured_execution_mode: Optional[str],
    ) -> WindowTaskRunner:
        workflow_data = workflow_info["data"]
        workflow_name = workflow_info["name"]
        get_parent_config = getattr(self, "_get_parent_config", None)
        runtime_config = get_parent_config() if callable(get_parent_config) else None
        runner = WindowTaskRunner(
            window_info,
            workflow_data,
            self.task_modules,
            workflow_file_path=workflow_info.get("file_path"),
            workflow_slot=workflow_index,
            start_gate_event=self._batch_start_gate_event,
            bound_windows=self.bound_windows,
            execution_mode=configured_execution_mode,
            runtime_config=runtime_config,
        )
        runner.setProperty("workflow_index", workflow_index)
        runner.setProperty("workflow_name", workflow_name)
        runner.status_updated.connect(self.on_window_status_updated)
        runner.step_updated.connect(self.on_window_step_updated)
        runner.finished.connect(runner.deleteLater)
        runner.task_completed.connect(
            partial(self.on_workflow_completed, workflow_index=workflow_index)
        )
        runner.finished.connect(
            partial(self.on_workflow_thread_finished, window_id, workflow_index)
        )
        logger.info(
            "\u521b\u5efa\u5de5\u4f5c\u6d41\u8fd0\u884c\u5668 %s/%s: %s",
            workflow_index + 1,
            workflow_total,
            workflow_name,
        )
        return runner

    def _register_window_task_runners(self, window_id: str, runners: List[WindowTaskRunner]):
        self.window_runners[window_id] = runners
        self._window_workflow_results[window_id] = {idx: None for idx in range(len(runners))}
        self._refresh_multi_window_mode_env()

    def _schedule_window_task_runners(self, window_id: str, runners: List[WindowTaskRunner]):
        for runner in runners:
            self._enqueue_runner_start(runner)

        dispatched_count = self._dispatch_pending_runner_starts()
        queued_count = sum(1 for runner in runners if getattr(runner, "_queued_for_start", False))
        if not self._is_start_aborted(window_id):
            self._update_single_window_table_status(
                window_id,
                "\u7b49\u5f85\u5f00\u59cb" if queued_count > 0 and dispatched_count <= 0 else "\u6b63\u5728\u542f\u52a8",
                "\u5de5\u4f5c\u6d41\u5df2\u52a0\u5165\u8c03\u5ea6\u961f\u5217" if queued_count > 0 else "\u5de5\u4f5c\u6d41\u542f\u52a8\u4e2d",
            )
        logger.info(
            "\u7a97\u53e3%s\u5de5\u4f5c\u6d41\u5df2\u52a0\u5165\u8c03\u5ea6: total=%d, dispatched=%d, queued=%d",
            window_id,
            len(runners),
            dispatched_count,
            queued_count,
        )

    def on_workflow_completed(self, window_id: str, success: bool, workflow_index: int):
        logger.info(f"窗口{window_id}的工作流{workflow_index + 1}已完成，成功={success}")
        result_map = self._window_workflow_results.setdefault(window_id, {})
        result_map[workflow_index] = bool(success)
        self._try_finalize_window_workflows(window_id)
        self._dispatch_pending_runner_starts()

    def on_workflow_thread_finished(self, window_id: str, workflow_index: int):
        logger.info(f"窗口{window_id}的工作流线程{workflow_index + 1}已退出")
        self._try_finalize_window_workflows(window_id)
        self._dispatch_pending_runner_starts()

    def _try_finalize_window_workflows(self, window_id: str):
        runners = self._get_window_runner_list(window_id)
        if not runners:
            stored = self.window_runners.get(str(window_id), self.window_runners.get(window_id))
            if stored is None and window_id not in self._window_workflow_results:
                return
            scheduler = getattr(self, "scheduler", None)
            if scheduler is not None:
                scheduler.finalize_orphaned_stop(window_id)
            self.on_window_task_completed(window_id, False)
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
        self._update_window_completion_status(row, success, window_id=window_id)
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

    def _update_window_completion_status(self, row: int, success: bool, window_id: str = ""):
        resolved_id = str(window_id or "").strip() or (self._resolve_window_id_by_row(row) if row >= 0 else "")
        scheduler = getattr(self, "scheduler", None)
        if scheduler is not None and resolved_id:
            job = scheduler.get_job(resolved_id)
            if job is not None and job.state in {TaskState.STOPPED, TaskState.STOPPING}:
                if job.state == TaskState.STOPPING:
                    scheduler.apply_runner_state(resolved_id, TaskState.STOPPED)
                self._paint_job_snapshot(resolved_id)
                return
        if row >= 0 and self._get_window_status_text(row) == "已中断":
            return
        status_text = TaskState.COMPLETED.value if success else TaskState.FAILED.value
        step_text = "工作流已完成" if success else "工作流执行失败"
        if resolved_id:
            self._update_single_window_table_status(resolved_id, status_text, step_text)
            return
        if row < 0:
            return
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
            workflow_item = self.window_table.item(row, 1)
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
