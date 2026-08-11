import hashlib
import logging
import os
import threading
from typing import Any, Dict, Optional

from task_workflow.card_display import format_step_detail
from utils.thread_start_utils import is_thread_start_task_type

logger = logging.getLogger(__name__)


class WindowTaskRunnerSlotsMixin:
    @staticmethod
    def _is_start_task_type(task_type: Any) -> bool:
        return is_thread_start_task_type(task_type)

    @staticmethod
    def _parse_card_id_as_int(card_id: Any) -> Optional[int]:
        try:
            if card_id is None:
                return None
            return int(str(card_id).strip())
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _get_cpu_logical_thread_limit() -> int:
        try:
            return max(1, int(os.cpu_count() or 1))
        except Exception:
            return 1

    @classmethod
    def _get_execution_slot_limit(cls) -> int:
        cpu_limit = cls._get_cpu_logical_thread_limit()
        default_limit = max(1, cpu_limit // 2)
        raw_value = str(os.getenv("LCA_CC_MAX_CONCURRENT_RUNNERS") or "").strip()
        if not raw_value:
            return default_limit
        try:
            configured_limit = int(raw_value)
        except Exception:
            return default_limit
        return max(1, min(cpu_limit, configured_limit))

    @classmethod
    def _get_execution_slot_semaphore(cls):
        with cls._execution_slot_lock:
            limit = cls._get_execution_slot_limit()
            if (
                cls._execution_slot_semaphore is None
                or cls._execution_slot_limit != limit
            ):
                cls._execution_slot_limit = limit
                cls._execution_slot_semaphore = threading.BoundedSemaphore(limit)
            return cls._execution_slot_semaphore, limit

    def _acquire_execution_slot(self) -> bool:
        semaphore, limit = self._get_execution_slot_semaphore()
        self.step_updated.emit(self.window_id, f"等待执行槽位({limit})")
        while not self._should_stop:
            try:
                if semaphore.acquire(timeout=0.05):
                    self._execution_slot_acquired = True
                    self._execution_slot_ref = semaphore
                    logger.info("窗口%s已获取执行槽位，limit=%s", self.window_id, limit)
                    return True
            except Exception as exc:
                logger.warning("窗口%s获取执行槽位失败: %s", self.window_id, exc)
                return False
        return False

    def _release_execution_slot(self) -> None:
        if not self._execution_slot_acquired:
            return
        self._execution_slot_acquired = False
        semaphore = self._execution_slot_ref
        self._execution_slot_ref = None
        if semaphore is None:
            return
        try:
            semaphore.release()
            logger.info("窗口%s已释放执行槽位", self.window_id)
        except ValueError:
            logger.warning("窗口%s释放执行槽位时检测到计数异常", self.window_id)

    @staticmethod
    def _count_runtime_vars(variables_data: Optional[Dict[str, Any]]) -> int:
        if not isinstance(variables_data, dict):
            return 0
        global_vars = variables_data.get("global_vars")
        if isinstance(global_vars, dict):
            return len(global_vars)
        try:
            return int(variables_data.get("count") or 0)
        except Exception:
            return len(variables_data)

    def _rebuild_card_step_labels(self, cards: Any) -> None:
        labels: Dict[str, str] = {}
        if not isinstance(cards, list):
            self._card_step_labels = labels
            return

        for card in cards:
            if not isinstance(card, dict):
                continue
            card_id = card.get("id")
            if card_id is None:
                continue
            step_info = format_step_detail("正在执行", card=card, card_id=card_id)
            labels[str(card_id)] = step_info

        self._card_step_labels = labels

    def _build_workflow_id(self) -> str:
        window_part = str(self.window_info.get("hwnd", self.window_id) or self.window_id).strip() or "unknown"
        slot_part = str(self.workflow_slot)
        workflow_path = str(self.workflow_file_path or "").strip()
        if workflow_path:
            normalized = os.path.normcase(os.path.abspath(workflow_path)).replace("\\", "/")
        else:
            card_count = 0
            try:
                cards = self.workflow_data.get("cards", []) if isinstance(self.workflow_data, dict) else []
                card_count = len(cards) if isinstance(cards, list) else 0
            except Exception:
                card_count = 0
            normalized = f"memory:{window_part}:{slot_part}:{card_count}"
        digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]
        return f"cc_{window_part}_{slot_part}_{digest}"

    def _import_workflow_variables(self, workflow_id: str) -> None:
        if not isinstance(self.workflow_data, dict):
            return
        variables_data = self.workflow_data.get("variables")
        if not isinstance(variables_data, dict):
            return
        try:
            from task_workflow.workflow_context import import_global_vars

            import_global_vars(variables_data, workflow_id=workflow_id)
            logger.info(
                "窗口%s加载运行变量: workflow_id=%s, var_count=%d",
                self.window_id,
                workflow_id,
                self._count_runtime_vars(variables_data),
            )
        except Exception as exc:
            logger.warning("窗口%s加载运行变量失败: %s", self.window_id, exc)

    def _capture_runtime_variables_from_executor(self, executor_obj) -> bool:
        if executor_obj is None:
            return False
        try:
            runtime_vars = getattr(executor_obj, "_final_runtime_variables", None)
            if isinstance(runtime_vars, dict):
                self._last_runtime_variables = dict(runtime_vars)
                return True
        except Exception:
            pass
        return False
