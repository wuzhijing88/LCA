# -*- coding: utf-8 -*-
from __future__ import annotations

import ctypes
import logging
import mmap
import os
import struct
import subprocess
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from utils.app_paths import get_app_root
from utils.plugin.bind_errors import BindOutcome
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
_OWNS_HOST = False
_OWNER_PID = 0
_ATTACHED_HOST_PID = 0

_PIPE_CONNECT_TIMEOUT = 5.0
PLUGIN_INIT_TIMEOUT = 8.0
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_PROCESS_TERMINATE = 0x0001
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_SET_INFORMATION = 0x0200
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PLUGIN_OWNER_PID_ENV = "LCA_PLUGIN_OWNER_PID"
PLUGIN_HOST_PID_ENV = "LCA_PLUGIN_HOST_PID"
PLUGIN_ATTACH_REQUIRED_ENV = "LCA_PLUGIN_ATTACH_REQUIRED"

_PREWARM_LOCK = threading.Lock()
_PREWARM_ACTIVE = False


class PluginTransportError(RuntimeError):
    """插件命名管道已断开或发生 I/O 错误。"""


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
    lib.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    lib.TerminateProcess.restype = wintypes.BOOL
    lib.WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
    lib.WaitNamedPipeW.restype = wintypes.BOOL
    return lib


def _read_plugin_config() -> dict:
    from utils.runtime_config import get_runtime_config

    data = get_runtime_config()
    return {
        "plugin_reg_code": str((data or {}).get("plugin_reg_code") or ""),
        "plugin_extra_code": str((data or {}).get("plugin_extra_code") or ""),
    }


_PLUGIN_RUNTIME_FILES = ("PluginHost.exe", "dm.dll", "RegDll.dll")
_PE_MACHINE_I386 = 0x014C
_PE_MACHINE_AMD64 = 0x8664
_PE_MACHINE_ARM64 = 0xAA64
_PE_MACHINE_NAMES = {
    _PE_MACHINE_I386: "x86",
    _PE_MACHINE_AMD64: "x64",
    _PE_MACHINE_ARM64: "arm64",
}


def _is_plugin_runtime_dir(directory: Path) -> bool:
    return directory.is_dir() and all((directory / name).is_file() for name in _PLUGIN_RUNTIME_FILES)


def read_pe_machine(path: Path) -> Optional[int]:
    """读取 PE 头的 Machine 字段；不是有效 PE 时返回 None。"""
    try:
        with open(path, "rb") as handle:
            header = handle.read(64)
            if len(header) < 64 or header[:2] != b"MZ":
                return None
            pe_offset = struct.unpack_from("<I", header, 60)[0]
            handle.seek(pe_offset)
            signature = handle.read(6)
            if len(signature) < 6 or signature[:4] != b"PE\0\0":
                return None
            return struct.unpack_from("<H", signature, 4)[0]
    except OSError:
        return None


def check_plugin_runtime_arch(directory: Path) -> Optional[str]:
    """dm.dll 只有 32 位 COM 实现，宿主也必须是 32 位；不匹配时返回说明文字，正常返回 None。

    文件存在性由 _is_plugin_runtime_dir 负责；这里只看能读出 PE 头的文件的 Machine 字段。
    """
    problems: list[str] = []
    for name in _PLUGIN_RUNTIME_FILES:
        machine = read_pe_machine(directory / name)
        if machine is not None and machine != _PE_MACHINE_I386:
            arch = _PE_MACHINE_NAMES.get(machine, hex(machine))
            problems.append(f"{name} 是 {arch}，插件链路要求全部为 32 位(x86)")
    if not problems:
        return None
    return "插件运行库架构不匹配：" + "；".join(problems)


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


class NamedFrameLock:
    """跨进程互斥：帧共享内存只有一块，主进程和附着的子进程 capture→读帧必须成对进行。"""

    def __init__(self, name: str, timeout: float = 5.0):
        self._name = str(name)
        self._timeout_ms = max(50, int(float(timeout) * 1000))
        self._handle = None
        self._fallback = threading.RLock()
        try:
            import win32event

            self._win32event = win32event
            self._handle = win32event.CreateMutex(None, False, self._name)
        except Exception:
            self._win32event = None
            self._handle = None

    def __enter__(self):
        if self._handle is None:
            self._fallback.acquire()
            return self
        import pywintypes  # noqa: F401 — 确保 win32 异常类型已加载

        rc = self._win32event.WaitForSingleObject(self._handle, self._timeout_ms)
        if rc not in (0, 0x80):  # WAIT_OBJECT_0 / WAIT_ABANDONED
            raise RuntimeError("等待插件帧锁超时")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._handle is None:
            self._fallback.release()
            return
        try:
            self._win32event.ReleaseMutex(self._handle)
        except Exception:
            pass


