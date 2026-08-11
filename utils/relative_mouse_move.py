# -*- coding: utf-8 -*-

"""Relative mouse move helpers."""

import math
import time
from typing import Callable, Optional

from utils.precise_sleep import precise_sleep


_MIN_RELATIVE_MOVE_STEP_SECONDS = 0.002


def _to_non_negative_float(value, default: float = 0.0) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return max(0.0, float(default))


def _resolve_step_count(distance: float, duration: float, smoothness: Optional[int]) -> int:
    safe_distance = max(0.0, float(distance))
    safe_duration = _to_non_negative_float(duration)

    steps = 0
    try:
        if smoothness is not None:
            steps = int(smoothness)
    except (TypeError, ValueError):
        steps = 0

    if steps <= 0:
        steps = max(1, int(safe_distance))

    if safe_distance > 0:
        steps = min(steps, max(1, int(safe_distance)))

    if safe_duration > 0:
        max_steps_by_duration = max(1, int(safe_duration / _MIN_RELATIVE_MOVE_STEP_SECONDS))
        steps = min(steps, max_steps_by_duration)
        if safe_distance > 1 and steps < 2:
            steps = 2

    return max(1, steps)


def _sleep_interruptibly(duration: float, stop_checker=None) -> bool:
    remaining = _to_non_negative_float(duration)
    if remaining <= 0:
        return True

    if stop_checker is None:
        precise_sleep(remaining)
        return True

    deadline = time.perf_counter() + remaining
    while True:
        if stop_checker():
            return False
        current_remaining = deadline - time.perf_counter()
        if current_remaining <= 0:
            return True
        precise_sleep(min(current_remaining, _MIN_RELATIVE_MOVE_STEP_SECONDS))


def generate_relative_path_points(offset_x: int, offset_y: int, steps: int, use_bezier: bool) -> list:
    """Build relative path points from (0, 0)."""
    if steps <= 1:
        return [(0.0, 0.0), (float(offset_x), float(offset_y))]

    dx = float(offset_x)
    dy = float(offset_y)
    distance = math.hypot(dx, dy)

    if use_bezier and distance > 0:
        perp_x = -dy / distance
        perp_y = dx / distance
        amplitude = min(100.0, distance * 0.2)
        control_x = dx * 0.5 + perp_x * amplitude
        control_y = dy * 0.5 + perp_y * amplitude

        def point_at(progress: float) -> tuple:
            inverse = 1.0 - progress
            x = (inverse * inverse * 0.0) + (2.0 * inverse * progress * control_x) + (progress * progress * dx)
            y = (inverse * inverse * 0.0) + (2.0 * inverse * progress * control_y) + (progress * progress * dy)
            return (x, y)
    else:
        def point_at(progress: float) -> tuple:
            eased = progress * progress * (3.0 - 2.0 * progress)
            return (dx * eased, dy * eased)

    points = [(0.0, 0.0)]
    for index in range(1, steps + 1):
        points.append(point_at(index / float(steps)))
    return points


def perform_timed_relative_move(
    offset_x: int,
    offset_y: int,
    duration: float,
    move_step: Callable[[int, int], bool],
    *,
    smoothness: Optional[int] = None,
    use_bezier: bool = False,
    stop_checker=None,
) -> bool:
    """Execute relative move across a duration."""
    total_x = int(offset_x)
    total_y = int(offset_y)
    if total_x == 0 and total_y == 0:
        return True

    safe_duration = _to_non_negative_float(duration)
    if safe_duration <= 0:
        return bool(move_step(total_x, total_y))

    distance = math.hypot(total_x, total_y)
    steps = _resolve_step_count(distance, safe_duration, smoothness)
    if steps <= 1:
        if not move_step(total_x, total_y):
            return False
        return _sleep_interruptibly(safe_duration, stop_checker)

    points = generate_relative_path_points(total_x, total_y, steps, use_bezier)
    step_delay = safe_duration / float(steps)

    prev_int_x = 0
    prev_int_y = 0
    for index in range(1, len(points)):
        if stop_checker and stop_checker():
            return False

        point_x, point_y = points[index]
        next_x = int(round(point_x))
        next_y = int(round(point_y))
        delta_x = next_x - prev_int_x
        delta_y = next_y - prev_int_y
        prev_int_x = next_x
        prev_int_y = next_y

        if delta_x != 0 or delta_y != 0:
            if not move_step(delta_x, delta_y):
                return False

        if not _sleep_interruptibly(step_delay, stop_checker):
            return False

    return True
