# -*- coding: utf-8 -*-
"""常驻预热的工作流子进程池。"""

from __future__ import annotations

import logging
import os
import secrets
import socket
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import List, Optional

from app_core.runtime.process_tree import terminate_process_tree
from app_core.runtime.worker_entry import build_worker_launch_command, build_worker_process_env
from services.ocr_socket_message_utils import recv_message
from services.worker_process_cleanup import register_worker_process, unregister_worker_process
from utils.app_paths import get_app_root

logger = logging.getLogger(__name__)

_MAX_IDLE = 1
_LOCK = threading.Lock()
_PREWARM_ACTIVE = False
_SHUTTING_DOWN = False


@dataclass
class WarmWorkflowWorker:
    process: subprocess.Popen
    socket: socket.socket
    auth_token: str
    plugin_host_pid: str = ""


_IDLE: List[WarmWorkflowWorker] = []


def _current_plugin_host_pid() -> str:
    try:
        from utils.plugin.runtime import plugin_attach_env

        return str(plugin_attach_env().get("LCA_PLUGIN_HOST_PID") or "")
    except Exception:
        return ""


def _needs_plugin_attach() -> bool:
    """截图引擎或键鼠后端任一走插件，子进程都必须附着到主进程的宿主。"""
    try:
        from services.ocr_pool_policy import resolve_screenshot_engine
        from utils.capture.engine_ids import is_plugin_screenshot_engine

        if is_plugin_screenshot_engine(resolve_screenshot_engine()):
            return True
    except Exception:
        pass
    try:
        from utils.input_simulation.mode_utils import is_plugin_input_backend
        from utils.runtime_config import get_runtime_config

        return bool(is_plugin_input_backend(get_runtime_config()))
    except Exception:
        return False


def _worker_matches_runtime(worker: WarmWorkflowWorker) -> bool:
    current = _current_plugin_host_pid()
    stored = str(getattr(worker, "plugin_host_pid", "") or "")
    if stored == current:
        return True
    if stored and current and stored != current:
        return False
    if not stored and current:
        return not _needs_plugin_attach()
    return True


def _is_warm_worker_alive(worker: WarmWorkflowWorker) -> bool:
    try:
        return worker.process.poll() is None
    except Exception:
        return False


def _discard_warm_worker(worker: Optional[WarmWorkflowWorker]) -> None:
    if worker is None:
        return
    sock = getattr(worker, "socket", None)
    if sock is not None:
        try:
            sock.close()
        except Exception:
            pass
    process = getattr(worker, "process", None)
    if process is None:
        return
    try:
        already_stopped = process.poll() is not None
    except Exception:
        already_stopped = True
    if already_stopped:
        try:
            unregister_worker_process(process)
        except Exception:
            pass
        return
    try:
        terminate_process_tree(process, wait_timeout=3.0, force=True)
    except Exception:
        logger.debug("终止预热工作流子进程失败", exc_info=True)
    try:
        if process.poll() is not None:
            unregister_worker_process(process)
    except Exception:
        pass


def is_workflow_worker_prewarm_active() -> bool:
    with _LOCK:
        return bool(_PREWARM_ACTIVE)


def _take_idle_worker() -> Optional[WarmWorkflowWorker]:
    discarded: List[WarmWorkflowWorker] = []
    selected: Optional[WarmWorkflowWorker] = None
    with _LOCK:
        while _IDLE:
            worker = _IDLE.pop(0)
            if _is_warm_worker_alive(worker) and _worker_matches_runtime(worker):
                selected = worker
                break
            discarded.append(worker)
    for worker in discarded:
        _discard_warm_worker(worker)
    return selected


def acquire_warm_workflow_worker(*, wait_timeout: float = 0.0) -> Optional[WarmWorkflowWorker]:
    worker = _take_idle_worker()
    if worker is not None:
        return worker
    try:
        timeout = max(0.0, float(wait_timeout or 0.0))
    except (TypeError, ValueError):
        timeout = 0.0
    if timeout <= 0:
        return None
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with _LOCK:
            if _SHUTTING_DOWN or not _PREWARM_ACTIVE:
                break
        time.sleep(0.05)
        worker = _take_idle_worker()
        if worker is not None:
            return worker
    return _take_idle_worker()


