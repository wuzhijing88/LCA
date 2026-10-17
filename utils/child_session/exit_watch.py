# -*- coding: utf-8 -*-
"""LCA 退出后的桌面分身注销检测进程。"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import os
import subprocess
import sys
import time
from typing import Callable, Optional, Sequence

from utils.app_paths import get_app_root, get_system_log_path, is_packaged_runtime, resolve_running_executable
from utils.child_session import native as child_native
from utils.child_session.ownership import ChildSessionLease
from utils.child_session.runtime import is_child_session_instance

logger = logging.getLogger(__name__)

EXIT_WATCH_FLAG = "--child-session-exit-watch"
PARENT_PID_FLAG = "--parent-pid"
_MUTEX_NAME = "Local\\LCA.ChildSessionExitWatch"
_SYNCHRONIZE = 0x00100000
_ERROR_ALREADY_EXISTS = 183
_CREATE_NEW_PROCESS_GROUP = 0x00000200
_CREATE_BREAKAWAY_FROM_JOB = 0x01000000
_CREATE_NO_WINDOW = 0x08000000

QuerySession = Callable[[], Optional[int]]
RequestLogoff = Callable[[int], str]
Clock = Callable[[], float]
Sleeper = Callable[[float], None]
Logger = Callable[[str], None]


def is_exit_watch_requested(argv: Sequence[str]) -> bool:
    return EXIT_WATCH_FLAG in list(argv)


def parse_parent_pid(argv: Sequence[str]) -> int:
    args = list(argv)
    for index, token in enumerate(args):
        if token == PARENT_PID_FLAG:
            if index + 1 >= len(args):
                raise ValueError("缺少 --parent-pid 参数值")
            return _positive_pid(args[index + 1])
        if str(token).startswith(PARENT_PID_FLAG + "="):
            return _positive_pid(str(token).split("=", 1)[1])
    raise ValueError("缺少 --parent-pid")


def _windowless_interpreter() -> str:
    executable = os.path.abspath(sys.executable)
    if executable.lower().endswith("python.exe"):
        pythonw = os.path.join(os.path.dirname(executable), "pythonw.exe")
        if os.path.isfile(pythonw):
            return pythonw
    return executable


def build_exit_watch_command(parent_pid: int) -> list[str]:
    pid = _positive_pid(parent_pid)
    if is_packaged_runtime():
        executable = os.path.abspath(resolve_running_executable() or sys.executable)
        return [executable, EXIT_WATCH_FLAG, PARENT_PID_FLAG, str(pid)]
    return [
        _windowless_interpreter(),
        "-m",
        "utils.child_session.exit_watch",
        PARENT_PID_FLAG,
        str(pid),
    ]


def finish_orphan_session(
    session_id: int,
    query: QuerySession,
    request_logoff: RequestLogoff,
    sleep: Sleeper,
    clock: Clock,
    *,
    busy_seconds: float,
    drain_seconds: float,
    poll_seconds: float,
) -> str:
    current = query()
    if current is None:
        return "已注销"
    if int(current) != int(session_id):
        return "会话已更换"
    busy_deadline = clock() + float(busy_seconds)
    while True:
        result = request_logoff(int(session_id))
        if result == "gone":
            return "已注销"
        if result == "ok":
            break
        if result == "busy" and clock() < busy_deadline:
            sleep(float(poll_seconds))
            current = query()
            if current is None:
                return "已注销"
            if int(current) != int(session_id):
                return "会话已更换"
            continue
        return "注销失败"
    deadline = clock() + float(drain_seconds)
    while clock() < deadline:
        current = query()
        if current is None or int(current) != int(session_id):
            return "已注销"
        sleep(float(poll_seconds))
    return "注销未完成"


def execute_exit_watch(
    parent_pid: int,
    wait_parent: Callable[[], None],
    query: QuerySession,
    request_logoff: RequestLogoff,
    sleep: Sleeper,
    clock: Clock,
    log: Logger,
    *,
    busy_seconds: float,
    drain_seconds: float,
    poll_seconds: float,
    claim_cleanup: Optional[Callable[[], bool]] = None,
) -> int:
    log("检测进程已启动，等待 LCA 退出")
    wait_parent()
    log("LCA 已退出")
    if claim_cleanup is not None and not claim_cleanup():
        log("已有其他 LCA 实例接管桌面分身，检测进程退出")
        return 0
    session_id = query()
    if session_id is None:
        log("分身已注销，检测进程退出")
        return 0
    log(f"分身会话 {int(session_id)} 未注销，开始注销")
    outcome = finish_orphan_session(
        int(session_id),
        query,
        request_logoff,
        sleep,
        clock,
        busy_seconds=busy_seconds,
        drain_seconds=drain_seconds,
        poll_seconds=poll_seconds,
    )
    log(outcome)
    return 0 if outcome == "已注销" else 1


def start_exit_watch() -> None:
    if is_child_session_instance():
        return
    try:
        if _watch_mutex_exists():
            return
        command = build_exit_watch_command(os.getpid())
        # CREATE_NO_WINDOW 才能压住 python 的控制台。再加 DETACHED_PROCESS 时窗口仍会弹出来。
        flags = (
            _CREATE_NEW_PROCESS_GROUP
            | _CREATE_NO_WINDOW
            | _CREATE_BREAKAWAY_FROM_JOB
        )
        kwargs = {
            "cwd": get_app_root(),
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "close_fds": True,
        }
        try:
            subprocess.Popen(command, creationflags=flags, **kwargs)
        except OSError:
            flags = _CREATE_NEW_PROCESS_GROUP | _CREATE_NO_WINDOW
            subprocess.Popen(command, creationflags=flags, **kwargs)
    except Exception as exc:
        logger.warning("启动桌面分身退出检测进程失败: %s", exc)
        return
    logger.info("已启动桌面分身退出检测进程")


def run_exit_watch(argv: Sequence[str]) -> int:
    try:
        parent_pid = parse_parent_pid(argv)
    except ValueError as exc:
        _append_log(str(exc))
        return 2
    if parent_pid == os.getpid():
        _append_log("--parent-pid 不能是检测进程自己")
        return 2
    if not _claim_watch_mutex():
        _append_log("已有检测进程，退出")
        return 0
    lease = ChildSessionLease()
    try:
        return execute_exit_watch(
            parent_pid,
            lambda: _wait_for_process_exit(parent_pid),
            lambda: child_native.try_get_child_session_id(strict=True),
            _request_logoff,
            time.sleep,
            time.monotonic,
            _append_log,
            busy_seconds=child_native.CHILD_SESSION_LOGOFF_BUSY_SECONDS,
            drain_seconds=child_native.CHILD_SESSION_LOGOFF_DRAIN_SECONDS,
            poll_seconds=child_native.CHILD_SESSION_LOGOFF_POLL_SECONDS,
            claim_cleanup=lease.acquire,
        )
    finally:
        lease.release()
        _release_watch_mutex()


def _positive_pid(raw: object) -> int:
    try:
        pid = int(str(raw).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"--parent-pid 的值无效: {raw!r}") from exc
    if pid <= 0:
        raise ValueError(f"--parent-pid 的值无效: {raw!r}")
    return pid


def _request_logoff(session_id: int) -> str:
    if child_native._wts().WTSLogoffSession(None, int(session_id), False):
        return "ok"
    error = ctypes.get_last_error()
    if error in (child_native.ERROR_FILE_NOT_FOUND, child_native.ERROR_NOT_FOUND):
        return "gone"
    if error == child_native.ERROR_RPC_SERVER_TOO_BUSY:
        return "busy"
    _append_log(f"注销分身会话 {int(session_id)} 失败，Win32 错误 {error}")
    return "error"


def _wait_for_process_exit(pid: int) -> None:
    kernel32 = _kernel32()
    access = _SYNCHRONIZE | 0x1000
    handle = kernel32.OpenProcess(access, False, int(pid))
    if not handle:
        return
    try:
        kernel32.WaitForSingleObject(handle, 0xFFFFFFFF)
    finally:
        kernel32.CloseHandle(handle)


def _watch_mutex_exists() -> bool:
    kernel32 = _kernel32()
    handle = kernel32.OpenMutexW(_SYNCHRONIZE, False, _MUTEX_NAME)
    if not handle:
        return False
    kernel32.CloseHandle(handle)
    return True


_mutex_handle = None


def _claim_watch_mutex() -> bool:
    global _mutex_handle
    kernel32 = _kernel32()
    handle = kernel32.CreateMutexW(None, False, _MUTEX_NAME)
    if not handle:
        return False
    if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return False
    _mutex_handle = handle
    return True


def _release_watch_mutex() -> None:
    global _mutex_handle
    handle = _mutex_handle
    _mutex_handle = None
    if handle:
        _kernel32().CloseHandle(handle)


def _append_log(line: str) -> None:
    path = get_system_log_path("LCA")
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"{stamp} - INFO - [pid={os.getpid()}] - [退出检测] - {line}\n")


_KERNEL32 = None


def _kernel32() -> ctypes.WinDLL:
    global _KERNEL32
    if _KERNEL32 is None:
        dll = ctypes.WinDLL("kernel32", use_last_error=True)
        dll.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        dll.OpenProcess.restype = wintypes.HANDLE
        dll.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        dll.WaitForSingleObject.restype = wintypes.DWORD
        dll.CloseHandle.argtypes = [wintypes.HANDLE]
        dll.CloseHandle.restype = wintypes.BOOL
        dll.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
        dll.OpenMutexW.restype = wintypes.HANDLE
        dll.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        dll.CreateMutexW.restype = wintypes.HANDLE
        _KERNEL32 = dll
    return _KERNEL32


def main(argv: Optional[Sequence[str]] = None) -> int:
    return run_exit_watch(sys.argv if argv is None else argv)


if __name__ == "__main__":
    sys.exit(main())
