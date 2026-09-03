# -*- coding: utf-8 -*-
"""主进程工作流执行代理。"""

from __future__ import annotations

import logging
import os
import queue
import select
import secrets
import socket
import subprocess
import threading
import time
from typing import Any, Dict, Iterable, Optional

from PySide6.QtCore import QObject, QTimer, Signal

from app_core.runtime.process_tree import ProcessTerminationError, terminate_process_tree
from services.ocr_socket_message_utils import recv_message, send_message
from services.socket_message_utils import SocketMessageError
from services.worker_process_cleanup import register_worker_process, unregister_worker_process
from task_workflow.process_payload import build_process_workflow_payload
from task_workflow.workflow_worker_pool import (
    WarmWorkflowWorker,
    acquire_warm_workflow_worker,
    is_workflow_worker_prewarm_active,
    release_warm_workflow_worker,
    schedule_workflow_worker_prewarm,
)
from utils.app_paths import get_app_root
from app_core.runtime.worker_entry import build_worker_launch_command, build_worker_process_env

logger = logging.getLogger(__name__)


class _LaunchCancelled(RuntimeError):
    """Internal signal used when a worker launch is stopped before ready."""


def _resolve_payload_screenshot_engine(
    *,
    screenshot_engine: Optional[str],
) -> str:
    normalized = str(screenshot_engine or "").strip().lower()
    if not normalized:
        raise ValueError("创建工作流子进程必须显式指定 screenshot_engine")
    from utils.capture.engine_ids import is_supported_screenshot_engine

    if not is_supported_screenshot_engine(normalized):
        raise ValueError(f"不支持的工作流截图引擎: {normalized}")
    return normalized