def frame_lock_name(owner_pid: int) -> str:
    return f"Local\\lca-plugin-frame-lock-{int(owner_pid)}"


class PluginRpc:
    def __init__(self, transport, frame_buf: Optional[memoryview] = None, frame_lock=None):
        self._transport = transport
        self._frame_buf = frame_buf
        self._frame_lock = frame_lock
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
            guard = self._frame_lock if self._frame_lock is not None else _NULL_GUARD
            with guard:
                self.call("capture", hwnd=int(hwnd), display=str(display), input_hwnd=int(input_hwnd or hwnd))
                frame = self.read_frame()
                return None if frame is None else frame.copy()


class _NullGuard:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


_NULL_GUARD = _NullGuard()


class PluginClient:
    """宿主按 hwnd 给每个窗口一个 dm 对象；带 hwnd 的调用路由到对应对象，0 表示最近绑定的那个。"""

    def __init__(self, rpc: Optional[PluginRpc] = None):
        self._rpc = rpc

    def init(self, plugin_dir: str, reg_code: str, extra_code: str = "") -> None:
        if self._rpc is None:
            raise RuntimeError("plugin rpc missing")
        if not str(reg_code or "").strip():
            raise RuntimeError("未填写插件注册码")
        self._rpc.call(
            "init",
            plugin_dir=str(plugin_dir or ""),
            reg_code=str(reg_code),
            extra_code=str(extra_code or ""),
        )

    def bind(
        self,
        display_hwnd: int,
        input_hwnd: int,
        display: str,
        mouse: str,
        keypad: str,
        mode: int,
        public: str = "",
        fake_active: bool = False,
    ) -> BindOutcome:
        """返回 BindOutcome（可直接当布尔用）；失败时附带 dm.GetLastError 与宿主侧异常文本。

        public 为 BindWindowEx 的 public 串（如 dx.public.input.ime）；fake_active 绑定成功后开启后台假激活。
        """
        result = self._rpc.call(
            "bind",
            display_hwnd=int(display_hwnd),
            input_hwnd=int(input_hwnd),
            display=str(display),
            mouse=str(mouse),
            keypad=str(keypad),
            mode=int(mode),
            public=str(public or ""),
            fake_active=bool(fake_active),
        )
        return BindOutcome.from_rpc(result)

    def unbind(self, hwnd: int = 0) -> bool:
        """hwnd>0 只解绑该窗口的 dm 对象；0 解绑宿主内全部对象。"""
        try:
            self._rpc.call("unbind", hwnd=int(hwnd or 0))
            return True
        except Exception:
            logger.debug("plugin unbind failed", exc_info=True)
            return False

    def force_unbind(self, hwnd: int) -> bool:
        try:
            result = self._rpc.call("force_unbind", hwnd=int(hwnd))
        except Exception:
            logger.debug("plugin force_unbind failed", exc_info=True)
            return False
        return bool(isinstance(result, dict) and result.get("ok"))

    def is_bind(self, hwnd: int) -> bool:
        """问大漠该窗口当前是否仍处于绑定状态（宿主缓存与实际不一致时以此为准）。"""
        try:
            result = self._rpc.call("is_bind", hwnd=int(hwnd))
        except Exception:
            logger.debug("plugin is_bind failed", exc_info=True)
            return False
        return bool(isinstance(result, dict) and result.get("bound"))

    def fake_active(self, hwnd: int, enable: bool) -> bool:
        return bool(self._rpc.call("fake_active", hwnd=int(hwnd), enable=bool(enable)))

    def stats(self) -> dict:
        """宿主对象池统计：slots（绑定中的窗口数）、free（空闲对象）、registrations（累计 Reg 次数）。"""
        result = self._rpc.call("stats")
        return dict(result) if isinstance(result, dict) else {}

    def send_string(self, hwnd: int, text: str, ime: bool = False, target: int = 0) -> bool:
        """hwnd 选择绑定该窗口的 dm 对象；target 为实际收字的（子）窗口，缺省即 hwnd。"""
        args = {"hwnd": int(hwnd), "text": str(text or ""), "ime": bool(ime)}
        if int(target or 0) > 0 and int(target) != int(hwnd):
            args["target"] = int(target)
        return bool(self._rpc.call("send_string", **args))

    def version(self) -> str:
        return str(self._rpc.call("version") or "")

    def capture_bgr(self, hwnd: int, display: str, input_hwnd: int = 0):
        return self._rpc.capture_bgr(hwnd, display, input_hwnd)

    def move_to(self, x: int, y: int, hwnd: int = 0) -> bool:
        return bool(self._rpc.call("move_to", x=int(x), y=int(y), hwnd=int(hwnd or 0)))

    def mouse_click(self, button: str = "left", hwnd: int = 0) -> bool:
        return bool(self._rpc.call("mouse_click", button=str(button), hwnd=int(hwnd or 0)))

    def mouse_double_click(self, button: str = "left", hwnd: int = 0) -> bool:
        return bool(self._rpc.call("mouse_double_click", button=str(button), hwnd=int(hwnd or 0)))

    def mouse_down(self, button: str = "left", hwnd: int = 0) -> bool:
        return bool(self._rpc.call("mouse_down", button=str(button), hwnd=int(hwnd or 0)))

    def mouse_up(self, button: str = "left", hwnd: int = 0) -> bool:
        return bool(self._rpc.call("mouse_up", button=str(button), hwnd=int(hwnd or 0)))

    def wheel(self, delta: int, hwnd: int = 0) -> bool:
        return bool(self._rpc.call("wheel", delta=int(delta), hwnd=int(hwnd or 0)))

    def key_down(self, vk_code: int, hwnd: int = 0) -> bool:
        return bool(self._rpc.call("key_down", vk_code=int(vk_code), hwnd=int(hwnd or 0)))

    def key_up(self, vk_code: int, hwnd: int = 0) -> bool:
        return bool(self._rpc.call("key_up", vk_code=int(vk_code), hwnd=int(hwnd or 0)))

    def key_press(self, vk_code: int, hwnd: int = 0) -> bool:
        return bool(self._rpc.call("key_press", vk_code=int(vk_code), hwnd=int(hwnd or 0)))

    def key_press_str(self, text: str, delay: int = 30, hwnd: int = 0) -> bool:
        return bool(self._rpc.call("key_press_str", text=str(text or ""), delay=int(delay), hwnd=int(hwnd or 0)))

    def client_size(self, hwnd: int) -> tuple[int, int]:
        result = self._rpc.call("client_size", hwnd=int(hwnd))
        if isinstance(result, dict):
            return int(result.get("width") or 0), int(result.get("height") or 0)
        return (0, 0)

    def last_error(self, hwnd: int = 0) -> int:
        try:
            return int(self._rpc.call("last_error", hwnd=int(hwnd or 0)) or 0)
        except Exception:
            return 0

    def close(self) -> None:
        """共享宿主由主进程预热并复用，关闭客户端不断开、也不 shutdown。"""
        return


