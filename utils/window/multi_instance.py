# -*- coding: utf-8 -*-
"""通用程序多开：关闭命名互斥句柄、占用互斥体、或直接启动。"""

from __future__ import annotations

import ctypes
import logging
import os
import re
import subprocess
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass, field
from typing import Callable, Iterable, List, Optional, Sequence, Set

from utils.window.hwnd_utils import as_hwnd, get_window_text

logger = logging.getLogger(__name__)

MODE_CLOSE_MUTEX = "close_mutex"
MODE_OCCUPY_MUTEX = "occupy_mutex"
MODE_DIRECT = "direct"

MODE_LABELS = (
    (MODE_CLOSE_MUTEX, "关闭互斥句柄（通用）"),
    (MODE_OCCUPY_MUTEX, "占用互斥体（微信/QQ 类）"),
    (MODE_DIRECT, "直接启动"),
)

PROCESS_DUP_HANDLE = 0x0040
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_ACCESS = (
    PROCESS_DUP_HANDLE | PROCESS_QUERY_INFORMATION | PROCESS_QUERY_LIMITED_INFORMATION
)
DUPLICATE_CLOSE_SOURCE = 0x00000001
DUPLICATE_SAME_ACCESS = 0x00000002
ERROR_ALREADY_EXISTS = 183
ERROR_ACCESS_DENIED = 5
STATUS_INFO_LENGTH_MISMATCH = 0xC0000004
STATUS_BUFFER_OVERFLOW = 0x80000005
STATUS_BUFFER_TOO_SMALL = 0xC0000023
STATUS_OBJECT_NAME_NOT_FOUND = 0xC0000034
ProcessHandleInformation = 51
ObjectNameInformation = 1
ObjectTypeInformation = 2
SE_KERNEL_OBJECT = 6
DACL_SECURITY_INFORMATION = 0x00000004
MUTEX_ALL_ACCESS = 0x001F0001
ACL_REVISION = 2
TOKEN_ADJUST_PRIVILEGES = 0x0020
TOKEN_QUERY = 0x0008
SE_PRIVILEGE_ENABLED = 0x00000002
GW_OWNER = 4

_SESSION_OBJECT_PREFIX = re.compile(r"^\\Sessions\\\d+\\BaseNamedObjects\\", re.IGNORECASE)
_GLOBAL_OBJECT_PREFIX = re.compile(r"^\\BaseNamedObjects\\", re.IGNORECASE)
_LOCK_NAME_MARKERS = (
    "instance",
    "singleton",
    "singleinstance",
    "already",
    "exist",
    "identity",
    "oneinstance",
    "app_instance",
    "check for other",
    "other instance",
    "onlyone",
    "unique",
)
_LAUNCHER_NAME_MARKERS = ("launch", "launcher", "startgame", "patcher", "updater", "启动器")
_HELPER_EXE_STEMS = {
    "ffmpeg",
    "cefclient",
    "crashpad_handler",
}
_SYSTEM_MUTEX_MARKERS = (
    "wilstaging",
    "wilerror",
    "sm0:",
    "dbwinmutex",
    "midimapper",
    "ddraw",
    "raspbfile",
    "zonescache",
    "zoneslocked",
    "cc_trace_event",
    "mpay_ipc",
    "shimsharedmemory",
    "windows_immersive",
)

LogFn = Callable[[str], None]
StopFn = Callable[[], bool]


def _is_stopped(should_stop: Optional[StopFn] = None) -> bool:
    return bool(should_stop and should_stop())


def _interruptible_sleep(seconds: float, should_stop: Optional[StopFn] = None) -> bool:
    """Sleep up to seconds. Return True if stopped."""
    deadline = time.time() + max(0.0, float(seconds))
    while time.time() < deadline:
        if _is_stopped(should_stop):
            return True
        time.sleep(min(0.1, max(0.0, deadline - time.time())))
    return _is_stopped(should_stop)


class UNICODE_STRING(ctypes.Structure):
    _fields_ = [
        ("Length", wintypes.USHORT),
        ("MaximumLength", wintypes.USHORT),
        ("Buffer", ctypes.c_void_p),
    ]


class PROCESS_HANDLE_TABLE_ENTRY_INFO(ctypes.Structure):
    _fields_ = [
        ("HandleValue", ctypes.c_void_p),
        ("HandleCount", ctypes.c_size_t),
        ("PointerCount", ctypes.c_size_t),
        ("GrantedAccess", wintypes.DWORD),
        ("ObjectTypeIndex", wintypes.ULONG),
        ("HandleAttributes", wintypes.ULONG),
        ("Reserved", wintypes.ULONG),
    ]


class PROCESS_HANDLE_SNAPSHOT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("NumberOfHandles", ctypes.c_size_t),
        ("Reserved", ctypes.c_size_t),
        ("Handles", PROCESS_HANDLE_TABLE_ENTRY_INFO * 1),
    ]


class SID_IDENTIFIER_AUTHORITY(ctypes.Structure):
    _fields_ = [("Value", ctypes.c_ubyte * 6)]


class LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]


class LUID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Luid", LUID), ("Attributes", wintypes.DWORD)]


class TOKEN_PRIVILEGES(ctypes.Structure):
    _fields_ = [("PrivilegeCount", wintypes.DWORD), ("Privileges", LUID_AND_ATTRIBUTES * 1)]


