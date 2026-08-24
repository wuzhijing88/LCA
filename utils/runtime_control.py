#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""任务运行时控制工具。"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import Callable, Iterator, Optional

_ORIGINAL_SLEEP = time.sleep
_TLS = threading.local()
_CONTROL_SLEEP_SLICE = 0.01
_PATCH_INSTALLED = False


def _get_control_stack() -> list[Callable[[], bool]]:
    stack = getattr(_TLS, "control_stack", None)
    if stack is None:
        stack = []
        _TLS.control_stack = stack
    return stack


def _get_bypass_depth() -> int:
    return int(getattr(_TLS, "control_bypass_depth", 0) or 0)


def _set_bypass_depth(depth: int) -> None:
    _TLS.control_bypass_depth = max(0, int(depth or 0))


def get_thread_control_checker() -> Optional[Callable[[], bool]]:
    if _get_bypass_depth() > 0:
        return None
    stack = getattr(_TLS, "control_stack", None)
    if not stack:
        return None
    checker = stack[-1]
    return checker if callable(checker) else None


def poll_thread_control() -> bool:
    """轮询当前线程控制器。暂停时阻塞，停止时返回 True。"""
    checker = get_thread_control_checker()
    if checker is None:
        return False
    depth = _get_bypass_depth()
    _set_bypass_depth(depth + 1)
    try:
        return bool(checker())
    except Exception:
        return False
    finally:
        _set_bypass_depth(depth)


def controlled_sleep(duration: float) -> None:
    """带线程控制的 sleep。未注册控制器时退化为原生 sleep。"""
    try:
        total = float(duration)
    except (TypeError, ValueError):
        total = 0.0
    total = max(0.0, total)
    if total <= 0.0:
        return

    checker = get_thread_control_checker()
    if checker is None:
        _ORIGINAL_SLEEP(total)
        return

    deadline = time.perf_counter() + total
    while True:
        if poll_thread_control():
            return
        remaining = deadline - time.perf_counter()
        if remaining <= 0.0:
            return
        _ORIGINAL_SLEEP(min(_CONTROL_SLEEP_SLICE, remaining))


def install_global_sleep_patch() -> None:
    """全局替换 time.sleep，使任务线程自动具备暂停感知能力。"""
    global _PATCH_INSTALLED
    if _PATCH_INSTALLED:
        return
    time.sleep = controlled_sleep
    _PATCH_INSTALLED = True


@contextmanager
def thread_control_context(checker: Optional[Callable[[], bool]]) -> Iterator[None]:
    """为当前线程注册运行时控制器。"""
    if not callable(checker):
        yield
        return

    stack = _get_control_stack()
    stack.append(checker)
    try:
        yield
    finally:
        if stack:
            stack.pop()