class NamedPipeTransport:
    def __init__(self, handle):
        self._handle = handle
        self._pending = b""

    def request(self, payload: dict) -> dict:
        try:
            self._handle.write(pack_message(payload))
            self._handle.flush()
        except (OSError, ValueError) as exc:
            raise PluginTransportError("plugin pipe write failed") from exc
        while True:
            try:
                chunk = self._handle.read(4096)
            except (OSError, ValueError) as exc:
                raise PluginTransportError("plugin pipe read failed") from exc
            if not chunk:
                error = EOFError("plugin pipe closed")
                raise PluginTransportError(str(error)) from error
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


def _pid_alive(pid: object) -> bool:
    try:
        value = int(pid or 0)
    except (TypeError, ValueError):
        return False
    if value <= 0:
        return False
    k32 = _kernel32()
    handle = k32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, value)
    if not handle:
        handle = k32.OpenProcess(_PROCESS_TERMINATE, False, value)
    if not handle:
        return False
    k32.CloseHandle(handle)
    return True


def _kill_pid(pid: object) -> None:
    try:
        value = int(pid or 0)
    except (TypeError, ValueError):
        return
    if value <= 0:
        return
    k32 = _kernel32()
    handle = k32.OpenProcess(_PROCESS_TERMINATE, False, value)
    if not handle:
        return
    try:
        k32.TerminateProcess(handle, 1)
    finally:
        k32.CloseHandle(handle)


