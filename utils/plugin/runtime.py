# -*- coding: utf-8 -*-
from __future__ import annotations

import ctypes
import logging
import mmap
import os
import subprocess
import threading
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any, Callable, Optional

from utils.app_paths import get_app_root
from utils.plugin.protocol import (
    FRAME_MAP_SIZE,
    feed_messages,
    map_name,
    pack_message,
    pipe_name,
    read_bgr_frame,
)

logger = logging.getLogger(__name__)

_COOLDOWN_HITS = 0
_COOLDOWN_UNTIL = 0.0
_COOLDOWN_LOCK = threading.Lock()

_ENSURE_LOCK = threading.Lock()
_CACHED_RPC: Optional["PluginRpc"] = None
_HOST_PROC: Optional[subprocess.Popen] = None
_JOB_HANDLE = None
_PIPE_FILE = None
_FRAME_MAP = None

_PIPE_CONNECT_TIMEOUT = 5.0
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_PROCESS_TERMINATE = 0x0001
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_SET_INFORMATION = 0x0200


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def _kernel32():
    lib = ctypes.WinDLL("kernel32", use_last_error=True)
    lib.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    lib.CreateJobObjectW.restype = wintypes.HANDLE
    lib.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    lib.SetInformationJobObject.restype = wintypes.BOOL
    lib.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    lib.AssignProcessToJobObject.restype = wintypes.BOOL
    lib.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    lib.OpenProcess.restype = wintypes.HANDLE
    lib.CloseHandle.argtypes = [wintypes.HANDLE]
    lib.CloseHandle.restype = wintypes.BOOL
    lib.WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
    lib.WaitNamedPipeW.restype = wintypes.BOOL
    return lib


def _read_plugin_config() -> dict:
    try:
        from app_core.config_store import load_config

        data = load_config()
    except Exception:
        data = {}
    return {
        "plugin_dir": str((data or {}).get("plugin_dir") or "").strip(),
        "plugin_reg_code": str((data or {}).get("plugin_reg_code") or ""),
    }


_PLUGIN_RUNTIME_FILES = ("PluginHost.exe", "dm.dll", "RegDll.dll")


def _is_plugin_runtime_dir(directory: Path) -> bool:
    return directory.is_dir() and all((directory / name).is_file() for name in _PLUGIN_RUNTIME_FILES)


def find_plugin_dir() -> Optional[Path]:
    try:
        root = Path(get_app_root())
    except Exception:
        root = Path(__file__).resolve().parents[2]
    candidate = root / "tools" / "plugin"
    try:
        resolved = candidate.resolve()
    except OSError:
        return None
    if _is_plugin_runtime_dir(resolved):
        return resolved
    return None


def is_plugin_runtime_available() -> bool:
    return find_plugin_dir() is not None


def launch_host_command(exe: Path, pipe: str) -> list[str]:
    return [str(exe), "--pipe", str(pipe)]


def note_host_init_failure() -> None:
    global _COOLDOWN_HITS, _COOLDOWN_UNTIL
    with _COOLDOWN_LOCK:
        _COOLDOWN_HITS += 1
        if _COOLDOWN_HITS >= 3:
            _COOLDOWN_UNTIL = time.monotonic() + 10.0


def note_host_init_success() -> None:
    global _COOLDOWN_HITS, _COOLDOWN_UNTIL
    with _COOLDOWN_LOCK:
        _COOLDOWN_HITS = 0
        _COOLDOWN_UNTIL = 0.0


def should_cool_down() -> bool:
    with _COOLDOWN_LOCK:
        return time.monotonic() < _COOLDOWN_UNTIL


class LoopbackTransport:
    def __init__(self, handler: Callable[[dict], dict]):
        self._handler = handler

    def request(self, payload: dict) -> dict:
        return dict(self._handler(payload))


class PluginRpc:
    def __init__(self, transport, frame_buf: Optional[memoryview] = None):
        self._transport = transport
        self._frame_buf = frame_buf
        self._next_id = 1
        self._lock = threading.RLock()

    def call(self, method: str, **args: Any) -> Any:
        with self._lock:
            msg_id = self._next_id
            self._next_id += 1
            reply = self._transport.request({"id": msg_id, "method": method, "args": dict(args)})
        if not reply.get("ok"):
            raise RuntimeError(str(reply.get("error") or f"{method} failed"))
        return reply.get("result")

    def read_frame(self):
        if self._frame_buf is None:
            return None
        return read_bgr_frame(self._frame_buf)

    def capture_bgr(self, hwnd: int, display: str, input_hwnd: int = 0):
        with self._lock:
            self.call("capture", hwnd=int(hwnd), display=str(display), input_hwnd=int(input_hwnd or hwnd))
            frame = self.read_frame()
            return None if frame is None else frame.copy()


