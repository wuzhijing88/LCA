import ctypes
import os
import threading
from ctypes import wintypes
from typing import Optional


_state_lock = threading.Lock()
_setup_attempted = False


def get_process_dpi_awareness() -> Optional[int]:
    """返回当前进程 DPI 感知级别。0=unaware,1=system,2=per-monitor,3=per-monitor-v2。"""
    if getattr(ctypes, "windll", None) is None:
        return None

    try:
        shcore = ctypes.windll.shcore
        kernel32 = ctypes.windll.kernel32
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        shcore.GetProcessDpiAwareness.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_int)]
        shcore.GetProcessDpiAwareness.restype = getattr(ctypes, "HRESULT", ctypes.c_long)
        awareness = ctypes.c_int(-1)
        hr = shcore.GetProcessDpiAwareness(kernel32.GetCurrentProcess(), ctypes.byref(awareness))
        if hr == 0:
            return int(awareness.value)
    except Exception:
        pass

    try:
        user32 = ctypes.windll.user32
        user32.GetThreadDpiAwarenessContext.restype = wintypes.HANDLE
        user32.GetAwarenessFromDpiAwarenessContext.argtypes = [wintypes.HANDLE]
        user32.GetAwarenessFromDpiAwarenessContext.restype = ctypes.c_int
        awareness = int(user32.GetAwarenessFromDpiAwarenessContext(user32.GetThreadDpiAwarenessContext()))
        if awareness >= 0:
            return awareness
    except Exception:
        pass

    return None


def enable_process_dpi_awareness() -> Optional[int]:
    """尽早启用进程 DPI 感知。多次调用安全，只保留一条实现链路。"""
    global _setup_attempted

    if os.name != "nt":
        return None

    with _state_lock:
        if _setup_attempted:
            return get_process_dpi_awareness()
        _setup_attempted = True

    user32 = None
    try:
        user32 = ctypes.windll.user32
    except Exception:
        user32 = None

    if user32 is not None:
        try:
            dpi_context_per_monitor_v2 = ctypes.c_void_p(-4)
            if user32.SetProcessDpiAwarenessContext(dpi_context_per_monitor_v2):
                return get_process_dpi_awareness()
        except Exception:
            pass

    try:
        shcore = ctypes.windll.shcore
        process_per_monitor_dpi_aware = 2
        hr = shcore.SetProcessDpiAwareness(process_per_monitor_dpi_aware)
        if hr in (0, -2147024891):
            return get_process_dpi_awareness()
    except Exception:
        pass

    if user32 is not None:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass

    return get_process_dpi_awareness()
