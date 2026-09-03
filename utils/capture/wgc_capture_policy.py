# -*- coding: utf-8 -*-
from dataclasses import dataclass
from typing import Any, Callable, Optional

from utils.window.hwnd_utils import as_hwnd


@dataclass(frozen=True)
class DetachedWgcResources:
    session: Any
    frame_pool: Any
    item: Any
    latest_frame: Any


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
        return target
    try:
        root = as_hwnd(get_root_hwnd(target))
    except Exception:
        return target
    return root or target


def detach_wgc_owned_resources(owner: Any) -> DetachedWgcResources:
    taken = DetachedWgcResources(
        session=getattr(owner, "session", None),
        frame_pool=getattr(owner, "frame_pool", None),
        item=getattr(owner, "item", None),
        latest_frame=getattr(owner, "latest_frame", None),
    )
    owner.session = None
    owner.frame_pool = None
    owner.item = None
    owner.latest_frame = None
    return taken
