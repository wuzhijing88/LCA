# -*- coding: utf-8 -*-
"""运行期日志整洁策略。"""

from __future__ import annotations

import logging
from typing import Iterable, Optional


class BoundedLogMessageFilter(logging.Filter):
    """限制单条日志长度，避免超长日志挤占日志输出。"""

    def __init__(self, max_chars: int):
        super().__init__()
        self.max_chars = max(128, int(max_chars or 0))

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
            if len(message) > self.max_chars:
                overflow = len(message) - self.max_chars
                record.msg = f"{message[:self.max_chars]}...[截断{overflow}字符]"
                record.args = ()
        except Exception:
            pass
        return True


class RuntimeLogNoiseFilter(logging.Filter):
    """过滤运行期高频噪声日志，只保留关键结果与错误。"""

    _QUIET_INFO_LOGGER_PREFIXES = (
        "comtypes.client._code_cache",
        "ui.main_window_parts",
        "ui.workflow_parts",
        "ui.panels",
        "ui.coordinate_selector",
        "ui.ocr_region_selector",
        "ui.widgets.custom_widgets",
        "utils.wgc_hwnd_capture",
        "utils.screenshot_helper",
        "task_workflow.executor",
        "task_workflow.process_worker",
    )

    _QUIET_INFO_MESSAGE_FRAGMENTS = (
        "CustomDropdown init:",
        "输入模拟器缓存已清除",
        "前台输入驱动管理器已关闭",
        "DPI监控已启用",
        "DPI监控已禁用",
        "配置已保存到 ",
        "已注册主题切换回调:",
    )

    _DEBUG_MARKERS = (
        "[DEBUG]",
        "[调试]",
        "[DRAG_DEBUG]",
        "[CONN_DEBUG]",
        "[PARAM_CONN_DEBUG]",
        "[PARAM_UPDATE]",
        "[位置验证]",
        "[窗口调试]",
        "[OCR测试-诊断]",
        "[APPLY]",
        "[INIT]",
        "[SERIALIZE]",
    )

    _DEBUG_WARNING_FRAGMENTS = (
        "remove_connection 被调用",
        "connection 对象:",
        "connection 类型:",
        "Attempting to remove connection",
        "Connection removal 完成",
        "起点卡片 sequential 连接:",
        "成功创建sequential连接:",
        "起点卡片参数更新:",
        "确认: self.cards",
        "更新后 start_card.parameters =",
        "更新后 self.cards[",
    )

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            logger_name = str(getattr(record, "name", "") or "")
            message = record.getMessage()
        except Exception:
            return True

        # 关键用户操作日志必须保留，即使来源属于默认静默的 UI 模块。
        important_operation_log = any(
            marker in message for marker in ("[卡片删除]", "[撤回]")
        )

        if (
            record.levelno < logging.WARNING
            and logger_name.startswith(self._QUIET_INFO_LOGGER_PREFIXES)
            and not important_operation_log
        ):
            return False

        if record.levelno < logging.WARNING:
            if any(fragment in message for fragment in self._QUIET_INFO_MESSAGE_FRAGMENTS):
                return False

        if record.levelno < logging.ERROR:
            if any(marker in message for marker in self._DEBUG_MARKERS):
                return False
            if any(fragment in message for fragment in self._DEBUG_WARNING_FRAGMENTS):
                return False

        return True


def install_runtime_log_filters(
    handlers: Optional[Iterable[logging.Handler]],
    max_message_chars: int,
) -> None:
    if not handlers:
        return
    for handler in handlers:
        try:
            handler.addFilter(RuntimeLogNoiseFilter())
            handler.addFilter(BoundedLogMessageFilter(max_message_chars))
        except Exception:
            continue


def configure_noisy_logger_levels() -> None:
    """统一压低高频日志等级，避免主日志被操作细节淹没。"""

    noisy_logger_prefixes = (
        "comtypes.client._code_cache",
        "task_workflow.executor",
        "task_workflow.process_worker",
        "ui.main_window_parts",
        "ui.workflow_parts",
        "ui.panels",
        "ui.coordinate_selector",
        "ui.ocr_region_selector",
        "ui.widgets.custom_widgets",
        "utils.wgc_hwnd_capture",
        "utils.screenshot_helper",
        "urllib3.connectionpool",
        "PIL",
        "onnxruntime",
    )

    for logger_name in noisy_logger_prefixes:
        logging.getLogger(logger_name).setLevel(logging.WARNING)
