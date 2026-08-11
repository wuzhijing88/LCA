import logging
import traceback

logger = logging.getLogger(__name__)


def control_center_toggle_pause_all_tasks(ctx):
    """暂停/恢复所有正在运行的工作流"""
    self = ctx
    logger.info("=== 中控软件：toggle_pause_all_tasks 被调用 ===")

    target_window_ids = getattr(self, "_cc_active_pause_window_filter", None)
    if target_window_ids:
        logger.info(f"中控暂停/恢复过滤窗口: {sorted(target_window_ids)}")

    scope_text = "目标窗口" if target_window_ids is not None else "全部窗口"

    try:
        has_unpaused_running = bool(self._has_unpaused_running_runners(target_window_ids=target_window_ids))
        has_paused = bool(self._is_any_runner_paused(target_window_ids=target_window_ids))

        if has_unpaused_running:
            logger.info("暂停运行中的工作流")
            self.log_message(f"正在暂停{scope_text}工作流...")
            paused_window_ids = self._pause_all_running_runners(target_window_ids=target_window_ids)
            self.log_message(f"已暂停 {len(paused_window_ids)} 个窗口的工作流")
            result = {
                "action": "pause",
                "window_ids": sorted(paused_window_ids),
            }
        elif has_paused:
            logger.info("恢复暂停中的工作流")
            self.log_message(f"正在恢复{scope_text}工作流...")
            resumed_window_ids = self._resume_all_paused_runners(target_window_ids=target_window_ids)
            self.log_message(f"已恢复 {len(resumed_window_ids)} 个窗口的工作流")
            result = {
                "action": "resume",
                "window_ids": sorted(resumed_window_ids),
            }
        else:
            logger.info("暂停运行中的工作流")
            self.log_message(f"正在暂停{scope_text}工作流...")
            paused_window_ids = self._pause_all_running_runners(target_window_ids=target_window_ids)
            self.log_message(f"已暂停 {len(paused_window_ids)} 个窗口的工作流")
            result = {
                "action": "pause",
                "window_ids": sorted(paused_window_ids),
            }

        self._sync_pause_all_button_text()
        return result
    except Exception as e:
        logger.error(f"暂停/恢复全部任务失败: {e}")
        logger.error(traceback.format_exc())
        self.log_message(f"错误：{str(e)}")
        return None
