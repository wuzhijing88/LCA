# -*- coding: utf-8 -*-
"""
输入资源守卫：
- 统一管理键盘/鼠标输入的互斥访问
- 提供任务级别的输入能力判定
- 提供公平队列锁与统计信息，便于并发场景观测
"""

from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional, Tuple

from utils.input_simulation.mode_utils import is_foreground_mode

_DEFAULT_INPUT_LOCK_TIMEOUT_SEC = 30.0
_DEFAULT_INPUT_LOCK_WARN_WAIT_MS = 200.0
_LOCK_REGISTRY_GUARD = threading.Lock()
_LOCK_REGISTRY: Dict[str, "_FairReentrantLock"] = {}
_GUARD_LOCAL = threading.local()

# 默认需要独占输入资源的卡片
_DEFAULT_INPUT_TASK_TYPES = {
    "模拟鼠标操作",
    "模拟键盘操作",
    "图片点击",
    "录制回放",
}


class _FairReentrantLock:
    """支持可重入的公平队列锁（FIFO）。"""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._owner_tid: Optional[int] = None
        self._depth = 0
        self._ticket_seed = 0
        self._wait_queue = []
        self._stats = {
            "acquire_requests": 0,
            "acquired_count": 0,
            "reentrant_acquire_count": 0,
            "timeout_count": 0,
            "total_wait_ms": 0.0,
            "max_wait_ms": 0.0,
            "queue_peak": 0,
            "last_owner": "",
        }

    def acquire(self, *, timeout: Optional[float], owner: str = "") -> Tuple[bool, float]:
        start = time.perf_counter()
        current_tid = threading.get_ident()
        deadline = None if timeout is None else (start + max(0.0, float(timeout)))

        with self._cond:
            self._stats["acquire_requests"] += 1

            # 可重入：同线程直接通过
            if self._owner_tid == current_tid:
                self._depth += 1
                self._stats["acquired_count"] += 1
                self._stats["reentrant_acquire_count"] += 1
                wait_ms = (time.perf_counter() - start) * 1000.0
                return True, wait_ms

            self._ticket_seed += 1
            ticket = self._ticket_seed
            self._wait_queue.append(ticket)
            queue_len = len(self._wait_queue)
            if queue_len > self._stats["queue_peak"]:
                self._stats["queue_peak"] = queue_len

            while True:
                is_head = bool(self._wait_queue) and self._wait_queue[0] == ticket
                if is_head and self._owner_tid is None:
                    self._owner_tid = current_tid
                    self._depth = 1
                    self._wait_queue.pop(0)

                    wait_ms = (time.perf_counter() - start) * 1000.0
                    self._stats["acquired_count"] += 1
                    self._stats["total_wait_ms"] += wait_ms
                    if wait_ms > self._stats["max_wait_ms"]:
                        self._stats["max_wait_ms"] = wait_ms
                    self._stats["last_owner"] = str(owner or "")
                    return True, wait_ms

                if deadline is not None:
                    remaining = deadline - time.perf_counter()
                    if remaining <= 0:
                        try:
                            self._wait_queue.remove(ticket)
                        except ValueError:
                            pass
                        self._stats["timeout_count"] += 1
                        wait_ms = (time.perf_counter() - start) * 1000.0
                        self._stats["total_wait_ms"] += wait_ms
                        if wait_ms > self._stats["max_wait_ms"]:
                            self._stats["max_wait_ms"] = wait_ms
                        return False, wait_ms
                    self._cond.wait(timeout=remaining)
                else:
                    self._cond.wait()

    def release(self) -> None:
        current_tid = threading.get_ident()
        with self._cond:
            if self._owner_tid != current_tid:
                raise RuntimeError("input guard lock release from non-owner thread")
            self._depth -= 1
            if self._depth <= 0:
                self._depth = 0
                self._owner_tid = None
                self._cond.notify_all()

    def snapshot(self) -> Dict[str, Any]:
        with self._cond:
            stats = dict(self._stats)
            stats["owner_tid"] = self._owner_tid
            stats["owner_depth"] = self._depth
            stats["queue_depth"] = len(self._wait_queue)
            return stats


def _get_lock(resource: str) -> _FairReentrantLock:
    key = str(resource or "global_input").strip() or "global_input"
    with _LOCK_REGISTRY_GUARD:
        lock = _LOCK_REGISTRY.get(key)
        if lock is None:
            lock = _FairReentrantLock()
            _LOCK_REGISTRY[key] = lock
        return lock


