#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
窗口句柄截图公共工具。

统一处理：
- 子窗口句柄归一化
- DWM 边界获取
- 基于目标句柄的客户区/窗口区裁剪
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    cv2 = None
    CV2_AVAILABLE = False

try:
    import ctypes
    from ctypes import wintypes
    import win32gui
    WIN32_AVAILABLE = True
except ImportError:
    ctypes = None
    wintypes = None
    win32gui = None
    WIN32_AVAILABLE = False


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CaptureTargetInfo:
    target_hwnd: int
    capture_hwnd: int
    is_child_window: bool


def resolve_capture_target(hwnd: int) -> CaptureTargetInfo:
    """解析截图目标句柄。子窗口统一映射到顶层父窗口。"""
    target_hwnd = int(hwnd or 0)
    capture_hwnd = target_hwnd
    is_child_window = False

    if not target_hwnd or not WIN32_AVAILABLE:
        return CaptureTargetInfo(target_hwnd=target_hwnd, capture_hwnd=capture_hwnd, is_child_window=False)

    try:
        root_hwnd = int(win32gui.GetAncestor(target_hwnd, 2) or 0)
        if root_hwnd and root_hwnd != target_hwnd:
            capture_hwnd = root_hwnd
            is_child_window = True
    except Exception as exc:
        logger.debug(f"解析顶层窗口失败: hwnd={target_hwnd}, error={exc}")

    return CaptureTargetInfo(
        target_hwnd=target_hwnd,
        capture_hwnd=capture_hwnd,
        is_child_window=is_child_window,
    )


def get_window_rect_with_dwm(hwnd: int) -> Optional[Tuple[int, int, int, int]]:
    """使用 DWM 获取窗口实际可见边界。"""
    if not hwnd or not WIN32_AVAILABLE or ctypes is None or wintypes is None:
        return None

    try:
        dwmapi = ctypes.windll.dwmapi
        rect = wintypes.RECT()
        result = dwmapi.DwmGetWindowAttribute(
            wintypes.HWND(int(hwnd)),
            wintypes.DWORD(9),
            ctypes.byref(rect),
            ctypes.sizeof(rect),
        )
        if result == 0:
            return (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))
    except Exception as exc:
        logger.debug(f"DWM 边界获取失败: hwnd={hwnd}, error={exc}")

    return None


def get_screen_rect(hwnd: int, client_area_only: bool) -> Optional[Tuple[int, int, int, int]]:
    """获取目标句柄在屏幕坐标系中的逻辑矩形。"""
    if not hwnd or not WIN32_AVAILABLE:
        return None

    try:
        if client_area_only:
            rect = win32gui.GetClientRect(hwnd)
            width = int(rect[2] - rect[0])
            height = int(rect[3] - rect[1])
            if width <= 0 or height <= 0:
                return None
            left, top = win32gui.ClientToScreen(hwnd, (0, 0))
            return (int(left), int(top), int(left + width), int(top + height))

        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        if int(right) <= int(left) or int(bottom) <= int(top):
            return None
        return (int(left), int(top), int(right), int(bottom))
    except Exception as exc:
        logger.debug(f"屏幕矩形获取失败: hwnd={hwnd}, client={client_area_only}, error={exc}")
        return None


