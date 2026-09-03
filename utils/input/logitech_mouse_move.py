# -*- coding: utf-8 -*-
"""罗技虚拟鼠标只吃相对位移。

IbInputSimulator 把 MOUSEEVENTF_ABSOLUTE 的 dx/dy 当成 0~65536 归一化值：
`MulDiv(value, screen_size, 65536)`。若直接塞屏幕像素，常见点击点会塌到
屏幕原点附近，表现为找图成功但鼠标飞到 (0, 0)。
"""

from __future__ import annotations

from typing import Literal, Tuple

MoveKind = Literal["noop", "relative"]


def logitech_pixels_as_absolute_collapse(
    pixel_x: int,
    pixel_y: int,
    screen_width: int = 1920,
    screen_height: int = 1080,
) -> Tuple[int, int]:
    """复现 DLL 把像素误当归一化绝对坐标时的落点。"""
    width = max(1, int(screen_width))
    height = max(1, int(screen_height))
    return int(pixel_x) * width // 65536, int(pixel_y) * height // 65536


def plan_logitech_absolute_move(
    target_x: int,
    target_y: int,
    current_x: int,
    current_y: int,
    tolerance: int = 1,
) -> Tuple[MoveKind, int, int]:
    """把屏幕像素目标收成相对位移，禁止再发像素级绝对包。"""
    dx = int(target_x) - int(current_x)
    dy = int(target_y) - int(current_y)
    safe_tolerance = max(0, int(tolerance))
    if abs(dx) <= safe_tolerance and abs(dy) <= safe_tolerance:
        return "noop", 0, 0
    return "relative", dx, dy