def _read_attach_env() -> Optional[tuple[int, int]]:
    try:
        owner = int(str(os.environ.get(PLUGIN_OWNER_PID_ENV) or "").strip() or 0)
        host = int(str(os.environ.get(PLUGIN_HOST_PID_ENV) or "").strip() or 0)
    except (TypeError, ValueError):
        return None
    required = str(os.environ.get(PLUGIN_ATTACH_REQUIRED_ENV) or "").strip() == "1"
    if owner <= 0:
        return None
    if required:
        return owner, max(0, host)
    if host <= 0:
        return None
    return owner, host


def owns_plugin_host() -> bool:
    return bool(_OWNS_HOST)


def plugin_attach_env() -> dict[str, str]:
    try:
        inherited_owner = int(str(os.environ.get(PLUGIN_OWNER_PID_ENV) or "").strip() or 0)
    except (TypeError, ValueError):
        inherited_owner = 0
    owner = int(_OWNER_PID or inherited_owner or os.getpid())
    host = 0
    proc = _HOST_PROC
    if proc is not None and proc.poll() is None:
        host = int(proc.pid or 0)
    if host <= 0:
        host = int(_ATTACHED_HOST_PID or 0)
    if owner <= 0:
        return {}
    result = {
        PLUGIN_OWNER_PID_ENV: str(owner),
        PLUGIN_ATTACH_REQUIRED_ENV: "1",
    }
    if host > 0:
        result[PLUGIN_HOST_PID_ENV] = str(host)
    if owner == os.getpid() and (host <= 0 or not _pid_alive(host)):
        schedule_plugin_host_prewarm()
    return result


def prewarm_plugin_host() -> bool:
    cfg = _read_plugin_config()
    if not str(cfg.get("plugin_reg_code") or "").strip():
        return False
    if not is_plugin_runtime_available():
        return False
    try:
        ensure_plugin_rpc()
        return True
    except Exception:
        logger.debug("预热插件宿主失败", exc_info=True)
        return False


def schedule_plugin_host_prewarm() -> bool:
    """幂等调度单一 daemon 线程预热 owner 插件宿主。"""
    global _PREWARM_ACTIVE
    with _PREWARM_LOCK:
        if _PREWARM_ACTIVE:
            return False
        _PREWARM_ACTIVE = True

    def _worker() -> None:
        global _PREWARM_ACTIVE
        try:
            prewarm_plugin_host()
        finally:
            with _PREWARM_LOCK:
                _PREWARM_ACTIVE = False

    worker = threading.Thread(target=_worker, name="plugin-prewarm", daemon=True)
    try:
        worker.start()
    except Exception:
        with _PREWARM_LOCK:
            _PREWARM_ACTIVE = False
        logger.debug("启动插件宿主预热线程失败", exc_info=True)
        return False
    return True


def _release_local_rpc_locked() -> None:
    global _CACHED_RPC, _PIPE_FILE, _FRAME_MAP
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


def invalidate_plugin_rpc_connection() -> None:
    """仅丢弃本进程管道/映射，使附加进程下次连接稳定 owner pipe。"""
    with _ENSURE_LOCK:
        _release_local_rpc_locked()


def _teardown_host_locked() -> None:
    global _HOST_PROC, _JOB_HANDLE, _OWNS_HOST, _OWNER_PID, _ATTACHED_HOST_PID
    attached = int(_ATTACHED_HOST_PID or 0)
    _release_local_rpc_locked()
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
    elif attached > 0:
        _kill_pid(attached)
    _OWNS_HOST = False
    _OWNER_PID = 0
    _ATTACHED_HOST_PID = 0


def terminate_plugin_host() -> None:
    with _ENSURE_LOCK:
        _teardown_host_locked()


def _call_rpc_with_timeout(
    rpc: "PluginRpc",
    timeout: float,
    method: str,
    **args: Any,
) -> Any:
    box: dict = {}

    def _worker() -> None:
        try:
            box["result"] = rpc.call(method, **args)
        except Exception as exc:  # noqa: BLE001
            box["err"] = exc

    try:
        wait_seconds = max(0.05, float(timeout))
    except (TypeError, ValueError):
        wait_seconds = PLUGIN_INIT_TIMEOUT
    worker = threading.Thread(target=_worker, name=f"plugin-{method}", daemon=True)
    worker.start()
    worker.join(wait_seconds)
    if worker.is_alive():
        raise RuntimeError(f"插件 {method} 超时")
    if "err" in box:
        raise box["err"]
    return box.get("result")


