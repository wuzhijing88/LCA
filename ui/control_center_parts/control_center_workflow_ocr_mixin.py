import logging
import math
import threading

from PySide6.QtWidgets import QApplication

logger = logging.getLogger(__name__)


class ControlCenterWorkflowOcrMixin:
    def _precreate_ocr_processes(self, valid_windows: list):
        window_count = len(valid_windows)
        process_count = math.ceil(window_count / 3)
        logger.info(f"\u3010OCR\u9884\u521b\u5efa\u3011\u68c0\u6d4b\u5230 {window_count} \u4e2a\u6709\u6548\u7a97\u53e3\uff0c\u9700\u8981\u521b\u5efa {process_count} \u4e2aOCR\u8fdb\u7a0b")
        self.log_message(
            f"\u9884\u521b\u5efaOCR\u8fdb\u7a0b: {window_count}\u4e2a\u7a97\u53e3 -> {process_count}\u4e2a\u8fdb\u7a0b\uff08\u540e\u53f0\u6267\u884c\uff09"
        )

        def precreate_in_background():
            try:
                from services.multiprocess_ocr_pool import get_multiprocess_ocr_pool

                ocr_pool = get_multiprocess_ocr_pool()
                for index, window_data in enumerate(valid_windows, start=1):
                    if getattr(self, "_is_closing", False):
                        logger.info("\u3010OCR\u9884\u521b\u5efa\u3011\u68c0\u6d4b\u5230\u4e2d\u63a7\u7a97\u53e3\u5173\u95ed\uff0c\u505c\u6b62\u7ee7\u7eed\u9884\u521b\u5efa")
                        break
                    hwnd = window_data["hwnd"]
                    title = window_data["title"]
                    success = ocr_pool.preregister_window(title, hwnd)
                    if success:
                        logger.info(
                            f"\u3010OCR\u9884\u521b\u5efa\u3011\u7a97\u53e3 {index}/{window_count} \u6ce8\u518c\u6210\u529f: {title} (HWND: {hwnd})"
                        )
                    else:
                        logger.warning(
                            f"\u3010OCR\u9884\u521b\u5efa\u3011\u7a97\u53e3 {index}/{window_count} \u6ce8\u518c\u5931\u8d25: {title} (HWND: {hwnd})"
                        )
                logger.info(f"\u3010OCR\u9884\u521b\u5efa\u3011\u5b8c\u6210\uff0c\u5df2\u521b\u5efa {process_count} \u4e2aOCR\u8fdb\u7a0b")
            except Exception as e:
                logger.exception(f"\u3010OCR\u9884\u521b\u5efa\u3011\u5931\u8d25: {e}")

        precreate_thread = threading.Thread(
            target=precreate_in_background,
            daemon=True,
            name="OCR-Precreate",
        )
        precreate_thread.start()
        logger.info("\u3010OCR\u9884\u521b\u5efa\u3011\u540e\u53f0\u7ebf\u7a0b\u5df2\u542f\u52a8\uff0c\u4e0d\u963b\u585eUI")
        return precreate_thread

    def _force_cleanup_ocr_processes(self):
        logger.info("\u3010OCR\u6e05\u7406\u3011\u5f00\u59cb\u5f3a\u5236\u5173\u95ed\u6240\u6709OCR\u5b50\u8fdb\u7a0b...")
        self.log_message("\u6b63\u5728\u5173\u95edOCR\u8fdb\u7a0b...")
        try:
            from services.multiprocess_ocr_pool import cleanup_ocr_services_on_stop

            cleanup_ocr_services_on_stop(deep_cleanup=True)
            logger.info("\u3010OCR\u6e05\u7406\u3011\u5df2\u5f3a\u5236\u5173\u95ed\u6240\u6709OCR\u5b50\u8fdb\u7a0b")
            self.log_message("OCR\u8fdb\u7a0b\u5df2\u5173\u95ed")
        except Exception as e:
            logger.exception(f"\u3010OCR\u6e05\u7406\u3011\u5173\u95edOCR\u5b50\u8fdb\u7a0b\u5931\u8d25: {e}")

    def _check_and_cleanup_ocr_if_all_done(self):
        if self.is_any_task_running():
            return

        logger.info("\u3010OCR\u5ef6\u8fdf\u6e05\u7406\u3011\u6240\u6709\u4efb\u52a1\u5df2\u5b8c\u6210\uff0c\u542f\u52a830\u79d2\u5ef6\u8fdf\u6e05\u7406\u5b9a\u65f6\u5668")
        try:
            app = QApplication.instance()
            if not app:
                return
            main_windows = [w for w in app.topLevelWidgets() if hasattr(w, "task_state_manager")]
            if not main_windows:
                return
            main_window = main_windows[0]
            task_state_manager = getattr(main_window, "task_state_manager", None)
            if task_state_manager:
                task_state_manager.confirm_stopped()
                logger.info("\u3010OCR\u5ef6\u8fdf\u6e05\u7406\u3011\u5df2\u542f\u52a830\u79d2\u5ef6\u8fdf\u5b9a\u65f6\u5668\uff08\u4e2d\u63a7\u4efb\u52a1\u5b8c\u6210\uff09")
        except Exception as e:
            logger.warning(f"\u542f\u52a8OCR\u5ef6\u8fdf\u6e05\u7406\u5931\u8d25: {e}")
