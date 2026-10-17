# -*- coding: utf-8 -*-
"""用 BetterGI 同款 WinForms AxHost 宿主进程嵌入 Child Session。"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QWindow
from PySide6.QtWidgets import QApplication, QSizePolicy, QVBoxLayout, QWidget

from utils.app_paths import get_app_root
from utils.child_session import native as child_native

logger = logging.getLogger(__name__)

CREATE_NO_WINDOW = 0x08000000
HOST_READY_WAIT_SECONDS = 30
HOST_READY_POLL_SECONDS = 0.05


@dataclass(frozen=True)
class ChildSessionConnectionFailedEventArgs:
    message: str
    error_code: int = 0
    extended_error_code: Optional[int] = None


def _resolve_rdp_port() -> int:
    return child_native.get_configured_rdp_port()


def _reap_host_process(process: subprocess.Popen) -> None:
    try:
        process.wait(timeout=5)
        return
    except Exception:
        pass
    try:
        process.kill()
    except Exception:
        return
    try:
        process.wait(timeout=2)
    except Exception:
        pass


def rdp_child_host_exe() -> str:
    root = get_app_root()
    path = os.path.join(root, "tools", "rdp_child_host", "RdpChildHost.exe")
    if not os.path.isfile(path):
        raise FileNotFoundError("找不到桌面分身宿主 RdpChildHost.exe")
    return path


class RdpActiveXHost(QWidget):
    connection_failed = Signal(object)
    login_completed = Signal()
    desktop_update_failed = Signal(str)
    desktop_update_succeeded = Signal(int, int)
    transport_connected = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._process: Optional[subprocess.Popen] = None
        self._reader: Optional[threading.Thread] = None
        self._stdin_lock = threading.Lock()
        self._connected_state = 0
        self._host_disposed = False
        self._send_system_shortcuts_to_remote = True
        self._audio_muted = False
        self._smart_sizing_enabled = True
        self._block_physical_mouse = False
        self._connection_attempt_in_progress = False
        self._connection_failure_reported = False
        self._disconnect_requested = False
        self._pending_reconnect_size: Optional[QSize] = None
        self._last_connection_diagnostic: Optional[ChildSessionConnectionFailedEventArgs] = None
        self._ready = threading.Event()
        self._desktop_width = 1920
        self._desktop_height = 1080
        self._host_hwnd = 0
        self._session_ended = False
        self._recreate_host_on_next_connect = False
        self._output_generation = 0
        self._embed_container = None
        self._embed_window = None
        self._place_timer = QTimer(self)
        self._place_timer.setInterval(50)
        self._place_timer.timeout.connect(self._sync_place)
        self._last_place = None
        self.transport_connected.connect(self._present_desktop)


    @property
    def last_connection_diagnostic(self) -> Optional[ChildSessionConnectionFailedEventArgs]:
        return self._last_connection_diagnostic

    @property
    def connected_state(self) -> int:
        return int(self._connected_state)

    def set_smart_sizing(self, enabled: bool) -> None:
        self._smart_sizing_enabled = bool(enabled)
        if self._process is None:
            return
        self._write("SMART_SIZING {0}".format("1" if enabled else "0"))

    def set_send_system_shortcuts_to_remote(self, enabled: bool) -> None:
        self._send_system_shortcuts_to_remote = bool(enabled)
        if self._process is not None:
            # KeyboardHookMode 只在宿主的 Connect() 中读取。设置重连时必须
            # 重建宿主，才能让新的 --shortcuts 参数进入 RDP ActiveX。
            self._recreate_host_on_next_connect = True

    def set_audio_muted(self, muted: bool) -> None:
        self._audio_muted = bool(muted)
        if self._process is None:
            return
        self._write("MUTE {0}".format("1" if self._audio_muted else "0"))

    def set_block_physical_mouse(self, enabled: bool) -> None:
        self._block_physical_mouse = bool(enabled)
        if self._process is None:
            return
        self._write("MOUSE_BLOCK {0}".format("1" if self._block_physical_mouse else "0"))

    def apply_desktop_size(self, width: int, height: int) -> None:
        self._desktop_width = int(width)
        self._desktop_height = int(height)
        if self._process is None:
            return
        self._write(
            "DESKTOP {0} {1}".format(self._desktop_width, self._desktop_height)
        )

    def connect_to_child_session(self, width: int, height: int) -> None:
        if self.connected_state != 0:
            return
        self._desktop_width = int(width)
        self._desktop_height = int(height)
        if self._session_ended or self._recreate_host_on_next_connect:
            self._retire_host_process()
            self._session_ended = False
            self._recreate_host_on_next_connect = False
        self._ensure_host(width, height)
        # 新宿主或断开后复用的宿主都要重新下发一次模式，不能沿用上一次
        # Python 侧的缓存状态。
        self._connection_attempt_in_progress = True
        self._connection_failure_reported = False
        self._last_connection_diagnostic = None
        self._disconnect_requested = False
        self._connected_state = 2
        self._write(
            "MOUSE_BLOCK {0}".format("1" if self._block_physical_mouse else "0")
        )
        self._write(
            "DESKTOP {0} {1}".format(self._desktop_width, self._desktop_height)
        )
        if self._embed_container is None:
            self._sync_place()
        self._write("CONNECT")

    def reconnect_to_child_session(self, width: int, height: int) -> None:
        size = QSize(int(width), int(height))
        if self._disconnect_requested or self._pending_reconnect_size is not None:
            self._pending_reconnect_size = size
            return
        if self.connected_state == 0:
            self.connect_to_child_session(size.width(), size.height())
            return
        self._pending_reconnect_size = size
        if not self._disconnect_core():
            self._pending_reconnect_size = None
            self.connect_to_child_session(size.width(), size.height())

    def disconnect_session(self) -> None:
        self._pending_reconnect_size = None
        self._disconnect_core()

    def expect_disconnect(self) -> None:
        self._disconnect_requested = True

    def send_show_desktop_shortcut(self) -> None:
        self._send_session_keys("WIN_D", "显示桌面")

    def send_task_view_shortcut(self) -> None:
        self._send_session_keys("WIN_TAB", "任务视图")

    def _send_session_keys(self, chord: str, action: str) -> None:
        if self._process is None or self.connected_state != 1:
            raise RuntimeError("桌面分身尚未进入桌面，无法{0}。".format(action))
        self._write("KEYS {0}".format(chord))

    def is_input_window_focused(self) -> bool:
        return False

    def dispose(self) -> None:
        if self._host_disposed:
            return
        self._host_disposed = True
        self._output_generation += 1
        self._place_timer.stop()
        self._pending_reconnect_size = None
        self._release_embed()
        try:
            self._write("QUIT")
        except Exception:
            pass
        process = self._process
        self._process = None
        if process is not None:
            try:
                if process.stdin is not None:
                    process.stdin.close()
            except Exception:
                pass
            try:
                process.terminate()
            except Exception:
                pass
            threading.Thread(
                target=_reap_host_process,
                args=(process,),
                daemon=True,
                name="rdp-host-reap",
            ).start()
        self._join_reader()
        self._connected_state = 0

    def _retire_host_process(self) -> None:
        self._output_generation += 1
        self._place_timer.stop()
        self._release_embed()
        self._host_hwnd = 0
        self._ready.clear()
        self._last_place = None
        self._connected_state = 0
        process = self._process
        self._process = None
        if process is None:
            return
        try:
            if process.stdin is not None:
                process.stdin.write(b"QUIT\n")
                process.stdin.flush()
                process.stdin.close()
        except Exception:
            pass
        try:
            process.terminate()
        except Exception:
            pass
        threading.Thread(
            target=_reap_host_process,
            args=(process,),
            daemon=True,
            name="rdp-host-reap",
        ).start()
        self._join_reader()

    def _release_embed(self) -> None:
        container = self._embed_container
        self._embed_container = None
        self._embed_window = None
        if container is None:
            return
        container.hide()
        container.setParent(None)
        container.deleteLater()

    def _join_reader(self) -> None:
        reader = self._reader
        self._reader = None
        if reader is None or reader is threading.current_thread():
            return
        reader.join(timeout=2)

    def _store_host_hwnd(self, line: str) -> bool:
        prefix = ""
        if line.startswith("HWND "):
            prefix = "HWND "
        elif line.startswith("句柄 "):
            prefix = "句柄 "
        if not prefix:
            return False
        text = line[len(prefix):].strip()
        try:
            self._host_hwnd = int(text)
        except ValueError:
            logger.error("桌面分身宿主窗口句柄无效: %s", text)
        return True

    def _present_desktop(self) -> None:
        if self._host_disposed:
            return
        self._sync_place()
        self._place_timer.stop()
        if not self._host_hwnd or self._embed_container is not None:
            return
        try:
            self._embed_host_window()
        except Exception as exc:
            logger.error("无法嵌入桌面分身画面: %s", exc)
            self._place_timer.start()
            self._report_failure("无法嵌入桌面分身画面。", 0)

    def _embed_host_window(self) -> None:
        if self._embed_container is not None:
            return
        hwnd = int(self._host_hwnd)
        if hwnd <= 0:
            raise RuntimeError("桌面分身宿主没有报告窗口句柄，无法显示桌面。")
        foreign = QWindow.fromWinId(hwnd)
        container = QWidget.createWindowContainer(foreign, self)
        container.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout = self.layout()
        if layout is None:
            layout = QVBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
        layout.addWidget(container)
        self._embed_window = foreign
        self._embed_container = container
        self._place_timer.stop()
        self._last_place = None
        self._write("EMBEDDED")

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._place_timer.stop()
        if not self._host_disposed:
            self._write("HIDE")

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._process is None or self._host_disposed:
            return
        if self._embed_container is not None:
            self._place_timer.stop()
            self._write("SHOW")
            return
        if self._connected_state == 1:
            self._place_timer.stop()
            return
        self._place_timer.start()
        self._sync_place()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_place()

    def closeEvent(self, event) -> None:
        self.dispose()
        super().closeEvent(event)

    def _ensure_host(self, width: int, height: int) -> None:
        if self._process is not None and self._process.poll() is None:
            return
        if self._process is not None:
            self._retire_host_process()
        self._release_embed()
        self._host_hwnd = 0
        parent = int(self.winId())
        if not parent:
            raise RuntimeError("桌面分身窗口尚未完成初始化，无法创建 RDP 控件。")
        exe = rdp_child_host_exe()
        args = [
            exe,
            "--parent",
            str(parent),
            "--width",
            str(max(200, int(width))),
            "--height",
            str(max(200, int(height))),
            "--port",
            str(_resolve_rdp_port()),
            "--mute",
            "1" if self._audio_muted else "0",
            "--shortcuts",
            "1" if self._send_system_shortcuts_to_remote else "0",
            "--smart-sizing",
            "1" if self._smart_sizing_enabled else "0",
            "--credssp",
            "1",
            "--mouse-block",
            "1" if self._block_physical_mouse else "0",
        ]
        self._ready.clear()
        self._process = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=CREATE_NO_WINDOW,
        )
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._reader.start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        self._wait_until_ready()

    def _wait_until_ready(self) -> None:
        app = QApplication.instance()
        deadline = time.monotonic() + float(HOST_READY_WAIT_SECONDS)
        while not self._ready.is_set():
            if time.monotonic() >= deadline:
                self._abort_unready_host()
                raise RuntimeError("桌面分身宿主没有在限定时间内就绪。")
            if app is not None:
                app.processEvents()
            self._ready.wait(HOST_READY_POLL_SECONDS)

    def _abort_unready_host(self) -> None:
        self._output_generation += 1
        process = self._process
        self._process = None
        if process is None:
            return
        try:
            process.kill()
        except Exception:
            pass
        try:
            process.wait(timeout=2)
        except Exception:
            pass
        self._join_reader()

    def _write(self, line: str) -> None:
        process = self._process
        if process is None or process.stdin is None:
            return
        try:
            with self._stdin_lock:
                process.stdin.write((line + "\n").encode("utf-8"))
                process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as exc:
            logger.warning("桌面分身宿主管道已断开: %s", exc)
            self._connected_state = 0
            self._connection_attempt_in_progress = False
            if not self._host_disposed:
                self._report_failure("桌面分身宿主进程已断开。", 0)

    def _read_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        for raw in iter(process.stderr.readline, b""):
            text = raw.decode("utf-8", errors="replace").strip()
            if text:
                logger.warning("RdpChildHost: %s", text)

    def _read_stdout(self) -> None:
        generation = self._output_generation
        process = self._process
        if process is None or process.stdout is None:
            return
        for raw in iter(process.stdout.readline, b""):
            if generation != self._output_generation:
                return
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            logger.info("RdpChildHost: %s", line)
            try:
                self._handle_host_line(line)
            except Exception as exc:
                logger.exception("处理桌面分身宿主消息失败: %s", exc)
                self._connected_state = 0
                self._connection_attempt_in_progress = False
                if not self._host_disposed:
                    self._report_failure("桌面分身宿主返回了无效消息。", 0)
        if generation != self._output_generation or self._host_disposed:
            return
        self._place_timer.stop()
        self._connected_state = 0
        self._connection_attempt_in_progress = False
        self._session_ended = True
        self._report_failure("桌面分身宿主进程已退出，RDP 连接已断开。", 0)

    def _handle_host_line(self, line: str) -> None:
        if line == "HOST_READY":
            self._ready.set()
            return
        if self._store_host_hwnd(line):
            return
        if (
            line.startswith("PROPERTY ")
            or line.startswith("CONNECT ")
            or line.startswith("SMART_SIZING_OK")
            or line.startswith("KEYS_OK")
            or line.startswith("MOUSE_BLOCK_OK")
            or line.startswith("MUTE_OK")
        ):
            return
        if (
            line.startswith("SMART_SIZING_FAILED ")
            or line.startswith("KEYS_FAILED ")
            or line.startswith("MUTE_FAILED ")
        ):
            logger.error("桌面分身宿主命令失败: %s", line)
            return
        if line == "CONNECTED":
            self.transport_connected.emit()
            return
        if line == "LOGIN":
            self._connected_state = 1
            self._connection_attempt_in_progress = False
            self._connection_failure_reported = False
            self._last_connection_diagnostic = None
            self.login_completed.emit()
            return
        if line.startswith("DESKTOP_OK "):
            parts = line.split()
            if len(parts) >= 3:
                self.desktop_update_succeeded.emit(int(parts[1]), int(parts[2]))
            return
        if line.startswith("DESKTOP_FAILED "):
            self.desktop_update_failed.emit(line.split(" ", 1)[1].strip())
            return
        if line.startswith("DISCONNECT "):
            parts = line.split(" ", 3)
            reason = int(parts[1])
            extended = int(parts[2]) if len(parts) > 2 and parts[2].lstrip("-").isdigit() else 0
            description = parts[3].strip() if len(parts) > 3 else ""
            if not self._disconnect_requested:
                self._session_ended = True
            self._connected_state = 0
            self._write("HIDE")
            self._on_disconnected(reason, extended, description)
            return
        if line.startswith("FATAL "):
            code = int(line.split(" ", 1)[1])
            self._connected_state = 0
            self._write("HIDE")
            self._report_failure(
                f"RDP 客户端发生致命错误：{_fatal_error_text(code)}\n\n错误代码：{_format_error(code)}",
                code,
            )
            return
        if line.startswith("LOGON "):
            code = int(line.split(" ", 1)[1])
            message = f"RDP 登录阶段：{_logon_error_text(code)}\n\n错误代码：{_format_error(code)}"
            if code in (-5, -4, -2, 3):
                self._last_connection_diagnostic = ChildSessionConnectionFailedEventArgs(message, code)
                return
            self._connection_attempt_in_progress = False
            self._report_failure(message.replace("RDP 登录阶段：", "RDP 登录失败：", 1), code)
            return
        if line.startswith("ERROR "):
            if self._disconnect_requested and _is_closed_session_error(line):
                return
            self._connection_attempt_in_progress = False
            self._report_failure(line[6:], 0)

    def _sync_place(self) -> None:
        if self._embed_container is not None or self._connected_state == 1:
            return
        if self._process is None or self._host_disposed or not self.isVisible():
            return
        top_left = self.mapToGlobal(QPoint(0, 0))
        place = (
            int(top_left.x()),
            int(top_left.y()),
            max(1, int(self.width())),
            max(1, int(self.height())),
        )
        if place == self._last_place:
            return
        self._last_place = place
        self._write("PLACE {0} {1} {2} {3}".format(*place))

    def _disconnect_core(self) -> bool:
        if self._process is None or self.connected_state == 0:
            return False
        self._disconnect_requested = True
        self._write("DISCONNECT")
        return True

    def _on_disconnected(self, disconnect_reason: int, extended: int = 0, description: str = "") -> None:
        failed_while_connecting = self._connection_attempt_in_progress
        self._connection_attempt_in_progress = False
        if self._disconnect_requested:
            self._disconnect_requested = False
            pending = self._pending_reconnect_size
            self._pending_reconnect_size = None
            if pending is not None:
                self.connect_to_child_session(pending.width(), pending.height())
            return
        if self._connection_failure_reported or (
            not failed_while_connecting and _is_normal_disconnect(disconnect_reason, extended)
        ):
            return
        title = "RDP 连接失败" if failed_while_connecting else "RDP 连接意外断开"
        if description:
            message = (
                f"{title}：{description}\n\n断开原因：{_format_error(disconnect_reason)}\n"
                f"扩展原因：{_format_error(extended)}"
            )
        else:
            message = (
                f"{title}。\n\n断开原因：{_format_error(disconnect_reason)}\n"
                f"扩展原因：{_format_error(extended)}"
            )
        hint = _disconnect_hint(disconnect_reason, extended)
        if hint:
            message = f"{message}\n\n{hint}"
        self._report_failure(message, disconnect_reason, extended)

    def _report_failure(
        self,
        message: str,
        error_code: int,
        extended_error_code: Optional[int] = None,
    ) -> None:
        if self._connection_failure_reported:
            return
        self._connection_failure_reported = True
        args = ChildSessionConnectionFailedEventArgs(message, int(error_code), extended_error_code)
        self._last_connection_diagnostic = args
        self.connection_failed.emit(args)


def _disconnect_hint(disconnect_reason: int, extended: int = 0) -> str:
    if int(disconnect_reason) == 2 and int(extended) == 12:
        return (
            "子会话已经连上，但 Windows 没有收到当前账户的密码，登录被拒绝。"
            "请在弹出的登录框中输入当前 Windows 账户的密码，不要填写 PIN。"
        )
    if int(disconnect_reason) != 516:
        return ""
    try:
        wrapper_enabled = child_native.is_rdp_wrapper_enabled()
    except Exception as exc:
        logger.warning("读取 RDP Wrapper 状态失败: %s", exc)
        wrapper_enabled = False
    if wrapper_enabled:
        return (
            "断开原因 516 表示没有建立到本机 Child Session 的连接。"
            "当前远程桌面服务仍加载着 RDP Wrapper。"
        )
    return (
        "断开原因 516 表示没有建立到本机 Child Session 的连接。"
        "请确认已启用远程桌面，并且本机 RDP 端口正在监听。"
    )


def _is_closed_session_error(line: str) -> bool:
    return "HRESULT=0x80004005" in line or "HRESULT=0x8000FFFF" in line


def _is_normal_disconnect(disconnect_reason: int, extended: int) -> bool:
    return disconnect_reason in (1, 2, 3) and extended in (0, 1, 2)


def _format_error(error_code: int) -> str:
    return f"{int(error_code)} (0x{int(error_code) & 0xFFFFFFFF:08X})"


def _fatal_error_text(error_code: int) -> str:
    mapping = {
        0: "发生未知错误。",
        1: "发生内部错误（1）。",
        2: "内存不足。",
        3: "无法创建 RDP 窗口。",
        4: "发生内部错误（2）。",
        5: "RDP 客户端进入了无效状态。",
        6: "发生内部错误（4）。",
        7: "发生不可恢复的连接错误。",
        100: "Windows 套接字初始化失败。",
    }
    return mapping.get(int(error_code), "发生未识别的致命错误。")


def _logon_error_text(error_code: int) -> str:
    mapping = {
        -7: "Winlogon 正在显示“拒绝断开现有会话”对话框。",
        -6: "Winlogon 正在显示“无权限”对话框。",
        -5: "Winlogon 正在显示会话争用选项。",
        -4: "Winlogon 正在显示重新连接选项。",
        -3: "Winlogon 已静默终止登录。",
        -1: "访问被拒绝。",
        0: "登录凭据无效。",
        1: "密码已过期，必须先修改密码。",
        2: "登录或登录后的处理发生错误。",
        3: "RDP 客户端正在显示登录警告。",
        -1073741715: "用户名或身份验证信息无效。",
        -1073741714: "身份验证受到用户账户限制。",
        -1073741276: "密码已过期，必须先修改密码。",
    }
    return mapping.get(int(error_code), "登录阶段发生未识别的错误或事件。")
