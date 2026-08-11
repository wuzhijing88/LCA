import logging

logger = logging.getLogger(__name__)


class ControlCenterWorkflowStopMixin:
    def _iter_target_window_runners(self, target_window_ids=None):
        target_filter = set(target_window_ids) if target_window_ids else None
        for window_id in list(self.window_runners.keys()):
            if target_filter is not None and window_id not in target_filter:
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
            from utils.runtime_image_cleanup import cleanup_yolo_runtime_on_stop

            cleanup_yolo_runtime_on_stop(release_engine=True, compact_memory=True)
        except Exception as e:
            logger.warning(f"\u4e2d\u63a7\u5ef6\u8fdf\u6e05\u7406YOLO\u8fd0\u884c\u65f6\u5931\u8d25: {e}")

    def _cleanup_screenshot_runtime_after_global_stop(self):
        try:
            from utils.screenshot_helper import cleanup_screenshot_engines_on_stop

            cleanup_screenshot_engines_on_stop(keep_current_engine=True)
        except Exception as e:
            logger.warning(f"\u4e2d\u63a7\u5ef6\u8fdf\u6e05\u7406\u622a\u56fe\u5b50\u8fdb\u7a0b\u5931\u8d25: {e}")

    def _cleanup_ocr_runtime_after_global_stop(self):
        try:
            from services.multiprocess_ocr_pool import cleanup_ocr_services_on_stop

            cleanup_ocr_services_on_stop(deep_cleanup=True)
        except Exception as e:
            logger.warning(f"\u4e2d\u63a7\u5ef6\u8fdf\u6e05\u7406OCR\u5b50\u8fdb\u7a0b\u5931\u8d25: {e}")

    def _cleanup_runtime_image_after_global_stop(self):
        try:
            from utils.runtime_image_cleanup import cleanup_runtime_image_memory

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
            for window_id, runner in self._iter_target_window_runners(target_window_ids=target_window_ids):
                try:
                    self._remove_runner_from_start_queue(runner)
                    if self._can_request_stop_runner(runner):
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
            self._update_window_table_status(
                stopping_window_ids,
                "\u6b63\u5728\u505c\u6b62",
                "\u6b63\u5728\u505c\u6b62\u5de5\u4f5c\u6d41",
            )

        self.log_message(f"\u5df2\u505c\u6b62 {stopped_count} \u4e2a\u5de5\u4f5c\u6d41")
        if target_filter is not None:
            self._dispatch_pending_runner_starts()
        self._refresh_multi_window_mode_env()

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
