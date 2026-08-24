# -*- coding: utf-8 -*-

"""
工作流上下文管理器
用于在工作流执行过程中在卡片间传递数据
"""

import logging
import threading
import time
from typing import TYPE_CHECKING, Dict, List, Any, Optional, Set
from dataclasses import dataclass, field

from task_workflow.workflow_identity import normalize_workflow_id

if TYPE_CHECKING:
    from task_workflow.run_context import RunContext

try:
    import numpy as _np  # type: ignore
except Exception:
    _np = None

logger = logging.getLogger(__name__)


@dataclass
class WorkflowContext:
    """工作流执行上下文"""
    workflow_id: str = "default"
    run_state: Optional["RunContext"] = field(default=None, repr=False)
    # OCR识别结果存储 {card_id: [ocr_results]}
    ocr_results: Dict[int, List[Dict[str, Any]]] = field(default_factory=dict)
    # OCR结果快照，避免成功/失败分支提前清空上下文后丢失
    ocr_result_snapshots: Dict[int, Dict[str, Any]] = field(default_factory=dict)

    # 图片识别结果存储 {card_id: image_results}
    image_results: Dict[int, Dict[str, Any]] = field(default_factory=dict)

    # YOLO检测结果存储 {card_id: yolo_result}
    yolo_results: Dict[int, Dict[str, Any]] = field(default_factory=dict)

    # 通用数据存储 {card_id: {key: value}}
    card_data: Dict[int, Dict[str, Any]] = field(default_factory=dict)

    # AI conversation context {context_id: [messages]}
    ai_conversations: Dict[str, List[Dict[str, str]]] = field(default_factory=dict)

    # Shared capture frames for parallel tasks
    shared_captures: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    shared_capture_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def _monitor_configs(self) -> Dict[int, Dict[str, Any]]:
        if self.run_state is None:
            return {}
        return self.run_state.monitor_configs

    @_monitor_configs.setter
    def _monitor_configs(self, value: Dict[int, Dict[str, Any]]) -> None:
        if self.run_state is None:
            from task_workflow.run_context import RunContext

            self.run_state = RunContext(workflow_id=self.workflow_id)
        self.run_state.monitor_configs = dict(value or {})

    @property
    def _should_stop_workflow(self) -> bool:
        return bool(self.run_state and self.run_state.should_stop_workflow)

    @_should_stop_workflow.setter
    def _should_stop_workflow(self, value: Any) -> None:
        if self.run_state is None:
            from task_workflow.run_context import RunContext

            self.run_state = RunContext(workflow_id=self.workflow_id)
        self.run_state.should_stop_workflow = bool(value)

    def clear(self):
        """清空所有上下文数据"""
        self.ocr_results.clear()
        self.ocr_result_snapshots.clear()
        self.image_results.clear()
        self.yolo_results.clear()
        self.card_data.clear()
        self.ai_conversations.clear()
        self.shared_captures.clear()
        if self.run_state is not None:
            self.run_state.monitor_configs.clear()
            self.run_state.should_stop_workflow = False
        # Runtime routing metadata (best-effort).
        try:
            self.runtime_resource_lane_key = None
            self.runtime_start_card_id = None
            self.runtime_window_hwnd = None
            self.runtime_resource_lane_updated_ts = 0.0
        except Exception:
            pass
        self._run_gc_collect()
        logger.debug("工作流上下文已清空")

    @staticmethod
    def _run_gc_collect() -> None:
        try:
            import gc

            gc.collect()
        except Exception:
            pass

    @staticmethod
    def _sanitize_card_data_value(key: str, value: Any) -> Any:
        """防止将大图对象直接写入card_data，避免主进程长期持有图片内存。"""
        key_text = str(key or "")

        # numpy数组（截图/模板）直接降级为元信息
        if _np is not None and isinstance(value, _np.ndarray):
            nbytes = int(getattr(value, "nbytes", 0) or 0)
            if nbytes > 0:
                return {
                    "__trimmed__": True,
                    "type": "ndarray",
                    "key": key_text,
                    "shape": list(value.shape),
                    "dtype": str(value.dtype),
                    "bytes": nbytes,
                }

        # 大二进制对象降级为元信息
        if isinstance(value, (bytes, bytearray, memoryview)):
            size = len(value)
            if size >= 64 * 1024:
                return {
                    "__trimmed__": True,
                    "type": type(value).__name__,
                    "key": key_text,
                    "bytes": int(size),
                }

        # Qt/PIL图像对象降级为元信息
        class_name = type(value).__name__
        if class_name in ("QImage", "QPixmap", "Image"):
            width = getattr(value, "width", None)
            height = getattr(value, "height", None)
            try:
                width = int(width()) if callable(width) else (int(width) if width is not None else None)
            except Exception:
                width = None
            try:
                height = int(height()) if callable(height) else (int(height) if height is not None else None)
            except Exception:
                height = None

            payload = {
                "__trimmed__": True,
                "type": class_name,
                "key": key_text,
            }
            if width is not None and height is not None:
                payload["size"] = [width, height]
            return payload

        return value
    
    def set_ocr_results(self, card_id: int, results: List[Dict[str, Any]]):
        """设置OCR识别结果"""
        # 【内存泄漏修复】在存储新结果前，清理旧的OCR结果
        # 只保留最近的OCR结果，避免无限累积
        if len(self.ocr_results) > 10:  # 限制最多保留10个卡片的结果
            # 找出最旧的卡片ID（除了当前卡片）
            old_cards = sorted([cid for cid in self.ocr_results.keys() if cid != card_id])
            # 删除最旧的一半
            for old_card_id in old_cards[:len(old_cards)//2]:
                del self.ocr_results[old_card_id]
                logger.debug(f"自动清理旧OCR结果: 卡片 {old_card_id}")

        self.ocr_results[card_id] = results
        logger.debug(f"设置卡片 {card_id} 的OCR结果: {len(results)} 个文字 (最新)")

    def set_ocr_result_snapshot(
        self,
        card_id: int,
        results: Optional[List[Dict[str, Any]]],
        *,
        target_text: Any = "",
        match_mode: Any = "包含",
        region_offset: Any = None,
        window_hwnd: Any = None,
    ) -> None:
        """缓存本次OCR识别快照。"""
        normalized_results: List[Dict[str, Any]] = []
        if isinstance(results, list):
            for item in results:
                if isinstance(item, dict):
                    normalized_results.append(dict(item))

        self.ocr_result_snapshots[card_id] = {
            "results": normalized_results,
            "target_text": str(target_text or "").strip(),
            "match_mode": str(match_mode or "包含").strip() or "包含",
            "region_offset": region_offset,
            "window_hwnd": window_hwnd,
            "updated_at": float(time.time()),
        }

    def get_ocr_result_snapshot(self, card_id: int) -> Optional[Dict[str, Any]]:
        snapshot = self.ocr_result_snapshots.get(card_id)
        if isinstance(snapshot, dict):
            return dict(snapshot)
        return None

    def clear_ocr_result_snapshot(self, card_id: int) -> None:
        if card_id in self.ocr_result_snapshots:
            del self.ocr_result_snapshots[card_id]

    
    def get_ocr_results(self, card_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """获取OCR识别结果"""
        if card_id is not None:
            return self.ocr_results.get(card_id, [])
        
        # 如果没有指定卡片ID，返回最近的OCR结果
        if self.ocr_results:
            latest_card_id = max(self.ocr_results.keys())
            return self.ocr_results[latest_card_id]
        
        return []
    
    def get_latest_ocr_results(self) -> List[Dict[str, Any]]:
        """获取最新的OCR识别结果"""
        latest_card_id = self.get_latest_ocr_card_id()
        if latest_card_id is not None:
            logger.debug(f"使用最新OCR结果: 卡片ID {latest_card_id}")
            return self.ocr_results[latest_card_id]

        return []

    def get_latest_ocr_card_id(self) -> Optional[int]:
        """获取最新OCR结果的卡片ID"""
        if not self.ocr_results:
            return None
        return max(self.ocr_results.keys())

    def set_yolo_result(self, card_id: int, result: Dict[str, Any]):
        """设置YOLO检测结果

        Args:
            card_id: 卡片ID
            result: YOLO检测结果，包含:
                - target_x: 目标中心X坐标
                - target_y: 目标中心Y坐标
                - x1, y1, x2, y2: 目标边界框
                - class_name: 目标类别名
                - confidence: 置信度
                - selection_strategy: 选择策略（最近/最大/置信度最高）
                - all_detections: 所有检测到的目标列表
        """
        if len(self.yolo_results) > 10:
            old_cards = sorted([cid for cid in self.yolo_results.keys() if cid != card_id])
            for old_card_id in old_cards[:len(old_cards)//2]:
                del self.yolo_results[old_card_id]
                logger.debug(f"自动清理旧YOLO结果: 卡片 {old_card_id}")

        self.yolo_results.pop(card_id, None)
        self.yolo_results[card_id] = result
        logger.debug(f"设置卡片 {card_id} 的YOLO结果: 目标=({result.get('target_x')}, {result.get('target_y')})")

    def get_yolo_result(self, card_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """获取YOLO检测结果"""
        if card_id is not None:
            return self.yolo_results.get(card_id)

        if self.yolo_results:
            latest_card_id = next(reversed(self.yolo_results))
            return self.yolo_results[latest_card_id]

        return None

    def get_latest_yolo_result(self) -> Optional[Dict[str, Any]]:
        """获取最新的YOLO检测结果"""
        if not self.yolo_results:
            return None
        latest_card_id = next(reversed(self.yolo_results))
        logger.debug(f"使用最近写入的YOLO结果: 卡片ID {latest_card_id}")
        return self.yolo_results[latest_card_id]

    def clear_all_yolo_data(self):
        """清除所有YOLO相关结果。"""
        self.yolo_results.clear()
        logger.debug("清除所有YOLO相关数据")

    def clear_card_yolo_data(self, card_id: int):
        """清理单卡 YOLO 运行态数据。"""
        if card_id in self.yolo_results:
            del self.yolo_results[card_id]
            logger.debug(f"清理卡片 {card_id} 的 YOLO 结果")

    def set_card_data(self, card_id: int, key: str, value: Any):
        """设置卡片数据"""
        # 【内存泄漏修复】限制card_data的大小，防止无限累积
        if len(self.card_data) > 50:  # 限制最多50个卡片
            # 删除最旧的卡片数据
            old_cards = sorted(self.card_data.keys())[:len(self.card_data)//3]
            for old_card_id in old_cards:
                del self.card_data[old_card_id]
                logger.debug(f"自动清理旧卡片数据: 卡片 {old_card_id}")

        if card_id not in self.card_data:
            self.card_data[card_id] = {}
        sanitized = self._sanitize_card_data_value(key, value)
        self.card_data[card_id][key] = sanitized

        if sanitized is value:
            logger.debug(f"设置卡片 {card_id} 数据: {key} = {value}")
        else:
            logger.debug(
                "卡片%d数据键'%s'写入了大对象，已自动降级为元信息",
                card_id,
                key,
            )

    def _normalize_conversation_id(self, context_id: Optional[str]) -> str:
        key = str(context_id).strip() if context_id is not None else ""
        return key or "default"

    def get_ai_conversation(self, context_id: Optional[str]) -> List[Dict[str, str]]:
        # Get AI conversation
        key = self._normalize_conversation_id(context_id)
        return list(self.ai_conversations.get(key, []))

    def clear_ai_conversation(self, context_id: Optional[str]) -> None:
        # Clear AI conversation
        key = self._normalize_conversation_id(context_id)
        if key in self.ai_conversations:
            del self.ai_conversations[key]

    def append_ai_conversation(self, context_id: Optional[str], role: str, content: str,
                               max_rounds: Optional[int] = None) -> None:
        # Append AI conversation message
        if not content:
            return
        key = self._normalize_conversation_id(context_id)
        messages = self.ai_conversations.setdefault(key, [])
        messages.append({"role": role, "content": content})

        if max_rounds and max_rounds > 0:
            max_len = max_rounds * 2
            if len(messages) > max_len:
                self.ai_conversations[key] = messages[-max_len:]

    def set_multi_text_recognition_state(self, card_id: int, text_groups: list, current_index: int = 0, clicked_texts: list = None):
        """设置多组文字识别状态"""
        if clicked_texts is None:
            clicked_texts = []

        self.set_card_data(card_id, 'multi_text_groups', text_groups)
        self.set_card_data(card_id, 'current_text_index', current_index)
        self.set_card_data(card_id, 'clicked_texts', clicked_texts.copy())
        now = time.time()
        card_data = self.card_data.get(card_id, {})
        last_log_ts = card_data.get('_multi_text_log_ts')
        if last_log_ts is None or now - last_log_ts >= 0.5:
            logger.debug(
                f"设置多组文字识别状态: 卡片{card_id}, 当前组{current_index}/{len(text_groups)}, 已匹配{len(clicked_texts)}个文字"
            )
            card_data['_multi_text_log_ts'] = now
            self.card_data[card_id] = card_data

    def get_multi_text_recognition_state(self, card_id: int):
        """获取多组文字识别状态"""
        if card_id not in self.card_data:
            return None, 0, []

        card_data = self.card_data[card_id]
        text_groups = card_data.get('multi_text_groups', [])
        current_index = card_data.get('current_text_index', 0)
        clicked_texts = card_data.get('clicked_texts', [])

        return text_groups, current_index, clicked_texts

    def advance_text_recognition_index(self, card_id: int):
        """推进到下一组文字识别"""
        text_groups, current_index, clicked_texts = self.get_multi_text_recognition_state(card_id)
        if text_groups:
            new_index = current_index + 1
            self.set_card_data(card_id, 'current_text_index', new_index)
            logger.info(f"推进到下一组文字: 卡片{card_id}, 新索引{new_index}/{len(text_groups)}")

            # 返回是否还有下一组需要处理
            return new_index < len(text_groups)
        return False

    def add_clicked_text(self, card_id: int, clicked_text: str):
        """添加已匹配的文字"""
        text_groups, current_index, clicked_texts = self.get_multi_text_recognition_state(card_id)
        if clicked_text not in clicked_texts:
            clicked_texts.append(clicked_text)
            self.set_card_data(card_id, 'clicked_texts', clicked_texts)
            logger.debug(f"添加已匹配文字: 卡片{card_id}, 文字'{clicked_text}', 总计{len(clicked_texts)}个")

    def is_multi_text_recognition_complete(self, card_id: int):
        """检查多组文字识别是否完成"""
        text_groups, current_index, clicked_texts = self.get_multi_text_recognition_state(card_id)
        if not text_groups:
            return True
        return current_index >= len(text_groups) - 1

    def reset_multi_text_recognition_state(self, card_id: int, text_groups: list):
        """重置多组文字识别状态"""
        self.set_multi_text_recognition_state(card_id, text_groups, 0, [])
        logger.info(f"重置多组文字识别状态: 卡片{card_id}, 共{len(text_groups)}组文字")
    
    def get_card_data(self, card_id: int, key: str, default: Any = None) -> Any:
        """获取卡片数据"""
        return self.card_data.get(card_id, {}).get(key, default)

    def set_shared_capture(self, hwnd: int, client_area_only: bool, image: Any):
        """Store a shared capture frame for parallel tasks."""
        # 当前架构不在上下文层持有截图帧，避免增加常驻内存。
        return None

    def get_shared_capture(self, hwnd: int, client_area_only: bool) -> Optional[Any]:
        """Get a shared capture frame if it matches the request."""
        # 当前架构不在上下文层共享截图帧。
        return None

    def clear_shared_captures(self):
        """Clear all shared capture frames."""
        with self.shared_capture_lock:
            self.shared_captures.clear()

    def clear_card_ocr_context(self, card_id: int):
        """清除指定卡片的OCR上下文数据（不包括记忆）"""
        # 清除OCR识别结果（上下文）
        if card_id in self.ocr_results:
            del self.ocr_results[card_id]
            logger.debug(f"清除卡片 {card_id} 的OCR上下文结果")

        # 清除OCR上下文相关的卡片数据（不包括记忆数据）
        if card_id in self.card_data:
            card_data = self.card_data[card_id]
            context_keys = ['ocr_target_text', 'ocr_match_mode', 'ocr_region_offset', 'ocr_window_hwnd']
            for key in context_keys:
                if key in card_data:
                    del card_data[key]
                    logger.debug(f"清除卡片 {card_id} 的OCR上下文数据: {key}")

    def clear_card_ocr_data(self, card_id: int):
        """清除指定卡片的所有OCR相关数据（包括记忆）"""
        # 清除OCR识别结果
        if card_id in self.ocr_results:
            del self.ocr_results[card_id]
            logger.debug(f"清除卡片 {card_id} 的OCR识别结果")
        self.clear_ocr_result_snapshot(card_id)

        # 清除所有OCR相关的卡片数据（包括记忆）
        if card_id in self.card_data:
            card_data = self.card_data[card_id]
            all_ocr_keys = ['ocr_target_text', 'ocr_match_mode', 'ocr_region_offset',
                           'multi_text_groups', 'current_text_index', 'clicked_texts',
                           '_multi_text_log_ts']
            for key in all_ocr_keys:
                if key in card_data:
                    del card_data[key]
                    logger.debug(f"清除卡片 {card_id} 的OCR数据: {key}")

            # 如果卡片数据为空，删除整个卡片数据
            if not card_data:
                del self.card_data[card_id]
                logger.debug(f"清除卡片 {card_id} 的所有数据")

    def clear_card_runtime_data(self, card_id: int):
        """清理单卡运行态数据（OCR/YOLO/card_data）。"""
        self.clear_card_ocr_data(card_id)
        self.clear_card_yolo_data(card_id)
        if card_id in self.card_data:
            del self.card_data[card_id]
            logger.debug(f"清理卡片 {card_id} 的剩余 card_data")

    def clear_all_ocr_data(self):
        """清除所有OCR相关数据"""
        self.ocr_results.clear()
        self.ocr_result_snapshots.clear()

        # 清除所有卡片的OCR相关数据
        for card_id in list(self.card_data.keys()):
            self.clear_card_ocr_data(card_id)

        self._run_gc_collect()
        logger.debug("清除所有OCR相关数据")

    def clear_runtime_state_for_new_run(self):
        """清理上次执行遗留的 OCR/YOLO/卡片缓存。"""
        card_cache_count = len(self.card_data)
        self.ocr_results.clear()
        self.ocr_result_snapshots.clear()
        self.yolo_results.clear()
        self.card_data.clear()
        self._run_gc_collect()
        logger.info(
            "执行前运行态清理完成: 清理卡片缓存 %d 个",
            card_cache_count,
        )

    def clear_multi_image_memory(self):
        """清除所有多图识别记忆数据"""
        cleared_count = 0
        for card_id in list(self.card_data.keys()):
            card_data = self.card_data[card_id]
            memory_keys = ['clicked_images', 'success_images']
            for key in memory_keys:
                if key in card_data:
                    del card_data[key]
                    cleared_count += 1
                    logger.debug(f"清除卡片 {card_id} 的多图识别记忆: {key}")

            # 如果卡片数据为空，删除整个卡片数据
            if not card_data:
                del self.card_data[card_id]
                logger.debug(f"清除卡片 {card_id} 的所有数据")

        if cleared_count > 0:
            logger.info(f"清除了 {cleared_count} 个多图识别记忆数据")
        else:
            logger.debug("没有找到需要清除的多图识别记忆数据")


class WorkflowContextManager:
    """工作流上下文管理器（单例模式）"""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self._contexts: Dict[str, WorkflowContext] = {}
            self._context_last_access: Dict[str, float] = {}
            self._context_keys_by_object: Dict[int, str] = {}
            self._thread_context_refs: Dict[int, str] = {}
            self._thread_local = threading.local()
            self._manager_lock = threading.RLock()
            self._max_contexts = 64
            self._context_ttl_seconds = 1800.0
            self._prune_interval_seconds = 30.0
            self._last_prune_ts = 0.0
            self._initialized = True
            logger.debug("工作流上下文管理器初始化完成")

    @staticmethod
    def _normalize_workflow_id(workflow_id: Optional[str]) -> str:
        return normalize_workflow_id(workflow_id)

    def _touch_context_unlocked(self, workflow_id: str) -> None:
        self._context_last_access[workflow_id] = time.monotonic()

    def _bind_context_unlocked(self, workflow_id: str, context: WorkflowContext) -> None:
        context.workflow_id = workflow_id
        self._contexts[workflow_id] = context
        self._context_keys_by_object[id(context)] = workflow_id
        self._touch_context_unlocked(workflow_id)

    def _find_context_key_unlocked(self, context: Optional[WorkflowContext]) -> Optional[str]:
        if context is None:
            return None
        key = self._context_keys_by_object.get(id(context))
        if key:
            return key
        for workflow_id, existing in self._contexts.items():
            if existing is context:
                self._context_keys_by_object[id(context)] = workflow_id
                return workflow_id
        return None

    def _register_thread_context_unlocked(self, workflow_id: str) -> None:
        self._thread_context_refs[threading.get_ident()] = workflow_id

    def _prune_dead_thread_refs_unlocked(self) -> None:
        alive_thread_ids = {thread.ident for thread in threading.enumerate() if thread.ident is not None}
        for thread_id in list(self._thread_context_refs.keys()):
            if thread_id not in alive_thread_ids:
                self._thread_context_refs.pop(thread_id, None)

    def _ensure_default_context_unlocked(self) -> WorkflowContext:
        context = self._contexts.get("default")
        if context is None:
            context = WorkflowContext(workflow_id="default")
            self._bind_context_unlocked("default", context)
            logger.debug("创建新的工作流上下文: default")
        else:
            context.workflow_id = "default"
            self._touch_context_unlocked("default")
        return context

    def _prune_contexts_unlocked(self, force: bool = False, preserve_ids: Optional[Set[str]] = None) -> List[WorkflowContext]:
        if not self._contexts:
            return []

        now = time.monotonic()
        if not force and (now - self._last_prune_ts) < self._prune_interval_seconds and len(self._contexts) <= self._max_contexts:
            return []

        self._last_prune_ts = now
        self._prune_dead_thread_refs_unlocked()

        protected_ids: Set[str] = {"default"}
        if preserve_ids:
            protected_ids.update(preserve_ids)
        protected_ids.update(self._thread_context_refs.values())

        thread_context = getattr(self._thread_local, "context", None)
        thread_context_key = self._find_context_key_unlocked(thread_context)
        if thread_context_key:
            protected_ids.add(thread_context_key)

        to_remove: List[str] = []
        for workflow_id in list(self._contexts.keys()):
            if workflow_id in protected_ids:
                continue
            last_access = self._context_last_access.get(workflow_id, now)
            if (now - last_access) > self._context_ttl_seconds:
                to_remove.append(workflow_id)

        remaining_count = len(self._contexts) - len(to_remove)
        if remaining_count > self._max_contexts:
            candidates = [
                workflow_id
                for workflow_id in self._contexts.keys()
                if workflow_id not in protected_ids and workflow_id not in to_remove
            ]
            ordered = sorted(candidates, key=lambda wid: self._context_last_access.get(wid, 0.0))
            to_remove.extend(ordered[:remaining_count - self._max_contexts])

        removed_contexts: List[WorkflowContext] = []
        for workflow_id in dict.fromkeys(to_remove):
            context = self._contexts.pop(workflow_id, None)
            if context is None:
                continue
            self._context_last_access.pop(workflow_id, None)
            self._context_keys_by_object.pop(id(context), None)
            removed_contexts.append(context)

        if removed_contexts:
            logger.debug("自动回收工作流上下文: %d 个", len(removed_contexts))
        return removed_contexts

    def _clear_context_list(self, contexts: List[WorkflowContext]) -> None:
        for context in contexts:
            try:
                context.clear()
            except Exception:
                pass

    @property
    def contexts(self) -> Dict[str, WorkflowContext]:
        """兼容外部读操作，返回上下文快照。"""
        with self._manager_lock:
            return dict(self._contexts)

    def get_diagnostics(self) -> Dict[str, Any]:
        """返回上下文池诊断信息（只读）。"""
        with self._manager_lock:
            self._prune_dead_thread_refs_unlocked()
            return {
                "context_count": len(self._contexts),
                "context_keys": sorted(self._contexts.keys()),
                "thread_context_ref_count": len(self._thread_context_refs),
                "thread_context_refs": dict(self._thread_context_refs),
                "max_contexts": int(self._max_contexts),
                "context_ttl_seconds": float(self._context_ttl_seconds),
                "prune_interval_seconds": float(self._prune_interval_seconds),
            }

    def get_context(self, workflow_id: str = "default") -> WorkflowContext:
        """获取工作流上下文"""
        workflow_key = self._normalize_workflow_id(workflow_id)
        contexts_to_clear: List[WorkflowContext] = []
        with self._manager_lock:
            context = self._contexts.get(workflow_key)
            if context is None:
                context = WorkflowContext(workflow_id=workflow_key)
                self._bind_context_unlocked(workflow_key, context)
                logger.debug(f"创建新的工作流上下文: {workflow_key}")
            else:
                context.workflow_id = workflow_key
                self._touch_context_unlocked(workflow_key)

            # A read of another workflow must not replace the executing
            # thread's pinned context. Current-context APIs own that binding.
            contexts_to_clear = self._prune_contexts_unlocked(preserve_ids={workflow_key})

        self._clear_context_list(contexts_to_clear)
        return context

    def get_current_context(self) -> WorkflowContext:
        """获取当前线程的工作流上下文"""
        contexts_to_clear: List[WorkflowContext] = []
        with self._manager_lock:
            context = getattr(self._thread_local, "context", None)
            workflow_key = self._find_context_key_unlocked(context)

            if context is None or workflow_key is None:
                context = self._ensure_default_context_unlocked()
                workflow_key = "default"
                self._thread_local.context = context

            self._touch_context_unlocked(workflow_key)
            context.workflow_id = workflow_key
            self._register_thread_context_unlocked(workflow_key)
            contexts_to_clear = self._prune_contexts_unlocked(preserve_ids={workflow_key})

        self._clear_context_list(contexts_to_clear)
        return context

    def set_current_context(self, context: WorkflowContext):
        """设置当前线程的工作流上下文"""
        contexts_to_clear: List[WorkflowContext] = []
        with self._manager_lock:
            target_context = context
            workflow_key = self._find_context_key_unlocked(target_context)

            if workflow_key is None:
                if target_context is None:
                    target_context = self._ensure_default_context_unlocked()
                    workflow_key = "default"
                else:
                    workflow_key = self._normalize_workflow_id(
                        getattr(target_context, "workflow_id", None)
                    )
                    previous_context = self._contexts.get(workflow_key)
                    if previous_context is not None and previous_context is not target_context:
                        self._context_keys_by_object.pop(id(previous_context), None)
                    self._bind_context_unlocked(workflow_key, target_context)

            self._thread_local.context = target_context
            target_context.workflow_id = workflow_key
            self._touch_context_unlocked(workflow_key)
            self._register_thread_context_unlocked(workflow_key)
            contexts_to_clear = self._prune_contexts_unlocked(preserve_ids={workflow_key})

        self._clear_context_list(contexts_to_clear)

    def clear_context(self, workflow_id: str = "default"):
        """清空指定工作流的上下文"""
        workflow_key = self._normalize_workflow_id(workflow_id)
        context_to_clear: Optional[WorkflowContext] = None
        contexts_to_clear: List[WorkflowContext] = []

        with self._manager_lock:
            context_to_clear = self._contexts.pop(workflow_key, None)
            if context_to_clear is None:
                return

            self._context_last_access.pop(workflow_key, None)
            self._context_keys_by_object.pop(id(context_to_clear), None)

            for thread_id, thread_workflow_id in list(self._thread_context_refs.items()):
                if thread_workflow_id == workflow_key:
                    self._thread_context_refs.pop(thread_id, None)

            current_context = getattr(self._thread_local, "context", None)
            if current_context is context_to_clear:
                fallback_context = self._ensure_default_context_unlocked()
                self._thread_local.context = fallback_context
                self._register_thread_context_unlocked("default")

            contexts_to_clear = self._prune_contexts_unlocked()

        if context_to_clear is not None:
            self._clear_context_list([context_to_clear])
        self._clear_context_list(contexts_to_clear)
        logger.debug(f"清空工作流上下文: {workflow_key}")

    def clear_all_contexts(self):
        """清空所有工作流上下文"""
        contexts_to_clear: List[WorkflowContext] = []
        with self._manager_lock:
            contexts_to_clear = list(self._contexts.values())
            self._contexts.clear()
            self._context_last_access.clear()
            self._context_keys_by_object.clear()
            self._thread_context_refs.clear()
            self._last_prune_ts = 0.0

            fallback_context = WorkflowContext()
            self._bind_context_unlocked("default", fallback_context)
            self._thread_local.context = fallback_context
            self._register_thread_context_unlocked("default")

        self._clear_context_list(contexts_to_clear)
        logger.debug("清空所有工作流上下文")


# 全局上下文管理器实例
_context_manager = WorkflowContextManager()


def _safe_positive_int(value: Any) -> Optional[int]:
    try:
        parsed = int(value)
    except Exception:
        return None
    if parsed <= 0:
        return None
    return parsed


def _safe_nonnegative_int(value: Any) -> Optional[int]:
    try:
        parsed = int(value)
    except Exception:
        return None
    if parsed < 0:
        return None
    return parsed


def build_resource_lane_key(
    workflow_id: Optional[str],
    start_card_id: Optional[Any] = None,
    window_hwnd: Optional[Any] = None,
) -> str:
    workflow_text = str(workflow_id or "").strip() or "default"
    start_value = _safe_nonnegative_int(start_card_id)
    hwnd_value = _safe_positive_int(window_hwnd)
    start_text = str(start_value) if start_value is not None else "none"
    hwnd_text = str(hwnd_value) if hwnd_value is not None else "none"
    return f"{workflow_text}::start:{start_text}::hwnd:{hwnd_text}"


def _set_context_resource_lane_attrs(
    context: Optional[WorkflowContext],
    lane_key: Optional[str],
    start_card_id: Optional[Any] = None,
    window_hwnd: Optional[Any] = None,
) -> Optional[str]:
    if context is None:
        return None

    normalized_lane = str(lane_key or "").strip() or None
    normalized_start = _safe_nonnegative_int(start_card_id)
    normalized_hwnd = _safe_positive_int(window_hwnd)

    try:
        context.runtime_resource_lane_key = normalized_lane
        context.runtime_start_card_id = normalized_start
        context.runtime_window_hwnd = normalized_hwnd
        context.runtime_resource_lane_updated_ts = time.time()
    except Exception:
        return None
    return normalized_lane


def set_workflow_resource_lane(
    workflow_id: str = "default",
    start_card_id: Optional[Any] = None,
    window_hwnd: Optional[Any] = None,
    lane_key: Optional[str] = None,
) -> Optional[str]:
    context = get_workflow_context(workflow_id)
    computed_lane = str(lane_key or "").strip()
    if not computed_lane:
        computed_lane = build_resource_lane_key(workflow_id, start_card_id=start_card_id, window_hwnd=window_hwnd)
    return _set_context_resource_lane_attrs(
        context=context,
        lane_key=computed_lane,
        start_card_id=start_card_id,
        window_hwnd=window_hwnd,
    )


def clear_workflow_resource_lane(workflow_id: str = "default") -> None:
    context = get_workflow_context(workflow_id)
    _set_context_resource_lane_attrs(context=context, lane_key=None, start_card_id=None, window_hwnd=None)


def get_current_resource_lane_key(window_hwnd: Optional[Any] = None) -> Optional[str]:
    target_hwnd = _safe_positive_int(window_hwnd)
    try:
        context = get_current_workflow_context()
    except Exception:
        context = None
    if context is None:
        return None

    context_workflow_id = str(getattr(context, "workflow_id", "") or "").strip() or "default"
    context_lane = str(getattr(context, "runtime_resource_lane_key", "") or "").strip()
    context_start = _safe_nonnegative_int(getattr(context, "runtime_start_card_id", None))
    context_hwnd = _safe_positive_int(getattr(context, "runtime_window_hwnd", None))

    if context_lane:
        if target_hwnd is not None and context_hwnd is not None and target_hwnd != context_hwnd:
            return build_resource_lane_key(
                context_workflow_id,
                start_card_id=context_start,
                window_hwnd=target_hwnd,
            )
        return context_lane

    return build_resource_lane_key(
        context_workflow_id,
        start_card_id=context_start,
        window_hwnd=target_hwnd if target_hwnd is not None else context_hwnd,
    )

def get_workflow_context(workflow_id: str = "default") -> WorkflowContext:
    """获取工作流上下文的便捷函数"""
    if workflow_id == "default":
        return _context_manager.get_current_context()
    return _context_manager.get_context(workflow_id)

def get_current_workflow_context() -> WorkflowContext:
    """获取当前工作流上下文的便捷函数"""
    return _context_manager.get_current_context()

def set_current_workflow_context(context: WorkflowContext) -> None:
    """设置当前线程的工作流上下文。"""
    if context is None:
        context = _context_manager.get_context("default")
    _context_manager.set_current_context(context)

def set_ocr_results(card_id: int, results: List[Dict[str, Any]], workflow_id: str = "default"):
    """设置OCR识别结果的便捷函数"""
    context = get_workflow_context(workflow_id)
    context.set_ocr_results(card_id, results)

def get_ocr_results(card_id: Optional[int] = None, workflow_id: str = "default") -> List[Dict[str, Any]]:
    """获取OCR识别结果的便捷函数"""
    context = get_workflow_context(workflow_id)
    return context.get_ocr_results(card_id)

def get_latest_ocr_results(workflow_id: str = "default") -> List[Dict[str, Any]]:
    """获取最新OCR识别结果的便捷函数"""
    context = get_workflow_context(workflow_id)
    return context.get_latest_ocr_results()

def clear_workflow_context(workflow_id: str = "default"):
    """清空工作流上下文的便捷函数"""
    _context_manager.clear_context(workflow_id)

def get_workflow_context_diagnostics() -> Dict[str, Any]:
    """获取工作流上下文池诊断信息。"""
    return _context_manager.get_diagnostics()

def clear_all_workflow_contexts():
    """清空所有工作流上下文的便捷函数"""
    _context_manager.clear_all_contexts()

def clear_card_ocr_context(card_id: int, workflow_id: str = "default"):
    """清除指定卡片的OCR上下文数据的便捷函数"""
    context = get_workflow_context(workflow_id)
    context.clear_card_ocr_context(card_id)

def clear_card_ocr_data(card_id: int, workflow_id: str = "default"):
    """清除指定卡片的OCR数据的便捷函数"""
    context = get_workflow_context(workflow_id)
    context.clear_card_ocr_data(card_id)

def clear_card_runtime_data(card_id: int, workflow_id: str = "default"):
    """清理单卡运行态数据。"""
    context = get_workflow_context(workflow_id)
    context.clear_card_runtime_data(card_id)

def clear_all_ocr_data(workflow_id: str = "default"):
    """清除所有OCR数据的便捷函数"""
    context = get_workflow_context(workflow_id)
    context.clear_all_ocr_data()

def clear_runtime_state_for_new_run(workflow_id: str = "default"):
    """执行前清理运行态缓存。"""
    context = get_workflow_context(workflow_id)
    context.clear_runtime_state_for_new_run()

def clear_multi_image_memory(workflow_id: str = "default"):
    """清除所有多图识别记忆数据的便捷函数"""
    context = get_workflow_context(workflow_id)
    context.clear_multi_image_memory()


def clear_all_yolo_data(workflow_id: str = "default"):
    """清除指定上下文的YOLO运行态数据。"""
    context = get_workflow_context(workflow_id)
    context.clear_all_yolo_data()

def clear_card_yolo_data(card_id: int, workflow_id: str = "default"):
    """清理单卡 YOLO 运行态数据。"""
    context = get_workflow_context(workflow_id)
    context.clear_card_yolo_data(card_id)

def clear_all_yolo_runtime_data():
    """清除当前上下文池中全部YOLO运行态数据。"""
    context_snapshot = _context_manager.contexts
    seen_context_ids = set()
    for context in context_snapshot.values():
        context_id = id(context)
        if context_id in seen_context_ids:
            continue
        seen_context_ids.add(context_id)
        try:
            context.clear_all_yolo_data()
        except Exception:
            continue


def set_yolo_result(card_id: int, result: Dict[str, Any], workflow_id: str = "default"):
    """设置YOLO检测结果的便捷函数"""
    context = get_workflow_context(workflow_id)
    context.set_yolo_result(card_id, result)


def get_yolo_result(card_id: Optional[int] = None, workflow_id: str = "default") -> Optional[Dict[str, Any]]:
    """获取YOLO检测结果的便捷函数"""
    context = get_workflow_context(workflow_id)
    return context.get_yolo_result(card_id)


def get_latest_yolo_result(workflow_id: str = "default") -> Optional[Dict[str, Any]]:
    """获取最新YOLO检测结果的便捷函数"""
    context = get_workflow_context(workflow_id)
    return context.get_latest_yolo_result()