def get_input_guard_stats(resource: Optional[str] = None) -> Dict[str, Any]:
    if resource is not None:
        lock = _get_lock(resource)
        return lock.snapshot()

    with _LOCK_REGISTRY_GUARD:
        items = list(_LOCK_REGISTRY.items())

    result: Dict[str, Any] = {}
    for name, lock in items:
        result[name] = lock.snapshot()
    return result


def get_input_lock_wait_warn_ms() -> float:
    raw = os.environ.get("LCA_INPUT_LOCK_WARN_WAIT_MS")
    if raw is None:
        return _DEFAULT_INPUT_LOCK_WARN_WAIT_MS
    try:
        value = float(raw)
    except Exception:
        return _DEFAULT_INPUT_LOCK_WARN_WAIT_MS
    if value <= 0:
        return _DEFAULT_INPUT_LOCK_WARN_WAIT_MS
    return value


def get_input_lock_timeout_seconds() -> float:
    raw = os.environ.get("LCA_INPUT_LOCK_TIMEOUT_SEC")
    if raw is None:
        return _DEFAULT_INPUT_LOCK_TIMEOUT_SEC
    try:
        value = float(raw)
    except Exception:
        return _DEFAULT_INPUT_LOCK_TIMEOUT_SEC
    if value <= 0:
        return _DEFAULT_INPUT_LOCK_TIMEOUT_SEC
    return value


def _normalize_lock_scope(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"global", "window", "auto"}:
        return text
    raise ValueError(f"未知输入锁范围: {value!r}")


def resolve_input_lock_resource(
    execution_mode: Any = None,
    target_hwnd: Any = None,
    task_type: str = "",
) -> str:
    scope = _normalize_lock_scope(os.environ.get("LCA_INPUT_LOCK_SCOPE", "auto"))
    mode_raw = str(execution_mode or "").strip()
    hwnd_value = None
    try:
        if target_hwnd not in (None, ""):
            hwnd_value = int(target_hwnd)
    except Exception:
        hwnd_value = None

    if scope == "global":
        return "global_input"
    if scope == "window":
        if hwnd_value is None:
            return "global_input"
        return f"window:{hwnd_value}"

    # auto:
    # 前台与录制回放等全局动作默认串行到全局输入资源
    if is_foreground_mode(mode_raw) or str(task_type or "").strip() == "录制回放":
        return "global_input"

    # 只要是非前台且有目标窗口，就按窗口维度加锁，避免误回退到全局串行。
    if hwnd_value is not None:
        return f"window:{hwnd_value}"

    return "global_input"


def _push_guard_resource(resource: str) -> None:
    stack = getattr(_GUARD_LOCAL, "stack", None)
    if stack is None:
        stack = []
        _GUARD_LOCAL.stack = stack
    stack.append(str(resource))


def _pop_guard_resource() -> None:
    stack = getattr(_GUARD_LOCAL, "stack", None)
    if not stack:
        return
    stack.pop()


def get_current_input_guard_resource() -> Optional[str]:
    stack = getattr(_GUARD_LOCAL, "stack", None)
    if not stack:
        return None
    return stack[-1]


def task_requires_input_lock(
    task_type: str,
    params: Optional[Dict[str, Any]] = None,
    task_module: Any = None,
) -> bool:
    # 任务模块可显式声明（最高优先级）
    if task_module is not None:
        marker = getattr(task_module, "REQUIRES_INPUT_LOCK", None)
        if isinstance(marker, bool):
            return marker

        fn = getattr(task_module, "requires_input_lock", None)
        if callable(fn):
            return bool(fn(params or {}))

    if task_type in _DEFAULT_INPUT_TASK_TYPES:
        return True

    return False


@contextmanager
def acquire_input_guard(
    *,
    owner: str = "",
    timeout: Optional[float] = None,
    resource: str = "global_input",
) -> Iterator[Tuple[bool, float]]:
    lock_resource = str(resource or "global_input").strip() or "global_input"
    lock = _get_lock(lock_resource)
    timeout_value = get_input_lock_timeout_seconds() if timeout is None else float(timeout)
    acquire_timeout = None if timeout_value <= 0 else timeout_value

    acquired, wait_ms = lock.acquire(timeout=acquire_timeout, owner=owner)
    try:
        if acquired:
            _push_guard_resource(lock_resource)
        yield acquired, wait_ms
    finally:
        if acquired:
            _pop_guard_resource()
            lock.release()
