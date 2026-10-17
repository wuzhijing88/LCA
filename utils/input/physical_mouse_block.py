"""绑定窗口的输入队列屏蔽；窗口消息输入不经过 WH_MOUSE。"""

from __future__ import annotations

import atexit
import ctypes
from ctypes import wintypes
from pathlib import Path
from queue import Queue
import threading

import win32gui

from utils.app_paths import get_app_root

_COMMAND = 0x8001
_TIMER = 0x0113
_sessions = set()


def _check(error: int, action: str) -> None:
    if error:
        raise OSError(error, f"{action}失败：{ctypes.FormatError(error).strip()}")


class _MouseBlockSession:
    """一个进程共用一个钩子线程；原生回调无需进入 Python 或获取 GIL。"""

    def __init__(self, targets):
        if ctypes.sizeof(ctypes.c_void_p) != 8:
            raise RuntimeError("屏蔽物理鼠标需要 64 位运行环境")
        self._targets = tuple(targets)
        self._requests = Queue()
        self._request_lock = threading.Lock()
        self._stopped = False
        self._ready = threading.Event()
        self._error = None
        self._native = None
        self._unreleased = False
        self._thread_id = 0
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        self._user32.PostThreadMessageW.restype = wintypes.BOOL
        self._thread = threading.Thread(target=self._run, name="后台物理鼠标屏蔽", daemon=True)

    def start(self):
        _sessions.add(self)
        try:
            self._thread.start()
        except Exception:
            _sessions.discard(self)
            raise
        # 安装必须确认完成，不能在结果未知时开始后台操作。
        self._ready.wait()
        if self._error is not None:
            self._thread.join()
            if not self._unreleased:
                _sessions.discard(self)
            raise self._error

    @property
    def active(self):
        return self._thread.is_alive()

    def update(self, targets):
        self._request(tuple(targets))

    def check(self):
        if self._error is not None:
            raise self._error
        if not self.active:
            raise RuntimeError("物理鼠标屏蔽已停止，禁止继续后台输入")

    def close(self):
        if self.active:
            self._request(None)
        if self._thread.ident is not None:
            self._thread.join()
        if self._unreleased:
            _check(self._native.StopMouseBlock(), "卸载物理鼠标屏蔽")
            self._unreleased = False
            self._unload()
        _sessions.discard(self)

    def _unload(self):
        if self._native is not None:
            from _ctypes import FreeLibrary

            FreeLibrary(self._native._handle)
            self._native = None

    def _request(self, targets):
        completed = threading.Event()
        result = []
        with self._request_lock:
            if self._stopped or not self.active:
                raise RuntimeError("物理鼠标屏蔽线程已停止")
            self._requests.put((targets, completed, result))
            if not self._user32.PostThreadMessageW(self._thread_id, _COMMAND, 0, 0):
                completed.set()
                raise ctypes.WinError(ctypes.get_last_error())
        completed.wait()
        if result:
            raise result[0]

    def _run(self):
        native = None
        started = False
        timer = 0
        user32 = self._user32
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p]
        user32.SetTimer.restype = ctypes.c_size_t
        user32.KillTimer.argtypes = [wintypes.HWND, ctypes.c_size_t]
        user32.KillTimer.restype = wintypes.BOOL
        user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        user32.GetMessageW.restype = wintypes.BOOL
        user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
        user32.IsWindow.argtypes = [wintypes.HWND]
        user32.IsWindow.restype = wintypes.BOOL

        def set_targets(call, targets):
            handles = (wintypes.HWND * len(targets))(*targets)
            _check(call(handles, len(targets)), "设置物理鼠标屏蔽窗口")
            self._targets = targets

        try:
            path = Path(get_app_root()) / "tools" / "background_input" / "MouseBlock.dll"
            if not path.is_file():
                raise FileNotFoundError(f"缺少物理鼠标屏蔽组件：{path}")
            native = ctypes.WinDLL(str(path), use_last_error=True)
            self._native = native
            for name in ("StartMouseBlock", "UpdateMouseBlock"):
                call = getattr(native, name)
                call.argtypes = [ctypes.POINTER(wintypes.HWND), wintypes.LONG]
                call.restype = wintypes.DWORD
            native.StopMouseBlock.argtypes = []
            native.StopMouseBlock.restype = wintypes.DWORD
            message = wintypes.MSG()
            user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 0)
            self._thread_id = kernel32.GetCurrentThreadId()
            set_targets(native.StartMouseBlock, self._targets)
            started = True
            timer = user32.SetTimer(None, 0, 300, None)
            if not timer:
                raise ctypes.WinError(ctypes.get_last_error())
            self._ready.set()
            while True:
                status = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                if status == -1:
                    raise ctypes.WinError(ctypes.get_last_error())
                if status == 0:
                    break
                if message.message == _COMMAND:
                    targets, completed, result = self._requests.get_nowait()
                    if completed.is_set():
                        continue
                    try:
                        if targets is None:
                            _check(native.StopMouseBlock(), "卸载物理鼠标屏蔽")
                            started = False
                        else:
                            set_targets(native.UpdateMouseBlock, targets)
                        self._error = None
                    except Exception as exc:
                        result.append(exc)
                    finally:
                        completed.set()
                    if not started:
                        break
                elif message.message == _TIMER and message.wParam == timer:
                    live = tuple(hwnd for hwnd in self._targets if user32.IsWindow(hwnd))
                    if not live:
                        _check(native.StopMouseBlock(), "卸载物理鼠标屏蔽")
                        started = False
                        break
                    if live != self._targets:
                        set_targets(native.UpdateMouseBlock, live)
        except Exception as exc:
            self._error = exc
        finally:
            if timer:
                user32.KillTimer(None, timer)
            if started:
                try:
                    _check(native.StopMouseBlock(), "卸载物理鼠标屏蔽")
                except Exception as exc:
                    self._error = exc
                    self._unreleased = True
            if not self._unreleased:
                self._unload()
            with self._request_lock:
                self._stopped = True
                self._ready.set()
                while not self._requests.empty():
                    _, completed, result = self._requests.get_nowait()
                    result.append(self._error or RuntimeError("物理鼠标屏蔽线程已停止"))
                    completed.set()


