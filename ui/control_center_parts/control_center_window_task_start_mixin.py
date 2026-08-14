import logging
from functools import partial
from typing import Dict, List, Optional

from PySide6.QtWidgets import QMessageBox

from app_core.control_plane import JobState

from ..main_window_parts.main_window_support import normalize_execution_mode_setting
from ..control_center_parts.control_center_runtime import WindowTaskRunner

logger = logging.getLogger(__name__)


class ControlCenterWindowTaskStartMixin:
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
