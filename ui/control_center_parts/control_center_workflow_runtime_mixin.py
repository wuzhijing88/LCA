import logging
import threading
from PySide6.QtCore import QTimer
import math
from PySide6.QtWidgets import QApplication

logger = logging.getLogger(__name__)

class ControlCenterWorkflowRuntimeMixin:

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
            self._set_start_all_button_state(True, "开始")
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
            window_id = self._window_runtime_id(window_info, row)
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
        self._set_start_all_button_state(True, "开始")
        self.log_message(f"\u5df2\u542f\u52a8 {self._started_count} \u4e2a\u7a97\u53e3\u7684\u5de5\u4f5c\u6d41")
        logger.info(f"\u6240\u6709\u7a97\u53e3\u542f\u52a8\u5b8c\u6210\uff0c\u5171\u542f\u52a8 {self._started_count} \u4e2a")

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

            cleanup_ocr_services_on_stop()
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

    def _iter_target_window_runners(self, target_window_ids=None):
        target_filter = set(target_window_ids) if target_window_ids else None
        for window_id in list(self.window_runners.keys()):
            if target_filter is not None and not self._job_id_in_filter(window_id, target_filter):
                continue
            for runner in self._get_window_runner_list(window_id):
                yield window_id, runner

    def _confirm_global_stop(self, app):
        try:
            if app and hasattr(app, "task_state_manager"):
                app.task_state_manager.confirm_stopped()
                logger.info("\u5df2\u786e\u8ba4\u5168\u5c40\u505c\u6b62\u5b8c\u6210\uff0c\u72b6\u6001\u7ba1\u7406\u5668\u5df2\u91cd\u7f6e")
                self.log_message("\u5168\u5c40\u505c\u6b62\u5b8c\u6210")
        except Exception as e:
            logger.error(f"\u786e\u8ba4\u5168\u5c40\u505c\u6b62\u65f6\u53d1\u751f\u9519\u8bef: {e}")

    def _request_deferred_global_stop_cleanup(self):
        self._deferred_global_stop_cleanup_pending = True
        logger.info("\u4e2d\u63a7\u5168\u5c40\u505c\u6b62\u6e05\u7406\u5df2\u767b\u8bb0\uff0c\u7b49\u5f85\u6240\u6709\u4efb\u52a1\u9000\u51fa\u540e\u6267\u884c")
        self._try_run_deferred_global_stop_cleanup()

    def _try_run_deferred_global_stop_cleanup(self) -> bool:
        if not self._deferred_global_stop_cleanup_pending:
            return False
        if self.is_any_task_running():
            return False

        self._deferred_global_stop_cleanup_pending = False
        logger.info("\u5f00\u59cb\u6267\u884c\u4e2d\u63a7\u505c\u6b62\u540e\u7684\u5ef6\u8fdf\u5168\u5c40\u8d44\u6e90\u6e05\u7406")
        self._cleanup_yolo_runtime_after_global_stop()
        self._cleanup_screenshot_runtime_after_global_stop()
        self._cleanup_ocr_runtime_after_global_stop()
        self._cleanup_runtime_image_after_global_stop()
        logger.info("\u4e2d\u63a7\u505c\u6b62\u540e\u7684\u5ef6\u8fdf\u5168\u5c40\u8d44\u6e90\u6e05\u7406\u5b8c\u6210")
        return True

    def _cleanup_yolo_runtime_after_global_stop(self):
        try:
            from app_core.runtime.runtime_image_cleanup import cleanup_yolo_runtime_on_stop

            cleanup_yolo_runtime_on_stop(release_engine=True, compact_memory=True)
        except Exception as e:
            logger.warning(f"\u4e2d\u63a7\u5ef6\u8fdf\u6e05\u7406YOLO\u8fd0\u884c\u65f6\u5931\u8d25: {e}")

    def _cleanup_screenshot_runtime_after_global_stop(self):
        try:
            from services.screenshot_pool import cleanup_screenshot_engines_on_stop

            cleanup_screenshot_engines_on_stop(keep_current_engine=True)
        except Exception as e:
            logger.warning(f"\u4e2d\u63a7\u5ef6\u8fdf\u6e05\u7406\u622a\u56fe\u5b50\u8fdb\u7a0b\u5931\u8d25: {e}")

    def _cleanup_ocr_runtime_after_global_stop(self):
        try:
            from services.multiprocess_ocr_pool import cleanup_ocr_services_on_stop

            cleanup_ocr_services_on_stop()
        except Exception as e:
            logger.warning(f"\u4e2d\u63a7\u5ef6\u8fdf\u6e05\u7406OCR\u5b50\u8fdb\u7a0b\u5931\u8d25: {e}")

    def _cleanup_runtime_image_after_global_stop(self):
        try:
            from app_core.runtime.runtime_image_cleanup import cleanup_runtime_image_memory

            cleanup_runtime_image_memory(
                reason="control_center_stop_all_tasks",
                cleanup_screenshot_engines=False,
                cleanup_template_cache=True,
            )
        except Exception as e:
            logger.warning(f"\u4e2d\u63a7\u5ef6\u8fdf\u6e05\u7406\u56fe\u7247\u7f13\u5b58\u5931\u8d25: {e}")

    def _can_request_stop_runner(self, runner) -> bool:
        runner_thread_running = False
        try:
            runner_thread_running = bool(runner.isRunning())
        except Exception:
            runner_thread_running = False

        try:
            should_stop_runner = bool(runner.can_stop or runner_thread_running)
        except Exception:
            should_stop_runner = runner_thread_running

        if not should_stop_runner:
            try:
                should_stop_runner = (self._get_runner_state_value(runner) == "\u7b49\u5f85\u5f00\u59cb")
            except Exception:
                should_stop_runner = False
        return should_stop_runner

    def _direct_stop_all_tasks(self, target_window_ids=None):
        stopped_count = 0
        stopping_window_ids = set()
        target_filter = set(target_window_ids) if target_window_ids else None
        pending_removed = self._cancel_pending_start_windows(target_window_ids=target_window_ids)
        if pending_removed > 0:
            logger.info("\u505c\u6b62\u4efb\u52a1\u65f6\u5df2\u53d6\u6d88\u672a\u542f\u52a8\u7a97\u53e3\u961f\u5217: %d", pending_removed)

        previous_dispatch_state = self._runner_dispatch_suspended
        self._runner_dispatch_suspended = True
        try:
            requested_job_ids = set()
            for window_id, runner in self._iter_target_window_runners(target_window_ids=target_window_ids):
                try:
                    self._remove_runner_from_start_queue(runner)
                    if self._can_request_stop_runner(runner):
                        scheduler = getattr(self, "scheduler", None)
                        if scheduler is not None and window_id not in requested_job_ids:
                            scheduler.request_stop(window_id)
                            requested_job_ids.add(window_id)
                        runner.stop()
                        stopped_count += 1
                        stopping_window_ids.add(window_id)
                        logger.info(f"\u5df2\u505c\u6b62\u7a97\u53e3{window_id}\u7684\u4e00\u4e2a\u5de5\u4f5c\u6d41")
                    else:
                        state_value = "\u672a\u77e5"
                        try:
                            state_value = runner.current_state.value
                        except Exception:
                            pass
                        logger.info(f"\u7a97\u53e3{window_id}\u7684\u5de5\u4f5c\u6d41\u72b6\u6001\u4e3a'{state_value}'\uff0c\u8df3\u8fc7\u505c\u6b62\u64cd\u4f5c")
                except Exception as e:
                    logger.error(f"\u505c\u6b62\u7a97\u53e3{window_id}\u5de5\u4f5c\u6d41\u65f6\u53d1\u751f\u9519\u8bef: {e}")
        finally:
            self._runner_dispatch_suspended = previous_dispatch_state

        if stopping_window_ids:
            for window_id in stopping_window_ids:
                self._sync_job_from_runners(window_id)
        self._finalize_orphaned_active_jobs(target_window_ids)

        self.log_message(f"\u5df2\u505c\u6b62 {stopped_count} \u4e2a\u5de5\u4f5c\u6d41")
        if target_filter is not None:
            self._dispatch_pending_runner_starts()
        self._refresh_multi_window_mode_env()

    def _finalize_orphaned_active_jobs(self, target_window_ids=None):
        scheduler = getattr(self, "scheduler", None)
        if scheduler is None:
            return
        for snapshot in scheduler.list_jobs():
            if not snapshot.is_active:
                continue
            if not self._job_id_in_filter(snapshot.job_id, target_window_ids):
                continue
            if self._get_window_runner_list(snapshot.job_id):
                continue
            scheduler.request_stop(snapshot.job_id)
            scheduler.finalize_orphaned_stop(snapshot.job_id)
            self._cleanup_window_task_runners(snapshot.job_id)
            self._window_workflow_results.pop(snapshot.job_id, None)
            self._paint_job_snapshot(snapshot.job_id)

    def _force_stop_all_completion(self, target_window_ids=None):
        logger.info("\u5f3a\u5236\u5b8c\u6210\u6240\u6709\u505c\u6b62\u64cd\u4f5c")
        target_filter = set(target_window_ids) if target_window_ids else None
        for window_id, runner in self._iter_target_window_runners(target_window_ids=target_window_ids):
            try:
                if self._get_runner_state_value(runner) == "\u6b63\u5728\u505c\u6b62":
                    runner._force_stop_completion()
            except Exception as e:
                logger.error(f"\u5f3a\u5236\u505c\u6b62\u7a97\u53e3{window_id}\u65f6\u53d1\u751f\u9519\u8bef: {e}")

        remaining_count = self._count_running_runners(target_window_ids=target_window_ids)
        if remaining_count > 0:
            self.log_message(f"\u505c\u6b62\u68c0\u67e5\u5b8c\u6210\uff0c\u4ecd\u6709 {remaining_count} \u4e2a\u5de5\u4f5c\u6d41\u7b49\u5f85\u9000\u51fa")
        elif target_filter is not None:
            self.log_message("\u76ee\u6807\u7a97\u53e3\u5de5\u4f5c\u6d41\u5df2\u505c\u6b62")
        else:
            self.log_message("\u6240\u6709\u5de5\u4f5c\u6d41\u5df2\u505c\u6b62")

        self._try_run_deferred_global_stop_cleanup()
        self._refresh_multi_window_mode_env()
