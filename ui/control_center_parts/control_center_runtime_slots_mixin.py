import hashlib
import logging
import os
import threading
from typing import Any, Dict, Optional

from task_workflow.card_display import format_step_detail
from task_workflow.thread_start import is_thread_start_task_type

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
        self._emit_step(f"等待执行槽位({limit})")
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