def spawn_ready_workflow_worker() -> Optional[WarmWorkflowWorker]:
    if _SHUTTING_DOWN:
        return None

    server_socket: Optional[socket.socket] = None
    client_socket: Optional[socket.socket] = None
    process: Optional[subprocess.Popen] = None
    try:
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind(("127.0.0.1", 0))
        server_socket.listen(1)
        port = int(server_socket.getsockname()[1])

        project_root = get_app_root()
        auth_token = secrets.token_hex(32)
        child_env = build_worker_process_env(project_root=project_root)
        child_env["LCA_WORKFLOW_WORKER"] = "1"
        child_env["LCA_WORKFLOW_AUTH_TOKEN"] = auth_token
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        command = build_worker_launch_command(
            worker_flag="--workflow-worker",
            module_name="task_workflow.process_worker",
            standalone_flag="--workflow-worker-standalone",
            extra_args=["--port", str(port)],
            project_root=project_root,
        )
        process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=project_root,
            env=child_env,
            creationflags=creation_flags,
        )
        register_worker_process(process, "--workflow-worker")

        server_socket.settimeout(0.2)
        deadline = time.monotonic() + 8.0
        while True:
            if _SHUTTING_DOWN:
                raise RuntimeError("应用正在退出，取消预热工作流子进程")
            if time.monotonic() >= deadline:
                raise TimeoutError("预热工作流子进程连接 ready 超时")
            try:
                client_socket, _addr = server_socket.accept()
                break
            except socket.timeout:
                if process.poll() is not None:
                    raise RuntimeError("预热工作流子进程提前退出")
                continue

        ready_message = recv_message(client_socket, timeout=20.0, logger=logger)
        if not isinstance(ready_message, dict) or ready_message.get("type") != "ready":
            raise RuntimeError(f"未收到预热工作流子进程 ready 消息: {ready_message}")
        if not secrets.compare_digest(str(ready_message.get("auth_token") or ""), auth_token):
            raise RuntimeError("预热工作流子进程认证失败")
        return WarmWorkflowWorker(
            process=process,
            socket=client_socket,
            auth_token=auth_token,
            plugin_host_pid=str(child_env.get("LCA_PLUGIN_HOST_PID") or ""),
        )
    except Exception as exc:
        logger.debug("预热工作流子进程失败: %s", exc, exc_info=True)
        if client_socket is not None:
            try:
                client_socket.close()
            except Exception:
                pass
        if process is not None:
            _discard_warm_worker(
                WarmWorkflowWorker(process=process, socket=client_socket, auth_token="")
            )
        return None
    finally:
        if server_socket is not None:
            try:
                server_socket.close()
            except Exception:
                pass


def schedule_workflow_worker_prewarm() -> bool:
    global _PREWARM_ACTIVE
    with _LOCK:
        if _SHUTTING_DOWN or _PREWARM_ACTIVE:
            return False
        live_idle = [worker for worker in _IDLE if _is_warm_worker_alive(worker)]
        discarded = [worker for worker in _IDLE if not _is_warm_worker_alive(worker)]
        _IDLE[:] = live_idle
        should_start = len(live_idle) < _MAX_IDLE
        if should_start:
            _PREWARM_ACTIVE = True

    for worker in discarded:
        _discard_warm_worker(worker)
    if not should_start:
        return False

    def _worker() -> None:
        global _PREWARM_ACTIVE
        try:
            spawned = spawn_ready_workflow_worker()
            if spawned is None:
                return
            with _LOCK:
                if _SHUTTING_DOWN or any(_is_warm_worker_alive(item) for item in _IDLE):
                    _discard_warm_worker(spawned)
                    return
                _IDLE.append(spawned)
            logger.info(
                "已预热工作流子进程 pid=%s",
                getattr(spawned.process, "pid", "?"),
            )
        finally:
            with _LOCK:
                _PREWARM_ACTIVE = False

    thread = threading.Thread(target=_worker, name="WorkflowWorkerPrewarm", daemon=True)
    try:
        thread.start()
    except Exception:
        with _LOCK:
            _PREWARM_ACTIVE = False
        logger.debug("启动工作流子进程预热线程失败", exc_info=True)
        return False
    return True


def release_warm_workflow_worker(worker: Optional[WarmWorkflowWorker]) -> bool:
    if worker is None or not _is_warm_worker_alive(worker):
        _discard_warm_worker(worker)
        schedule_workflow_worker_prewarm()
        return False
    extras: List[WarmWorkflowWorker] = []
    with _LOCK:
        extras = list(_IDLE)
        _IDLE.clear()
        _IDLE.append(worker)
    for extra in extras:
        _discard_warm_worker(extra)
    logger.info(
        "已回收工作流子进程 pid=%s",
        getattr(worker.process, "pid", "?"),
    )
    return True


def recycle_warm_workflow_workers() -> bool:
    with _LOCK:
        items = list(_IDLE)
        _IDLE.clear()
    for item in items:
        _discard_warm_worker(item)
    return schedule_workflow_worker_prewarm()


def shutdown_warm_workflow_workers() -> None:
    global _SHUTTING_DOWN
    with _LOCK:
        _SHUTTING_DOWN = True
        items = list(_IDLE)
        _IDLE.clear()
    for item in items:
        _discard_warm_worker(item)
