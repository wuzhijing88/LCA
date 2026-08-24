#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一高精度睡眠实现。"""

import math
import time

from utils.runtime_control import poll_thread_control


def _to_non_negative_float(value, name: str) -> float:
    try:
        converted = float(value)
    except (TypeError, ValueError):
        raise TypeError(f"{name} 必须是有限数值") from None
    if not math.isfinite(converted) or converted < 0.0:
        raise ValueError(f"{name} 必须是大于等于零的有限数值")
    return converted


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
    total = _to_non_negative_float(duration, "duration")
    spin_tail = _to_non_negative_float(spin_threshold, "spin_threshold")
    spin_tail = min(spin_tail, 0.01)
    coarse_step = _to_non_negative_float(coarse_slice, "coarse_slice")
    if coarse_step <= 0.0:
        raise ValueError("coarse_slice 必须大于零")

    if total <= 0.0:
        return

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