def _init_rpc(rpc: "PluginRpc", directory: Path, cfg: dict) -> None:
    _call_rpc_with_timeout(
        rpc,
        PLUGIN_INIT_TIMEOUT,
        "init",
        plugin_dir=str(directory),
        reg_code=str(cfg["plugin_reg_code"]),
        extra_code=str(cfg.get("plugin_extra_code") or ""),
    )


def _connect_existing_host(owner_pid: int, host_pid: int, directory: Path, cfg: dict) -> "PluginRpc":
    global _CACHED_RPC, _PIPE_FILE, _FRAME_MAP, _OWNS_HOST, _OWNER_PID, _ATTACHED_HOST_PID
    _ = host_pid
    if not _pid_alive(owner_pid):
        raise RuntimeError("共享插件宿主 owner 未就绪")
    pipe_file = _connect_named_pipe(pipe_name(owner_pid), timeout=_PIPE_CONNECT_TIMEOUT)
    _PIPE_FILE = pipe_file
    mapping = _open_frame_map(owner_pid)
    _FRAME_MAP = mapping
    rpc = PluginRpc(
        NamedPipeTransport(pipe_file),
        frame_buf=memoryview(mapping),
        frame_lock=NamedFrameLock(frame_lock_name(owner_pid)),
    )
    _init_rpc(rpc, directory, cfg)
    actual_host_pid = int(rpc.call("host_pid") or 0)
    if actual_host_pid <= 0:
        raise RuntimeError("共享插件宿主未返回有效 PID")
    _OWNS_HOST = False
    _OWNER_PID = int(owner_pid)
    _ATTACHED_HOST_PID = actual_host_pid
    _CACHED_RPC = rpc
    return rpc


def ensure_plugin_rpc() -> PluginRpc:
    global _ATTACHED_HOST_PID, _CACHED_RPC, _HOST_PROC, _JOB_HANDLE
    global _PIPE_FILE, _FRAME_MAP, _OWNS_HOST, _OWNER_PID
    with _ENSURE_LOCK:
        if _CACHED_RPC is not None:
            if _OWNS_HOST and _host_alive():
                return _CACHED_RPC
            if (not _OWNS_HOST) and _pid_alive(_ATTACHED_HOST_PID):
                return _CACHED_RPC
            _release_local_rpc_locked()
        if should_cool_down():
            raise RuntimeError("插件宿主冷却中")
        if not is_plugin_runtime_available():
            raise RuntimeError("插件运行库不可用")
        directory = find_plugin_dir()
        if directory is None:
            raise RuntimeError("插件运行库不可用")
        arch_problem = check_plugin_runtime_arch(directory)
        if arch_problem:
            raise RuntimeError(arch_problem)
        exe = directory / "PluginHost.exe"
        cfg = _read_plugin_config()
        if not str(cfg.get("plugin_reg_code") or "").strip():
            raise RuntimeError("未填写插件注册码")
        attach = _read_attach_env()
        if attach is not None:
            try:
                return _connect_existing_host(attach[0], attach[1], directory, cfg)
            except Exception as exc:
                logger.warning("挂载共享插件宿主重连失败", exc_info=True)
                _release_local_rpc_locked()
                _OWNS_HOST = False
                _OWNER_PID = 0
                _ATTACHED_HOST_PID = 0
                raise RuntimeError("共享插件宿主未就绪/重连失败") from exc
        pid = os.getpid()
        pipe = pipe_name(pid)
        launched = False
        try:
            # CREATE_BREAKAWAY_FROM_JOB remains unset so the child can stay in our job.
            # CREATE_NO_WINDOW hides the console if PluginHost was built as CUI by mistake.
            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            proc = subprocess.Popen(
                launch_host_command(exe, pipe),
                cwd=str(directory),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags,
            )
            launched = True
            _HOST_PROC = proc
            _JOB_HANDLE = _attach_host_job(proc)
            pipe_file = _connect_named_pipe(pipe, timeout=_PIPE_CONNECT_TIMEOUT)
            _PIPE_FILE = pipe_file
            mapping = _open_frame_map(pid)
            _FRAME_MAP = mapping
            rpc = PluginRpc(
                NamedPipeTransport(pipe_file),
                frame_buf=memoryview(mapping),
                frame_lock=NamedFrameLock(frame_lock_name(pid)),
            )
            _init_rpc(rpc, directory, cfg)
            note_host_init_success()
            _OWNS_HOST = True
            _OWNER_PID = pid
            _CACHED_RPC = rpc
            return rpc
        except Exception:
            if launched:
                note_host_init_failure()
            _teardown_host_locked()
            raise


PLUGIN_UNBIND_TIMEOUT = 3.0


