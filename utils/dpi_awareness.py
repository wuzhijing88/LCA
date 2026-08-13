import ctypes
import os
import threading
from ctypes import wintypes

# DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
_DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = wintypes.HANDLE(-4)
_ERROR_ACCESS_DENIED = 5

_state_lock = threading.Lock()
_setup_attempted = False
_user32 = None


def _load_user32():
    global _user32
    if _user32 is None:
        if os.name != "nt":
            raise RuntimeError("DPI awareness is only available on Windows")
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.SetProcessDpiAwarenessContext.argtypes = [wintypes.HANDLE]
        user32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
        user32.GetThreadDpiAwarenessContext.restype = wintypes.HANDLE
        user32.GetAwarenessFromDpiAwarenessContext.argtypes = [wintypes.HANDLE]
        user32.GetAwarenessFromDpiAwarenessContext.restype = ctypes.c_int
        user32.AreDpiAwarenessContextsEqual.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        user32.AreDpiAwarenessContextsEqual.restype = wintypes.BOOL
        _user32 = user32
    return _user32


def get_process_dpi_awareness() -> int:
    """Return 0=unaware, 1=system, 2=per-monitor (including per-monitor v2)."""
    user32 = _load_user32()
    awareness = int(user32.GetAwarenessFromDpiAwarenessContext(user32.GetThreadDpiAwarenessContext()))
    if awareness < 0:
        raise OSError("GetAwarenessFromDpiAwarenessContext failed")
    return awareness


def _is_per_monitor_v2() -> bool:
    user32 = _load_user32()
    return bool(
        user32.AreDpiAwarenessContextsEqual(
            user32.GetThreadDpiAwarenessContext(),
            _DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2,
        )
    )


def enable_process_dpi_awareness() -> int:
    """Request per-monitor v2. If the host already locked DPI, keep that level."""
    global _setup_attempted

    with _state_lock:
        if _setup_attempted:
            return get_process_dpi_awareness()
        _setup_attempted = True

    user32 = _load_user32()
    if user32.SetProcessDpiAwarenessContext(_DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2):
        return get_process_dpi_awareness()
    if _is_per_monitor_v2():
        return get_process_dpi_awareness()

    error_code = ctypes.get_last_error()
    if error_code == _ERROR_ACCESS_DENIED:
        # python.exe / packaged manifest already locked process DPI; it cannot be changed.
        return get_process_dpi_awareness()
    raise OSError(error_code, "SetProcessDpiAwarenessContext(PER_MONITOR_AWARE_V2) failed")
