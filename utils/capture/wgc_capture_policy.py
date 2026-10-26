# -*- coding: utf-8 -*-
from typing import Callable, Optional

from utils.window.hwnd_utils import as_hwnd


def should_force_static_window_rebuild(
    *,
    now_ts: float,
    last_rebuild_ts: float,
    cooldown_sec: float,
) -> bool:
    if float(cooldown_sec) <= 0.0:
        return True
    if last_rebuild_ts <= 0.0:
        return True
    return (now_ts - last_rebuild_ts) >= float(cooldown_sec)


def should_crop_wgc_as_child(request_hwnd: int, capture_hwnd: int) -> bool:
    req = as_hwnd(request_hwnd)
    cap = as_hwnd(capture_hwnd)
    return req != 0 and cap != 0 and req != cap


def resolve_wgc_capture_hwnd(
    hwnd: int,
    *,
    get_root_hwnd: Optional[Callable[[int], int]] = None,
) -> int:
    target = as_hwnd(hwnd)
    if not target:
        return 0
    if get_root_hwnd is None:
        raise RuntimeError("缺少WGC顶层窗口解析器")
    root = as_hwnd(get_root_hwnd(target))
    if not root:
        raise RuntimeError("无法确定WGC捕获窗口")
    return root
