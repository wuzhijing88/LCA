# -*- coding: utf-8 -*-
"""桌面分身 Child Session 的跨进程所有权租约。"""

from __future__ import annotations

import ctypes
import os
import threading
from typing import Optional


_MUTEX_NAME = "Local\\LCA.ChildSessionOwner"
_ERROR_ALREADY_EXISTS = 183

_LOCAL_LOCK = threading.Lock()


class ChildSessionLease:
    """用命名互斥体保证同一台机器只有一个 LCA 实例管理分身。"""

    def __init__(self) -> None:
        self._handle: Optional[int] = None
        self._local_held = False

    @property
    def held(self) -> bool:
        return self._handle is not None or self._local_held

    def acquire(self) -> bool:
        if self.held:
            return True
        if os.name != "nt":
            self._local_held = _LOCAL_LOCK.acquire(blocking=False)
            return self._local_held

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int
        kernel32.SetLastError.argtypes = [ctypes.c_uint]
        kernel32.SetLastError.restype = None
        kernel32.SetLastError(0)
        handle = kernel32.CreateMutexW(None, False, _MUTEX_NAME)
        if not handle:
            error = ctypes.get_last_error()
            raise OSError(error, f"无法创建桌面分身所有权锁（Win32 错误 {error}）")
        if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return False
        self._handle = int(handle)
        return True

    def release(self) -> None:
        if self._local_held:
            self._local_held = False
            _LOCAL_LOCK.release()
        handle = self._handle
        self._handle = None
        if handle is None or os.name != "nt":
            return
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int
        kernel32.CloseHandle(handle)