class _MouseBlockLease:
    def __init__(self, manager, token):
        self._manager = manager
        self._token = token

    def close(self):
        if self._token is not None:
            self._manager.release(self._token)
            self._token = None

    def check(self):
        self._manager.check(self._token)


class PhysicalMouseBlockManager:
    """缓存实例、临时动作、多线程共用引用计数，最后一个使用者负责卸载。"""

    def __init__(self):
        self._lock = threading.RLock()
        self._leases = {}
        self._session = None

    def acquire(self, targets):
        with self._lock:
            token = object()
            windows = tuple(sorted(set(targets)))
            if not windows:
                raise ValueError("屏蔽物理鼠标需要绑定窗口")
            existing = {hwnd for values in self._leases.values() for hwnd in values if win32gui.IsWindow(hwnd)}
            merged = tuple(sorted(existing.union(windows)))
            if self._session is not None and not self._session.active:
                self._session.close()
                self._session = None
            if self._session is None:
                self._session = _MouseBlockSession(merged)
                try:
                    self._session.start()
                except Exception:
                    self._session.close()
                    self._session = None
                    raise
            else:
                self._session.update(merged)
            self._leases[token] = windows
            return _MouseBlockLease(self, token)

    def check(self, token):
        with self._lock:
            if token not in self._leases or self._session is None:
                raise RuntimeError("物理鼠标屏蔽已释放，禁止继续后台输入")
            self._session.check()

    def release(self, token):
        with self._lock:
            if token not in self._leases:
                return
            remaining = {key: value for key, value in self._leases.items() if key is not token}
            live = tuple(sorted({hwnd for values in remaining.values() for hwnd in values if win32gui.IsWindow(hwnd)}))
            if self._session is not None:
                if not live or not self._session.active:
                    self._session.close()
                    self._session = None
                else:
                    self._session.update(live)
            self._leases = remaining

    def close(self):
        with self._lock:
            if self._session is not None:
                self._session.close()
                self._session = None
            self._leases.clear()


physical_mouse_block_manager = PhysicalMouseBlockManager()


def _close_sessions():
    errors = []
    try:
        physical_mouse_block_manager.close()
    except Exception as exc:
        errors.append(str(exc))
    for session in tuple(_sessions):
        try:
            session.close()
        except Exception as exc:
            errors.append(str(exc))
    if errors:
        raise RuntimeError("卸载物理鼠标屏蔽失败：" + "；".join(errors))


atexit.register(_close_sessions)
