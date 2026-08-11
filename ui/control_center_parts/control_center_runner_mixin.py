import logging
import os
from collections import deque
from typing import Optional

from PySide6.QtCore import QThread

try:
    from shiboken6 import isValid as _qt_is_valid
except Exception:
    _qt_is_valid = None

from ..control_center_parts.control_center_runtime import TaskState, WindowTaskRunner

logger = logging.getLogger(__name__)


class ControlCenterRunnerMixin:
    _PAUSE_BLOCKED_STATE_VALUES = {"正在停止", "已中断", "已完成", "执行失败"}

    @staticmethod
    def _is_qt_runner_valid(runner) -> bool:
        if runner is None:
            return False
        if _qt_is_valid is None:
            return True
        try:
            return bool(_qt_is_valid(runner))
        except Exception:
            return False

    def _safe_runner_window_id(self, runner) -> str:
        if not self._is_qt_runner_valid(runner):
            return ""
        try:
            return str(getattr(runner, "window_id", "") or "")
        except Exception:
            return ""

    def _safe_runner_thread_running(self, runner) -> bool:
        if not self._is_qt_runner_valid(runner):
            return False
        try:
            return bool(runner.isRunning())
        except Exception:
            return False

    def _count_running_runners(self, target_window_ids=None) -> int:
        running_count = 0
        target_filter = set(target_window_ids) if target_window_ids else None
        for runners in self.window_runners.values():
            if not isinstance(runners, list):
                runners = [runners]
            for runner in runners:
                try:
                    if target_filter is not None and runner.window_id not in target_filter:
                        continue
                    if runner and runner.is_running:
                        running_count += 1
                except Exception:
                    continue
        return running_count

    def _get_runner_state_value(self, runner) -> str:
        if not self._is_qt_runner_valid(runner):
            return ""
        try:
            current_state = runner.current_state
            if callable(current_state):
                current_state = current_state()
        except Exception:
            return ""
        return str(getattr(current_state, "value", current_state) or "")

    def _is_runner_pause_controllable(self, runner) -> bool:
        if runner is None:
            return False
        try:
            if not runner.is_running:
                return False
        except Exception:
            return False
        return self._get_runner_state_value(runner) not in self._PAUSE_BLOCKED_STATE_VALUES

    def _is_runner_paused(self, runner) -> bool:
        if not self._is_runner_pause_controllable(runner):
            return False
        try:
            executor = getattr(runner, "executor", None)
            return executor is not None and getattr(executor, "_paused", False)
        except Exception:
            return False

    def _count_unpaused_running_runners(self, target_window_ids=None) -> int:
        running_count = 0
        target_filter = set(target_window_ids) if target_window_ids else None
        for runners in self.window_runners.values():
            if not isinstance(runners, list):
                runners = [runners]
            for runner in runners:
                try:
                    if target_filter is not None and runner.window_id not in target_filter:
                        continue
                    if not self._is_runner_pause_controllable(runner):
                        continue
                    if self._is_runner_paused(runner):
                        continue
                    running_count += 1
                except Exception:
                    continue
        return running_count

    def _has_unpaused_running_runners(self, target_window_ids=None) -> bool:
        return self._count_unpaused_running_runners(target_window_ids=target_window_ids) > 0

    def _count_started_runner_threads(self) -> int:
        active_count = 0
        for runners in self.window_runners.values():
            if not isinstance(runners, list):
                runners = [runners]
            for runner in runners:
                try:
                    thread_running = bool(runner and runner.isRunning())
                except Exception:
                    thread_running = False
                try:
                    thread_pending_start = bool(
                        runner
                        and getattr(runner, "_thread_start_requested", False)
                        and not getattr(runner, "_task_completed_emitted", False)
                        and not getattr(runner, "_queued_for_start", False)
                    )
                    if thread_running or thread_pending_start:
                        active_count += 1
                except Exception:
                    continue
        return active_count

    def _get_runner_dispatch_limit(self) -> int:
        try:
            return max(1, int(WindowTaskRunner._get_execution_slot_limit()))
        except Exception:
            return 1

    def _enqueue_runner_start(self, runner: Optional[WindowTaskRunner]) -> bool:
        if runner is None:
            return False
        if getattr(runner, "_queued_for_start", False):
            return False
        if getattr(runner, "_thread_start_requested", False):
            return False
        if getattr(runner, "_task_completed_emitted", False):
            return False
        runner._queued_for_start = True
        self._runner_start_queue.append(runner)
        return True

    def _remove_runner_from_start_queue(self, runner: Optional[WindowTaskRunner]) -> bool:
        if runner is None:
            return False
        if not getattr(runner, "_queued_for_start", False):
            return False

        removed = False
        kept_queue = deque()
        while self._runner_start_queue:
            queued_runner = self._runner_start_queue.popleft()
            if queued_runner is runner:
                removed = True
                continue
            kept_queue.append(queued_runner)
        self._runner_start_queue = kept_queue
        runner._queued_for_start = False
        return removed

    def _dispatch_pending_runner_starts(self) -> int:
        if getattr(self, "_is_closing", False):
            return 0
        if self._runner_dispatch_suspended:
            return 0
        if self._runner_dispatch_in_progress:
            return 0

        started_count = 0
        dispatch_limit = self._get_runner_dispatch_limit()
        active_count = self._count_started_runner_threads()
        self._runner_dispatch_in_progress = True
        try:
            while active_count < dispatch_limit and self._runner_start_queue:
                runner = self._runner_start_queue.popleft()
                if runner is None:
                    continue

                runner._queued_for_start = False

                if getattr(runner, "_task_completed_emitted", False):
                    continue
                if getattr(runner, "_should_stop", False):
                    try:
                        runner.stop()
                    except Exception:
                        pass
                    continue

                try:
                    runner._thread_start_requested = True
                    runner.start()
                    try:
                        runner.setPriority(QThread.Priority.LowPriority)
                    except Exception as e:
                        logger.warning(f"设置线程优先级失败: {e}")
                    started_count += 1
                    active_count += 1
                    logger.info(
                        "中控调度启动runner: window_id=%s, workflow_index=%s, active=%s/%s",
                        runner.window_id,
                        runner.property("workflow_index"),
                        active_count,
                        dispatch_limit,
                    )
                except Exception as e:
                    runner._thread_start_requested = False
                    logger.error(f"调度启动runner失败: window_id={runner.window_id}, error={e}")
                    try:
                        runner._set_state(TaskState.FAILED, f"错误: {e}")
                        runner._emit_task_completed_once(False)
                    except Exception:
                        pass
        finally:
            self._runner_dispatch_in_progress = False

        if started_count > 0:
            self._refresh_multi_window_mode_env()
        return started_count

    def _refresh_multi_window_mode_env(self):
        has_pending = bool(self._start_all_in_progress)
        has_pending = has_pending or bool(self._pending_windows)
        has_pending = has_pending or bool(self._pending_valid_windows)
        has_pending = has_pending or bool(self._runner_start_queue)
        has_running = self._count_running_runners() > 0
        should_enable = bool(has_pending or has_running)
        if should_enable:
            os.environ["MULTI_WINDOW_MODE"] = "true"
            return
        os.environ.pop("MULTI_WINDOW_MODE", None)

    def _cancel_pending_start_windows(self, target_window_ids=None) -> int:
        target_filter = set(target_window_ids) if target_window_ids else None
        removed_count = 0

        def _should_remove(entry) -> bool:
            if target_filter is None:
                return True
            if not isinstance(entry, dict):
                return False
            window_id = self._resolve_window_id_by_row(entry.get("row", -1))
            return bool(window_id and window_id in target_filter)

        if isinstance(self._pending_windows, list):
            kept = []
            for item in self._pending_windows:
                if _should_remove(item):
                    removed_count += 1
                    continue
                kept.append(item)
            self._pending_windows = kept

        if isinstance(self._pending_valid_windows, list):
            kept_valid = []
            for item in self._pending_valid_windows:
                if _should_remove(item):
                    removed_count += 1
                    continue
                kept_valid.append(item)
            self._pending_valid_windows = kept_valid if kept_valid else None

        if target_filter is None:
            self._cancel_start_sequence = True
            self._ocr_check_timer_active = False

        if (not self._pending_windows) and (not self._pending_valid_windows):
            self._start_all_in_progress = False
            gate = getattr(self, "_batch_start_gate_event", None)
            if gate is not None:
                try:
                    gate.set()
                except Exception:
                    pass
                self._batch_start_gate_event = None
            if hasattr(self, "start_all_btn") and self.start_all_btn is not None:
                self.start_all_btn.setEnabled(True)
                self.start_all_btn.setText("全部开始")

        self._refresh_multi_window_mode_env()
        return removed_count

    def _is_any_runner_paused(self, target_window_ids=None) -> bool:
        target_filter = set(target_window_ids) if target_window_ids else None
        for runners in self.window_runners.values():
            if not isinstance(runners, list):
                runners = [runners]
            for runner in runners:
                try:
                    if target_filter is not None and runner.window_id not in target_filter:
                        continue
                    if self._is_runner_paused(runner):
                        return True
                except Exception:
                    continue
        return False

    def _sync_pause_all_button_text(self):
        if not hasattr(self, "pause_all_btn") or self.pause_all_btn is None:
            return
        selected_window_ids = self._get_selected_window_ids()
        target_window_ids = selected_window_ids if selected_window_ids else None
        scope_text = "选中" if selected_window_ids else "全部"
        if self._has_unpaused_running_runners(target_window_ids=target_window_ids):
            self.pause_all_btn.setText(f"暂停{scope_text}")
        elif self._is_any_runner_paused(target_window_ids=target_window_ids):
            self.pause_all_btn.setText(f"恢复{scope_text}")
        else:
            self.pause_all_btn.setText(f"暂停{scope_text}")

    def _window_has_running_runner(self, window_id: str) -> bool:
        runners = self.window_runners.get(str(window_id))
        if not runners:
            return False
        if not isinstance(runners, list):
            runners = [runners]
        for runner in runners:
            try:
                if self._is_runner_pause_controllable(runner):
                    return True
            except Exception:
                continue
        return False

    def _window_has_paused_runner(self, window_id: str) -> bool:
        runners = self.window_runners.get(str(window_id))
        if not runners:
            return False
        if not isinstance(runners, list):
            runners = [runners]
        for runner in runners:
            try:
                if self._is_runner_paused(runner):
                    return True
            except Exception:
                continue
        return False

    def _pause_single_window_runners(self, window_id: str) -> bool:
        paused_any = False
        window_id = str(window_id)
        runners = self.window_runners.get(window_id)
        if not runners:
            return False
        if not isinstance(runners, list):
            runners = [runners]

        for runner in runners:
            try:
                if not self._is_runner_pause_controllable(runner):
                    continue
                if self._is_runner_paused(runner):
                    continue
                pause_runner = getattr(runner, "pause", None)
                if callable(pause_runner):
                    if pause_runner():
                        paused_any = True
                        logger.info(f"已暂停窗口 {window_id} 的工作流")
                    continue

                executor = getattr(runner, "executor", None)
                if executor is None or not hasattr(executor, "pause"):
                    continue
                executor.pause()
                paused_any = True
                logger.info(f"已暂停窗口 {window_id} 的工作流")
            except Exception as exc:
                logger.warning(f"暂停窗口 {window_id} 失败: {exc}")

        if paused_any:
            self._sync_pause_all_button_text()
        return paused_any

    def _resume_single_window_runners(self, window_id: str) -> bool:
        resumed_any = False
        window_id = str(window_id)
        runners = self.window_runners.get(window_id)
        if not runners:
            return False
        if not isinstance(runners, list):
            runners = [runners]

        for runner in runners:
            try:
                if not self._is_runner_paused(runner):
                    continue
                resume_runner = getattr(runner, "resume", None)
                if callable(resume_runner):
                    if resume_runner():
                        resumed_any = True
                        logger.info(f"已恢复窗口 {window_id} 的工作流")
                    continue

                executor = getattr(runner, "executor", None)
                if executor is None or not hasattr(executor, "resume"):
                    continue
                executor.resume()
                resumed_any = True
                logger.info(f"已恢复窗口 {window_id} 的工作流")
            except Exception as exc:
                logger.warning(f"恢复窗口 {window_id} 失败: {exc}")

        if resumed_any:
            self._sync_pause_all_button_text()
        return resumed_any

    def _pause_all_running_runners(self, reason: str = "", target_window_ids=None):
        paused_window_ids = set()
        target_filter = set(target_window_ids) if target_window_ids else None

        for window_id in list(self.window_runners.keys()):
            if target_filter is not None and window_id not in target_filter:
                continue
            if self._pause_single_window_runners(window_id):
                paused_window_ids.add(window_id)

        if paused_window_ids and reason:
            self.log_message(f"{reason}：已暂停 {len(paused_window_ids)} 个窗口")
        return paused_window_ids

    def _resume_all_paused_runners(self, reason: str = "", target_window_ids=None):
        resumed_window_ids = set()
        target_filter = set(target_window_ids) if target_window_ids else None

        for window_id in list(self.window_runners.keys()):
            if target_filter is not None and window_id not in target_filter:
                continue
            if self._resume_single_window_runners(window_id):
                resumed_window_ids.add(window_id)

        if resumed_window_ids and reason:
            self.log_message(f"{reason}：已恢复 {len(resumed_window_ids)} 个窗口")
        return resumed_window_ids
