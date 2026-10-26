import hashlib
import logging
import os
import threading
from typing import Any, Dict

from task_workflow.card_display import format_step_detail
from task_workflow.thread_start import is_thread_start_task_type

logger = logging.getLogger(__name__)


class WindowTaskRunnerSlotsMixin:
    @staticmethod
    def _is_start_task_type(task_type: Any) -> bool:
        return is_thread_start_task_type(task_type)

    @staticmethod
    def _get_cpu_logical_thread_limit() -> int:
        cpu_limit = os.cpu_count()
        if isinstance(cpu_limit, bool) or not isinstance(cpu_limit, int) or cpu_limit < 1:
            raise RuntimeError("无法确定 CPU 逻辑线程数")
        return cpu_limit

    @classmethod
    def _get_execution_slot_limit(cls) -> int:
        cpu_limit = cls._get_cpu_logical_thread_limit()
        default_limit = max(1, cpu_limit // 2)
        raw_value = os.getenv("LCA_CC_MAX_CONCURRENT_RUNNERS")
        if raw_value is None:
            return default_limit
        try:
            configured_limit = int(raw_value)
        except ValueError as exc:
            raise ValueError("中控并发数必须是整数") from exc
        if not 1 <= configured_limit <= cpu_limit:
            raise ValueError(f"中控并发数必须在 1 到 {cpu_limit} 之间")
        return configured_limit

    @classmethod
    def _get_execution_slot_semaphore(cls):
        with cls._execution_slot_lock:
            limit = cls._get_execution_slot_limit()
            if cls._execution_slot_semaphore is None:
                cls._execution_slot_limit = limit
                cls._execution_slot_semaphore = threading.BoundedSemaphore(limit)
            elif cls._execution_slot_limit != limit:
                raise RuntimeError("中控并发数已改变，请重启应用后使用新配置")
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
            raise RuntimeError("执行槽位已获取，但缺少可释放的槽位对象")
        semaphore.release()
        logger.info("窗口%s已释放执行槽位", self.window_id)

    def _rebuild_card_step_labels(self, cards: Any) -> None:
        labels: Dict[str, str] = {}
        if not isinstance(cards, list):
            raise TypeError("工作流卡片必须是列表")

        for card in cards:
            if not isinstance(card, dict):
                raise TypeError("工作流卡片数据必须是字典")
            card_id = card.get("id")
            if isinstance(card_id, bool) or not isinstance(card_id, int) or card_id < 0:
                raise ValueError("卡片ID必须是非负整数")
            step_info = format_step_detail("正在执行", card=card, card_id=card_id)
            labels[str(card_id)] = step_info

        self._card_step_labels = labels

    def _build_workflow_id(self) -> str:
        window_part = self.job_id
        slot_part = str(self.workflow_slot)
        workflow_path = str(self.workflow_file_path or "").strip()
        if workflow_path:
            normalized = os.path.normcase(os.path.abspath(workflow_path)).replace("\\", "/")
        else:
            card_count = len(self.workflow_data["cards"])
            normalized = f"memory:{window_part}:{slot_part}:{card_count}"
        digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]
        return f"cc_{window_part}_{slot_part}_{digest}"
