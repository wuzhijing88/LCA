# -*- coding: utf-8 -*-
"""主进程工作流执行代理。"""

from __future__ import annotations

import copy
import logging
import os
import queue
import select
import socket
import subprocess
import threading
from typing import Any, Dict, Optional

from PySide6.QtCore import QObject, QTimer, Signal

from services.ocr_socket_message_utils import recv_message, send_message
from task_workflow.process_payload import build_process_workflow_payload
from utils.worker_entry import build_worker_launch_command, build_worker_process_env

logger = logging.getLogger(__name__)


def _resolve_payload_screenshot_engine(
    *,
    screenshot_engine: Optional[str] = None,
    workflow_data: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    candidates = [
        screenshot_engine,
        workflow_data.get("screenshot_engine") if isinstance(workflow_data, dict) else None,
        config.get("screenshot_engine") if isinstance(config, dict) else None,
    ]
    for candidate in candidates:
        normalized = str(candidate or "").strip().lower()
        if normalized:
            return normalized
    return None


def _kill_process_tree(process: Optional[subprocess.Popen]) -> None:
    if process is None:
        return
    pid = 0
    try:
        pid = int(process.pid or 0)
    except Exception:
        pid = 0

    if pid > 0 and os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=3.0,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception:
            pass

    try:
        if process.poll() is None:
            process.kill()
    except Exception:
        pass


class ProcessWorkflowThreadHandle(QObject):
    started = Signal()
    finished = Signal()

    def __init__(self, executor_proxy: "ProcessWorkflowExecutorProxy", parent=None):
        super().__init__(parent)
        self._executor_proxy = executor_proxy
        self._running = False
        self._finished_emitted = False
        self._executor_proxy.bind_thread_handle(self)

    def start(self):
        if self._running:
            return
        self._running = True
        self._finished_emitted = False
        self.started.emit()

    def quit(self):
        if not self._running:
            return
        if self._executor_proxy.has_execution_finished() or not self._executor_proxy.is_running():
            self._emit_finished_once()
            return
        try:
            self._executor_proxy.request_stop(force=True)
        except Exception:
            pass

    def terminate(self):
        try:
            self._executor_proxy.terminate()
        finally:
            self._emit_finished_once()

    def wait(self, timeout_ms: Optional[int] = None) -> bool:
        ok = self._executor_proxy.wait_for_exit(timeout_ms)
        if ok:
            self._emit_finished_once()
        return ok

    def isRunning(self) -> bool:
        return bool(self._running and self._executor_proxy.is_running())

    def _notify_stopped(self):
        self._emit_finished_once()

    def _emit_finished_once(self):
        if self._finished_emitted:
            self._running = False
            return
        self._finished_emitted = True
        self._running = False
        self.finished.emit()


class ProcessWorkflowExecutorProxy(QObject):
    execution_started = Signal()
    execution_finished = Signal(bool, str)
    card_executing = Signal(int)
    card_finished = Signal(int, bool)
    overlay_update_requested = Signal(object)
    error_occurred = Signal(int, str)
    path_updated = Signal(int, str, str)
    param_updated = Signal(int, str, object)
    path_resolution_failed = Signal(int, str)
    step_details = Signal(str)
    show_warning = Signal(str, str)
    step_log = Signal(str, str, bool)

    def __init__(self, payload: Dict[str, Any], parent=None):
        super().__init__(parent)
        self._payload = copy.deepcopy(payload if isinstance(payload, dict) else {})
        self.workflow_id = self._payload.get("workflow_id")
        self._final_runtime_variables: Dict[str, Any] = {}

        self._process: Optional[subprocess.Popen] = None
        self._socket: Optional[socket.socket] = None
        self._launch_thread: Optional[threading.Thread] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._io_lock = threading.Lock()
        self._state_lock = threading.RLock()
        self._event_queue: "queue.Queue[dict]" = queue.Queue()
        self._exit_event = threading.Event()
        self._launching = False
        self._running = False
        self._paused = False
        self._received_execution_finished = False
        self._thread_handle: Optional[ProcessWorkflowThreadHandle] = None

        self._drain_timer = QTimer(self)
        self._drain_timer.setInterval(16)
        self._drain_timer.timeout.connect(self._drain_events)

    def _enqueue_message(self, message: Dict[str, Any]) -> None:
        message_type = str(message.get("type") or "").strip().lower()
        if message_type == "signal":
            signal_name = str(message.get("name") or "").strip()
            if signal_name == "execution_finished":
                with self._state_lock:
                    self._received_execution_finished = True
                    self._paused = False
        self._event_queue.put(message)

    @staticmethod
    def _is_socket_peer_closed(sock: Optional[socket.socket]) -> bool:
        if sock is None:
            return True

        try:
            readable, _, _ = select.select([sock], [], [], 0)
        except Exception:
            return True

        if not readable:
            return False

        peek_flag = getattr(socket, "MSG_PEEK", None)
        if peek_flag is None:
            return False

        try:
            data = sock.recv(1, peek_flag)
        except BlockingIOError:
            return False
        except socket.timeout:
            return False
        except OSError:
            return True

        return data == b""

    def bind_thread_handle(self, thread_handle: ProcessWorkflowThreadHandle) -> None:
        self._thread_handle = thread_handle

    def moveToThread(self, thread):
        return None

    def has_execution_finished(self) -> bool:
        return bool(self._received_execution_finished)

    def get_pause_state(self) -> str:
        with self._state_lock:
            paused = bool(self._paused)
            launching = bool(self._launching)
            running = bool(self._running)
            process = self._process

        process_running = False
        if process is not None:
            try:
                process_running = process.poll() is None
            except Exception:
                process_running = False

        if paused and (running or launching or process_running):
            return "paused"
        if running or launching or process_running:
            return "running"
        return "idle"

    def is_running(self) -> bool:
        with self._state_lock:
            if self._running or self._launching:
                return True
            if self._process is not None:
                try:
                    return self._process.poll() is None
                except Exception:
                    return False
            return False

    def run(self):
        with self._state_lock:
            if self._running or self._launching:
                return
            self._launching = True
            self._running = True
            self._paused = False
            self._exit_event.clear()
            self._received_execution_finished = False
            self._final_runtime_variables = {}

        if not self._drain_timer.isActive():
            self._drain_timer.start()

        self._launch_thread = threading.Thread(
            target=self._launch_worker,
            daemon=True,
            name="WorkflowProcessLaunch",
        )
        self._launch_thread.start()

    def _build_worker_command(self, port: int) -> list[str]:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return build_worker_launch_command(
            worker_flag="--workflow-worker",
            module_name="task_workflow.process_worker",
            standalone_flag="--workflow-worker-standalone",
            extra_args=["--port", str(port)],
            require_python_executable=True,
            project_root=project_root,
        )

    def _launch_worker(self):
        server_socket: Optional[socket.socket] = None
        client_socket: Optional[socket.socket] = None
        process: Optional[subprocess.Popen] = None
        try:
            server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_socket.bind(("127.0.0.1", 0))
            server_socket.listen(1)
            port = int(server_socket.getsockname()[1])

            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            child_env = build_worker_process_env(project_root=project_root)
            child_env["LCA_WORKFLOW_WORKER"] = "1"

            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            cmd = self._build_worker_command(port)
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=project_root,
                env=child_env,
                creationflags=creation_flags,
            )

            server_socket.settimeout(8.0)
            client_socket, _addr = server_socket.accept()
            ready_message = recv_message(client_socket, timeout=20.0, logger=logger)
            if not isinstance(ready_message, dict) or ready_message.get("type") != "ready":
                raise RuntimeError(f"未收到工作流子进程 ready 消息: {ready_message}")

            if not send_message(client_socket, {"command": "init", "payload": self._payload}, logger=logger):
                raise RuntimeError("发送工作流初始化消息失败")

            with self._state_lock:
                self._process = process
                self._socket = client_socket
                self._launching = False
                self._running = True

            client_socket.settimeout(0.5)
            self._reader_thread = threading.Thread(
                target=self._reader_loop,
                daemon=True,
                name="WorkflowProcessReader",
            )
            self._reader_thread.start()
            return
        except Exception as exc:
            logger.error("启动工作流子进程失败: %s", exc)
            self._enqueue_message(
                {
                    "type": "signal",
                    "name": "execution_finished",
                    "args": [False, f"启动工作流子进程失败: {exc}"],
                }
            )
        finally:
            if server_socket is not None:
                try:
                    server_socket.close()
                except Exception:
                    pass
            if client_socket is not None and (self._socket is None or client_socket is not self._socket):
                try:
                    client_socket.close()
                except Exception:
                    pass
            if process is not None and process is not self._process:
                _kill_process_tree(process)
            with self._state_lock:
                self._launching = False

    def _reader_loop(self):
        process = self._process
        sock = self._socket
        if process is None or sock is None:
            self._on_process_stopped()
            return

        try:
            while True:
                message = recv_message(sock, timeout=0.5, logger=logger)
                if message is not None:
                    self._enqueue_message(message)
                    continue
                if process.poll() is not None:
                    if self._is_socket_peer_closed(sock):
                        break
                    # 子进程已退出但socket缓冲区可能还有未读完的尾包，
                    # 继续读取直到真正EOF，避免漏掉最后的 execution_finished。
                    continue
                if self._is_socket_peer_closed(sock):
                    break
        except Exception as exc:
            logger.warning("工作流子进程读取失败: %s", exc)
        finally:
            if process.poll() is None:
                try:
                    process.wait(timeout=1.0)
                except Exception:
                    pass
            self._on_process_stopped()

    def _on_process_stopped(self):
        with self._state_lock:
            self._running = False
            self._launching = False
            self._paused = False
            self._exit_event.set()

        if not self._received_execution_finished:
            return_code = None
            try:
                if self._process is not None:
                    return_code = self._process.poll()
            except Exception:
                return_code = None
            message = "工作流子进程已退出"
            if return_code not in (None, 0):
                message = f"工作流子进程异常退出，退出码={return_code}"
            self._enqueue_message(
                {
                    "type": "signal",
                    "name": "execution_finished",
                    "args": [False, message],
                }
            )

        self._event_queue.put({"type": "__process_stopped__"})

    def _drain_events(self):
        drained = 0
        while drained < 200:
            try:
                message = self._event_queue.get_nowait()
            except queue.Empty:
                break
            drained += 1
            self._dispatch_message(message)

        if not self.is_running() and self._event_queue.empty() and self._drain_timer.isActive():
            self._drain_timer.stop()

    def _dispatch_message(self, message: Dict[str, Any]):
        message_type = str(message.get("type") or "").strip().lower()
        if message_type == "runtime_variables":
            payload = message.get("data")
            if isinstance(payload, dict):
                self._final_runtime_variables = payload
            return

        if message_type == "signal":
            signal_name = str(message.get("name") or "").strip()
            args = list(message.get("args") or [])
            if signal_name == "execution_finished":
                self._received_execution_finished = True
                with self._state_lock:
                    self._paused = False
            signal_obj = getattr(self, signal_name, None)
            if signal_obj is not None:
                try:
                    signal_obj.emit(*args)
                except Exception as exc:
                    logger.warning("分发代理信号失败: %s -> %s", signal_name, exc)
            return

        if message_type == "__process_stopped__":
            self._cleanup_transport_only()
            if self._thread_handle is not None:
                try:
                    self._thread_handle._notify_stopped()
                except Exception:
                    pass
            return

    def _cleanup_transport_only(self):
        sock = None
        process = None
        with self._state_lock:
            sock = self._socket
            process = self._process
            self._socket = None
            self._process = None
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass
        if process is not None:
            try:
                process.wait(timeout=0.1)
            except Exception:
                pass

    def _send_command(self, command: str, **kwargs) -> bool:
        with self._state_lock:
            sock = self._socket
        if sock is None:
            return False
        payload = {"command": command}
        payload.update(kwargs)
        with self._io_lock:
            return bool(send_message(sock, payload, logger=logger))

    def request_stop(self, force: bool = False):
        with self._state_lock:
            self._paused = False
        sent = self._send_command("request_stop", force=bool(force))
        if not sent and force:
            self.terminate()
            return True
        return bool(sent)

    def pause(self):
        sent = self._send_command("pause")
        if sent:
            with self._state_lock:
                self._paused = True
        return sent

    def resume(self):
        sent = self._send_command("resume")
        if sent:
            with self._state_lock:
                self._paused = False
        return sent

    def wait_for_exit(self, timeout_ms: Optional[int] = None) -> bool:
        timeout_sec = None if timeout_ms is None else max(0.0, float(timeout_ms) / 1000.0)
        return bool(self._exit_event.wait(timeout_sec))

    def terminate(self):
        process = None
        sock = None
        with self._state_lock:
            process = self._process
            sock = self._socket
            self._paused = False
        if sock is not None:
            try:
                self._send_command("shutdown")
            except Exception:
                pass
            try:
                sock.close()
            except Exception:
                pass
        if process is not None:
            _kill_process_tree(process)
        self._on_process_stopped()


