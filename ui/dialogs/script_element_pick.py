"""元素拾取进程客户端；取消不等待 UIAutomation 原生调用返回。"""
import ctypes
import hashlib
import json
import msvcrt
import os
from ctypes import wintypes
from pathlib import Path
import subprocess
import tempfile
import threading
import time

import psutil
from PySide6.QtCore import QObject, Signal

from services.element_pick_worker import ElementInfo, MAX_MESSAGE_BYTES, PROTOCOL_VERSION, WORKER_FLAG, decode_message

READ_TIMEOUT = 8.0


class _LowLevelKeyboardData(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class EscapeKeyWatcher(QObject):
    """拾取期间用系统键盘钩子锁存 Esc 短按，避免轮询漏键。"""

    escape_pressed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread = None
        self._thread_id = 0
        self._hook = None
        self._callback = None
        self._ready = threading.Event()
        self._startup_error = None
        self._escape_latched = threading.Event()

    def start(self):
        if self._thread is not None:
            raise RuntimeError("Esc 监听已经启动")
        self._thread = threading.Thread(
            target=self._run_hook,
            name="lca-script-element-escape-hook",
            daemon=False,
        )
        self._thread.start()
        if not self._ready.wait(5):
            self.stop()
            raise TimeoutError("Esc 监听启动超时")
        if self._startup_error is not None:
            error, self._startup_error = self._startup_error, None
            self.stop()
            raise RuntimeError(f"无法启动 Esc 监听：{error}") from error

    def _run_hook(self):
        hook = None
        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            callback_type = ctypes.WINFUNCTYPE(
                ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM,
            )
            user32.SetWindowsHookExW.argtypes = [
                ctypes.c_int, callback_type, wintypes.HINSTANCE, wintypes.DWORD,
            ]
            user32.SetWindowsHookExW.restype = ctypes.c_void_p
            user32.CallNextHookEx.argtypes = [
                ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM,
            ]
            user32.CallNextHookEx.restype = ctypes.c_ssize_t
            user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
            user32.UnhookWindowsHookEx.restype = wintypes.BOOL
            user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
            user32.GetMessageW.restype = ctypes.c_int
            user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
            user32.PeekMessageW.restype = wintypes.BOOL
            user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
            user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
            user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            user32.PostThreadMessageW.restype = wintypes.BOOL
            kernel32.GetCurrentThreadId.restype = wintypes.DWORD
            kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
            kernel32.GetModuleHandleW.restype = wintypes.HMODULE
            self._thread_id = int(kernel32.GetCurrentThreadId())

            @callback_type
            def on_key(code, message, data):
                if code >= 0 and message in (0x0100, 0x0104):
                    key = ctypes.cast(data, ctypes.POINTER(_LowLevelKeyboardData)).contents
                    if key.vkCode == 0x1B:
                        if not self._escape_latched.is_set():
                            self._escape_latched.set()
                            self.escape_pressed.emit()
                        return 1
                return user32.CallNextHookEx(hook, code, message, data)

            self._callback = on_key
            hook = user32.SetWindowsHookExW(
                13, on_key, kernel32.GetModuleHandleW(None), 0,
            )
            if not hook:
                raise ctypes.WinError(ctypes.get_last_error())
            self._hook = hook
            message = wintypes.MSG()
            # 先创建线程消息队列，确保 start() 返回后立即 stop() 也能投递 WM_QUIT。
            user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 0)
            self._ready.set()
            while True:
                result = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result == 0:
                    break
                if result == -1:
                    raise ctypes.WinError(ctypes.get_last_error())
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
        except Exception as error:
            self._startup_error = error
            self._ready.set()
        finally:
            if hook:
                try:
                    if not user32.UnhookWindowsHookEx(hook):
                        self._startup_error = self._startup_error or ctypes.WinError(ctypes.get_last_error())
                except Exception as error:
                    self._startup_error = self._startup_error or error
            self._hook = None
            self._callback = None

    def stop(self):
        thread = self._thread
        if thread is None:
            return
        if thread.is_alive() and self._thread_id:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.PostThreadMessageW.argtypes = [
                wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
            ]
            user32.PostThreadMessageW.restype = wintypes.BOOL
            posted = False
            post_error = None
            for _ in range(5):
                if user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0):
                    posted = True
                    break
                post_error = ctypes.WinError(ctypes.get_last_error())
                if not thread.is_alive():
                    break
                time.sleep(0.01)
            if not posted and thread.is_alive():
                raise post_error or RuntimeError("无法通知 Esc 监听线程退出")
        thread.join(2)
        if thread.is_alive():
            raise TimeoutError("Esc 监听未能及时退出")
        self._thread = None
        if self._startup_error is not None:
            error, self._startup_error = self._startup_error, None
            raise RuntimeError(f"Esc 监听卸载失败：{error}") from error


def _worker_command(path, digest):
    from app_core.runtime.worker_entry import build_worker_launch_command
    return build_worker_launch_command(WORKER_FLAG, "services.element_pick_worker", "--standalone",
                                       ["--request", str(path), "--digest", digest])


