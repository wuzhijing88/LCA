#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按系统键盘重复率补发按住期间的连发。"""

from __future__ import annotations

import logging
import math
import time
from typing import Callable, Optional

from utils.input.input_timing import plan_key_repeat_times, read_system_keyboard_repeat

logger = logging.getLogger(__name__)


def _validate_hold_parameters(duration: float, repeat_interval: Optional[float]):
    try:
        hold = float(duration)
    except (TypeError, ValueError):
        raise ValueError("按住时长必须是大于等于0的有限秒数") from None
    if not math.isfinite(hold) or hold < 0:
        raise ValueError("按住时长必须是大于等于0的有限秒数")
    interval = None
    if repeat_interval is not None:
        try:
            interval = float(repeat_interval)
        except (TypeError, ValueError):
            raise ValueError("连发间隔必须是大于0的有限秒数") from None
        if not math.isfinite(interval) or interval <= 0:
            raise ValueError("连发间隔必须是大于0的有限秒数")
    return hold, interval


def run_system_repeat_schedule(
    *,
    repeat: Callable[[], bool],
    duration: float,
    sleep: Callable[[float], None],
    enable_repeat: bool,
    repeat_interval: Optional[float] = None,
    stop_checker: Optional[Callable[[], bool]] = None,
) -> bool:
    """按住期间按延迟/速率调用 repeat；enable_repeat 为假时只等待。"""
    def check_stop():
        if callable(stop_checker) and stop_checker():
            raise InterruptedError("按键操作已停止")

    def wait(seconds):
        check_stop()
        if not callable(stop_checker):
            sleep(seconds)
            return
        remaining = float(seconds)
        while remaining > 0:
            check_stop()
            step = min(remaining, 0.02)
            sleep(step)
            remaining -= step
        check_stop()

    check_stop()
    hold, interval = _validate_hold_parameters(duration, repeat_interval)
    if hold <= 0:
        return True
    if not enable_repeat:
        wait(hold)
        return True
    if interval is None:
        delay, interval = read_system_keyboard_repeat()
    else:
        delay = interval
    # 按计划时间点调度，而不是每次补发后重新完整等待一个间隔。
    # 补发动作（尤其是驱动层的松开/按下）本身有耗时，必须从剩余时长中扣除，
    # 否则连发次数越多，按住总时长就会越长。
    elapsed = 0.0
    clock_noise = 0.0005
    for stamp in plan_key_repeat_times(hold, delay, interval):
        gap = stamp - elapsed
        if gap > 0:
            started = time.perf_counter()
            wait(gap)
            actual = time.perf_counter() - started
            overshoot = actual - gap
            elapsed += gap + (overshoot if overshoot > clock_noise else 0.0)
        check_stop()
        if elapsed >= hold:
            break
        started = time.perf_counter()
        if not bool(repeat()):
            return False
        actual = time.perf_counter() - started
        elapsed += actual if actual > clock_noise else 0.0
    remaining = hold - elapsed
    if remaining > 0:
        wait(remaining)
    return True


def hold_with_system_repeat(
    *,
    down: Callable[[], bool],
    up: Callable[[], bool],
    repeat: Callable[[], bool],
    duration: float,
    sleep: Callable[[float], None],
    enable_repeat: bool = True,
    repeat_interval: Optional[float] = None,
    stop_checker: Optional[Callable[[], bool]] = None,
) -> bool:
    """先按下，可选按延迟/速率调用 repeat，最后松开。"""
    if callable(stop_checker) and stop_checker():
        raise InterruptedError("按键操作已停止")
    hold, interval = _validate_hold_parameters(duration, repeat_interval)
    if not bool(down()):
        return False
    held = True
    try:
        if not run_system_repeat_schedule(
            repeat=repeat,
            duration=hold,
            sleep=sleep,
            enable_repeat=enable_repeat,
            repeat_interval=interval,
            stop_checker=stop_checker,
        ):
            return False
        if not bool(up()):
            return False
        held = False
        return True
    finally:
        if held:
            try:
                up()
            except Exception:
                logger.exception("按键补松开失败")