def _kill_process_tree(process: Optional[subprocess.Popen]) -> None:
    if process is None:
        return
    pid = 0
    try:
        pid = int(process.pid or 0)
    except Exception:
        pid = 0

    try:
        terminate_process_tree(process, wait_timeout=3.0, force=True)
    except ProcessTerminationError as exc:
        logger.warning("工作流进程树终止失败: %s", exc)
    try:
        if process.poll() is not None and pid > 0:
            unregister_worker_process(pid)
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
        # Payload builder already returns an execution snapshot. Keeping one
        # shallow top-level copy avoids duplicating large workflow graphs per window.
        self._payload = dict(payload if isinstance(payload, dict) else {})
        self.workflow_id = self._payload.get("workflow_id")
        self._auth_token = secrets.token_hex(32)

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
        self._stop_event = threading.Event()
        self._launch_server_socket: Optional[socket.socket] = None
        self._launch_client_socket: Optional[socket.socket] = None
        self._launch_generation = 0
        self._received_execution_finished = False
        self._reader_error_status: Optional[str] = None
        self._thread_handle: Optional[ProcessWorkflowThreadHandle] = None
        self._force_stop_timer: Optional[threading.Timer] = None
        self._plugin_host_pid = ""
        self._recycle_worker = False

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
            launch_thread = self._launch_thread
            if launch_thread is not None and launch_thread.is_alive():
                logger.warning("工作流启动线程仍在退出，拒绝重复启动")
                return
            if self._process is not None:
                try:
                    if self._process.poll() is None:
                        logger.warning("工作流子进程仍在退出，拒绝重复启动")
                        return
                except Exception:
                    return
            self._launch_generation += 1
            launch_generation = self._launch_generation
            self._stop_event.clear()
            self._launching = True
            self._running = True
            self._paused = False
            self._exit_event.clear()
            self._received_execution_finished = False
            self._reader_error_status = None
            self._recycle_worker = False

        if not self._drain_timer.isActive():
            self._drain_timer.start()

        self._launch_thread = threading.Thread(
            target=self._launch_worker,
            args=(launch_generation,),
            daemon=True,
            name="WorkflowProcessLaunch",
        )
        self._launch_thread.start()

    def _build_worker_command(self, port: int) -> list[str]:
        project_root = get_app_root()
        return build_worker_launch_command(
            worker_flag="--workflow-worker",
            module_name="task_workflow.process_worker",
            standalone_flag="--workflow-worker-standalone",
            extra_args=["--port", str(port)],
            project_root=project_root,
        )

    def _launch_cancelled(self, generation: int) -> bool:
        with self._state_lock:
            return generation != self._launch_generation or self._stop_event.is_set()

    def _try_adopt_warm_worker(self, generation: int) -> bool:
        scheduled = schedule_workflow_worker_prewarm()
        if scheduled or is_workflow_worker_prewarm_active():
            logger.info("等待预热工作流子进程就绪")
        leased = acquire_warm_workflow_worker(wait_timeout=15.0)
        if leased is None:
            return False

        process = leased.process
        client_socket = leased.socket
        try:
            if self._launch_cancelled(generation):
                raise _LaunchCancelled()
            self._auth_token = str(leased.auth_token or "")
            self._plugin_host_pid = str(getattr(leased, "plugin_host_pid", "") or "")
            if not send_message(client_socket, {"command": "init", "payload": self._payload}, logger=logger):
                raise RuntimeError("发送工作流初始化消息失败")
            with self._state_lock:
                if self._launch_cancelled(generation):
                    raise _LaunchCancelled()
                self._process = process
                self._socket = client_socket
                self._launch_client_socket = None
                self._launching = False
                self._running = True
            try:
                client_socket.settimeout(0.5)
            except Exception:
                pass
            self._reader_thread = threading.Thread(
                target=self._reader_loop,
                daemon=True,
                name="WorkflowProcessReader",
            )
            self._reader_thread.start()
            logger.info("接管预热工作流子进程 pid=%s", getattr(process, "pid", "?"))
            return True
        except _LaunchCancelled:
            _kill_process_tree(process)
            try:
                client_socket.close()
            except Exception:
                pass
            raise
        except Exception:
            logger.warning("接管预热工作流子进程失败，回退冷启动", exc_info=True)
            _kill_process_tree(process)
            try:
                client_socket.close()
            except Exception:
                pass
            return False

    def _launch_worker(self, generation: int):
        server_socket: Optional[socket.socket] = None
        client_socket: Optional[socket.socket] = None
        process: Optional[subprocess.Popen] = None
        launch_succeeded = False
        try:
            if self._launch_cancelled(generation):
                raise _LaunchCancelled()
            if self._try_adopt_warm_worker(generation):
                launch_succeeded = True
                return
            logger.info("预热工作流子进程未就绪，冷启动")

            server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_socket.bind(("127.0.0.1", 0))
            server_socket.listen(1)
            with self._state_lock:
                self._launch_server_socket = server_socket
            port = int(server_socket.getsockname()[1])

            project_root = get_app_root()
            child_env = build_worker_process_env(project_root=project_root)
            child_env["LCA_WORKFLOW_WORKER"] = "1"
            child_env["LCA_WORKFLOW_AUTH_TOKEN"] = self._auth_token
            self._plugin_host_pid = str(child_env.get("LCA_PLUGIN_HOST_PID") or "")

            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            cmd = self._build_worker_command(port)
            if self._launch_cancelled(generation):
                raise _LaunchCancelled()
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=project_root,
                env=child_env,
                creationflags=creation_flags,
            )
            register_worker_process(process, "--workflow-worker")

            with self._state_lock:
                if generation != self._launch_generation or self._stop_event.is_set():
                    raise _LaunchCancelled()
                self._process = process
                self._launch_client_socket = None
            if self._launch_cancelled(generation):
                raise _LaunchCancelled()

            server_socket.settimeout(0.2)
            deadline = time.monotonic() + 8.0
            while True:
                if self._launch_cancelled(generation):
                    raise _LaunchCancelled()
                if time.monotonic() >= deadline:
                    raise TimeoutError("工作流子进程连接 ready 超时")
                try:
                    client_socket, _addr = server_socket.accept()
                    break
                except socket.timeout:
                    continue
            with self._state_lock:
                self._launch_client_socket = client_socket
            if self._launch_cancelled(generation):
                raise _LaunchCancelled()
            ready_message = recv_message(client_socket, timeout=20.0, logger=logger)
            if not isinstance(ready_message, dict) or ready_message.get("type") != "ready":
                raise RuntimeError(f"未收到工作流子进程 ready 消息: {ready_message}")
            if not secrets.compare_digest(
                str(ready_message.get("auth_token") or ""),
                self._auth_token,
            ):
                raise RuntimeError("工作流子进程认证失败")

            if self._launch_cancelled(generation):
                raise _LaunchCancelled()

            if not send_message(client_socket, {"command": "init", "payload": self._payload}, logger=logger):
                raise RuntimeError("发送工作流初始化消息失败")

            with self._state_lock:
                if self._launch_cancelled(generation):
                    raise _LaunchCancelled()
                self._process = process
                self._socket = client_socket
                self._launch_client_socket = None
                self._launching = False
                self._running = True

            client_socket.settimeout(0.5)
            self._reader_thread = threading.Thread(
                target=self._reader_loop,
                daemon=True,
                name="WorkflowProcessReader",
            )
            self._reader_thread.start()
            launch_succeeded = True
            return
        except _LaunchCancelled:
            logger.debug("工作流子进程启动已取消")
        except Exception as exc:
            logger.error("启动工作流子进程失败: %s", exc)
            if not self._stop_event.is_set():
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
            with self._state_lock:
                if self._launch_client_socket is client_socket:
                    self._launch_client_socket = None
            if process is not None and not launch_succeeded:
                _kill_process_tree(process)
            with self._state_lock:
                if not launch_succeeded and self._process is process:
                    self._process = None
                if self._launch_server_socket is server_socket:
                    self._launch_server_socket = None
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
                    if str(message.get("type") or "").strip().lower() == "idle":
                        self._recycle_worker = True
                        break
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
        except SocketMessageError as exc:
            self._reader_error_status = str(exc.status or "unknown")
            logger.warning("工作流子进程通信中断: status=%s", self._reader_error_status)
        except Exception as exc:
            logger.warning("工作流子进程读取失败: %s", exc)
        finally:
            if self._recycle_worker:
                self._on_process_stopped()
            else:
                self._finalize_dead_worker(process)

    def _finalize_dead_worker(self, process: Optional[subprocess.Popen]) -> None:
        if process is not None:
            try:
                if process.poll() is None:
                    process.wait(timeout=1.0)
            except Exception:
                pass
        self._on_process_stopped()

    def _on_process_stopped(self):
        force_stop_timer = self._force_stop_timer
        self._force_stop_timer = None
        if force_stop_timer is not None:
            force_stop_timer.cancel()
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
            if self._reader_error_status:
                message = f"工作流子进程通信中断，状态={self._reader_error_status}"
            elif return_code not in (None, 0):
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
        alive = False
        try:
            alive = process is not None and process.poll() is None
        except Exception:
            alive = False
        if alive and sock is not None and self._recycle_worker:
            release_warm_workflow_worker(
                WarmWorkflowWorker(
                    process=process,
                    socket=sock,
                    auth_token=str(self._auth_token or ""),
                    plugin_host_pid=str(self._plugin_host_pid or ""),
                )
            )
            return
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
            try:
                if process.poll() is not None:
                    unregister_worker_process(process)
            except Exception:
                pass
        schedule_workflow_worker_prewarm()

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
        if sent and force:
            raw_timeout = str(os.getenv("LCA_FORCE_STOP_TIMEOUT_SEC", "5") or "5")
            try:
                timeout_seconds = max(0.1, float(raw_timeout))
            except (TypeError, ValueError):
                timeout_seconds = 5.0

            def enforce_deadline():
                if self.is_running():
                    logger.warning(
                        "工作流未在 %.1f 秒内响应停止，执行进程树终止",
                        timeout_seconds,
                    )
                    self.terminate()

            old_timer = self._force_stop_timer
            if old_timer is not None:
                old_timer.cancel()
            timer = threading.Timer(timeout_seconds, enforce_deadline)
            timer.daemon = True
            timer.name = "WorkflowForceStopDeadline"
            self._force_stop_timer = timer
            timer.start()
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
        launch_server_socket = None
        launch_client_socket = None
        launch_thread = None
        self._stop_event.set()
        self._recycle_worker = False
        with self._state_lock:
            process = self._process
            sock = self._socket
            launch_server_socket = self._launch_server_socket
            launch_client_socket = self._launch_client_socket
            launch_thread = self._launch_thread
            self._launch_generation += 1
            self._paused = False
            self._running = False
            self._launching = False
        if launch_server_socket is not None:
            try:
                launch_server_socket.close()
            except Exception:
                pass
        if launch_client_socket is not None:
            try:
                launch_client_socket.close()
            except Exception:
                pass
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
        if (
            launch_thread is not None
            and launch_thread is not threading.current_thread()
            and launch_thread.is_alive()
        ):
            launch_thread.join(timeout=1.0)
        self._on_process_stopped()