def create_process_workflow_bundle(payload: Dict[str, Any], parent=None) -> tuple[ProcessWorkflowExecutorProxy, ProcessWorkflowThreadHandle]:
    executor = ProcessWorkflowExecutorProxy(payload=payload, parent=parent)
    thread_handle = ProcessWorkflowThreadHandle(executor_proxy=executor, parent=parent)
    return executor, thread_handle


def create_process_workflow_runtime(
    *,
    cards_data: Dict[str, Any],
    connections_data: list[Dict[str, Any]],
    execution_mode: str,
    images_dir: Optional[str],
    workflow_id: str,
    workflow_filepath: Optional[str] = None,
    start_card_id: Optional[int] = None,
    start_card_ids=None,
    target_window_title: Optional[str] = None,
    target_hwnd: Optional[int] = None,
    thread_labels: Optional[Dict[int, str]] = None,
    bound_windows: Optional[list[Dict[str, Any]]] = None,
    logger_obj=None,
    enable_thread_window_binding: bool = True,
    single_mode_overrides: Optional[Dict[str, Any]] = None,
    multi_thread_overrides: Optional[Dict[str, Any]] = None,
    screenshot_engine: Optional[str] = None,
    workflow_data: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None,
    parent=None,
):
    payload = build_process_workflow_payload(
        cards_data=cards_data,
        connections_data=connections_data,
        execution_mode=execution_mode,
        screenshot_engine=_resolve_payload_screenshot_engine(
            screenshot_engine=screenshot_engine,
            workflow_data=workflow_data,
            config=config,
        ),
        images_dir=images_dir,
        workflow_id=workflow_id,
        workflow_filepath=workflow_filepath,
        start_card_id=start_card_id,
        start_card_ids=start_card_ids,
        target_window_title=target_window_title,
        target_hwnd=target_hwnd,
        thread_labels=thread_labels,
        bound_windows=bound_windows,
        logger_obj=logger_obj,
        enable_thread_window_binding=enable_thread_window_binding,
        single_mode_overrides=single_mode_overrides,
        multi_thread_overrides=multi_thread_overrides,
    )
    return create_process_workflow_bundle(payload=payload, parent=parent)
