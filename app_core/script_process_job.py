"""Windows ownership boundary for a script worker and all of its descendants."""

from __future__ import annotations

import ctypes
import os
import threading
import time
from ctypes import wintypes


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("process_time", ctypes.c_int64),
        ("job_time", ctypes.c_int64),
        ("flags", wintypes.DWORD),
        ("minimum_working_set", ctypes.c_size_t),
        ("maximum_working_set", ctypes.c_size_t),
        ("active_processes", wintypes.DWORD),
        ("affinity", ctypes.c_size_t),
        ("priority", wintypes.DWORD),
        ("scheduling", wintypes.DWORD),
    ]


class _Counters(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_uint64)
        for name in (
            "read_operations",
            "write_operations",
            "other_operations",
            "read_bytes",
            "write_bytes",
            "other_bytes",
        )
    ]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("basic", _BasicLimits),
        ("counters", _Counters),
        ("process_memory", ctypes.c_size_t),
        ("job_memory", ctypes.c_size_t),
        ("peak_process_memory", ctypes.c_size_t),
        ("peak_job_memory", ctypes.c_size_t),
    ]


class ProcessJob:
    def __init__(self):
        if os.name != "nt":
            raise OSError("独立脚本进程管理仅支持 Windows")
        self._lock = threading.Lock()
        self._kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self._kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self._kernel.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        self._kernel.SetInformationJobObject.restype = wintypes.BOOL
        self._kernel.AssignProcessToJobObject.argtypes = [
            wintypes.HANDLE,
            wintypes.HANDLE,
        ]
        self._kernel.AssignProcessToJobObject.restype = wintypes.BOOL
        self._kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self._kernel.CloseHandle.restype = wintypes.BOOL
        self._handle = self._kernel.CreateJobObjectW(None, None)
        if not self._handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = _ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self._kernel.SetInformationJobObject(
            self._handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
        ):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def assign(self, process):
        with self._lock:
            if self._handle is None:
                raise OSError("脚本进程组已关闭")
            if process.poll() is not None:
                return
            if not self._kernel.AssignProcessToJobObject(
                self._handle, int(process._handle)
            ):
                raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        with self._lock:
            if self._handle is not None:
                if not self._kernel.CloseHandle(self._handle):
                    raise ctypes.WinError(ctypes.get_last_error())
                self._handle = None

    def terminate_and_wait(self, timeout: float = 10.0):
        """结束整个进程组，并等待子进程释放文件后再允许清理构建目录。"""
        with self._lock:
            if self._handle is None:
                return
            terminate = self._kernel.TerminateJobObject
            terminate.argtypes = [wintypes.HANDLE, wintypes.UINT]
            terminate.restype = wintypes.BOOL
            query = self._kernel.QueryInformationJobObject
            query.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
            query.restype = wintypes.BOOL
            open_process = self._kernel.OpenProcess
            open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            open_process.restype = wintypes.HANDLE
            wait = self._kernel.WaitForSingleObject
            wait.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            wait.restype = wintypes.DWORD
            # 作业的活动计数归零时，进程可能仍在关闭文件句柄。
            # 先保留所有进程句柄，逐个等待真正退出后才能删除构建日志。
            count = 64
            while True:
                class ProcessIds(ctypes.Structure):
                    _fields_ = [("assigned", wintypes.DWORD), ("listed", wintypes.DWORD), ("ids", ctypes.c_size_t * count)]
                processes = ProcessIds()
                if query(self._handle, 3, ctypes.byref(processes), ctypes.sizeof(processes), None):
                    break
                error = ctypes.get_last_error()
                if error != 234:
                    raise ctypes.WinError(error)
                count = max(count * 2, processes.assigned)
            handles = []
            deadline = time.monotonic() + timeout
            try:
                for pid in processes.ids[:processes.listed]:
                    handle = open_process(0x100000, False, pid)  # SYNCHRONIZE
                    if handle:
                        handles.append(handle)
                    elif ctypes.get_last_error() != 87:  # 已退出的进程无需再等待。
                        raise ctypes.WinError(ctypes.get_last_error())
                if not terminate(self._handle, 1):
                    raise ctypes.WinError(ctypes.get_last_error())
                for handle in handles:
                    result = wait(handle, max(0, int((deadline - time.monotonic()) * 1000)))
                    if result == 258:
                        raise TimeoutError("等待编译进程组退出超时")
                    if result != 0:
                        raise ctypes.WinError(ctypes.get_last_error())
            finally:
                for handle in handles:
                    self._kernel.CloseHandle(handle)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