def create_process_workflow_bundle(payload: Dict[str, Any], parent=None) -> tuple[ProcessWorkflowExecutorProxy, ProcessWorkflowThreadHandle]:
    executor = ProcessWorkflowExecutorProxy(payload=payload, parent=parent)
    thread_handle = ProcessWorkflowThreadHandle(executor_proxy=executor, parent=parent)
    return executor, thread_handle


def create_process_workflow_runtime(
    *,
    cards_data: Dict[Any, Any],
    connections_data: list[Dict[str, Any]],
    execution_mode: str,
    images_dir: Optional[str],
    workflow_id: str,
    workflow_filepath: Optional[str] = None,
    start_card_ids: Iterable[int],
    target_window_title: Optional[str] = None,
    target_hwnd: Optional[int] = None,
    thread_labels: Optional[Dict[int, str]] = None,
    bound_windows: Optional[list[Dict[str, Any]]] = None,
    custom_width: Any = 0,
    custom_height: Any = 0,
    screenshot_engine: str,
    test_mode: Any = None,
    prefer_memory_reference: bool = False,
    parent=None,
):
    payload = build_process_workflow_payload(
        cards_data=cards_data,
        connections_data=connections_data,
        execution_mode=execution_mode,
        screenshot_engine=_resolve_payload_screenshot_engine(
            screenshot_engine=screenshot_engine,
        ),
        images_dir=images_dir,
        workflow_id=workflow_id,
        workflow_filepath=workflow_filepath,
        start_card_ids=start_card_ids,
        target_window_title=target_window_title,
        target_hwnd=target_hwnd,
        thread_labels=thread_labels,
        bound_windows=bound_windows,
        custom_width=custom_width,
        custom_height=custom_height,
        test_mode=test_mode,
        prefer_file_reference=(
            str(os.getenv("LCA_WORKFLOW_PAYLOAD_MODE", "") or "").strip().lower()
            == "reference"
        ),
        prefer_memory_reference=prefer_memory_reference,
    )
    return create_process_workflow_bundle(payload=payload, parent=parent)