def build_crop_candidate(
    frame_w: int,
    frame_h: int,
    base_rect: Tuple[int, int, int, int],
    target_rect: Tuple[int, int, int, int],
) -> Optional[Tuple[int, int, int, int, float, int]]:
    """基于屏幕矩形构建裁剪候选。"""
    if frame_w <= 0 or frame_h <= 0:
        return None
    if not base_rect or len(base_rect) != 4:
        return None
    if not target_rect or len(target_rect) != 4:
        return None

    base_left, base_top, base_right, base_bottom = [int(v) for v in base_rect]
    target_left, target_top, target_right, target_bottom = [int(v) for v in target_rect]

    base_w = int(base_right - base_left)
    base_h = int(base_bottom - base_top)
    target_w = int(target_right - target_left)
    target_h = int(target_bottom - target_top)
    if base_w <= 0 or base_h <= 0 or target_w <= 0 or target_h <= 0:
        return None

    scale_x = float(frame_w) / float(base_w)
    scale_y = float(frame_h) / float(base_h)

    offset_x = int(round((target_left - base_left) * scale_x))
    offset_y = int(round((target_top - base_top) * scale_y))
    expected_w = max(1, int(round(target_w * scale_x)))
    expected_h = max(1, int(round(target_h * scale_y)))

    crop_x = max(0, min(offset_x, frame_w - 1))
    crop_y = max(0, min(offset_y, frame_h - 1))
    crop_w = min(expected_w, frame_w - crop_x)
    crop_h = min(expected_h, frame_h - crop_y)
    if crop_w <= 0 or crop_h <= 0:
        return None

    expected_area = max(1, expected_w * expected_h)
    actual_area = crop_w * crop_h
    coverage = float(actual_area) / float(expected_area)
    penalty = (
        abs(crop_x - offset_x)
        + abs(crop_y - offset_y)
        + abs(crop_w - expected_w)
        + abs(crop_h - expected_h)
    )
    return (crop_x, crop_y, crop_w, crop_h, coverage, penalty)


def crop_frame_by_hwnd(
    frame: np.ndarray,
    target_hwnd: int,
    capture_hwnd: int,
    client_area_only: bool,
    capture_window_rect: Optional[Tuple[int, int, int, int]],
    capture_dwm_rect: Optional[Tuple[int, int, int, int]] = None,
    min_coverage: float = 0.98,
    max_size_delta: int = 2,
) -> Optional[np.ndarray]:
    """把 capture_hwnd 的截图，裁成 target_hwnd 对应区域。"""
    if frame is None:
        return None
    if not WIN32_AVAILABLE:
        return frame

    frame_h, frame_w = frame.shape[:2]
    if frame_h <= 0 or frame_w <= 0:
        return None

    target_rect = get_screen_rect(target_hwnd, client_area_only=client_area_only)
    if target_rect is None:
        logger.error(
            f"句柄裁剪失败: 无法获取目标矩形, target={target_hwnd}, capture={capture_hwnd}, client={client_area_only}"
        )
        return None

    target_w = int(target_rect[2] - target_rect[0])
    target_h = int(target_rect[3] - target_rect[1])

    candidates: List[Tuple[int, int, int, int, float, int]] = []
    seen_base_rects = set()
    for base_rect in (capture_window_rect, capture_dwm_rect):
        if not base_rect:
            continue
        normalized = tuple(int(v) for v in base_rect)
        if normalized in seen_base_rects:
            continue
        seen_base_rects.add(normalized)
        item = build_crop_candidate(
            frame_w=frame_w,
            frame_h=frame_h,
            base_rect=normalized,
            target_rect=target_rect,
        )
        if item is not None:
            candidates.append(item)

    if not candidates:
        logger.error(
            f"句柄裁剪失败: 无可用裁剪候选, target={target_hwnd}, capture={capture_hwnd}, client={client_area_only}"
        )
        return None

    best_candidate = candidates[0]
    for item in candidates[1:]:
        if (item[4] > best_candidate[4]) or (item[4] == best_candidate[4] and item[5] < best_candidate[5]):
            best_candidate = item

    crop_x, crop_y, crop_w, crop_h, coverage, _penalty = best_candidate
    if coverage < float(min_coverage):
        logger.error(
            f"句柄裁剪失败: 覆盖率不足, target={target_hwnd}, capture={capture_hwnd}, coverage={coverage:.3f}, expected={target_w}x{target_h}, actual={crop_w}x{crop_h}"
        )
        return None

    cropped = frame[crop_y:crop_y + crop_h, crop_x:crop_x + crop_w].copy()
    if cropped.size == 0:
        return None

    if abs(crop_w - target_w) > int(max_size_delta) or abs(crop_h - target_h) > int(max_size_delta):
        logger.error(
            f"句柄裁剪失败: 尺寸偏差过大, target={target_hwnd}, capture={capture_hwnd}, expected={target_w}x{target_h}, actual={crop_w}x{crop_h}"
        )
        return None

    if (crop_w != target_w or crop_h != target_h) and CV2_AVAILABLE:
        cropped = cv2.resize(cropped, (target_w, target_h), interpolation=cv2.INTER_LINEAR)

    return cropped
