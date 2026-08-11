#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一高精度睡眠实现。"""

import time

from utils.runtime_control import poll_thread_control


def _to_non_negative_float(value, default: float = 0.0) -> float:
    try:
        converted = float(value)
    except (TypeError, ValueError):
        converted = float(default)
    return max(0.0, converted)


def precise_sleep(
    duration: float,
    *,
    spin_threshold: float = 0.002,
    coarse_slice: float = 0.01,
) -> None:
    """高精度睡眠。

    策略：
    1) 先用分片 sleep 让出 CPU（避免长时间忙等）。
    2) 最后 `spin_threshold` 时间段使用忙等保证精度。
    """
    total = _to_non_negative_float(duration)
    if total <= 0.0:
        return

    # 短时长优先纯忙等待，避免系统调度片导致的毫秒级抖动。
    if total <= 0.12:
        target_short = time.perf_counter() + total
        while time.perf_counter() < target_short:
            if poll_thread_control():
                return
            pass
        return

    spin_tail = _to_non_negative_float(spin_threshold, default=0.002)
    # 尾段忙等不宜过大，避免无意义高占用
    spin_tail = min(spin_tail, 0.01)

    coarse_step = _to_non_negative_float(coarse_slice, default=0.01)
    if coarse_step <= 0.0:
        coarse_step = 0.001

    target = time.perf_counter() + total

    while True:
        if poll_thread_control():
            return
        remaining = target - time.perf_counter()
        if remaining <= spin_tail:
            break

        sleep_for = min(coarse_step, remaining - spin_tail)
        if sleep_for >= 0.001:
            time.sleep(sleep_for)
        else:
            time.sleep(0)

    while time.perf_counter() < target:
        if poll_thread_control():
            return
        pass