def _element_info(value):
    fields = {"name", "automation_id", "class_name", "control_type", "bounding_rect"}
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("元素拾取结果字段无效")
    if any(not isinstance(value[key], str) for key in fields - {"bounding_rect"}):
        raise ValueError("元素拾取结果属性无效")
    bounds = value["bounding_rect"]
    if not isinstance(bounds, list) or len(bounds) != 4 or any(type(item) is not int for item in bounds) or bounds[2] <= 0 or bounds[3] <= 0:
        raise ValueError("元素拾取结果范围无效")
    return ElementInfo(**{**value, "bounding_rect": tuple(bounds)})


def _close_worker(process, job, assigned):
    from services.worker_process_cleanup import unregister_worker_process
    try:
        if assigned:
            job.terminate_and_wait(timeout=3)
        elif process is not None and process.poll() is None:
            process.terminate()
    finally:
        try:
            job.close()
        finally:
            if process is not None:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=3)
                try:
                    unregister_worker_process(process)
                finally:
                    try:
                        if process.stdout is not None:
                            process.stdout.close()
                    finally:
                        process._handle.Close()


def _read_messages(process, pending):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.PeekNamedPipe.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                                    ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    kernel.PeekNamedPipe.restype = wintypes.BOOL
    available = wintypes.DWORD()
    pipe = msvcrt.get_osfhandle(process.stdout.fileno())
    if not kernel.PeekNamedPipe(pipe, None, 0, None, ctypes.byref(available), None):
        if ctypes.get_last_error() == 109:  # 子进程关闭输出端，剩余结果已在上一轮读完。
            return pending, []
        raise ctypes.WinError(ctypes.get_last_error())
    if not available.value:
        return pending, []
    pending += os.read(process.stdout.fileno(), min(65536, available.value))
    lines = pending.split(b"\n")
    pending = lines.pop()
    if len(pending) > MAX_MESSAGE_BYTES:
        raise ValueError("元素拾取消息超过长度上限")
    return pending, [decode_message(line) for line in lines]


def pick_element(confirm, cancelled, progress):
    from app_core.runtime.worker_entry import build_worker_process_env
    from app_core.script_process_job import ProcessJob
    from services.worker_process_cleanup import register_worker_process

    if cancelled.is_set():
        return None
    with tempfile.TemporaryDirectory(prefix="lca-element-pick-") as directory:
        source = Path(directory) / "request.json"
        payload = json.dumps({"version": PROTOCOL_VERSION}).encode("utf-8")
        source.write_bytes(payload)
        job = ProcessJob()
        process = None
        assigned = False
        try:
            process = subprocess.Popen(
                _worker_command(source, hashlib.sha256(payload).hexdigest()),
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                env=build_worker_process_env(include_plugin_attach=False),
                creationflags=subprocess.CREATE_NO_WINDOW | 0x00000004,
            )
            job.assign(process)
            assigned = True
            register_worker_process(process, WORKER_FLAG)
            psutil.Process(process.pid).resume()
            pending = b""
            previous_sequence = None
            previous_bounds = None
            deadline = time.monotonic() + READ_TIMEOUT
            while True:
                if cancelled.wait(0.01):
                    return None
                if confirm.is_set() and not (Path(directory) / "confirm").exists():
                    (Path(directory) / "confirm").touch()
                return_code = process.poll()
                pending, messages = _read_messages(process, pending)
                for message in messages:
                    kind = message.get("kind")
                    if kind == "selected" and set(message) == {"version", "kind", "info"}:
                        return _element_info(message["info"])
                    if kind == "cancelled" and set(message) == {"version", "kind"}:
                        return None
                    if kind == "failed" and set(message) == {"version", "kind", "message"} and isinstance(message["message"], str):
                        raise RuntimeError("元素拾取失败：" + message["message"])
                    if kind != "progress" or set(message) != {"version", "kind", "sequence", "info"} or type(message["sequence"]) is not int:
                        raise ValueError("元素拾取进程返回了非法状态")
                    if message["sequence"] != previous_sequence:
                        previous_sequence = message["sequence"]
                        deadline = time.monotonic() + READ_TIMEOUT
                        info = _element_info(message["info"]) if message["info"] is not None else None
                        bounds = info.bounding_rect if info is not None else None
                        if bounds is not None and bounds != previous_bounds and not cancelled.is_set():
                            progress(bounds)
                            previous_bounds = bounds
                if return_code is not None:
                    raise RuntimeError("元素拾取进程意外退出，未返回结果")
                if time.monotonic() >= deadline:
                    raise TimeoutError("元素读取超时，已终止本次拾取进程")
        finally:
            _close_worker(process, job, assigned)



def escape_pressed():
    import ctypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.GetAsyncKeyState.restype = ctypes.c_short
    return bool(user32.GetAsyncKeyState(0x1B) & 0x8000)
