import logging
from typing import List

from ..control_center_parts.control_center_window_task_completion_mixin import ControlCenterWindowTaskCompletionMixin
from ..control_center_parts.control_center_window_task_start_mixin import ControlCenterWindowTaskStartMixin

logger = logging.getLogger(__name__)


class ControlCenterWindowTaskMixin(
    ControlCenterWindowTaskStartMixin,
    ControlCenterWindowTaskCompletionMixin,
):
    def _get_window_runner_list(self, window_id) -> List:
        runners = self.window_runners.get(str(window_id), [])
        if not isinstance(runners, list):
            runners = [runners]
        return [runner for runner in runners if self._is_qt_runner_valid(runner)]

    def stop_window_task(self, row):
        window_info = self.sorted_windows[row]
        window_id = str(window_info.get("hwnd", row))
        window_title = str(window_info.get("title", "未知窗口"))

        try:
            logger.info(f"停止窗口工作流：{window_id}")
            stop_requested = self._direct_stop_window_task(window_id)
        except Exception as e:
            logger.error(f"停止窗口失败：window_id={window_id}, error={e}")
            self.log_message(f"停止窗口失败：{window_id} -> {e}")
            return False

        if not stop_requested:
            self.log_message(f"窗口未在运行或停止请求未发送：{window_title}")
            return False

        self.on_selection_changed()
        self._update_single_window_table_status(window_id, "正在停止", "正在停止工作流")
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
        row = self.find_window_row(window_id)
        if row >= 0:
            self._set_status_cell(row, status)
            self._refresh_overview_metrics()

    def on_window_step_updated(self, window_id, step_info):
        row = self.find_window_row(window_id)
        if row >= 0:
            self._set_step_cell(row, step_info)
