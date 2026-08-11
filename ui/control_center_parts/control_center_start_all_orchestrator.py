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
            window_id = str(window_info.get("hwnd", row))
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


def _check_parent_window_running_conflict(self) -> bool:
    if not self.parent_window or not hasattr(self.parent_window, "_is_any_workflow_running"):
        return False
    if not self.parent_window._is_any_workflow_running():
        return False
    logger.warning("\u4e3b\u7a97\u53e3\u6709\u4efb\u52a1\u6b63\u5728\u8fd0\u884c\uff0c\u4e2d\u63a7\u62d2\u7edd\u542f\u52a8\u65b0\u4efb\u52a1")
    QMessageBox.warning(
        self,
        "\u65e0\u6cd5\u542f\u52a8",
        "\u4e3b\u7a97\u53e3\u6b63\u5728\u6267\u884c\u4efb\u52a1\uff0c\u8bf7\u7b49\u5f85\u4e3b\u7a97\u53e3\u4efb\u52a1\u5b8c\u6210\u6216\u505c\u6b62\u540e\u518d\u4ece\u4e2d\u63a7\u542f\u52a8\u3002\n\n"
        "\u4e2d\u63a7\u548c\u4e3b\u7a97\u53e3\u7684\u6267\u884c\u5668\u4e0d\u80fd\u540c\u65f6\u8fd0\u884c\uff0c\u5426\u5219\u53ef\u80fd\u5bfc\u81f4\u7a0b\u5e8f\u5361\u6b7b\u3002"
    )
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
            window_id = str(window_info.get("hwnd", row))
            if target_window_ids is not None and window_id not in target_window_ids:
                continue
            hwnd = window_info.get("hwnd")
            title = window_info.get("title", "\u672a\u77e5\u7a97\u53e3")
            if window_id not in self.window_workflows or not self.window_workflows[window_id]:
                continue
            if is_valid_window_handle(hwnd):
                logger.debug(f"\u7a97\u53e3 {title} (HWND: {hwnd}) \u53e5\u67c4\u6709\u6548")
                valid_windows.append({"hwnd": hwnd, "title": title, "row": row})
            else:
                invalid_windows.append(f"{title} (HWND: {hwnd})")
        except Exception as e:
            logger.error(f"\u68c0\u67e5\u7a97\u53e3{row}\u65f6\u53d1\u751f\u9519\u8bef: {e}")
    return valid_windows, invalid_windows


def _confirm_invalid_windows_start(self, invalid_windows) -> bool:
    if not invalid_windows:
        return True
    warning_message = "\u4ee5\u4e0b\u7a97\u53e3\u53e5\u67c4\u65e0\u6548\uff0c\u70b9\u51fb\u64cd\u4f5c\u53ef\u80fd\u5931\u8d25\uff1a\n\n"
    warning_message += "\n".join(f"  - {item}" for item in invalid_windows)
    warning_message += "\n\n\u5efa\u8bae\uff1a\u5728\u5168\u5c40\u8bbe\u7f6e\u4e2d\u91cd\u65b0\u7ed1\u5b9a\u8fd9\u4e9b\u7a97\u53e3\u3002\n\n\u662f\u5426\u4ecd\u7136\u7ee7\u7eed\u542f\u52a8\uff1f"
    reply = QMessageBox.warning(
        self,
        "\u7a97\u53e3\u53e5\u67c4\u9a8c\u8bc1\u8b66\u544a",
        warning_message,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    if reply != QMessageBox.StandardButton.Yes:
        logger.info("\u7528\u6237\u53d6\u6d88\u542f\u52a8\u4efb\u52a1")
        return False
    return True


def _filter_yolo_blocked_windows(self, valid_windows, target_window_ids):
    blocked_windows = {}
    collect_blocked_windows = getattr(self, "_collect_yolo_blocked_windows", None)
    if callable(collect_blocked_windows):
        try:
            blocked_windows = collect_blocked_windows(target_window_ids)
        except Exception as e:
            logger.error(f"\u6536\u96c6YOLO\u53d7\u9650\u7a97\u53e3\u5931\u8d25: {e}")
            blocked_windows = {}
    if not blocked_windows:
        return valid_windows

    blocked_window_ids = set(blocked_windows.keys())
    filtered_windows = [
        item for item in valid_windows
        if str(item.get("hwnd", item.get("row"))) not in blocked_window_ids
    ]
    preview_lines = []
    for window_id, info in blocked_windows.items():
        title = str((info or {}).get("title") or window_id)
        workflow_names = (info or {}).get("workflow_names") or []
        preview_workflows = "\u3001".join([str(name) for name in workflow_names[:2]]) if workflow_names else "\u672a\u77e5\u5de5\u4f5c\u6d41"
        if len(workflow_names) > 2:
            preview_workflows += f" \u7b49{len(workflow_names)}\u4e2a"
        preview_lines.append(f"  - {title}: {preview_workflows}")

    warning_message = "\u4ee5\u4e0b\u7a97\u53e3\u5305\u542b YOLO \u5de5\u4f5c\u6d41\uff0c\u5df2\u4ece\u4e2d\u63a7\u542f\u52a8\u961f\u5217\u79fb\u9664\uff1a\n\n"
    warning_message += "\n".join(preview_lines[:8])
    if len(preview_lines) > 8:
        warning_message += f"\n  - \u5176\u4f59 {len(preview_lines) - 8} \u4e2a\u7a97\u53e3"
    warning_message += "\n\n\u8bf7\u5728\u4e3b\u7a97\u53e3\u5355\u5f00\u6267\u884c\u8fd9\u4e9b YOLO \u5de5\u4f5c\u6d41\u3002"
    QMessageBox.warning(self, "\u5df2\u8fc7\u6ee4YOLO\u7a97\u53e3", warning_message)
    self.log_message(f"\u5df2\u8fc7\u6ee4 {len(blocked_windows)} \u4e2a\u5305\u542bYOLO\u4efb\u52a1\u7684\u7a97\u53e3")
    logger.warning("\u4e2d\u63a7\u542f\u52a8\u8fc7\u6ee4YOLO\u7a97\u53e3: %s", sorted(blocked_window_ids))
    return filtered_windows


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


def control_center_start_all_tasks(ctx):
    self = ctx
    logger.info("\u5f00\u59cb\u542f\u52a8\u6240\u6709\u5de5\u4f5c\u6d41")
    self.log_message("\u6b63\u5728\u542f\u52a8\u6240\u6709\u5de5\u4f5c\u6d41...")
    target_window_ids = getattr(self, "_cc_active_start_window_filter", None)
    if target_window_ids:
        logger.info(f"\u4e2d\u63a7\u542f\u52a8\u8fc7\u6ee4\u7a97\u53e3: {sorted(target_window_ids)}")
    if _check_parent_window_running_conflict(self):
        return
    _cancel_control_center_ocr_cleanup(self)
    valid_windows, invalid_windows = _collect_start_candidate_windows(self, target_window_ids)
    if not _confirm_invalid_windows_start(self, invalid_windows):
        return
    valid_windows = _filter_yolo_blocked_windows(self, valid_windows, target_window_ids)
    if not valid_windows:
        self.log_message("\u6ca1\u6709\u53ef\u542f\u52a8\u7684\u76ee\u6807\u7a97\u53e3\uff08\u8bf7\u68c0\u67e5\u7a97\u53e3\u9009\u62e9\u548c\u5de5\u4f5c\u6d41\u5206\u914d\uff09")
        return
    _handle_control_center_batch_start(self, valid_windows)