class PluginClient:
    def __init__(self, rpc: Optional[PluginRpc] = None):
        self._rpc = rpc

    def init(self, plugin_dir: str, reg_code: str) -> None:
        if self._rpc is None:
            raise RuntimeError("plugin rpc missing")
        if not str(reg_code or "").strip():
            raise RuntimeError("未填写插件注册码")
        self._rpc.call("init", plugin_dir=str(plugin_dir or ""), reg_code=str(reg_code))

    def bind(self, display_hwnd: int, input_hwnd: int, display: str, mouse: str, keypad: str, mode: int) -> bool:
        result = self._rpc.call(
            "bind",
            display_hwnd=int(display_hwnd),
            input_hwnd=int(input_hwnd),
            display=str(display),
            mouse=str(mouse),
            keypad=str(keypad),
            mode=int(mode),
        )
        if isinstance(result, dict) and "ok" in result:
            return bool(result.get("ok"))
        return bool(result)

    def unbind(self) -> None:
        try:
            self._rpc.call("unbind")
        except Exception:
            logger.debug("plugin unbind failed", exc_info=True)

    def capture_bgr(self, hwnd: int, display: str, input_hwnd: int = 0):
        return self._rpc.capture_bgr(hwnd, display, input_hwnd)

    def move_to(self, x: int, y: int) -> bool:
        return bool(self._rpc.call("move_to", x=int(x), y=int(y)))

    def mouse_click(self, button: str = "left") -> bool:
        return bool(self._rpc.call("mouse_click", button=str(button)))

    def mouse_double_click(self, button: str = "left") -> bool:
        return bool(self._rpc.call("mouse_double_click", button=str(button)))

    def mouse_down(self, button: str = "left") -> bool:
        return bool(self._rpc.call("mouse_down", button=str(button)))

    def mouse_up(self, button: str = "left") -> bool:
        return bool(self._rpc.call("mouse_up", button=str(button)))

    def wheel(self, delta: int) -> bool:
        return bool(self._rpc.call("wheel", delta=int(delta)))

    def key_down(self, vk_code: int) -> bool:
        return bool(self._rpc.call("key_down", vk_code=int(vk_code)))

    def key_up(self, vk_code: int) -> bool:
        return bool(self._rpc.call("key_up", vk_code=int(vk_code)))

    def key_press(self, vk_code: int) -> bool:
        return bool(self._rpc.call("key_press", vk_code=int(vk_code)))

    def key_press_str(self, text: str, delay: int = 30) -> bool:
        return bool(self._rpc.call("key_press_str", text=str(text or ""), delay=int(delay)))

    def client_size(self, hwnd: int) -> tuple[int, int]:
        result = self._rpc.call("client_size", hwnd=int(hwnd))
        if isinstance(result, dict):
            return int(result.get("width") or 0), int(result.get("height") or 0)
        return (0, 0)

    def last_error(self) -> int:
        try:
            return int(self._rpc.call("last_error") or 0)
        except Exception:
            return 0

    def close(self) -> None:
        if self._rpc is None:
            return
        try:
            self._rpc.call("shutdown")
        except Exception:
            logger.debug("plugin shutdown failed", exc_info=True)


class NamedPipeTransport:
    def __init__(self, handle):
        self._handle = handle
        self._pending = b""

    def request(self, payload: dict) -> dict:
        self._handle.write(pack_message(payload))
        self._handle.flush()
        while True:
            chunk = self._handle.read(4096)
            if not chunk:
                raise RuntimeError("plugin pipe closed")
            messages, self._pending = feed_messages(self._pending + chunk)
            if messages:
                return messages[0]


def _create_kill_on_close_job():
    k32 = _kernel32()
    job = k32.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not k32.SetInformationJobObject(
        job,
        _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
        ctypes.byref(info),
        ctypes.sizeof(info),
    ):
        error = ctypes.get_last_error()
        k32.CloseHandle(job)
        raise ctypes.WinError(error)
    return job


def _assign_process_to_job(job, proc: subprocess.Popen) -> None:
    k32 = _kernel32()
    owned = False
    handle = getattr(proc, "_handle", None)
    if not handle:
        access = _PROCESS_TERMINATE | _PROCESS_SET_QUOTA | _PROCESS_SET_INFORMATION
        handle = k32.OpenProcess(access, False, int(proc.pid))
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        owned = True
    try:
        if not k32.AssignProcessToJobObject(job, handle):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        if owned:
            k32.CloseHandle(handle)