_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_ntdll = ctypes.WinDLL("ntdll")
_advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
_shell32 = ctypes.WinDLL("shell32", use_last_error=True)

_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL
_kernel32.GetCurrentProcess.restype = wintypes.HANDLE
_kernel32.DuplicateHandle.argtypes = [
    wintypes.HANDLE,
    wintypes.HANDLE,
    wintypes.HANDLE,
    ctypes.POINTER(wintypes.HANDLE),
    wintypes.DWORD,
    wintypes.BOOL,
    wintypes.DWORD,
]
_kernel32.DuplicateHandle.restype = wintypes.BOOL
_kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.SetLastError.argtypes = [wintypes.DWORD]
_kernel32.SetLastError.restype = None
_kernel32.LocalFree.argtypes = [ctypes.c_void_p]
_kernel32.LocalFree.restype = ctypes.c_void_p
_advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
_advapi32.OpenProcessToken.restype = wintypes.BOOL
_advapi32.LookupPrivilegeValueW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.POINTER(LUID)]
_advapi32.LookupPrivilegeValueW.restype = wintypes.BOOL
_advapi32.AdjustTokenPrivileges.argtypes = [
    wintypes.HANDLE,
    wintypes.BOOL,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.c_void_p,
    ctypes.c_void_p,
]
_advapi32.AdjustTokenPrivileges.restype = wintypes.BOOL
_advapi32.AllocateAndInitializeSid.argtypes = [
    ctypes.POINTER(SID_IDENTIFIER_AUTHORITY),
    ctypes.c_ubyte,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.POINTER(ctypes.c_void_p),
]
_advapi32.AllocateAndInitializeSid.restype = wintypes.BOOL
_advapi32.InitializeAcl.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD]
_advapi32.InitializeAcl.restype = wintypes.BOOL
_advapi32.AddAccessDeniedAce.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
_advapi32.AddAccessDeniedAce.restype = wintypes.BOOL
_advapi32.SetSecurityInfo.argtypes = [
    wintypes.HANDLE,
    ctypes.c_int,
    wintypes.DWORD,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_void_p,
]
_advapi32.SetSecurityInfo.restype = wintypes.DWORD
_advapi32.FreeSid.argtypes = [ctypes.c_void_p]
_advapi32.FreeSid.restype = ctypes.c_void_p
_ntdll.NtQueryInformationProcess.argtypes = [
    wintypes.HANDLE,
    ctypes.c_int,
    ctypes.c_void_p,
    wintypes.ULONG,
    ctypes.POINTER(wintypes.ULONG),
]
_ntdll.NtQueryInformationProcess.restype = ctypes.c_long
_ntdll.NtQueryObject.argtypes = [
    wintypes.HANDLE,
    ctypes.c_int,
    ctypes.c_void_p,
    wintypes.ULONG,
    ctypes.POINTER(wintypes.ULONG),
]
_ntdll.NtQueryObject.restype = ctypes.c_long
_shell32.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
_shell32.CommandLineToArgvW.restype = ctypes.POINTER(ctypes.c_wchar_p)


def _nt_code(status: int) -> int:
    return int(status) & 0xFFFFFFFF


def _nt_ok(status: int) -> bool:
    return int(status) >= 0


def _emit(log: Optional[LogFn], message: str) -> None:
    logger.info(message)
    if log is not None:
        log(message)


def parse_mutex_names(text: str) -> List[str]:
    names: List[str] = []
    seen: Set[str] = set()
    for raw in str(text or "").replace(",", "\n").splitlines():
        name = raw.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names


def split_launch_args(text: str) -> List[str]:
    raw = str(text or "").strip()
    if not raw:
        return []
    argc = ctypes.c_int(0)
    argv = _shell32.CommandLineToArgvW(raw, ctypes.byref(argc))
    if not argv:
        return [raw]
    try:
        return [argv[index] for index in range(int(argc.value))]
    finally:
        _kernel32.LocalFree(argv)


def kernel_path_to_mutex_name(path: str) -> str:
    name = str(path or "").strip()
    if not name:
        return ""
    session_match = _SESSION_OBJECT_PREFIX.match(name)
    if session_match:
        rest = name[session_match.end() :]
        return rest
    global_match = _GLOBAL_OBJECT_PREFIX.match(name)
    if global_match:
        rest = name[global_match.end() :]
        if rest.lower().startswith("global\\"):
            return rest
        return f"Global\\{rest}"
    return name.lstrip("\\")


def looks_like_instance_lock(name: str) -> bool:
    key = kernel_path_to_mutex_name(name).lower()
    if not key or is_system_mutex(name):
        return False
    return any(marker in key for marker in _LOCK_NAME_MARKERS)


def is_system_mutex(name: str) -> bool:
    key = kernel_path_to_mutex_name(name).lower()
    if not key:
        return True
    return any(marker in key for marker in _SYSTEM_MUTEX_MARKERS)


def exe_stem(path: str) -> str:
    return os.path.splitext(os.path.basename(str(path or "").strip()))[0].lower()


def is_app_instance_mutex(name: str, stems: Sequence[str] = ()) -> bool:
    if is_system_mutex(name):
        return False
    key = kernel_path_to_mutex_name(name).lower()
    if looks_like_instance_lock(name):
        return True
    for stem in stems:
        token = str(stem or "").strip().lower()
        if len(token) >= 3 and token in key:
            return True
    return False


