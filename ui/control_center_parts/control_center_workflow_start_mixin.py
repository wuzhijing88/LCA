import logging
import threading

from PySide6.QtCore import QTimer

logger = logging.getLogger(__name__)


class ControlCenterWorkflowStartMixin:
    def _wait_ocr_and_start_windows(self):
        self._set_start_all_button_state(False, "\u7b49\u5f85OCR...")
        self.log_message("\u6b63\u5728\u7b49\u5f85OCR\u8fdb\u7a0b\u521b\u5efa...")
        logger.info("\u3010OCR\u7b49\u5f85\u3011\u5f00\u59cb\u7b49\u5f85OCR\u9884\u521b\u5efa\u5b8c\u6210...")
        self._ocr_check_timer_active = True
        QTimer.singleShot(100, self._check_ocr_precreate_and_start_windows)

    def _check_ocr_precreate_and_start_windows(self):
        if getattr(self, "_is_closing", False):
            self._ocr_check_timer_active = False
            self._pending_valid_windows = None
            logger.info("\u3010OCR\u7b49\u5f85\u3011\u68c0\u6d4b\u5230\u4e2d\u63a7\u7a97\u53e3\u6b63\u5728\u5173\u95ed\uff0c\u53d6\u6d88\u540e\u7eed\u542f\u52a8\u6d41\u7a0b")
            return

        if not getattr(self, "_ocr_check_timer_active", False):
            logger.info("\u3010OCR\u7b49\u5f85\u3011\u7b49\u5f85\u5df2\u88ab\u53d6\u6d88")
            return

        ocr_thread = getattr(self, "_ocr_precreate_thread", None)
        if ocr_thread and ocr_thread.is_alive():
            logger.debug("\u3010OCR\u7b49\u5f85\u3011OCR\u7ebf\u7a0b\u4ecd\u5728\u8fd0\u884c\uff0c\u7ee7\u7eed\u7b49\u5f85...")
            QTimer.singleShot(100, self._check_ocr_precreate_and_start_windows)
            return

        if ocr_thread is not None:
            logger.info("\u3010OCR\u7b49\u5f85\u3011OCR\u9884\u521b\u5efa\u5b8c\u6210\uff0c\u5f00\u59cb\u542f\u52a8\u7a97\u53e3\u4efb\u52a1")
            self.log_message("OCR\u8fdb\u7a0b\u5c31\u7eea\uff0c\u5f00\u59cb\u542f\u52a8\u4efb\u52a1")
            self._ocr_precreate_thread = None
        else:
            logger.warning("\u3010OCR\u7b49\u5f85\u3011OCR\u7ebf\u7a0b\u5bf9\u8c61\u4e0d\u5b58\u5728\uff0c\u76f4\u63a5\u542f\u52a8\u7a97\u53e3")

        self._ocr_check_timer_active = False
        self._start_pending_valid_windows()

    def _start_pending_valid_windows(self):
        pending_valid_windows = list(self._pending_valid_windows or [])
        self._pending_valid_windows = None
        if pending_valid_windows:
            self._start_windows_sequentially(pending_valid_windows)

    def _start_windows_sequentially(self, valid_windows: list):
        self._pending_windows = list(valid_windows or [])
        self._started_count = 0
        self._start_all_in_progress = True
        self._cancel_start_sequence = False
        self._batch_start_gate_event = threading.Event() if self._should_use_batch_start_gate() else None
        self._refresh_multi_window_mode_env()
        self._set_start_all_button_state(False, "\u542f\u52a8\u4e2d...")
        self._start_next_window()

    def _should_use_batch_start_gate(self) -> bool:
        try:
            configured_delay = self._window_start_delay_sec
            return (
                len(self._pending_windows) > 1
                and configured_delay is not None
                and float(configured_delay) <= 0
            )
        except Exception:
            return False

    def _set_start_all_button_state(self, enabled: bool, text: str):
        if hasattr(self, "start_all_btn") and self.start_all_btn is not None:
            self.start_all_btn.setEnabled(enabled)
            self.start_all_btn.setText(text)

    def _release_batch_start_gate(self):
        gate = getattr(self, "_batch_start_gate_event", None)
        if gate is None:
            return
        try:
            gate.set()
        except Exception:
            pass
        self._batch_start_gate_event = None

    def _clear_pending_start_state(self, reenable_button: bool):
        self._release_batch_start_gate()
        self._pending_windows = []
        self._pending_valid_windows = None
        self._start_all_in_progress = False
        if reenable_button:
            self._set_start_all_button_state(True, "\u5168\u90e8\u5f00\u59cb")
        self._refresh_multi_window_mode_env()

    def _start_next_window(self):
        if self._cancel_start_sequence:
            self._clear_pending_start_state(reenable_button=True)
            return

        if getattr(self, "_is_closing", False):
            self._clear_pending_start_state(reenable_button=False)
            return

        if not self._pending_windows:
            self._on_all_windows_started()
            return

        window_data = self._pending_windows.pop(0)
        self._try_start_pending_window(window_data)

        if self._pending_windows:
            QTimer.singleShot(self._get_window_start_delay_ms(), self._start_next_window)
        else:
            self._on_all_windows_started()

    def _try_start_pending_window(self, window_data: dict):
        row = window_data.get("row")
        try:
            window_info = self.sorted_windows[row]
            window_id = str(window_info.get("hwnd", row))
            pending_count = 0
            for runner in self._get_window_runner_list(window_id):
                try:
                    if runner.has_pending_work:
                        pending_count += 1
                except Exception:
                    continue
            if pending_count > 0:
                logger.info(f"\u7a97\u53e3{window_id}\u5df2\u6709{pending_count}\u4e2a\u5de5\u4f5c\u6d41\u5728\u5904\u7406\u4e2d\uff0c\u8df3\u8fc7\u542f\u52a8")
                return

            started = bool(self.start_window_task(row))
            if started:
                self._started_count += 1
                logger.info(f"\u5df2\u542f\u52a8\u7a97\u53e3{window_id}\u7684\u5de5\u4f5c\u6d41")
            else:
                logger.info(f"\u7a97\u53e3{window_id}\u672a\u542f\u52a8\uff08\u5df2\u8df3\u8fc7\uff09")
        except Exception as e:
            logger.error(f"\u542f\u52a8\u7a97\u53e3{row}\u5de5\u4f5c\u6d41\u65f6\u53d1\u751f\u9519\u8bef: {e}")

    def _get_window_start_delay_ms(self) -> int:
        if self._window_start_delay_sec is not None:
            logger.info(f"\u7b49\u5f85 {self._window_start_delay_sec} \u79d2\u540e\u542f\u52a8\u4e0b\u4e00\u4e2a\u7a97\u53e3")
            return int(self._window_start_delay_sec * 1000)
        return 100

    def _on_all_windows_started(self):
        self._pending_windows = []
        self._start_all_in_progress = False
        self._pending_valid_windows = None
        self._release_batch_start_gate()
        self._refresh_multi_window_mode_env()
        self._set_start_all_button_state(True, "\u5168\u90e8\u5f00\u59cb")
        self.log_message(f"\u5df2\u542f\u52a8 {self._started_count} \u4e2a\u7a97\u53e3\u7684\u5de5\u4f5c\u6d41")
        logger.info(f"\u6240\u6709\u7a97\u53e3\u542f\u52a8\u5b8c\u6210\uff0c\u5171\u542f\u52a8 {self._started_count} \u4e2a")
