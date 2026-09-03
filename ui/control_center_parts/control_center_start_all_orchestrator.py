import logging

from PySide6.QtWidgets import QMessageBox

from ..workflow_parts.workflow_lifecycle import (
    cancel_ocr_cleanup_timer,
    get_main_window_task_state_manager,
    is_valid_window_handle,
    workflow_uses_ocr,
)

logger = logging.getLogger(__name__)


def _control_center_has_ocr_workflow(self, valid_windows: list) -> bool:
    for item in (valid_windows or []):
        try:
            row = int(item.get("row"))
            window_info = self.sorted_windows[row]
            window_id = self._window_runtime_id(window_info, row)
            workflows = self.window_workflows.get(window_id)
            if not workflows:
                continue
            if isinstance(workflows, dict):
                workflows = [workflows]
            if not isinstance(workflows, list):
                continue
            for workflow_item in workflows:
                if not isinstance(workflow_item, dict):
                    continue
                workflow_data = workflow_item.get("data")
                if isinstance(workflow_data, dict) and workflow_uses_ocr(workflow_data):
                    return True
        except Exception:
            continue
    return False


def _check_parent_window_running_conflict(self, interactive=True) -> bool:
    if not self.parent_window or not hasattr(self.parent_window, "_is_any_workflow_running"):
        return False
    if not self.parent_window._is_any_workflow_running():
        return False
    logger.warning("主窗口有任务正在运行，中控拒绝启动新任务")
    if interactive:
        QMessageBox.warning(
            self,
            "无法启动",
            "主窗口正在执行任务，请等待主窗口任务完成或停止后再从中控启动。\n\n"
            "中控和主窗口的执行器不能同时运行，否则可能导致程序卡死。",
        )
    else:
        self.log_message("中控定时启动跳过：主窗口正在执行任务")
    return True


def _cancel_control_center_ocr_cleanup(self):
    try:
        cancel_ocr_cleanup_timer(
            get_main_window_task_state_manager(),
            success_log="\u3010OCR\u5ef6\u8fdf\u6e05\u7406\u3011\u68c0\u6d4b\u5230\u4e2d\u63a7\u542f\u52a8\u4efb\u52a1\uff0c\u53d6\u6d88OCR\u5ef6\u8fdf\u6e05\u7406\u5b9a\u65f6\u5668",
            log_message_cb=self.log_message,
        )
    except Exception as e:
        logger.warning(f"\u53d6\u6d88OCR\u5ef6\u8fdf\u6e05\u7406\u5931\u8d25: {e}")


def _collect_start_candidate_windows(self, target_window_ids):
    valid_windows = []
    invalid_windows = []
    for row in range(self.window_table.rowCount()):
        try:
            window_info = self.sorted_windows[row]
            window_id = self._window_runtime_id(window_info, row)
            if target_window_ids is not None and not self._job_id_in_filter(window_id, target_window_ids, window_info):
                continue
            hwnd = window_info.get("hwnd")
            title = window_info.get("title", "\u672a\u77e5\u7a97\u53e3")
            if window_id not in self.window_workflows or not self.window_workflows[window_id]:
                continue
            if is_valid_window_handle(hwnd):
                logger.debug(f"\u7a97\u53e3 {title} (HWND: {hwnd}) \u53e5\u67c4\u6709\u6548")
                valid_windows.append({"hwnd": hwnd, "title": title, "row": row, "job_id": window_id})
            else:
                invalid_windows.append(f"{title} (HWND: {hwnd})")
        except Exception as e:
            logger.error(f"\u68c0\u67e5\u7a97\u53e3{row}\u65f6\u53d1\u751f\u9519\u8bef: {e}")
    return valid_windows, invalid_windows


def _confirm_invalid_windows_start(self, invalid_windows, interactive=True) -> bool:
    if not invalid_windows:
        return True
    if not interactive:
        self.log_message(f"中控定时启动已跳过 {len(invalid_windows)} 个无效句柄窗口")
        return True
    warning_message = "以下窗口句柄无效，点击操作可能失败：\n\n"
    warning_message += "\n".join(f"  - {item}" for item in invalid_windows)
    warning_message += "\n\n建议：在全局设置中重新绑定这些窗口。\n\n是否仍然继续启动？"
    reply = QMessageBox.warning(
        self,
        "窗口句柄验证警告",
        warning_message,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    if reply != QMessageBox.StandardButton.Yes:
        logger.info("\u7528\u6237\u53d6\u6d88\u542f\u52a8\u4efb\u52a1")
        return False
    return True


def _handle_control_center_batch_start(self, valid_windows):
    self._pending_valid_windows = valid_windows
    has_ocr_workflow = _control_center_has_ocr_workflow(self, valid_windows)
    if has_ocr_workflow:
        ocr_thread = self._precreate_ocr_processes(valid_windows)
        if ocr_thread:
            self._ocr_precreate_thread = ocr_thread
            self._wait_ocr_and_start_windows()
            return
        self._start_windows_sequentially(valid_windows)
        return
    logger.info("\u4e2d\u63a7\u542f\u52a8\uff1a\u5f53\u524d\u6279\u6b21\u5de5\u4f5c\u6d41\u4e0d\u5305\u542bOCR\u4efb\u52a1\uff0c\u8df3\u8fc7OCR\u8fdb\u7a0b\u9884\u521b\u5efa")
    self.log_message("\u5f53\u524d\u5de5\u4f5c\u6d41\u4e0d\u542bOCR\uff0c\u8df3\u8fc7OCR\u8fdb\u7a0b\u521b\u5efa")
    self._start_windows_sequentially(valid_windows)


def control_center_start_all_tasks(ctx, interactive=True):
    self = ctx
    if getattr(self, "_is_closing", False):
        return
    logger.info("开始启动所有工作流")
    self.log_message("正在启动所有工作流...")
    target_window_ids = getattr(self, "_cc_active_start_window_filter", None)
    if target_window_ids:
        logger.info(f"中控启动过滤窗口: {sorted(target_window_ids)}")
    if _check_parent_window_running_conflict(self, interactive=interactive):
        return
    from ui.control_center_parts.control_center_policy import (
        CONTROL_CENTER_FOREGROUND_BLOCK_MESSAGE,
        control_center_allows_execution_mode,
        resolve_control_center_execution_mode,
    )

    execution_mode = resolve_control_center_execution_mode(self)
    if not control_center_allows_execution_mode(execution_mode):
        logger.warning("前台模式禁止中控启动: mode=%s", execution_mode)
        if interactive:
            QMessageBox.warning(self, "无法启动", CONTROL_CENTER_FOREGROUND_BLOCK_MESSAGE)
        else:
            self.log_message("中控定时启动跳过：当前为前台模式")
        return
    _cancel_control_center_ocr_cleanup(self)
    if hasattr(self, "_refresh_bound_window_handles"):
        try:
            self._refresh_bound_window_handles()
        except Exception as refresh_error:
            logger.warning(f"中控启动前刷新绑定句柄失败: {refresh_error}")
    valid_windows, invalid_windows = _collect_start_candidate_windows(self, target_window_ids)
    if not _confirm_invalid_windows_start(self, invalid_windows, interactive=interactive):
        return
    if not valid_windows:
        self.log_message("\u6ca1\u6709\u53ef\u542f\u52a8\u7684\u76ee\u6807\u7a97\u53e3\uff08\u8bf7\u68c0\u67e5\u7a97\u53e3\u9009\u62e9\u548c\u5de5\u4f5c\u6d41\u5206\u914d\uff09")
        return
    _handle_control_center_batch_start(self, valid_windows)
