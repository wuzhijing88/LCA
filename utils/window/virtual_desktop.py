# -*- coding: utf-8 -*-
from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes
from typing import Any, Callable, Iterable, Optional

from utils.input_simulation.mode_utils import is_foreground_mode
from utils.window.hwnd_utils import as_hwnd

logger = logging.getLogger(__name__)

DesktopProbe = Callable[[int], Optional[bool]]

FOREGROUND_OTHER_DESKTOP_MESSAGE = (
    "目标窗口不在当前虚拟桌面。\n\n"
    "前台执行会强制切换桌面，已取消启动。\n"
    "请改用后台模式，或把目标窗口移到当前桌面后再执行。"
)

_CLSID_VIRTUAL_DESKTOP_MANAGER = "{AA509086-5CA9-4C25-8F95-589D3C07B48A}"
_IID_IVIRTUAL_DESKTOP_MANAGER = "{A5CD92FF-29BE-454C-8D04-D82879FB3F1B}"


def skip_cross_desktop_activation(hwnd: Any, *, log_prefix: str = "") -> bool:
    if not should_skip_window_activation(hwnd):
        return False
    prefix = f"[{log_prefix}] " if log_prefix else ""
    logger.info("%s目标窗口不在当前虚拟桌面，跳过激活以免切换桌面", prefix)
    return True


def should_skip_window_activation(
    hwnd: Any,
    *,
    desktop_probe: Optional[DesktopProbe] = None,
) -> bool:
    handle = as_hwnd(hwnd)
    if not handle:
        return False
    probe = desktop_probe or is_window_on_current_virtual_desktop
    try:
        on_current = probe(handle)
    except Exception:
        return False
    return on_current is False


def should_block_execution_start(
    execution_mode: Optional[str],
    hwnds: Iterable[Any] = (),
    *,
    desktop_probe: Optional[DesktopProbe] = None,
) -> Optional[str]:
    if not is_foreground_mode(execution_mode):
        return None
    probe = desktop_probe or is_window_on_current_virtual_desktop
    for raw in hwnds:
        handle = as_hwnd(raw)
        if not handle:
            continue
        try:
            on_current = probe(handle)
        except Exception:
            continue
        if on_current is False:
            return FOREGROUND_OTHER_DESKTOP_MESSAGE
    return None


def is_window_on_current_virtual_desktop(hwnd: Any) -> Optional[bool]:
    handle = as_hwnd(hwnd)
    if not handle:
        return None
    top_level = _resolve_top_level_hwnd(handle)
    try:
        return _query_is_window_on_current_desktop(top_level)
    except Exception as exc:
        logger.debug("虚拟桌面检测失败: hwnd=%s err=%s", handle, exc)
        return None


def _resolve_top_level_hwnd(hwnd: int) -> int:
    try:
        import win32con
        import win32gui

        root = as_hwnd(win32gui.GetAncestor(hwnd, win32con.GA_ROOT))
        return root or hwnd
    except Exception:
        return hwnd


_COINIT_APARTMENTTHREADED = 0x2
_CLSCTX_INPROC_SERVER = 0x1
_RPC_E_CHANGED_MODE = 0x80010106


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def _guid(value: str) -> _GUID:
    import uuid

    return _GUID.from_buffer_copy(uuid.UUID(value).bytes_le)


class _IVirtualDesktopManagerVtbl(ctypes.Structure):
    _fields_ = [
        ("QueryInterface", ctypes.c_void_p),
        ("AddRef", ctypes.c_void_p),
        (
            "Release",
            ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p),
        ),
        (
            "IsWindowOnCurrentVirtualDesktop",
            ctypes.WINFUNCTYPE(
                ctypes.HRESULT,
                ctypes.c_void_p,
                wintypes.HWND,
                ctypes.POINTER(wintypes.BOOL),
            ),
        ),
    ]


class _IVirtualDesktopManager(ctypes.Structure):
    _fields_ = [("lpVtbl", ctypes.POINTER(_IVirtualDesktopManagerVtbl))]


def _ole32():
    ole32 = ctypes.WinDLL("ole32")
    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    ole32.CoInitializeEx.restype = ctypes.HRESULT
    ole32.CoCreateInstance.argtypes = [
        ctypes.POINTER(_GUID),
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_GUID),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    ole32.CoCreateInstance.restype = ctypes.HRESULT
    ole32.CoUninitialize.argtypes = []
    ole32.CoUninitialize.restype = None
    return ole32


def _query_is_window_on_current_desktop(hwnd: int) -> Optional[bool]:
    ole32 = _ole32()
    hr = int(ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED)) & 0xFFFFFFFF
    if hr not in (0, 1, _RPC_E_CHANGED_MODE):
        logger.debug("CoInitializeEx 失败: 0x%08X", hr)
        return None
    # S_FALSE(1) 表示本线程已初始化，不能 Uninitialize。
    should_uninit = hr == 0

    ptr = ctypes.c_void_p()
    try:
        create_hr = ole32.CoCreateInstance(
            ctypes.byref(_guid(_CLSID_VIRTUAL_DESKTOP_MANAGER)),
            None,
            _CLSCTX_INPROC_SERVER,
            ctypes.byref(_guid(_IID_IVIRTUAL_DESKTOP_MANAGER)),
            ctypes.byref(ptr),
        )
        if create_hr != 0 or not ptr.value:
            logger.debug(
                "CoCreateInstance IVirtualDesktopManager 失败: 0x%08X",
                create_hr & 0xFFFFFFFF,
            )
            return None
        obj = ctypes.cast(ptr, ctypes.POINTER(_IVirtualDesktopManager)).contents
        vtbl = obj.lpVtbl.contents
        on_current = wintypes.BOOL()
        query_hr = vtbl.IsWindowOnCurrentVirtualDesktop(
            ptr,
            wintypes.HWND(hwnd),
            ctypes.byref(on_current),
        )
        if query_hr != 0:
            logger.debug(
                "IsWindowOnCurrentVirtualDesktop 失败: hwnd=%s hr=0x%08X",
                hwnd,
                query_hr & 0xFFFFFFFF,
            )
            return None
        return bool(on_current.value)
    finally:
        if ptr.value:
            try:
                obj = ctypes.cast(ptr, ctypes.POINTER(_IVirtualDesktopManager)).contents
                obj.lpVtbl.contents.Release(ptr)
            except Exception:
                pass
        if should_uninit:
            try:
                ole32.CoUninitialize()
            except Exception:
                pass