def unbind_plugin_host(timeout: float = PLUGIN_UNBIND_TIMEOUT, hwnd: int = 0) -> bool:
    """向当前宿主发 UnBindWindow（hwnd=0 解绑全部窗口）。只在宿主已存在且存活时发送，绝不为此拉起宿主；超时不阻塞调用方。"""
    with _ENSURE_LOCK:
        rpc = _CACHED_RPC
        alive = rpc is not None and (
            (_OWNS_HOST and _host_alive()) or ((not _OWNS_HOST) and _pid_alive(_ATTACHED_HOST_PID))
        )
    if not alive:
        return False
    try:
        _call_rpc_with_timeout(rpc, timeout, "unbind", hwnd=int(hwnd or 0))
        return True
    except Exception as exc:
        logger.warning("插件解绑失败: %s", exc)
        return False


def plugin_host_stats(timeout: float = 2.0) -> dict:
    """读取当前宿主的对象池统计；宿主不存在时返回空字典，绝不为此拉起宿主。"""
    with _ENSURE_LOCK:
        rpc = _CACHED_RPC
        alive = rpc is not None and (
            (_OWNS_HOST and _host_alive()) or ((not _OWNS_HOST) and _pid_alive(_ATTACHED_HOST_PID))
        )
    if not alive:
        return {}
    try:
        result = _call_rpc_with_timeout(rpc, timeout, "stats")
    except Exception as exc:
        logger.debug("读取插件宿主统计失败: %s", exc)
        return {}
    return dict(result) if isinstance(result, dict) else {}


def describe_plugin_host_stats(stats: Optional[dict]) -> str:
    values = dict(stats or {})
    if not values:
        return ""
    return (
        f"宿主对象池：绑定中 {int(values.get('slots') or 0)}，空闲 {int(values.get('free') or 0)}，"
        f"累计注册 {int(values.get('registrations') or 0)} 次（上限 {int(values.get('max_slots') or 0)} 个对象）"
    )


@dataclass(frozen=True)
class AuthProbeResult:
    ok: bool
    message: str
    version: str = ""


PLUGIN_AUTH_PROBE_TIMEOUT = 12.0


def probe_plugin_authorization(
    reg_code: str,
    extra_code: str = "",
    *,
    timeout: float = PLUGIN_AUTH_PROBE_TIMEOUT,
) -> AuthProbeResult:
    """用一个临时宿主验证注册码/附加码：init（Ver + Reg）成功即为通过，随后立刻关闭。

    不触碰共享宿主与冷却计数，设置页可以随时点、重复点。
    """
    code = str(reg_code or "").strip()
    if not code:
        return AuthProbeResult(False, "未填写插件注册码")
    directory = find_plugin_dir()
    if directory is None:
        return AuthProbeResult(False, "插件运行库不可用：安装目录 tools/plugin 缺少 PluginHost.exe / dm.dll / RegDll.dll")
    arch_problem = check_plugin_runtime_arch(directory)
    if arch_problem:
        return AuthProbeResult(False, arch_problem)

    pipe = f"{pipe_name(os.getpid())}-authprobe-{int(time.time() * 1000) % 100000}"
    proc: Optional[subprocess.Popen] = None
    pipe_file = None
    try:
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        proc = subprocess.Popen(
            launch_host_command(directory / "PluginHost.exe", pipe),
            cwd=str(directory),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
        )
        pipe_file = _connect_named_pipe(pipe, timeout=_PIPE_CONNECT_TIMEOUT)
        rpc = PluginRpc(NamedPipeTransport(pipe_file))
        _call_rpc_with_timeout(
            rpc,
            timeout,
            "init",
            plugin_dir=str(directory),
            reg_code=code,
            extra_code=str(extra_code or ""),
        )
        version = ""
        try:
            version = str(_call_rpc_with_timeout(rpc, 3.0, "version") or "")
        except Exception as exc:
            logger.debug("读取插件版本失败: %s", exc)
        try:
            _call_rpc_with_timeout(rpc, 2.0, "shutdown")
        except Exception:
            pass
        suffix = f"，dm 版本 {version}" if version else ""
        return AuthProbeResult(True, f"授权通过{suffix}", version)
    except Exception as exc:
        return AuthProbeResult(False, str(exc) or exc.__class__.__name__)
    finally:
        if pipe_file is not None:
            try:
                pipe_file.close()
            except Exception:
                pass
        if proc is not None:
            try:
                proc.wait(timeout=1.5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
