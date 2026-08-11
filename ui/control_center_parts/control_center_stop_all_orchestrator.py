import logging

from PySide6.QtCore import QTimer

logger = logging.getLogger(__name__)


def _schedule_force_stop_completion(self, target_window_ids, is_partial_stop: bool):
    if is_partial_stop:
        target_ids_snapshot = set(target_window_ids) if target_window_ids else set()
        QTimer.singleShot(
            2000,
            lambda ids=target_ids_snapshot: self._force_stop_all_completion(target_window_ids=ids),
        )
        return
    QTimer.singleShot(2000, self._force_stop_all_completion)


def control_center_stop_all_tasks(ctx):
    self = ctx
    logger.info("开始停止所有工作流")
    self.log_message("正在停止所有工作流...")

    target_window_ids = getattr(self, "_cc_active_stop_window_filter", None)
    is_partial_stop = target_window_ids is not None
    if target_window_ids:
        logger.info(f"中控停止过滤窗口: {sorted(target_window_ids)}")

    self._direct_stop_all_tasks(target_window_ids=target_window_ids)

    if is_partial_stop and self.is_any_task_running():
        self.log_message("目标窗口停止请求已发送，其他窗口继续运行")
    elif is_partial_stop:
        self.log_message("目标窗口停止请求已发送")

    if not is_partial_stop:
        try:
            self._request_deferred_global_stop_cleanup()
        except Exception as e:
            logger.warning(f"登记中控延迟清理失败: {e}")

    _schedule_force_stop_completion(self, target_window_ids, is_partial_stop)