@dataclass(frozen=True)
class KernelObject:
    pid: int
    handle: int
    type_name: str
    name: str

    @property
    def mutex_name(self) -> str:
        return kernel_path_to_mutex_name(self.name)


def object_matches_names(obj: KernelObject, names: Sequence[str]) -> bool:
    targets = [str(item).strip().lower() for item in names if str(item).strip()]
    if not targets:
        return False
    candidates = [
        obj.name.lower(),
        obj.mutex_name.lower(),
        kernel_path_to_mutex_name(obj.name).lower(),
    ]
    for target in targets:
        converted = kernel_path_to_mutex_name(target).lower()
        if len(converted) < 3:
            continue
        for candidate in candidates:
            if not candidate or is_system_mutex(candidate):
                continue
            if target == candidate or converted == candidate:
                return True
            if len(converted) >= 4 and (converted in candidate or candidate in converted):
                return True
    return False


class MutexOccupancy:
    """在本进程持有命名互斥体，并拒绝其它进程取得同一对象。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._handles: List[int] = []
        self._names: List[str] = []

    def names(self) -> List[str]:
        with self._lock:
            return list(self._names)

    def occupy(self, names: Sequence[str]) -> List[str]:
        occupied: List[str] = []
        for name in names:
            mutex_name = kernel_path_to_mutex_name(name)
            if not mutex_name:
                continue
            _kernel32.SetLastError(0)
            handle = _kernel32.CreateMutexW(None, False, mutex_name)
            error = ctypes.get_last_error()
            if not handle:
                if error == ERROR_ACCESS_DENIED:
                    occupied.append(mutex_name)
                    continue
                raise OSError(error, f"CreateMutexW 失败: {mutex_name}")
            try:
                _deny_everyone_mutex(handle)
            except OSError:
                _kernel32.CloseHandle(handle)
                raise
            with self._lock:
                self._handles.append(int(handle))
                if mutex_name not in self._names:
                    self._names.append(mutex_name)
            occupied.append(mutex_name)
        return occupied

    def close(self) -> None:
        with self._lock:
            handles = list(self._handles)
            self._handles.clear()
            self._names.clear()
        for handle in handles:
            _kernel32.CloseHandle(handle)


@dataclass
class LaunchRequest:
    exe_path: str
    arguments: str = ""
    working_dir: str = ""
    count: int = 1
    interval_sec: float = 1.0
    mode: str = MODE_CLOSE_MUTEX
    mutex_names: List[str] = field(default_factory=list)
    heuristic_only: bool = True
    window_timeout_sec: float = 15.0


@dataclass
class LaunchResult:
    pids: List[int] = field(default_factory=list)
    windows: List[dict] = field(default_factory=list)
    closed_objects: List[str] = field(default_factory=list)
    occupied_names: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    logs: List[str] = field(default_factory=list)


def enable_debug_privilege() -> bool:
    token = wintypes.HANDLE()
    if not _advapi32.OpenProcessToken(
        _kernel32.GetCurrentProcess(),
        TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY,
        ctypes.byref(token),
    ):
        return False
    try:
        luid = LUID()
        if not _advapi32.LookupPrivilegeValueW(None, "SeDebugPrivilege", ctypes.byref(luid)):
            return False
        privileges = TOKEN_PRIVILEGES()
        privileges.PrivilegeCount = 1
        privileges.Privileges[0].Luid = luid
        privileges.Privileges[0].Attributes = SE_PRIVILEGE_ENABLED
        return bool(
            _advapi32.AdjustTokenPrivileges(
                token, False, ctypes.byref(privileges), 0, None, None
            )
        )
    finally:
        _kernel32.CloseHandle(token)


def list_named_kernel_objects(
    pid: int,
    types: Sequence[str] = ("Mutant",),
) -> List[KernelObject]:
    wanted = {str(item).strip() for item in types if str(item).strip()}
    process = _kernel32.OpenProcess(PROCESS_ACCESS, False, int(pid))
    if not process:
        raise OSError(ctypes.get_last_error(), f"OpenProcess 失败: pid={pid}")
    try:
        entries = _query_process_handle_entries(process)
        type_by_index: dict[int, str] = {}
        found: List[KernelObject] = []
        for handle_value, type_index in entries:
            type_name = type_by_index.get(type_index)
            if type_name is None:
                type_name = _duplicate_query_type(process, handle_value)
                type_by_index[type_index] = type_name
            if wanted and type_name not in wanted:
                continue
            object_name = _duplicate_query_name(process, handle_value)
            if not object_name:
                continue
            found.append(
                KernelObject(
                    pid=int(pid),
                    handle=int(handle_value),
                    type_name=type_name,
                    name=object_name,
                )
            )
        return found
    finally:
        _kernel32.CloseHandle(process)


def close_kernel_objects(objects: Sequence[KernelObject]) -> int:
    closed = 0
    grouped: dict[int, List[KernelObject]] = {}
    for obj in objects:
        grouped.setdefault(int(obj.pid), []).append(obj)
    for pid, items in grouped.items():
        process = _kernel32.OpenProcess(PROCESS_DUP_HANDLE, False, pid)
        if not process:
            logger.warning("OpenProcess 失败: pid=%s err=%s", pid, ctypes.get_last_error())
            continue
        try:
            for obj in items:
                local = wintypes.HANDLE()
                if not _kernel32.DuplicateHandle(
                    process,
                    ctypes.c_void_p(obj.handle),
                    _kernel32.GetCurrentProcess(),
                    ctypes.byref(local),
                    0,
                    False,
                    DUPLICATE_CLOSE_SOURCE,
                ):
                    continue
                _kernel32.CloseHandle(local)
                closed += 1
        finally:
            _kernel32.CloseHandle(process)
    return closed


def scan_mutex_names_for_executable(exe_path: str, heuristic_only: bool = True) -> List[str]:
    pids = list_related_process_ids(exe_path)
    if not pids:
        raise FileNotFoundError("没有正在运行的该程序，请先启动一个实例再扫描")
    return _scan_mutex_names(pids, exe_path, heuristic_only)


def looks_like_launcher(exe_path: str) -> bool:
    stem = os.path.splitext(os.path.basename(str(exe_path or "").strip()))[0].lower()
    if not stem:
        return False
    return any(marker in stem for marker in _LAUNCHER_NAME_MARKERS)


def choose_followup_executable(selected_exe: str, spawned_exes: Sequence[str]) -> str:
    """启动器拉起游戏后，后续实例改开游戏本体，避免再跑一遍启动器把已开的关掉。"""
    selected = _normalize_exe_path(selected_exe)
    if not selected:
        return str(selected_exe or "")
    for path in spawned_exes:
        normalized = _normalize_exe_path(path)
        if not normalized or normalized == selected:
            continue
        if looks_like_launcher(normalized):
            continue
        if _is_helper_exe(normalized, selected):
            continue
        if is_same_install_tree(normalized, selected):
            return normalized
    return selected


def is_same_install_tree(process_exe: str, selected_exe: str) -> bool:
    selected = _normalize_exe_path(selected_exe)
    process = _normalize_exe_path(process_exe)
    if not selected or not process:
        return False
    if process == selected:
        return True
    return _path_is_under(process, os.path.dirname(selected))


def list_process_ids_for_executable(exe_path: str) -> List[int]:
    target = _normalize_exe_path(exe_path)
    if not target:
        return []
    import psutil

    pids: List[int] = []
    for process in psutil.process_iter(attrs=["pid"]):
        pid = int(process.info.get("pid") or 0)
        if pid <= 0:
            continue
        try:
            path = process.exe()
        except (psutil.Error, OSError):
            continue
        if _normalize_exe_path(path) == target:
            pids.append(pid)
    return pids


def list_related_process_ids(exe_path: str) -> List[int]:
    """选中启动器时，把同一安装目录下的游戏进程也算进来。"""
    target = _normalize_exe_path(exe_path)
    if not target:
        return []
    import psutil

    pids: List[int] = []
    for process in psutil.process_iter(attrs=["pid"]):
        pid = int(process.info.get("pid") or 0)
        if pid <= 0:
            continue
        try:
            path = process.exe()
        except (psutil.Error, OSError):
            continue
        if is_same_install_tree(path, target):
            pids.append(pid)
    return pids


def list_top_level_windows_for_pids(pids: Iterable[int]) -> List[dict]:
    pid_set = {int(pid) for pid in pids if int(pid) > 0}
    if not pid_set:
        return []
    import win32gui
    import win32process

    windows: List[dict] = []
    seen: Set[int] = set()

    def _callback(hwnd, _extra):
        handle = as_hwnd(hwnd)
        if handle == 0 or handle in seen:
            return True
        try:
            if win32gui.GetParent(handle):
                return True
            if win32gui.GetWindow(handle, GW_OWNER):
                return True
            if not win32gui.IsWindowVisible(handle):
                return True
            _thread_id, window_pid = win32process.GetWindowThreadProcessId(handle)
            if int(window_pid) not in pid_set:
                return True
            title = get_window_text(handle) or win32gui.GetWindowText(handle)
            class_name = win32gui.GetClassName(handle)
        except Exception:
            return True
        seen.add(handle)
        windows.append(
            {
                "hwnd": handle,
                "title": str(title or "").strip(),
                "pid": int(window_pid),
                "class_name": str(class_name or "").strip(),
            }
        )
        return True

    win32gui.EnumWindows(_callback, None)
    return windows


def launch_executable(exe_path: str, arguments: str = "", working_dir: str = "") -> subprocess.Popen:
    exe = os.path.abspath(str(exe_path or "").strip())
    if not exe or not os.path.isfile(exe):
        raise FileNotFoundError(f"找不到程序: {exe_path}")
    args = split_launch_args(arguments)
    cwd = str(working_dir or "").strip() or os.path.dirname(exe)
    if cwd and not os.path.isdir(cwd):
        raise FileNotFoundError(f"找不到工作目录: {cwd}")
    return subprocess.Popen(
        [exe, *args],
        cwd=cwd or None,
        close_fds=False,
    )


def launch_instances(
    request: LaunchRequest,
    occupancy: Optional[MutexOccupancy] = None,
    should_stop: Optional[StopFn] = None,
    log: Optional[LogFn] = None,
) -> LaunchResult:
    result = LaunchResult()

    def _log(message: str) -> None:
        result.logs.append(message)
        _emit(log, message)

    def _stopped() -> bool:
        return bool(should_stop and should_stop())

    exe = os.path.abspath(str(request.exe_path or "").strip())
    if not exe or not os.path.isfile(exe):
        result.errors.append(f"找不到程序: {request.exe_path}")
        return result
    count = max(1, int(request.count or 1))
    interval = max(0.0, float(request.interval_sec or 0.0))
    mode = str(request.mode or MODE_CLOSE_MUTEX).strip() or MODE_CLOSE_MUTEX
    names = [kernel_path_to_mutex_name(item) for item in request.mutex_names if str(item).strip()]
    enable_debug_privilege()

    launched: List[int] = []
    try:
        if mode == MODE_OCCUPY_MUTEX:
            holder = occupancy if occupancy is not None else MutexOccupancy()
            names = _resolve_occupy_names(exe, names, request, _log)
            if names:
                occupied = holder.occupy(names)
                result.occupied_names = list(holder.names())
                _log("已占用互斥体: " + "、".join(occupied))
            elif not names:
                _log("未提供互斥体名称，改为先启动 1 个再扫描")
                first_pids = _launch_one(exe, request, launched, result, _log, should_stop=should_stop)
                if _stopped():
                    result.pids = list(dict.fromkeys(launched))
                    _log("已停止多开")
                    return result
                scanned = _scan_mutex_names(first_pids, exe, request.heuristic_only)
                if not scanned:
                    result.errors.append("未扫描到可占用的互斥体")
                    _wait_for_windows(launched, request.window_timeout_sec, result, _log, should_stop=should_stop)
                    result.pids = list(dict.fromkeys(launched))
                    return result
                occupied = holder.occupy(scanned)
                result.occupied_names = list(holder.names())
                _log("已占用互斥体: " + "、".join(occupied))
                count = max(0, count - 1)
            for _index in range(count):
                if _stopped():
                    _log("已停止后续启动")
                    break
                _launch_one(exe, request, launched, result, _log, should_stop=should_stop)
                if interval and _index + 1 < count:
                    if _interruptible_sleep(interval, should_stop):
                        _log("已停止多开")
                        break
        elif mode == MODE_CLOSE_MUTEX:
            existing = list_related_process_ids(exe)
            existing_games = _pids_to_unlock(existing, exe)
            if existing_games and not _stopped():
                closed = _close_mutexes_for_pids(
                    existing_games,
                    names,
                    exe,
                    _log,
                    heuristic_only=request.heuristic_only,
                    wait_sec=2.0,
                    should_stop=should_stop,
                )
                result.closed_objects.extend(closed)
            current_exe = choose_followup_executable(exe, [_process_exe(pid) for pid in existing])
            if current_exe != exe:
                _log(f"已有游戏进程，后续改为启动 {os.path.basename(current_exe)}")
            for index in range(count):
                if _stopped():
                    _log("已停止多开")
                    break
                new_pids = _launch_one(
                    current_exe,
                    request,
                    launched,
                    result,
                    _log,
                    install_exe=exe,
                    should_stop=should_stop,
                )
                if _stopped():
                    _log("已停止多开")
                    break
                closed = _close_mutexes_for_pids(
                    _pids_to_unlock(new_pids, exe),
                    names,
                    exe,
                    _log,
                    heuristic_only=request.heuristic_only,
                    wait_sec=12.0,
                    should_stop=should_stop,
                )
                result.closed_objects.extend(closed)
                follow = choose_followup_executable(exe, [_process_exe(pid) for pid in new_pids])
                if follow != current_exe:
                    _log(f"后续实例改为启动 {os.path.basename(follow)}")
                    current_exe = follow
                if interval and index + 1 < count:
                    if _interruptible_sleep(interval, should_stop):
                        _log("已停止多开")
                        break
        else:
            for index in range(count):
                if _stopped():
                    _log("已停止多开")
                    break
                _launch_one(exe, request, launched, result, _log, should_stop=should_stop)
                if interval and index + 1 < count:
                    if _interruptible_sleep(interval, should_stop):
                        _log("已停止多开")
                        break
    except Exception as exc:
        message = f"多开失败: {exc}"
        result.errors.append(message)
        _log(message)
        logger.exception("多开失败")

    result.pids = list(dict.fromkeys(launched))
    if _stopped():
        return result
    _wait_for_windows(result.pids, request.window_timeout_sec, result, _log, should_stop=should_stop)
    return result


def _normalize_exe_path(path: str) -> str:
    value = str(path or "").strip()
    if not value:
        return ""
    return os.path.normcase(os.path.abspath(value))


def _path_is_under(path: str, root: str) -> bool:
    normalized_path = _normalize_exe_path(path)
    normalized_root = _normalize_exe_path(root)
    if not normalized_path or not normalized_root:
        return False
    if normalized_path == normalized_root:
        return True
    prefix = normalized_root.rstrip("\\/") + os.sep
    return normalized_path.startswith(prefix)


def _process_exe(pid: int) -> str:
    import psutil

    try:
        return psutil.Process(int(pid)).exe()
    except (psutil.Error, OSError):
        return ""


def _process_label(pid: int) -> str:
    path = _process_exe(pid)
    name = os.path.basename(path) if path else ""
    if name:
        return f"{pid} {name}"
    return str(pid)


def _collect_exe_stems(selected_exe: str, pids: Sequence[int]) -> List[str]:
    stems: List[str] = []
    seen: Set[str] = set()
    for path in [selected_exe, *(_process_exe(pid) for pid in pids)]:
        stem = exe_stem(path)
        if len(stem) < 3 or stem in seen:
            continue
        seen.add(stem)
        stems.append(stem)
    return stems


def _relative_exe_depth(process_exe: str, selected_exe: str) -> int:
    root = os.path.dirname(_normalize_exe_path(selected_exe))
    path = _normalize_exe_path(process_exe)
    if not path or not root:
        return 0
    if path == _normalize_exe_path(selected_exe):
        return 0
    if not _path_is_under(path, root):
        return 0
    relative = os.path.relpath(path, root)
    parts = [item for item in relative.split(os.sep) if item]
    return max(0, len(parts) - 1)


def _is_helper_exe(path: str, selected_exe: str = "") -> bool:
    stem = exe_stem(path)
    if not stem:
        return False
    if stem in _HELPER_EXE_STEMS or stem.startswith("crash") or stem.endswith("videoplayer") or "crashreporter" in stem:
        return True
    if selected_exe and _relative_exe_depth(path, selected_exe) > 1:
        return True
    return False


def _is_helper_process(pid: int, selected_exe: str = "") -> bool:
    return _is_helper_exe(_process_exe(pid), selected_exe)


def _pids_to_unlock(pids: Sequence[int], selected_exe: str) -> List[int]:
    unique = [int(pid) for pid in pids if int(pid) > 0]
    games = [
        pid
        for pid in unique
        if not looks_like_launcher(_process_exe(pid)) and not _is_helper_process(pid, selected_exe)
    ]
    if games:
        return games
    return [pid for pid in unique if not _is_helper_process(pid, selected_exe)]


def _deny_everyone_mutex(handle: int) -> None:
    authority = SID_IDENTIFIER_AUTHORITY((0, 0, 0, 0, 0, 1))
    everyone = ctypes.c_void_p()
    if not _advapi32.AllocateAndInitializeSid(
        ctypes.byref(authority),
        1,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        ctypes.byref(everyone),
    ):
        raise OSError(ctypes.get_last_error(), "AllocateAndInitializeSid 失败")
    try:
        acl_buffer = ctypes.create_string_buffer(1024)
        if not _advapi32.InitializeAcl(acl_buffer, 1024, ACL_REVISION):
            raise OSError(ctypes.get_last_error(), "InitializeAcl 失败")
        if not _advapi32.AddAccessDeniedAce(acl_buffer, ACL_REVISION, MUTEX_ALL_ACCESS, everyone):
            raise OSError(ctypes.get_last_error(), "AddAccessDeniedAce 失败")
        status = _advapi32.SetSecurityInfo(
            handle,
            SE_KERNEL_OBJECT,
            DACL_SECURITY_INFORMATION,
            None,
            None,
            acl_buffer,
            None,
        )
        if int(status) != 0:
            raise OSError(int(status), "SetSecurityInfo 失败")
    finally:
        _advapi32.FreeSid(everyone)


def _duplicate_handle(process: int, handle_value: int) -> int:
    dup = wintypes.HANDLE()
    if not _kernel32.DuplicateHandle(
        process,
        ctypes.c_void_p(handle_value),
        _kernel32.GetCurrentProcess(),
        ctypes.byref(dup),
        0,
        False,
        DUPLICATE_SAME_ACCESS,
    ):
        return 0
    return int(dup.value or 0)


def _duplicate_query_type(process: int, handle_value: int) -> str:
    dup = _duplicate_handle(process, handle_value)
    if not dup:
        return ""
    try:
        return _query_object_type(dup)
    finally:
        _kernel32.CloseHandle(dup)


def _duplicate_query_name(process: int, handle_value: int) -> str:
    dup = _duplicate_handle(process, handle_value)
    if not dup:
        return ""
    try:
        return _query_object_name(dup)
    finally:
        _kernel32.CloseHandle(dup)


def _query_process_handle_entries(process: int) -> List[tuple]:
    length = 0x10000
    for _attempt in range(8):
        buffer = ctypes.create_string_buffer(length)
        return_length = wintypes.ULONG(0)
        status = _ntdll.NtQueryInformationProcess(
            process,
            ProcessHandleInformation,
            buffer,
            length,
            ctypes.byref(return_length),
        )
        code = _nt_code(status)
        if _nt_ok(status):
            header = PROCESS_HANDLE_SNAPSHOT_INFORMATION.from_buffer_copy(buffer)
            offset = ctypes.sizeof(PROCESS_HANDLE_SNAPSHOT_INFORMATION) - ctypes.sizeof(
                PROCESS_HANDLE_TABLE_ENTRY_INFO
            )
            entry_size = ctypes.sizeof(PROCESS_HANDLE_TABLE_ENTRY_INFO)
            count = min(int(header.NumberOfHandles), max(0, (len(buffer) - offset) // entry_size))
            values: List[tuple] = []
            for index in range(count):
                start = offset + index * entry_size
                entry = PROCESS_HANDLE_TABLE_ENTRY_INFO.from_buffer_copy(buffer, start)
                handle_value = int(entry.HandleValue or 0)
                if handle_value:
                    values.append((handle_value, int(entry.ObjectTypeIndex)))
            return values
        if code in (STATUS_INFO_LENGTH_MISMATCH, STATUS_BUFFER_OVERFLOW, STATUS_BUFFER_TOO_SMALL):
            length = max(length * 2, int(return_length.value) + 0x1000)
            continue
        raise OSError(code, "NtQueryInformationProcess 失败")
    raise OSError(STATUS_INFO_LENGTH_MISMATCH, "NtQueryInformationProcess 缓冲区不足")


def _query_object_text(handle: int, info_class: int) -> str:
    length = 1024
    for _attempt in range(6):
        buffer = ctypes.create_string_buffer(length)
        return_length = wintypes.ULONG(0)
        status = _ntdll.NtQueryObject(
            handle,
            info_class,
            buffer,
            length,
            ctypes.byref(return_length),
        )
        code = _nt_code(status)
        if _nt_ok(status):
            info = UNICODE_STRING.from_buffer_copy(buffer)
            if not info.Buffer or not info.Length:
                return ""
            return ctypes.wstring_at(info.Buffer, info.Length // 2)
        if code == STATUS_OBJECT_NAME_NOT_FOUND:
            return ""
        if code in (STATUS_INFO_LENGTH_MISMATCH, STATUS_BUFFER_OVERFLOW, STATUS_BUFFER_TOO_SMALL):
            length = max(length * 2, int(return_length.value) + 64)
            continue
        return ""
    return ""


def _query_object_name(handle: int) -> str:
    return _query_object_text(handle, ObjectNameInformation)


def _query_object_type(handle: int) -> str:
    return _query_object_text(handle, ObjectTypeInformation)


def _select_objects_to_close(
    objects: Sequence[KernelObject],
    names: Sequence[str],
    stems: Sequence[str],
    heuristic_only: bool,
) -> List[KernelObject]:
    usable = [item for item in objects if not is_system_mutex(item.name)]
    if names:
        matched = [item for item in usable if object_matches_names(item, names)]
        if matched:
            return matched
    preferred = [item for item in usable if is_app_instance_mutex(item.name, stems)]
    if preferred:
        return preferred
    if heuristic_only:
        return []
    return usable


def _close_mutexes_for_pids(
    pids: Sequence[int],
    names: Sequence[str],
    selected_exe: str,
    log: LogFn,
    heuristic_only: bool = False,
    wait_sec: float = 8.0,
    should_stop: Optional[StopFn] = None,
) -> List[str]:
    closed_names: List[str] = []
    unique_pids = list(dict.fromkeys(int(pid) for pid in pids if int(pid) > 0))
    stems = _collect_exe_stems(selected_exe, unique_pids)
    for pid in unique_pids:
        if _is_stopped(should_stop):
            return closed_names
        if _is_helper_process(pid, selected_exe):
            continue
        try:
            objects = _wait_for_instance_objects(
                pid,
                names,
                stems,
                heuristic_only=heuristic_only,
                timeout_sec=wait_sec,
                log=log,
                should_stop=should_stop,
            )
        except OSError as exc:
            log(f"读取进程 {pid} 句柄失败: {exc}")
            continue
        if _is_stopped(should_stop):
            return closed_names
        labels = [item.mutex_name or item.name for item in objects]
        if labels:
            log(f"进程 {_process_label(pid)} 命名互斥体: " + "、".join(labels))
        selected = _select_objects_to_close(objects, names, stems, heuristic_only)
        if not selected:
            if names:
                log(f"进程 {_process_label(pid)} 未等到可关闭的单开锁")
            elif not objects:
                log(f"进程 {_process_label(pid)} 没有命名互斥体")
            else:
                log(f"进程 {_process_label(pid)} 没有可关闭的单开锁")
            continue
        closed = close_kernel_objects(selected)
        closed_labels = [item.mutex_name or item.name for item in selected]
        closed_names.extend(closed_labels)
        log(f"进程 {_process_label(pid)} 已关闭 {closed} 个互斥句柄: " + "、".join(closed_labels))
    return closed_names


def _wait_for_instance_objects(
    pid: int,
    names: Sequence[str],
    stems: Sequence[str],
    heuristic_only: bool,
    timeout_sec: float,
    log: Optional[LogFn] = None,
    should_stop: Optional[StopFn] = None,
) -> List[KernelObject]:
    deadline = time.time() + max(0.2, float(timeout_sec))
    last: List[KernelObject] = []
    waiting_logged = False
    while True:
        if _is_stopped(should_stop):
            return last
        try:
            last = list_named_kernel_objects(pid, types=("Mutant",))
        except OSError:
            if not _pid_is_running(pid):
                return last
            raise
        selected = _select_objects_to_close(last, names, stems, heuristic_only)
        preferred = [
            item
            for item in selected
            if is_app_instance_mutex(item.name, stems) or (names and object_matches_names(item, names))
        ]
        if preferred:
            return last
        if not _pid_is_running(pid) or time.time() >= deadline:
            return last
        if not waiting_logged:
            _emit(log, f"进程 {_process_label(pid)} 等待单开锁…")
            waiting_logged = True
        if _interruptible_sleep(0.3, should_stop):
            return last


def _wait_for_named_objects(pid: int, timeout_sec: float) -> List[KernelObject]:
    return _wait_for_instance_objects(pid, [], [], False, timeout_sec)


def _pid_is_running(pid: int) -> bool:
    import psutil

    try:
        return psutil.pid_exists(int(pid))
    except Exception:
        return False


def _collect_related_pids(
    root_pid: int,
    exe_path: str,
    before: Sequence[int],
    wait_sec: float = 12.0,
    log: Optional[LogFn] = None,
    should_stop: Optional[StopFn] = None,
) -> List[int]:
    import psutil

    found: List[int] = [int(root_pid)]
    before_set = set(int(pid) for pid in before)
    timeout = max(0.4, float(wait_sec))
    settle_deadline = time.time() + min(1.2, timeout)
    deadline = time.time() + timeout
    waiting_logged = False
    while time.time() < deadline:
        if _is_stopped(should_stop):
            break
        try:
            process = psutil.Process(int(root_pid))
            found.extend(int(child.pid) for child in process.children(recursive=True))
        except (psutil.Error, OSError):
            pass
        extra = [
            pid
            for pid in list_related_process_ids(exe_path)
            if pid not in before_set
        ]
        found.extend(extra)
        found = list(dict.fromkeys(pid for pid in found if pid > 0))
        other_exes = [
            pid
            for pid in found
            if pid != int(root_pid)
            and is_same_install_tree(_process_exe(pid), exe_path)
            and not _is_helper_process(pid, exe_path)
        ]
        has_window = bool(list_top_level_windows_for_pids(found))
        if other_exes:
            _emit(log, "已关联进程: " + "、".join(_process_label(pid) for pid in other_exes))
            _interruptible_sleep(0.4, should_stop)
            extra = [
                pid
                for pid in list_related_process_ids(exe_path)
                if pid not in before_set
            ]
            found.extend(extra)
            break
        if not _pid_is_running(root_pid) and extra:
            break
        settled = time.time() >= settle_deadline
        if settled and has_window and not looks_like_launcher(exe_path):
            break
        if settled and _pid_is_running(root_pid) and not looks_like_launcher(exe_path):
            break
        if settled and not waiting_logged:
            _emit(log, "正在等待关联进程…")
            waiting_logged = True
        if _interruptible_sleep(0.25, should_stop):
            break
    return [pid for pid in dict.fromkeys(found) if pid > 0 and (pid == int(root_pid) or pid not in before_set)]


def _launch_one(
    exe: str,
    request: LaunchRequest,
    launched: List[int],
    result: LaunchResult,
    log: LogFn,
    install_exe: str = "",
    should_stop: Optional[StopFn] = None,
) -> List[int]:
    install = install_exe or str(request.exe_path or exe)
    before = list_related_process_ids(install)
    arguments = request.arguments
    working_dir = request.working_dir
    if _normalize_exe_path(exe) != _normalize_exe_path(str(request.exe_path or exe)):
        arguments = ""
        if not str(working_dir or "").strip():
            working_dir = os.path.dirname(os.path.abspath(exe))
    process = launch_executable(exe, arguments, working_dir)
    pid = int(process.pid)
    log(f"已启动进程 {_process_label(pid)}")
    related = _collect_related_pids(
        pid,
        install,
        before,
        wait_sec=float(request.window_timeout_sec or 12.0),
        log=log,
        should_stop=should_stop,
    )
    launched.extend(related)
    return related


def _scan_mutex_names(pids: Sequence[int], selected_exe: str, heuristic_only: bool = False) -> List[str]:
    names: List[str] = []
    seen: Set[str] = set()
    stems = _collect_exe_stems(selected_exe, pids)
    for pid in pids:
        if _is_helper_process(int(pid), selected_exe):
            continue
        try:
            objects = list_named_kernel_objects(int(pid), types=("Mutant",))
        except OSError:
            continue
        selected = _select_objects_to_close(objects, [], stems, heuristic_only)
        for obj in selected:
            name = obj.mutex_name or obj.name
            if not name or name in seen:
                continue
            seen.add(name)
            names.append(name)
    return names


def _resolve_occupy_names(
    exe: str,
    names: Sequence[str],
    request: LaunchRequest,
    log: LogFn,
) -> List[str]:
    if names:
        return list(names)
    existing = list_related_process_ids(exe)
    if not existing:
        return []
    scanned = _scan_mutex_names(existing, exe, request.heuristic_only)
    if scanned:
        log("从已运行进程扫描到互斥体: " + "、".join(scanned))
    return scanned


def _wait_for_windows(
    pids: Sequence[int],
    timeout_sec: float,
    result: LaunchResult,
    log: LogFn,
    should_stop: Optional[StopFn] = None,
) -> None:
    unique = [int(pid) for pid in pids if int(pid) > 0]
    if not unique:
        return
    deadline = time.time() + max(0.2, float(timeout_sec))
    best: List[dict] = []
    while time.time() < deadline:
        if _is_stopped(should_stop):
            break
        found = list_top_level_windows_for_pids(unique)
        if len(found) > len(best):
            best = found
        if found:
            _interruptible_sleep(0.4, should_stop)
            best = list_top_level_windows_for_pids(unique)
            break
        if _interruptible_sleep(0.2, should_stop):
            break
    result.windows = best
    if best:
        titles = [item.get("title") or f"HWND {item.get('hwnd')}" for item in best]
        log(f"找到 {len(best)} 个窗口: " + "、".join(str(title) for title in titles))
        return
    log("进程已启动，但未找到窗口。可稍后在全局设置中绑定。")
