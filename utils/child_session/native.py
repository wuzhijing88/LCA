# -*- coding: utf-8 -*-
"""wtsapi32 Child Session 与 RDP 服务查询。"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import time
import winreg
from typing import Optional

ERROR_NOT_FOUND = 1168
ERROR_FILE_NOT_FOUND = 2
ERROR_RPC_SERVER_TOO_BUSY = 1753
NO_CHILD_SESSION_ID = 0xFFFFFFFF
DEFAULT_RDP_PORT = 3389
CHILD_SESSION_ENABLE_WAIT_SECONDS = 10
CHILD_SESSION_LOGOFF_DRAIN_SECONDS = 60
CHILD_SESSION_LOGOFF_POLL_SECONDS = 0.2
# RDP ActiveX 在登录初始化超时或刚断开时，TermService 可能持续一段时间返回
# RPC_SERVER_TOO_BUSY。注销必须覆盖这段释放窗口，否则会把仍在清理中的会话
# 错误地报告成注销失败，并在下一次启动时留下残留 Child Session。
CHILD_SESSION_LOGOFF_BUSY_SECONDS = CHILD_SESSION_LOGOFF_DRAIN_SECONDS
RDP_TCP_REGISTRY_PATH = r"SYSTEM\CurrentControlSet\Control\Terminal Server\WinStations\RDP-Tcp"
TERM_SERVICE_PARAMETERS_PATH = r"SYSTEM\CurrentControlSet\Services\TermService\Parameters"
RDP_WRAPPER_LIBRARY_NAME = "rdpwrap.dll"
RDP_INPUT_WINDOW_TITLE = "Input Capture Window"

_WTS: Optional[ctypes.WinDLL] = None
_USER32: Optional[ctypes.WinDLL] = None

def _wts() -> ctypes.WinDLL:
    global _WTS
    if _WTS is None:
        dll = ctypes.WinDLL("wtsapi32", use_last_error=True)
        dll.WTSEnableChildSessions.argtypes = [wintypes.BOOL]
        dll.WTSEnableChildSessions.restype = wintypes.BOOL
        dll.WTSIsChildSessionsEnabled.argtypes = [ctypes.POINTER(wintypes.BOOL)]
        dll.WTSIsChildSessionsEnabled.restype = wintypes.BOOL
        dll.WTSGetChildSessionId.argtypes = [ctypes.POINTER(wintypes.DWORD)]
        dll.WTSGetChildSessionId.restype = wintypes.BOOL
        dll.WTSLogoffSession.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL]
        dll.WTSLogoffSession.restype = wintypes.BOOL
        _WTS = dll
    return _WTS


def _user32() -> ctypes.WinDLL:
    global _USER32
    if _USER32 is None:
        dll = ctypes.WinDLL("user32", use_last_error=True)
        dll.EnumChildWindows.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.LPARAM]
        dll.EnumChildWindows.restype = wintypes.BOOL
        dll.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        dll.GetWindowTextW.restype = ctypes.c_int
        dll.SetFocus.argtypes = [wintypes.HWND]
        dll.SetFocus.restype = wintypes.HWND
        dll.GetFocus.argtypes = []
        dll.GetFocus.restype = wintypes.HWND
        dll.IsWindow.argtypes = [wintypes.HWND]
        dll.IsWindow.restype = wintypes.BOOL
        dll.IsChild.argtypes = [wintypes.HWND, wintypes.HWND]
        dll.IsChild.restype = wintypes.BOOL
        _USER32 = dll
    return _USER32


def _win32_error(operation: str) -> OSError:
    error = ctypes.get_last_error()
    return ctypes.WinError(error, f"{operation}（Win32 错误 {error}）")


def enable_child_sessions() -> None:
    if not _wts().WTSEnableChildSessions(True):
        raise _win32_error("无法启用 RDP Child Session")
    deadline = time.time() + float(CHILD_SESSION_ENABLE_WAIT_SECONDS)
    last_error = "已请求启用 Child Session，但系统仍未启用"
    while time.time() < deadline:
        try:
            if is_child_sessions_enabled():
                return
        except OSError as exc:
            last_error = str(exc)
        time.sleep(0.2)
    raise RuntimeError(last_error)


def is_child_sessions_enabled() -> bool:
    enabled = wintypes.BOOL(False)
    if not _wts().WTSIsChildSessionsEnabled(ctypes.byref(enabled)):
        raise _win32_error("无法读取 RDP Child Session 状态")
    return bool(enabled.value)


def try_get_child_session_id(*, strict: bool = False) -> Optional[int]:
    session_id = wintypes.DWORD(0)
    if not _wts().WTSGetChildSessionId(ctypes.byref(session_id)):
        if strict:
            error = ctypes.get_last_error()
            if error == ERROR_NOT_FOUND:
                return None
            raise ctypes.WinError(
                error,
                f"无法取得 RDP Child Session ID（Win32 错误 {error}）",
            )
        return None
    if int(session_id.value) == NO_CHILD_SESSION_ID:
        return None
    return int(session_id.value)


def terminate_child_session(*, wait: bool = True) -> Optional[int]:
    session_id = wintypes.DWORD(0)
    if not _wts().WTSGetChildSessionId(ctypes.byref(session_id)):
        error = ctypes.get_last_error()
        if error == ERROR_NOT_FOUND:
            return None
        raise ctypes.WinError(error, f"无法取得 RDP Child Session ID（Win32 错误 {error}）")
    value = int(session_id.value)
    if value == NO_CHILD_SESSION_ID:
        return None
    busy_deadline = time.time() + (float(CHILD_SESSION_LOGOFF_BUSY_SECONDS) if wait else 0)
    busy_retry_delay = float(CHILD_SESSION_LOGOFF_POLL_SECONDS)
    while True:
        if _wts().WTSLogoffSession(None, value, False):
            break
        error = ctypes.get_last_error()
        if error == ERROR_FILE_NOT_FOUND:
            return value
        if error == ERROR_RPC_SERVER_TOO_BUSY and time.time() < busy_deadline:
            time.sleep(busy_retry_delay)
            # 让 TermService 有时间完成会话清理，避免每 200ms 重复冲击 RPC。
            busy_retry_delay = min(busy_retry_delay * 2.0, 2.0)
            if try_get_child_session_id(strict=True) is None:
                return value
            continue
        raise ctypes.WinError(error, f"无法注销 Child Session {value}（Win32 错误 {error}）")
    if wait:
        _wait_until_child_session_gone()
    return value


def _wait_until_child_session_gone() -> None:
    deadline = time.time() + float(CHILD_SESSION_LOGOFF_DRAIN_SECONDS)
    while time.time() < deadline:
        if try_get_child_session_id(strict=True) is None:
            return
        time.sleep(float(CHILD_SESSION_LOGOFF_POLL_SECONDS))
    raise RuntimeError("注销桌面分身未完成，会话仍未结束")


def get_configured_rdp_port() -> int:
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            RDP_TCP_REGISTRY_PATH,
            0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        ) as key:
            raw, value_type = winreg.QueryValueEx(key, "PortNumber")
    except FileNotFoundError as exc:
        raise RuntimeError("无法读取 RDP 端口：缺少 RDP-Tcp 配置") from exc
    except OSError as exc:
        raise RuntimeError(f"无法读取 RDP 端口（Win32 错误 {exc.winerror}）") from exc
    if value_type not in (winreg.REG_DWORD, winreg.REG_DWORD_LITTLE_ENDIAN):
        raise RuntimeError(f"RDP 端口类型无效: {value_type}")
    port = int(raw)
    if port <= 0 or port > 65535:
        raise RuntimeError(f"RDP 端口无效: {port}")
    return port


def is_rdp_wrapper_enabled() -> bool:
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            TERM_SERVICE_PARAMETERS_PATH,
            0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        ) as key:
            raw, _value_type = winreg.QueryValueEx(key, "ServiceDll")
    except FileNotFoundError as exc:
        raise RuntimeError("无法读取远程桌面服务配置：缺少 TermService\\Parameters") from exc
    except OSError as exc:
        raise RuntimeError(f"无法读取远程桌面服务配置（Win32 错误 {exc.winerror}）") from exc
    path = str(raw or "")
    return RDP_WRAPPER_LIBRARY_NAME.lower() in path.lower()


def try_focus_rdp_input_window(rdp_host_hwnd: int) -> bool:
    input_window = _find_rdp_input_window(int(rdp_host_hwnd))
    if not input_window:
        return False
    user32 = _user32()
    user32.SetFocus(input_window)
    return int(user32.GetFocus() or 0) == input_window


def is_rdp_input_window_focused(rdp_host_hwnd: int) -> bool:
    input_window = _find_rdp_input_window(int(rdp_host_hwnd))
    if not input_window:
        return False
    return int(_user32().GetFocus() or 0) == input_window


_EnumChildProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def _find_rdp_input_window(rdp_host_hwnd: int) -> int:
    if not rdp_host_hwnd:
        return 0
    user32 = _user32()
    found = ctypes.c_void_p(0)

    @_EnumChildProc
    def callback(window, _lparam):
        buffer = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(window, buffer, 256)
        if buffer.value != RDP_INPUT_WINDOW_TITLE:
            return True
        found.value = window
        return False

    user32.EnumChildWindows(rdp_host_hwnd, callback, 0)
    return int(found.value or 0)
