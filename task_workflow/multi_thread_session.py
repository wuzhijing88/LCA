"""多起点并发执行会话（线程级调度器）。"""

import gc
import logging
import os
import threading
from typing import Any, Dict, List, Optional, Set, Tuple

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QThread, Qt, Signal
from shiboken6 import delete as delete_qt_object

from utils.window.hwnd_utils import as_hwnd

from task_workflow.card_display import find_card_by_id, format_step_detail
from task_workflow.executor import WorkflowExecutor
from task_workflow.thread_start import is_thread_start_task_type, validate_thread_target
from task_workflow.workflow_identity import (
    normalize_workflow_filepath,
    normalize_workflow_id,
)
from task_workflow.workflow_context import (
    clear_workflow_context,
)

logger = logging.getLogger(__name__)


class WorkflowMultiThreadSession(QObject):
    """将一个工作流按多个起点拆分为并发线程执行。"""

    execution_started = Signal()
    execution_finished = Signal(bool, str)  # success, message
    card_executing = Signal(int)
    card_finished = Signal(int, bool)
    error_occurred = Signal(int, str)
    path_updated = Signal(int, str, str)
    param_updated = Signal(int, str, object)
    path_resolution_failed = Signal(int, str)
    step_details = Signal(str)
    show_warning = Signal(str, str)
    step_log = Signal(str, str, bool)
    overlay_update_requested = Signal(object)

    def __init__(
        self,
        cards_data: Dict[str, Any],
        connections_data: List[Dict[str, Any]],
        task_modules: Dict[str, Any],
        start_card_ids: List[int],
        thread_labels: Optional[Dict[int, str]] = None,
        target_window_title: str = None,
        execution_mode: str = "foreground",
        images_dir: str = None,
        target_hwnd: int = None,
        workflow_id: Optional[str] = None,
        workflow_filepath: Optional[str] = None,
        thread_window_configs: Optional[Dict[int, Dict[str, Any]]] = None,
        get_image_data=None,
        parent=None,
        sounds_dir: str = None,
        dicts_dir: str = None,
        yolo_dir: str = None,
        replays_dir: str = None,
        plugins_dir: str = None,
        external_stop_checker=None,
        external_pause_checker=None,
    ):
        super().__init__(parent)
        if not isinstance(cards_data, dict) or not cards_data:
            raise ValueError("cards_data 必须是非空字典")
        if not isinstance(connections_data, list):
            raise TypeError("connections_data 必须是列表")
        if not isinstance(task_modules, dict):
            raise TypeError("task_modules 必须是字典")
        if not isinstance(start_card_ids, list) or len(start_card_ids) < 2:
            raise ValueError("多线程会话至少需要两个线程起点")
        if thread_labels is not None and not isinstance(thread_labels, dict):
            raise TypeError("thread_labels 必须是字典")
        for checker in (external_stop_checker, external_pause_checker):
            if checker is not None and not callable(checker):
                raise TypeError("外部线程控制检查必须可调用")
        self._external_stop_checker = external_stop_checker
        self._external_pause_checker = external_pause_checker
        self._external_paused = False

        self.cards_data = cards_data
        self.connections_data = connections_data
        self.task_modules = task_modules
        self.target_window_title = target_window_title
        if not isinstance(execution_mode, str) or not execution_mode.strip():
            raise ValueError("执行模式必须是非空字符串")
        self.execution_mode = execution_mode
        self.images_dir = images_dir
        self.sounds_dir = sounds_dir
        self.dicts_dir = dicts_dir
        self.yolo_dir = yolo_dir
        self.replays_dir = replays_dir
        self.plugins_dir = plugins_dir
        if target_hwnd is not None and (isinstance(target_hwnd, bool) or not isinstance(target_hwnd, int)):
            raise TypeError("目标窗口句柄必须是整数")
        self.target_hwnd = as_hwnd(target_hwnd) if target_hwnd is not None else None
        self.target_bind_id = None
        from task_workflow.resource_context import bind_resource_dirs

        bind_resource_dirs(
            {
                "images_dir": self.images_dir,
                "sounds_dir": self.sounds_dir,
                "dicts_dir": self.dicts_dir,
                "yolo_dir": self.yolo_dir,
                "replays_dir": self.replays_dir,
                "plugins_dir": self.plugins_dir,
            }
        )
        self.workflow_id = self._normalize_workflow_id(workflow_id)
        self.workflow_filepath = self._normalize_workflow_filepath(workflow_filepath)
        self.thread_window_configs = self._normalize_thread_window_configs(thread_window_configs)
        self.get_image_data = get_image_data
        self.test_mode = None
        self.bound_windows = []
        self.custom_width = 0
        self.custom_height = 0

        self._lock = threading.RLock()
        self._done_event = threading.Event()
        self._is_running = False
        self._stop_requested = False
        self._force_stop = False
        self._finished_threads: List[Tuple[int, int, QThread]] = []
        self._persistent_counters: Dict[str, Any] = {}
        self._initial_start_gate: Optional[threading.Event] = None
        self._initial_start_waiting_threads: Set[int] = set()
        self._applied_screenshot_worker_limit: Optional[int] = None
        self._memory_diag_enabled = self._read_bool_env("LCA_MT_MEM_DIAG", False)

        # 线程表：key 为线程ID（这里使用起点卡片ID）
        self._entries: Dict[int, Dict[str, Any]] = {}
        start_ids: List[int] = []
        seen_start_ids: Set[int] = set()
        for index, raw_id in enumerate(start_card_ids):
            if isinstance(raw_id, bool) or not isinstance(raw_id, int):
                raise TypeError(f"线程起点ID必须是整数: index={index}, value={raw_id!r}")
            if raw_id in seen_start_ids:
                raise ValueError(f"线程起点ID重复: {raw_id}")
            if raw_id not in self.cards_data:
                raise ValueError(f"线程起点卡片不存在: {raw_id}")
            if raw_id < 0 or not is_thread_start_task_type(self.cards_data[raw_id].get("task_type")):
                raise ValueError(f"卡片不是有效线程起点: {raw_id}")
            seen_start_ids.add(raw_id)
            start_ids.append(raw_id)

        cpu_thread_limit = self._detect_cpu_logical_threads()
        if len(start_ids) > cpu_thread_limit:
            raise ValueError(
                f"线程起点数量({len(start_ids)})超过CPU逻辑线程上限({cpu_thread_limit})"
            )

        labels = dict(thread_labels or {})
        unknown_label_ids = set(labels) - seen_start_ids
        if unknown_label_ids:
            raise ValueError(f"线程标签引用了未知起点: {sorted(unknown_label_ids)}")
        unknown_window_config_ids = set(self.thread_window_configs) - seen_start_ids
        if unknown_window_config_ids:
            raise ValueError(
                f"线程窗口配置引用了未知起点: {sorted(unknown_window_config_ids)}"
            )

        for idx, start_id in enumerate(start_ids, 1):
            label = str((thread_labels or {}).get(start_id) or f"线程起点{idx}")
            thread_window_config = self.thread_window_configs.get(start_id)
            if thread_window_config is None:
                entry_target_hwnd = self.target_hwnd
                entry_target_window_title = self.target_window_title
                entry_window_source_card_id = None
            else:
                entry_target_hwnd = thread_window_config["target_hwnd"]
                entry_target_window_title = thread_window_config.get(
                    "target_window_title",
                    "",
                )
                entry_window_source_card_id = thread_window_config.get("source_card_id")
            self._entries[start_id] = {
                "thread_id": start_id,
                "label": label,
                "default_start_card_id": start_id,
                "current_start_card_id": start_id,
                "launch_seq": 0,
                "executor": None,
                "thread": None,
                "launch_token": 0,
                "status": "idle",  # idle/starting/running/completed/failed/stopped
                "last_success": False,
                "last_message": "",
                "pending_launch": None,
                "pause_event": threading.Event(),
                "bind_id": thread_window_config["bind_id"] if thread_window_config is not None else None,
                "target_hwnd": entry_target_hwnd,
                "target_window_title": entry_target_window_title,
                "window_source_card_id": entry_window_source_card_id,
            }

        logger.info(
            "WorkflowMultiThreadSession 初始化完成: threads=%d, workflow_id=%s",
            len(self._entries),
            self.workflow_id,
        )

    @staticmethod
    def _normalize_workflow_id(workflow_id: Optional[str]) -> str:
        return normalize_workflow_id(workflow_id)

    @staticmethod
    def _normalize_workflow_filepath(workflow_filepath: Optional[str]) -> Optional[str]:
        return normalize_workflow_filepath(workflow_filepath)

    @staticmethod
    def _detect_cpu_logical_threads() -> int:
        cpu_count = os.cpu_count()
        if not isinstance(cpu_count, int) or isinstance(cpu_count, bool) or cpu_count <= 0:
            raise RuntimeError(f"无法确定CPU逻辑线程数: {cpu_count!r}")
        return cpu_count

    @staticmethod
    def _read_bool_env(name: str, default: bool = False) -> bool:
        raw = os.getenv(name)
        if raw is None:
            return default
        normalized = str(raw).strip().lower()
        if normalized in {"1", "true", "yes", "on", "y"}:
            return True
        if normalized in {"0", "false", "no", "off", "n"}:
            return False
        raise ValueError(f"环境变量 {name} 必须是布尔值: {raw!r}")

    @staticmethod
    def _read_int_env(name: str, default: int, min_value: int, max_value: int) -> int:
        raw = os.getenv(name)
        if raw is None:
            return default
        try:
            value = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"环境变量 {name} 必须是整数: {raw!r}") from exc
        if value < min_value or value > max_value:
            raise ValueError(
                f"环境变量 {name} 超出范围: {value}, 要求 {min_value}..{max_value}"
            )
        return value

    @staticmethod
    def _normalize_thread_window_configs(raw_configs: Optional[Dict[int, Dict[str, Any]]]) -> Dict[int, Dict[str, Any]]:
        if raw_configs is None:
            return {}
        if not isinstance(raw_configs, dict):
            raise TypeError("thread_window_configs 必须是字典")

        normalized: Dict[int, Dict[str, Any]] = {}
        for raw_start_id, raw_config in raw_configs.items():
            if isinstance(raw_start_id, bool) or not isinstance(raw_start_id, int):
                raise TypeError(f"线程窗口配置起点ID必须是整数: {raw_start_id!r}")
            if not isinstance(raw_config, dict):
                raise TypeError(f"线程窗口配置必须是字典: start_card_id={raw_start_id}")

            config = dict(raw_config)
            unknown_fields = set(config) - {"bind_id", "target_hwnd", "target_window_title", "source_card_id"}
            if unknown_fields:
                raise ValueError(f"线程窗口配置包含未知字段: {sorted(unknown_fields)}")
            if not isinstance(config.get("bind_id"), str) or not config["bind_id"].strip():
                raise ValueError(f"线程窗口配置缺少有效绑定标识: {raw_start_id}")
            if not isinstance(config.get("target_window_title", ""), str):
                raise TypeError("线程窗口标题必须是字符串")
            raw_target_hwnd = config.get("target_hwnd")
            if isinstance(raw_target_hwnd, bool) or not isinstance(raw_target_hwnd, int):
                raise ValueError(
                    f"线程窗口配置句柄无效: start_card_id={raw_start_id}, hwnd={raw_target_hwnd!r}"
                )
            target_hwnd = as_hwnd(raw_target_hwnd)
            if target_hwnd == 0:
                raise ValueError(
                    f"线程窗口配置句柄无效: start_card_id={raw_start_id}, hwnd={config.get('target_hwnd')!r}"
                )
            config["target_hwnd"] = target_hwnd
            normalized[raw_start_id] = config
        return normalized

    def _resolve_runtime_screenshot_limit(self) -> int:
        thread_count = max(1, len(self._entries))
        hard_limit = self._detect_cpu_logical_threads()
        configured_limit = self._read_int_env(
            "LCA_MT_SCREENSHOT_LIMIT",
            min(3, hard_limit),
            1,
            hard_limit,
        )
        return max(1, min(thread_count, hard_limit, configured_limit))

    def _apply_screenshot_worker_limit_for_run(self) -> None:
        target_limit = self._resolve_runtime_screenshot_limit()
        from services.screenshot_pool import set_screenshot_worker_limit

        applied_limit = int(set_screenshot_worker_limit(target_limit))
        if applied_limit != target_limit:
            raise RuntimeError(
                f"截图并发上限应用不一致: requested={target_limit}, applied={applied_limit}"
            )
        self._applied_screenshot_worker_limit = applied_limit
        logger.info(
            "多线程会话截图并发上限(同进程模式): limit=%d, threads=%d",
            applied_limit,
            len(self._entries),
        )

    def _restore_screenshot_worker_limit_after_run(self) -> None:
        from services.screenshot_pool import set_screenshot_worker_limit

        set_screenshot_worker_limit(None)
        self._applied_screenshot_worker_limit = None

    def _collect_memory_diag_snapshot(self, force_gc: bool = False) -> Dict[str, Any]:
        snapshot: Dict[str, Any] = {}
        snapshot["gc_before"] = tuple(gc.get_count())
        if force_gc:
            try:
                snapshot["gc_collected"] = int(gc.collect())
            except Exception as exc:
                snapshot["gc_error"] = str(exc)
        snapshot["gc_after"] = tuple(gc.get_count())

        try:
            objs = gc.get_objects()
            snapshot["workflow_executor_objects"] = sum(
                1 for obj in objs if isinstance(obj, WorkflowExecutor)
            )
            snapshot["qthread_objects"] = sum(1 for obj in objs if isinstance(obj, QThread))
        except Exception as exc:
            snapshot["gc_objects_error"] = str(exc)

        try:
            from task_workflow.workflow_context import get_workflow_context_diagnostics

            context_diag = get_workflow_context_diagnostics()
            snapshot["context_count"] = int(context_diag.get("context_count", 0))
            snapshot["context_keys_preview"] = list(context_diag.get("context_keys", []))[:8]
            snapshot["thread_context_ref_count"] = int(
                context_diag.get("thread_context_ref_count", 0)
            )
        except Exception as exc:
            snapshot["context_diag_error"] = str(exc)

        try:
            from utils.match.template_preloader import get_global_preloader

            template_stats = get_global_preloader().get_stats()
            total_bytes = int(template_stats.get("total_size_bytes", 0) or 0)
            snapshot["template_cached_count"] = int(template_stats.get("cached_count", 0))
            snapshot["template_cached_mb"] = round(total_bytes / 1024 / 1024, 4)
        except Exception as exc:
            snapshot["template_diag_error"] = str(exc)

        return snapshot

    def _log_memory_diag(self, stage: str, force_gc: bool = False) -> None:
        if not self._memory_diag_enabled:
            return
        try:
            diag = self._collect_memory_diag_snapshot(force_gc=force_gc)
            logger.info("[MT内存诊断] stage=%s, data=%s", stage, diag)
        except Exception as exc:
            logger.warning("[MT内存诊断] 输出失败(stage=%s): %s", stage, exc)

    def run(self):
        """启动会话（被主窗口放入线程调用）。"""
        from task_workflow.resource_context import bind_resource_dirs

        bind_resource_dirs(
            {
                "images_dir": self.images_dir,
                "sounds_dir": self.sounds_dir,
                "dicts_dir": getattr(self, "dicts_dir", "") or "",
                "yolo_dir": getattr(self, "yolo_dir", "") or "",
                "replays_dir": getattr(self, "replays_dir", "") or "",
                "plugins_dir": getattr(self, "plugins_dir", "") or "",
            }
        )
        with self._lock:
            if self._is_running:
                raise RuntimeError("多线程会话已在运行中")
            self._is_running = True
            self._done_event.clear()
            self._initial_start_gate = threading.Event() if self._entries and not self._stop_requested else None
            self._initial_start_waiting_threads = set(self._entries.keys()) if self._initial_start_gate else set()

            # 初始启动：每个线程都按默认起点启动
            for entry in self._entries.values():
                entry["pending_launch"] = None if self._stop_requested else {
                    "start_card_id": entry["default_start_card_id"],
                    "hold_start": self._initial_start_gate is not None,
                }
                entry["status"] = "stopped" if self._stop_requested else "idle"
                entry["last_message"] = ""
                entry["last_success"] = False

        success = False
        message = "会话异常终止"
        screenshot_limit_applied = False
        try:
            self._apply_screenshot_worker_limit_for_run()
            screenshot_limit_applied = True
            self._log_memory_diag("session_start", force_gc=False)
            self.execution_started.emit()
            self.step_details.emit(f"多线程执行开始，共 {len(self._entries)} 个线程")
            self._poll_external_control()
            self._process_pending_launches()
            with self._lock:
                self._check_done_locked()

            while not self._done_event.wait(0.01):
                self._poll_external_control()
                self._reap_finished_threads()
                self._process_pending_launches()
                with self._lock:
                    if self._stop_requested:
                        self._request_stop_all_locked(force=self._force_stop)
                    self._check_done_locked()

            with self._lock:
                success, message = self._build_final_result_locked()
        except Exception as e:
            logger.error("WorkflowMultiThreadSession run() exception: %s", e, exc_info=True)
            success = False
            message = f"会话执行异常: {e}"
        finally:
            with self._lock:
                self._release_initial_start_gate_locked()
                for entry in self._entries.values():
                    entry["pending_launch"] = None
                remaining_threads = [entry["thread"] for entry in self._entries.values() if entry["thread"] is not None]
            if remaining_threads:
                try:
                    self.request_stop(force=True)
                except Exception as exc:
                    success = False
                    message = f"停止剩余线程失败: {exc}"
                    logger.error(message, exc_info=True)
                for thread in remaining_threads:
                    thread.wait()
            self._reap_finished_threads()
            try:
                from app_core.runtime.runtime_image_cleanup import cleanup_runtime_image_memory

                cleanup_runtime_image_memory(
                    reason="multi_thread_session_finish",
                    cleanup_screenshot_engines=False,
                    cleanup_template_cache=False,
                )
            except Exception as exc:
                success = False
                message = f"多线程共享图像资源释放失败: {exc}"
                logger.error(message, exc_info=True)
            try:
                from utils.input.foreground_input_manager import get_foreground_input_manager

                fg_manager = get_foreground_input_manager()
                if fg_manager is not None:
                    fg_manager.release_all_inputs()
            except Exception as exc:
                success = False
                message = f"多线程会话结束时统一释放输入失败: {exc}"
                logger.error(message, exc_info=True)
            if screenshot_limit_applied:
                try:
                    self._restore_screenshot_worker_limit_after_run()
                except Exception as exc:
                    success = False
                    message = f"恢复截图并发上限失败: {exc}"
                    logger.error(message, exc_info=True)
            self._log_memory_diag("session_end", force_gc=True)
            with self._lock:
                self._is_running = False

        self.execution_finished.emit(success, message)

    def _poll_external_control(self):
        if self._external_stop_checker is not None:
            stopped = self._external_stop_checker()
            if not isinstance(stopped, bool):
                raise TypeError("外部停止检查必须返回布尔值")
            if stopped:
                self.request_stop()
        if self._external_pause_checker is not None:
            paused = self._external_pause_checker()
            if not isinstance(paused, bool):
                raise TypeError("外部暂停检查必须返回布尔值")
            self._external_paused = paused

    def is_running(self) -> bool:
        with self._lock:
            return self._is_running

    def should_defer_input_release(self, thread_id: Optional[int] = None) -> bool:
        """共享输入由会话在所有子线程退出后统一释放。"""
        with self._lock:
            if not self._is_running:
                return False
            if thread_id is not None and (isinstance(thread_id, bool) or not isinstance(thread_id, int)):
                raise ValueError("线程编号必须是整数")
            return True

    def request_stop(self, force: bool = False):
        with self._lock:
            self._stop_requested = True
            if force:
                self._force_stop = True
            for entry in self._entries.values():
                entry["pause_event"].clear()
                entry["pending_launch"] = None
                if self._is_entry_running_locked(entry):
                    if str(entry.get("status") or "") not in ("completed", "failed", "stopped"):
                        entry["status"] = "stopping"
                elif str(entry.get("status") or "") in ("starting", "running"):
                    entry["status"] = "stopped"
            self._release_initial_start_gate_locked()
            self._request_stop_all_locked(force=self._force_stop)
            self._check_done_locked()

    def pause(self):
        errors = []
        with self._lock:
            for entry in self._entries.values():
                entry["pause_event"].set()
                executor = entry.get("executor")
                if executor and self._is_entry_running_locked(entry):
                    try:
                        executor.pause()
                    except Exception as e:
                        errors.append(str(e))
        if errors:
            raise RuntimeError("暂停线程失败: " + "; ".join(errors))

    def resume(self):
        errors = []
        with self._lock:
            for entry in self._entries.values():
                entry["pause_event"].clear()
                executor = entry.get("executor")
                if executor and self._is_entry_running_locked(entry):
                    try:
                        executor.resume()
                    except Exception as e:
                        errors.append(str(e))
        if errors:
            raise RuntimeError("恢复线程失败: " + "; ".join(errors))

    def control_thread(
        self,
        action: str,
        target_thread: Any = "当前线程",
        start_card_id: Optional[int] = None,
        source_executor: Optional[WorkflowExecutor] = None,
    ) -> Tuple[bool, str]:
        """供“线程控制卡”调用。"""
        action_text = action
        action_key = {
            "启动/重启线程": "restart",
            "暂停线程": "pause",
            "恢复线程": "resume",
            "停止线程": "stop",
            "从指定卡片启动线程": "start_from_card",
        }.get(action_text) if isinstance(action_text, str) else None
        if not action_key:
            return False, f"不支持的线程动作: {action_text}"

        with self._lock:
            if self._stop_requested and action_key != "stop":
                return False, "会话正在停止，不能再启动、暂停或恢复线程"
            if not self._is_running:
                return False, "多线程会话未运行"
            if self._done_event.is_set():
                return False, "多线程会话已经结束"
            target_ids, error = self._resolve_target_thread_ids_locked(target_thread, source_executor)
            if error:
                return False, error
            if not target_ids:
                return False, "未匹配到目标线程"
            if action_key == "start_from_card":
                if isinstance(start_card_id, bool) or not isinstance(start_card_id, int) or start_card_id < 0:
                    return False, "请提供有效的指定卡片编号"
                if start_card_id not in self.cards_data:
                    return False, f"起始卡片不存在: {start_card_id}"
                adjacency = {}
                for connection in self.connections_data:
                    adjacency.setdefault(connection["start_card_id"], set()).add(connection["end_card_id"])
                for thread_id in target_ids:
                    visited = set()
                    pending = [self._entries[thread_id]["default_start_card_id"]]
                    while pending:
                        current_id = pending.pop()
                        if current_id in visited:
                            continue
                        visited.add(current_id)
                        pending.extend(adjacency.get(current_id, ()))
                    if start_card_id not in visited:
                        return False, f"指定卡片 {start_card_id} 不是线程 {thread_id} 的可达卡片"
            if action_key in {"pause", "resume"}:
                inactive = [thread_id for thread_id in target_ids if not self._is_entry_running_locked(self._entries[thread_id]) and not self._entries[thread_id]["pending_launch"]]
                if inactive:
                    return False, f"目标线程未运行: {inactive}"
            if action_key == "stop" and set(target_ids) == set(self._entries):
                try:
                    self.request_stop(force=True)
                except Exception as exc:
                    return False, f"停止全部线程失败: {exc}"
                return True, "已请求停止全部线程"

            results = []
            for thread_id in target_ids:
                ok, msg = self._apply_action_to_entry_locked(
                    thread_id=thread_id,
                    action_key=action_key,
                    start_card_id=start_card_id,
                )
                results.append((ok, msg))

            success = all(ok for ok, _ in results) and bool(results)
            merged = "; ".join(msg for _, msg in results if msg)
            if not merged:
                merged = "命令已处理"
            return success, merged

    def _resolve_target_thread_ids_locked(
        self,
        target_thread: Any,
        source_executor: Optional[WorkflowExecutor],
    ) -> Tuple[List[int], Optional[str]]:
        try:
            validate_thread_target(target_thread)
        except ValueError as exc:
            return [], str(exc)
        if target_thread == "当前线程":
            current_thread_id = getattr(source_executor, "thread_id", None)
            if current_thread_id in self._entries and self._entries[current_thread_id]["executor"] is source_executor:
                return [current_thread_id], None
            return [], "无法确定当前线程"

        if target_thread == "全部线程":
            return list(self._entries.keys()), None
        targets = target_thread if isinstance(target_thread, list) else [target_thread]
        target_ids = [int(target) for target in targets]
        missing = [thread_id for thread_id in target_ids if thread_id not in self._entries]
        if missing:
            return [], f"找不到目标线程: {missing}"
        return target_ids, None

    def _apply_action_to_entry_locked(
        self,
        thread_id: int,
        action_key: str,
        start_card_id: Optional[int],
    ) -> Tuple[bool, str]:
        entry = self._entries.get(thread_id)
        if not entry:
            return False, f"线程不存在: {thread_id}"
        label = entry.get("label", f"线程{thread_id}")

        if action_key == "pause":
            entry["pause_event"].set()
            executor = entry.get("executor")
            if executor is None and entry["pending_launch"]:
                return True, f"[{label}] 启动后保持暂停"
            if not executor or not self._is_entry_running_locked(entry):
                return False, f"[{label}] 未运行，无法暂停"
            try:
                executor.pause()
                return True, f"[{label}] 已暂停"
            except Exception as e:
                return False, f"[{label}] 暂停失败: {e}"

        if action_key == "resume":
            entry["pause_event"].clear()
            executor = entry.get("executor")
            if executor is None and entry["pending_launch"]:
                return True, f"[{label}] 已取消启动暂停"
            if not executor or not self._is_entry_running_locked(entry):
                return False, f"[{label}] 未运行，无法恢复"
            try:
                executor.resume()
                return True, f"[{label}] 已恢复"
            except Exception as e:
                return False, f"[{label}] 恢复失败: {e}"

        if action_key == "stop":
            entry["pause_event"].clear()
            entry["pending_launch"] = None
            self._initial_start_waiting_threads.discard(thread_id)
            if not self._initial_start_waiting_threads:
                self._release_initial_start_gate_locked()
            executor = entry.get("executor")
            if not executor or not self._is_entry_running_locked(entry):
                entry["status"] = "stopped"
                self._check_done_locked()
                return True, f"[{label}] 已停止"
            try:
                executor.request_stop(force=True)
                entry["status"] = "stopping"
                return True, f"[{label}] 停止中"
            except Exception as e:
                return False, f"[{label}] 停止失败: {e}"

        # 启动/重启/从指定卡片开始
        requested_start = start_card_id
        if action_key == "restart":
            requested_start = entry["default_start_card_id"]
        elif action_key == "start_from_card":
            if requested_start is None:
                return False, f"[{label}] 缺少起始卡片ID"

        if requested_start is None:
            return False, f"[{label}] 无法确定起始卡片ID"
        if requested_start not in self.cards_data:
            return False, f"[{label}] 起始卡片不存在: {requested_start}"
        entry["pause_event"].clear()

        if self._is_entry_running_locked(entry):
            entry["pending_launch"] = {"start_card_id": requested_start}
            executor = entry.get("executor")
            if executor is not None:
                try:
                    executor.request_stop(force=True)
                except Exception as e:
                    entry["pending_launch"] = None
                    return False, f"[{label}] 重启请求失败: {e}"
            return True, f"[{label}] 重启中，将从卡片 {requested_start} 开始"

        entry["pending_launch"] = {
            "start_card_id": requested_start,
            "hold_start": self._initial_start_gate is not None,
        }
        return True, f"[{label}] 已安排启动（卡片 {requested_start}）"

    def _make_thread_workflow_id_locked(self, entry: Dict[str, Any], start_card_id: int) -> str:
        entry["launch_seq"] = int(entry.get("launch_seq", 0) or 0) + 1
        thread_id = entry.get("thread_id")
        # 内存优化：使用线程级稳定 workflow_id，避免每次重启产生新上下文实例。
        return f"{self.workflow_id}#thread-{thread_id}"

    def _clear_executor_workflow_context(self, workflow_id: Optional[str]) -> None:
        clear_workflow_context(workflow_id)

    def _launch_entry_locked(self, entry: Dict[str, Any], start_card_id: int, hold_start: bool = False) -> Tuple[bool, str]:
        if self._stop_requested:
            return False, "会话正在停止"
        if self._is_entry_running_locked(entry):
            return False, "线程仍在运行中"

        if start_card_id not in self.cards_data:
            return False, f"起始卡片不存在: {start_card_id}"

        # 内存优化：多线程执行器仅做只读访问，不再为每个线程 deep copy 整个工作流。
        cards_data = self.cards_data
        connections_data = self.connections_data
        from task_workflow.thread_window_binding import require_window_dimension

        width = require_window_dimension(self.custom_width, "窗口宽度")
        height = require_window_dimension(self.custom_height, "窗口高度")
        if not isinstance(self.bound_windows, list):
            raise TypeError("绑定窗口必须是列表")

        workflow_id = self._make_thread_workflow_id_locked(entry, start_card_id)
        launch_token = int(entry.get("launch_seq", 0) or 0)
        entry_target_window_title = entry["target_window_title"]
        entry_target_hwnd = entry["target_hwnd"]
        self._clear_executor_workflow_context(workflow_id)
        executor = WorkflowExecutor(
            cards_data=cards_data,
            connections_data=connections_data,
            task_modules=self.task_modules,
            target_window_title=entry_target_window_title,
            execution_mode=self.execution_mode,
            start_card_id=start_card_id,
            images_dir=self.images_dir,
            target_hwnd=entry_target_hwnd,
            test_mode=None,
            workflow_id=workflow_id,
            workflow_filepath=self.workflow_filepath,
            get_image_data=self.get_image_data,
            external_pause_checker=lambda event=entry["pause_event"]: event.is_set() or self._external_paused,
            cleanup_runtime_image_on_finish=False,
            sounds_dir=self.sounds_dir,
            dicts_dir=getattr(self, "dicts_dir", None),
            yolo_dir=getattr(self, "yolo_dir", None),
            replays_dir=getattr(self, "replays_dir", None),
            plugins_dir=getattr(self, "plugins_dir", None),
        )
        executor.bound_windows = list(self.bound_windows)
        executor.custom_width = width
        executor.custom_height = height
        executor.target_bind_id = entry["bind_id"] if entry["bind_id"] is not None else self.target_bind_id

        thread = QThread()
        thread_id = entry["thread_id"]
        label = entry["label"]

        # 给卡片任务使用（线程控制卡可通过 executor.thread_session 找回会话）
        executor.thread_session = self
        executor.thread_id = thread_id
        executor.thread_label = label
        executor._session_launch_token = launch_token

        executor.moveToThread(thread)
        thread.finished.connect(
            lambda tid=thread_id, token=launch_token: self._on_child_thread_finished(tid, token),
            Qt.ConnectionType.DirectConnection,
        )
        thread.finished.connect(executor.deleteLater, Qt.ConnectionType.DirectConnection)

        if hold_start and self._initial_start_gate is not None:
            executor._start_gate_event = self._initial_start_gate
            thread.started.connect(
                lambda tid=thread_id: self._on_initial_hold_thread_started(tid),
                Qt.ConnectionType.DirectConnection,
            )
        def run_child():
            try:
                executor.run()
            except Exception as exc:
                logger.error("线程执行异常: %s", exc, exc_info=True)
                self._on_child_execution_finished(thread_id, launch_token, False, f"线程执行异常: {exc}")
            finally:
                thread.quit()

        thread.started.connect(run_child, Qt.ConnectionType.DirectConnection)

        # 关键：使用 DirectConnection，避免依赖会话线程事件循环
        executor.execution_started.connect(
            lambda tid=thread_id, lb=label: self._on_child_execution_started(tid, lb),
            Qt.ConnectionType.DirectConnection,
        )
        executor.card_executing.connect(
            lambda card_id, tid=thread_id: self._on_child_card_executing(tid, card_id),
            Qt.ConnectionType.DirectConnection,
        )
        executor.card_finished.connect(
            lambda card_id, success, tid=thread_id: self._on_child_card_finished(tid, card_id, success),
            Qt.ConnectionType.DirectConnection,
        )
        executor.error_occurred.connect(
            lambda card_id, message, tid=thread_id: self._on_child_error(tid, card_id, message),
            Qt.ConnectionType.DirectConnection,
        )
        executor.path_updated.connect(
            lambda card_id, name, value, tid=thread_id: self._on_child_path_updated(tid, card_id, name, value),
            Qt.ConnectionType.DirectConnection,
        )
        executor.param_updated.connect(
            lambda card_id, name, value, tid=thread_id: self._on_child_param_updated(tid, card_id, name, value),
            Qt.ConnectionType.DirectConnection,
        )
        executor.path_resolution_failed.connect(
            lambda card_id, path, tid=thread_id: self._on_child_path_failed(tid, card_id, path),
            Qt.ConnectionType.DirectConnection,
        )
        executor.step_details.connect(
            lambda message, tid=thread_id: self._on_child_step_details(tid, message),
            Qt.ConnectionType.DirectConnection,
        )
        executor.step_log.connect(
            lambda card_type, message, success, tid=thread_id: self._on_child_step_log(
                tid, card_type, message, success
            ),
            Qt.ConnectionType.DirectConnection,
        )
        executor.show_warning.connect(
            lambda title, message, tid=thread_id: self._on_child_warning(tid, title, message),
            Qt.ConnectionType.DirectConnection,
        )
        executor.overlay_update_requested.connect(
            lambda payload, tid=thread_id: self._on_child_overlay_update_requested(tid, payload),
            Qt.ConnectionType.DirectConnection,
        )

        executor.execution_finished.connect(
            lambda success, message, tid=thread_id, token=launch_token: self._on_child_execution_finished(
                tid, token, success, message
            ),
            Qt.ConnectionType.DirectConnection,
        )

        entry["executor"] = executor
        entry["thread"] = thread
        entry["launch_token"] = launch_token
        entry["status"] = "starting"
        entry["pending_launch"] = None
        entry["current_start_card_id"] = start_card_id
        entry["result_received"] = False

        try:
            thread.start()
        except Exception:
            if not thread.isRunning():
                self._disconnect_executor_signals(executor)
                thread.started.disconnect()
                thread.finished.disconnect()
                executor.thread_session = None
                delete_qt_object(executor)
                thread.deleteLater()
                QCoreApplication.sendPostedEvents(thread, QEvent.Type.DeferredDelete)
                entry["executor"] = None
                entry["thread"] = None
                entry["pending_launch"] = None
                entry["status"] = "failed"
                self._clear_executor_workflow_context(workflow_id)
            raise
        return True, "ok"

    def _is_entry_running_locked(self, entry: Dict[str, Any]) -> bool:
        return entry["thread"] is not None

    def _on_child_thread_finished(self, thread_id: int, launch_token: int):
        with self._lock:
            entry = self._entries.get(thread_id)
            if not entry:
                return
            if int(entry.get("launch_token", 0) or 0) != int(launch_token):
                return
            executor = entry["executor"]
            thread = entry["thread"]
            if thread is None or executor is None:
                return
            cleanup_errors = []
            try:
                self._disconnect_executor_signals(executor)
            except Exception as exc:
                cleanup_errors.append(str(exc))
            executor.thread_session = None
            executor.thread_id = None
            executor.thread_label = None
            try:
                self._clear_executor_workflow_context(executor.workflow_id)
            except Exception as exc:
                cleanup_errors.append(f"清理线程上下文失败: {exc}")
            if cleanup_errors or not entry["result_received"]:
                entry["status"] = "failed"
                entry["last_success"] = False
                entry["last_message"] = "; ".join(cleanup_errors) if cleanup_errors else "线程结束但未报告执行结果"
                logger.error("[%s] %s", entry["label"], entry["last_message"])
            entry["executor"] = None
            self._finished_threads.append((thread_id, launch_token, thread))
            self._check_done_locked()

    def _reap_finished_threads(self):
        with self._lock:
            finished_threads = self._finished_threads
            self._finished_threads = []
        for thread_id, launch_token, thread in finished_threads:
            thread.wait()
            thread.started.disconnect()
            thread.finished.disconnect()
            thread.deleteLater()
            QCoreApplication.sendPostedEvents(thread, QEvent.Type.DeferredDelete)
            with self._lock:
                entry = self._entries[thread_id]
                if entry["launch_token"] == launch_token and entry["thread"] is thread:
                    entry["thread"] = None
                self._check_done_locked()

    @staticmethod
    def _disconnect_executor_signals(executor_obj: WorkflowExecutor) -> None:
        signal_names = (
            "execution_started",
            "execution_finished",
            "card_executing",
            "card_finished",
            "error_occurred",
            "path_updated",
            "param_updated",
            "path_resolution_failed",
            "step_details",
            "step_log",
            "show_warning",
            "overlay_update_requested",
        )
        errors = []
        for signal_name in signal_names:
            try:
                getattr(executor_obj, signal_name).disconnect()
            except Exception as exc:
                errors.append(f"断开线程信号 {signal_name} 失败: {exc}")
        if errors:
            raise RuntimeError("; ".join(errors))

    def _request_stop_all_locked(self, force: bool):
        errors = []
        for entry in self._entries.values():
            entry["pending_launch"] = None
            executor = entry.get("executor")
            if not executor:
                continue
            try:
                if executor.run_context.is_stop_requested() and (not force or executor.run_context.is_force_stop_requested()):
                    continue
                executor.request_stop(force=force)
            except Exception as e:
                errors.append(f"[{entry['label']}] {e}")
                logger.warning("停止线程失败: %s", e)
        if errors:
            raise RuntimeError("; ".join(errors))

    def _check_done_locked(self):
        active = False
        for entry in self._entries.values():
            if entry.get("pending_launch") and not self._stop_requested:
                active = True
                break
            if self._is_entry_running_locked(entry):
                active = True
                break
        if not active:
            self._done_event.set()

    def _release_initial_start_gate_locked(self):
        gate = self._initial_start_gate
        self._initial_start_gate = None
        self._initial_start_waiting_threads.clear()
        if gate is not None:
            gate.set()

    def _on_initial_hold_thread_started(self, thread_id: int):
        gate = None
        with self._lock:
            if self._initial_start_gate is None:
                return
            self._initial_start_waiting_threads.discard(thread_id)
            if not self._initial_start_waiting_threads:
                gate = self._initial_start_gate
                self._initial_start_gate = None
        if gate is not None:
            gate.set()

    def _process_pending_launches(self):
        launch_queue: List[Tuple[int, int, bool]] = []
        with self._lock:
            for thread_id, entry in self._entries.items():
                pending = entry.get("pending_launch")
                if not pending or self._stop_requested:
                    continue
                if self._is_entry_running_locked(entry):
                    continue
                start_card_id = pending.get("start_card_id", entry.get("default_start_card_id"))
                hold_start = bool(pending.get("hold_start"))
                launch_queue.append((thread_id, start_card_id, hold_start))

        for thread_id, start_card_id, hold_start in launch_queue:
            with self._lock:
                entry = self._entries.get(thread_id)
                if not entry:
                    continue
                pending = entry.get("pending_launch")
                if not pending or self._stop_requested:
                    continue
                if self._is_entry_running_locked(entry):
                    continue
                start_card_id = pending["start_card_id"]
                hold_start = bool(pending.get("hold_start"))
                ok, message = self._launch_entry_locked(entry, start_card_id, hold_start=hold_start)
                if not ok:
                    entry["pending_launch"] = None
                    entry["status"] = "failed"
                    entry["last_success"] = False
                    entry["last_message"] = message
                    if hold_start:
                        self._initial_start_waiting_threads.discard(thread_id)
                        if not self._initial_start_waiting_threads:
                            self._release_initial_start_gate_locked()
                    logger.error("线程启动失败: %s", message)
                self._check_done_locked()

    def _label_of(self, thread_id: int) -> str:
        entry = self._entries.get(thread_id) or {}
        return str(entry.get("label") or f"线程{thread_id}")

    def _format_card_step_text(self, prefix: str, card_id: Any) -> str:
        card_obj = find_card_by_id(self.cards_data, card_id)
        return format_step_detail(prefix, card=card_obj, card_id=card_id)

    def _on_child_execution_started(self, thread_id: int, label: str):
        with self._lock:
            entry = self._entries.get(thread_id)
            if entry:
                entry["status"] = "running"
        self.step_details.emit(f"[{label}] 开始执行")

    def _on_child_card_executing(self, thread_id: int, card_id: int):
        self.card_executing.emit(card_id)
        self.step_details.emit(f"[{self._label_of(thread_id)}] {self._format_card_step_text('正在执行', card_id)}")

    def _on_child_card_finished(self, thread_id: int, card_id: int, success: bool):
        self.card_finished.emit(card_id, success)

    def _on_child_error(self, thread_id: int, card_id: int, message: str):
        self.error_occurred.emit(card_id, message)
        self.step_details.emit(f"[{self._label_of(thread_id)}] 错误: {message}")

    def _on_child_path_updated(self, thread_id: int, card_id: int, name: str, value: str):
        self.path_updated.emit(card_id, name, value)

    def _on_child_param_updated(self, thread_id: int, card_id: int, name: str, value: object):
        self.param_updated.emit(card_id, name, value)

    def _on_child_path_failed(self, thread_id: int, card_id: int, path: str):
        self.path_resolution_failed.emit(card_id, path)

    def _on_child_step_details(self, thread_id: int, message: str):
        self.step_details.emit(f"[{self._label_of(thread_id)}] {message}")

    def _on_child_step_log(self, thread_id: int, card_type: str, message: str, success: bool):
        prefix = f"[{self._label_of(thread_id)}] "
        self.step_log.emit(card_type, f"{prefix}{message}", success)

    def _on_child_warning(self, thread_id: int, title: str, message: str):
        self.show_warning.emit(title, f"[{self._label_of(thread_id)}] {message}")

    def _on_child_overlay_update_requested(self, thread_id: int, payload: object):
        if not isinstance(payload, dict):
            return
        relay_payload = dict(payload)
        relay_payload.setdefault("thread_id", thread_id)
        self.overlay_update_requested.emit(relay_payload)

    def _on_child_execution_finished(
        self,
        thread_id: int,
        launch_token: int,
        success: bool,
        message: str,
    ):
        label = self._label_of(thread_id)
        with self._lock:
            entry = self._entries.get(thread_id)
            if not entry:
                return
            if int(entry.get("launch_token", 0) or 0) != int(launch_token):
                logger.debug(
                    "忽略过期执行完成回调: thread_id=%s, launch_token=%s, current_token=%s",
                    thread_id,
                    launch_token,
                    entry.get("launch_token", 0),
                )
                return
            executor_obj = entry.get("executor")
            if executor_obj is None:
                logger.debug(
                    "执行完成回调到达时执行器已为空: thread_id=%s, launch_token=%s",
                    thread_id,
                    launch_token,
                )
                return
            entry["result_received"] = True
            message_text = str(message or "")
            entry["last_success"] = bool(success)
            entry["last_message"] = message_text
            if executor_obj._last_cleanup_errors:
                entry["pending_launch"] = None
            has_pending_restart = bool(entry.get("pending_launch")) and not self._stop_requested
            if has_pending_restart:
                entry["status"] = "idle"
            else:
                if not success:
                    entry["status"] = "failed"
                elif self._stop_requested or executor_obj.run_context.is_stop_requested():
                    entry["status"] = "stopped"
                else:
                    entry["status"] = "completed" if success else "failed"

            self._check_done_locked()

        if success:
            logger.debug("[%s] %s", label, message)
        else:
            logger.error("[%s] %s", label, message)

    def _build_final_result_locked(self) -> Tuple[bool, str]:
        if not self._entries:
            return False, "没有可执行线程"

        if self._stop_requested:
            failed = [entry["last_message"] for entry in self._entries.values() if entry["status"] == "failed"]
            if failed:
                return False, "多线程停止失败: " + "; ".join(failed)
            return True, "多线程执行已停止"

        total = len(self._entries)
        success_count = 0
        failed_count = 0
        for entry in self._entries.values():
            status = str(entry.get("status") or "")
            if status == "completed":
                success_count += 1
            elif status in ("failed",):
                failed_count += 1
            elif bool(entry.get("last_success")):
                success_count += 1
            elif status in ("stopped",):
                pass
            else:
                failed_count += 1

        if failed_count > 0:
            return False, f"多线程执行完成：成功 {success_count}/{total}，失败 {failed_count}"
        return True, f"多线程执行完成：成功 {success_count}/{total}"