def _attach_host_job(proc: subprocess.Popen):
    job = None
    try:
        job = _create_kill_on_close_job()
        _assign_process_to_job(job, proc)
        return job
    except Exception:
        logger.warning("plugin job object setup failed", exc_info=True)
        if job:
            try:
                _kernel32().CloseHandle(job)
            except Exception:
                logger.debug("plugin job close failed", exc_info=True)
        return None


def _connect_named_pipe(name: str, timeout: float = _PIPE_CONNECT_TIMEOUT):
    path = rf"\\.\pipe\{name}"
    k32 = _kernel32()
    deadline = time.monotonic() + float(timeout)
    last_error: Optional[BaseException] = None
    flags = os.O_RDWR | getattr(os, "O_BINARY", 0)
    while True:
        remaining_ms = int((deadline - time.monotonic()) * 1000)
        if remaining_ms <= 0:
            break
        k32.WaitNamedPipeW(path, min(remaining_ms, 200))
        try:
            fd = os.open(path, flags)
            return os.fdopen(fd, "r+b", buffering=0)
        except OSError as exc:
            last_error = exc
            if time.monotonic() >= deadline:
                break
            time.sleep(0.05)
    raise RuntimeError(f"plugin pipe connect timeout: {last_error}")


def _open_frame_map(pid: int):
    return mmap.mmap(-1, FRAME_MAP_SIZE, tagname=map_name(int(pid)))


def _host_alive() -> bool:
    proc = _HOST_PROC
    return proc is not None and proc.poll() is None


def _teardown_host_locked() -> None:
    global _CACHED_RPC, _HOST_PROC, _JOB_HANDLE, _PIPE_FILE, _FRAME_MAP
    _CACHED_RPC = None
    pipe = _PIPE_FILE
    _PIPE_FILE = None
    if pipe is not None:
        try:
            pipe.close()
        except Exception:
            logger.debug("plugin pipe close failed", exc_info=True)
    mapping = _FRAME_MAP
    _FRAME_MAP = None
    if mapping is not None:
        try:
            mapping.close()
        except Exception:
            logger.debug("plugin frame map close failed", exc_info=True)
    job = _JOB_HANDLE
    _JOB_HANDLE = None
    if job:
        try:
            _kernel32().CloseHandle(job)
        except Exception:
            logger.debug("plugin job close failed", exc_info=True)
    proc = _HOST_PROC
    _HOST_PROC = None
    if proc is not None:
        if proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                logger.debug("plugin host kill failed", exc_info=True)
        try:
            proc.wait(timeout=2)
        except Exception:
            pass


def terminate_plugin_host() -> None:
    with _ENSURE_LOCK:
        _teardown_host_locked()


def ensure_plugin_rpc() -> PluginRpc:
    global _CACHED_RPC, _HOST_PROC, _JOB_HANDLE, _PIPE_FILE, _FRAME_MAP
    with _ENSURE_LOCK:
        if _CACHED_RPC is not None and _host_alive():
            return _CACHED_RPC
        _teardown_host_locked()
        if should_cool_down():
            raise RuntimeError("插件宿主冷却中")
        if not is_plugin_runtime_available():
            raise RuntimeError("插件运行库不可用")
        directory = find_plugin_dir()
        if directory is None:
            raise RuntimeError("插件运行库不可用")
        exe = directory / "PluginHost.exe"
        cfg = _read_plugin_config()
        if not str(cfg.get("plugin_reg_code") or "").strip():
            raise RuntimeError("未填写插件注册码")
        pid = os.getpid()
        pipe = pipe_name(pid)
        launched = False
        try:
            # CREATE_BREAKAWAY_FROM_JOB remains unset so the child can stay in our job.
            proc = subprocess.Popen(
                launch_host_command(exe, pipe),
                cwd=str(directory),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            launched = True
            _HOST_PROC = proc
            _JOB_HANDLE = _attach_host_job(proc)
            pipe_file = _connect_named_pipe(pipe, timeout=_PIPE_CONNECT_TIMEOUT)
            _PIPE_FILE = pipe_file
            mapping = _open_frame_map(pid)
            _FRAME_MAP = mapping
            rpc = PluginRpc(NamedPipeTransport(pipe_file), frame_buf=memoryview(mapping))
            rpc.call("init", plugin_dir=str(directory), reg_code=str(cfg["plugin_reg_code"]))
            note_host_init_success()
            _CACHED_RPC = rpc
            return rpc
        except Exception:
            if launched:
                note_host_init_failure()
            _teardown_host_locked()
            raise
