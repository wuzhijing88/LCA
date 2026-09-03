"""主进程全局异常钩子：记录详细堆栈、尽量给用户一个可读的错误框，并区分致命错误。"""

from __future__ import annotations

import logging
import sys
from traceback import format_exception

_FATAL_EXCEPTION_TYPES = (MemoryError, SystemExit, KeyboardInterrupt)
_FATAL_MESSAGE_KEYWORDS = (
    "segmentation fault",
    "access violation",
    "stack overflow",
    "out of memory",
    "corrupted",
)


def is_fatal_exception(exctype, value) -> bool:
    """判断异常是否致命（必须退出）。"""
    if exctype in _FATAL_EXCEPTION_TYPES:
        return True
    error_msg = str(value).lower()
    return any(keyword in error_msg for keyword in _FATAL_MESSAGE_KEYWORDS)


def emergency_cleanup() -> None:
    """异常后的紧急处理：只把 Qt 事件泵一遍，不做任何可能再次抛错的资源释放。"""
    try:
        logging.info("执行紧急清理...")
        try:
            from PySide6.QtWidgets import QApplication

            if QApplication.instance():
                QApplication.processEvents()
        except Exception:
            pass
        logging.info("紧急清理完成")
    except Exception as e:
        logging.error(f"紧急清理失败: {e}")


def global_exception_handler(exctype, value, traceback_obj) -> None:
    """增强的全局异常处理函数，防止程序闪退并提供详细的错误信息。"""
    # 用户主动中断（Ctrl+C / IDE停止）按正常退出处理，避免误报严重异常
    if exctype is KeyboardInterrupt:
        logging.info("收到键盘中断信号，程序正常退出。")
        try:
            emergency_cleanup()
        except Exception:
            pass
        sys.exit(0)

    error_message = "发生了一个意外错误。程序将尝试继续运行，但建议保存工作并重启。"
    logging.critical("捕获到未处理的全局异常!", exc_info=(exctype, value, traceback_obj))

    is_fatal = is_fatal_exception(exctype, value)

    try:
        emergency_cleanup()
    except Exception as cleanup_ex:
        logging.error(f"紧急清理失败: {cleanup_ex}")

    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        if QApplication.instance():
            from ui.system_parts.message_box_translator import place_dialog_on_screen

            msg_box = QMessageBox()
            msg_box.setIcon(QMessageBox.Icon.Critical)
            msg_box.setWindowTitle("程序异常" if not is_fatal else "严重错误")
            msg_box.setText(error_message if not is_fatal else "发生了严重错误，程序必须退出。")
            msg_box.setDetailedText("\n".join(format_exception(exctype, value, traceback_obj)))

            if is_fatal:
                msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
                msg_box.setInformativeText("请保存重要数据并重启程序。")
            else:
                msg_box.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Ignore)
                msg_box.setInformativeText("您可以选择继续运行，但建议保存工作并重启程序。")

            place_dialog_on_screen(msg_box, reference_widget=QApplication.activeWindow())
            result = msg_box.exec()

            if is_fatal or result == QMessageBox.StandardButton.Ok:
                logging.info("用户选择退出或遇到致命错误，程序即将退出")
                sys.exit(1)
        else:
            print(f"CRITICAL ERROR: {error_message}", file=sys.stderr)
            print("--- TRACEBACK ---", file=sys.stderr)
            print("\n".join(format_exception(exctype, value, traceback_obj)), file=sys.stderr)
            print("-----------------", file=sys.stderr)
            if is_fatal:
                sys.exit(1)
    except Exception as e_handler_ex:
        logging.error(f"在全局异常处理器中显示错误时发生错误: {e_handler_ex}", exc_info=True)
        print(f"EXCEPTION IN EXCEPTION HANDLER: {e_handler_ex}", file=sys.stderr)
        print("Original error was not shown in GUI.", file=sys.stderr)
        if is_fatal:
            sys.exit(1)


def install_global_exception_hook() -> None:
    sys.excepthook = global_exception_handler
