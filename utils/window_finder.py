#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一的窗口查找工具
"""

import ctypes
from ctypes import wintypes
import logging
import re
from typing import Iterable, Optional, Sequence, Tuple
import win32gui

from utils.window_coordinate_common import normalize_window_hwnd

logger = logging.getLogger(__name__)


def _normalize_hwnd_list(handles: Optional[Iterable[int]]) -> list[int]:
    """标准化 HWND 列表并去重，保持原有顺序。"""
    normalized: list[int] = []
    seen: set[int] = set()

    for handle in handles or []:
        try:
            hwnd = int(handle or 0)
        except Exception:
            continue
        if not hwnd or hwnd in seen:
            continue
        normalized.append(hwnd)
        seen.add(hwnd)

    return normalized


def sanitize_window_lookup_title(window_title: str) -> str:
    """清理仅用于显示的标题附加信息，保留实际窗口标题主体。"""
    title = str(window_title or '').strip()
    if not title:
        return ''

    cleaned = title
    previous = None
    while cleaned != previous:
        previous = cleaned
        cleaned = re.sub(r'\s+\(HWND:\s*[^)]*\)\s*$', '', cleaned).strip()
        cleaned = re.sub(r'\s+\[[^\[\]]+\]\s*$', '', cleaned).strip()

    return cleaned or title


def find_all_exact_window_hwnds(window_title: str) -> list[int]:
    """查找所有标题完全匹配的可见顶级窗口。"""
    if not window_title:
        return []

    found_windows = []

    def enum_callback(hwnd, windows):
        try:
            if win32gui.IsWindowVisible(hwnd):
                current_title = win32gui.GetWindowText(hwnd)
                if current_title == window_title:
                    windows.append(int(hwnd))
        except Exception as error:
            logger.debug(f"枚举精确匹配窗口失败: {error}")
        return True

    try:
        win32gui.EnumWindows(enum_callback, found_windows)
    except Exception as error:
        logger.error(f"枚举精确匹配窗口失败: {error}")

    return found_windows


def find_unique_exact_window_hwnd(window_title: str) -> Optional[int]:
    """查找唯一的标题完全匹配顶级窗口。"""
    if not window_title:
        return None

    logger.info(f"查找唯一精确窗口: '{window_title}'")
    exact_matches = find_all_exact_window_hwnds(window_title)
    if len(exact_matches) == 1:
        hwnd = exact_matches[0]
        logger.info(f"精确匹配找到唯一窗口: {hwnd}")
        return hwnd
    if len(exact_matches) > 1:
        logger.warning(f"找到多个同名窗口，拒绝自动选择: {window_title} -> {exact_matches}")
        return None

    logger.warning(f"未找到标题完全匹配的窗口: '{window_title}'")
    return None

class WindowFinder:
    """窗口查找兼容入口。"""

    find_window = staticmethod(lambda window_title: find_unique_exact_window_hwnd(window_title))
    find_all_windows = staticmethod(lambda window_title: find_all_exact_window_hwnds(window_title))
    find_all_windows_exact = staticmethod(lambda window_title: find_all_exact_window_hwnds(window_title))
    find_unique_window_exact = staticmethod(lambda window_title: find_unique_exact_window_hwnd(window_title))
    _find_all_standard_windows = staticmethod(lambda window_title: find_all_exact_window_hwnds(window_title))
    _find_standard_window = staticmethod(lambda window_title: find_unique_exact_window_hwnd(window_title))
    list_all_windows = staticmethod(lambda: list_all_windows())


def list_all_windows():
    """列出所有可见窗口。"""
    user32 = ctypes.windll.user32
    windows = []

    def enum_callback(hwnd, lParam):
        try:
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buff, length + 1)
                    title = buff.value

                    class_name = ctypes.create_unicode_buffer(256)
                    user32.GetClassNameW(hwnd, class_name, 256)

                    if title.strip():
                        windows.append({
                            'hwnd': hwnd,
                            'title': title,
                            'class_name': class_name.value
                        })
        except Exception as e:
            logger.debug(f"枚举窗口时出错: {e}")
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(enum_callback), 0)

    return windows


def resolve_unique_window_hwnd(window_title: str):
    """查找并标准化唯一窗口句柄。"""
    hwnd = find_unique_exact_window_hwnd(window_title)
    normalized_hwnd, _ = normalize_window_hwnd(hwnd, title_hint=window_title)
    return normalized_hwnd or None


def resolve_exact_window_match(
    window_title: str,
    exact_hwnds: Sequence[int],
    *,
    preferred_hwnds: Optional[Iterable[int]] = None,
    prefer_preferred: bool = False,
    prefer_unpreferred: bool = False,
) -> Optional[int]:
    """按策略从多个同名顶级窗口中解析唯一句柄。"""
    matches = _normalize_hwnd_list(exact_hwnds)
    if not matches:
        return None

    if len(matches) == 1:
        hwnd = matches[0]
        logger.info(f"精确匹配找到唯一窗口: {window_title} -> {hwnd}")
        return hwnd

    preferred_set = set(_normalize_hwnd_list(preferred_hwnds))
    preferred_matches = [hwnd for hwnd in matches if hwnd in preferred_set]
    unpreferred_matches = [hwnd for hwnd in matches if hwnd not in preferred_set]

    if prefer_preferred and len(preferred_matches) == 1:
        hwnd = preferred_matches[0]
        logger.info(f"在多个同名窗口中命中唯一优先窗口: {window_title} -> {hwnd}")
        return hwnd

    if prefer_unpreferred and len(unpreferred_matches) == 1:
        hwnd = unpreferred_matches[0]
        logger.info(f"在多个同名窗口中命中唯一未绑定窗口: {window_title} -> {hwnd}")
        return hwnd

    logger.warning(f"找到多个同名顶级窗口，拒绝自动选择: {window_title} -> {matches}")
    return None


def find_window_with_parent_info(
    window_title: str,
    *,
    preferred_hwnds: Optional[Iterable[int]] = None,
    prefer_preferred: bool = False,
    prefer_unpreferred: bool = False,
) -> Tuple[Optional[int], bool, Optional[int]]:
    """查找窗口并返回父窗口信息；若顶级精确匹配已存在但不唯一，则拒绝回退到子窗口搜索。"""
    if not window_title:
        return None, False, None

    exact_matches = find_all_exact_window_hwnds(window_title)
    resolved_exact = resolve_exact_window_match(
        window_title,
        exact_matches,
        preferred_hwnds=preferred_hwnds,
        prefer_preferred=prefer_preferred,
        prefer_unpreferred=prefer_unpreferred,
    )
    if resolved_exact:
        return resolved_exact, False, None

    if exact_matches:
        return None, False, None

    found_hwnd: Optional[int] = None
    parent_hwnd: Optional[int] = None

    def enum_windows_proc(hwnd, _):
        nonlocal found_hwnd, parent_hwnd

        try:
            def enum_child_proc(child_hwnd, __):
                nonlocal found_hwnd, parent_hwnd
                try:
                    if win32gui.GetWindowText(child_hwnd) == window_title:
                        found_hwnd = int(child_hwnd)
                        parent_hwnd = int(hwnd)
                        logger.info(
                            f"找到匹配的子窗口: {window_title} "
                            f"(HWND: {found_hwnd}, 父窗口: {parent_hwnd})"
                        )
                        return False
                except Exception as error:
                    logger.debug(f"枚举子窗口失败: {error}")
                return True

            win32gui.EnumChildWindows(hwnd, enum_child_proc, 0)
        except Exception as error:
            logger.debug(f"枚举子窗口失败: {error}")

        return found_hwnd is None

    try:
        win32gui.EnumWindows(enum_windows_proc, 0)
    except Exception as error:
        logger.error(f"枚举窗口时出错: {error}")

    if found_hwnd:
        return found_hwnd, True, parent_hwnd

    logger.warning(f"未找到标题为 '{window_title}' 的窗口（包括子窗口）")
    return None, False, None
