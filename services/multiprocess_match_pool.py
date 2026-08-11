# -*- coding: utf-8 -*-
"""
Template matching subprocess pool.
Main process sends matching requests to a dedicated worker to keep OpenCV temporary memory away from the UI process.
"""

from __future__ import annotations

import atexit
import logging
import os
import socket
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

from services.socket_message_utils import (
    read_socket_max_message_bytes,
    recv_message as recv_socket_message,
    send_message as send_socket_message,
)
from services.worker_process_cleanup import cleanup_worker_processes
from utils.worker_entry import build_worker_launch_command, build_worker_process_env

if TYPE_CHECKING:
    import numpy as np

_NUMPY_MODULE = None


def _get_np():
    global _NUMPY_MODULE
    if _NUMPY_MODULE is None:
        import numpy as _np

        _NUMPY_MODULE = _np
    return _NUMPY_MODULE


logger = logging.getLogger(__name__)


def _read_socket_max_message_bytes() -> int:
    return read_socket_max_message_bytes(
        env_name="MATCH_SOCKET_MAX_MB",
        default_mb=64,
        min_mb=8,
        max_mb=512,
    )


def _read_float_env(name: str, default: float, min_value: float, max_value: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except Exception:
        return default
    return max(min_value, min(max_value, value))


_MAX_SOCKET_MESSAGE_BYTES = _read_socket_max_message_bytes()


def _send_message(sock: socket.socket, data: Dict[str, Any]) -> bool:
    return send_socket_message(sock, data)


def _recv_message(sock: socket.socket, timeout: float = 10.0) -> Optional[Dict[str, Any]]:
    return recv_socket_message(
        sock=sock,
        timeout=timeout,
        max_message_bytes=_MAX_SOCKET_MESSAGE_BYTES,
    )


def _is_process_alive(process: Optional[subprocess.Popen]) -> bool:
    if process is None:
        return False
    try:
        return process.poll() is None
    except Exception:
        return False


@dataclass
class MatchProcessInfo:
    process_id: str
    process: Optional[subprocess.Popen]
    socket_conn: Optional[socket.socket]
    socket_port: int
    is_active: bool = True
    last_used: float = 0.0
    io_lock: threading.Lock = field(default_factory=threading.Lock)


class MultiProcessMatchPool:
    def __init__(self):
        self._lock = threading.RLock()
        self._process_info: Optional[MatchProcessInfo] = None
        self._is_shutdown = False
        self._worker_connect_timeout = _read_float_env("MATCH_POOL_WORKER_CONNECT_TIMEOUT_SEC", 8.0, 1.0, 60.0)
        self._worker_ready_timeout = _read_float_env("MATCH_POOL_WORKER_READY_TIMEOUT_SEC", 20.0, 1.0, 60.0)
        self._match_timeout = _read_float_env("MATCH_POOL_TIMEOUT_SEC", 8.0, 0.2, 60.0)
        self._last_screenshot_context: Optional[Tuple[int, int, Tuple[int, ...], str]] = None

    def _build_worker_command(self, process_id: str, port: int) -> list:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return build_worker_launch_command(
            worker_flag="--match-worker",
            module_name="services.multiprocess_match_worker",
            standalone_flag="--match-worker-standalone",
            extra_args=["--process-id", process_id, "--port", str(port)],
            allow_main_script=True,
            require_python_executable=True,
            project_root=project_root,
        )

    def _terminate_worker(self, process_info: Optional[MatchProcessInfo]) -> None:
        if process_info is None:
            return

        process = process_info.process
        pid = None
        try:
            if process is not None:
                pid = int(process.pid)
        except Exception:
            pid = None

        try:
            if process_info.socket_conn is not None:
                try:
                    _send_message(process_info.socket_conn, {"command": "STOP"})
                except Exception:
                    pass
                try:
                    process_info.socket_conn.close()
                except Exception:
                    pass
                process_info.socket_conn = None
        except Exception:
            pass

        if process is None:
            return

        if os.name == "nt" and pid:
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=1.0,
                    check=False,
                )
                return
            except Exception:
                pass

        try:
            if _is_process_alive(process):
                process.terminate()
                try:
                    process.wait(timeout=0.8)
                except subprocess.TimeoutExpired:
                    process.kill()
                    try:
                        process.wait(timeout=0.3)
                    except Exception:
                        pass
        except Exception:
            pass

    def _create_worker(self) -> Optional[MatchProcessInfo]:
        process_id = f"match_process_{time.time_ns()}_{threading.get_ident()}"
        server_socket = None
        process = None
        try:
            server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_socket.bind(("127.0.0.1", 0))
            server_socket.listen(1)
            port = int(server_socket.getsockname()[1])

            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            cmd = self._build_worker_command(process_id, port)
            child_env = build_worker_process_env(project_root=project_root)

            creation_flags = 0
            startupinfo = None
            if os.name == "nt":
                creation_flags = subprocess.CREATE_NO_WINDOW
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=project_root,
                env=child_env,
                creationflags=creation_flags,
                startupinfo=startupinfo,
            )

            server_socket.settimeout(self._worker_connect_timeout)
            conn, _ = server_socket.accept()
            ready = _recv_message(conn, timeout=self._worker_ready_timeout)
            if not ready or not ready.get("success"):
                try:
                    conn.close()
                except Exception:
                    pass
                self._terminate_worker(MatchProcessInfo(process_id, process, None, port, is_active=False))
                return None

            conn.settimeout(None)
            logger.info("模板匹配子进程已启动: process_id=%s", process_id)
            return MatchProcessInfo(
                process_id=process_id,
                process=process,
                socket_conn=conn,
                socket_port=port,
                is_active=True,
                last_used=time.time(),
            )
        except Exception as exc:
            logger.warning("创建模板匹配子进程失败: %s", exc)
            if process is not None:
                self._terminate_worker(MatchProcessInfo(process_id, process, None, 0, is_active=False))
            return None
        finally:
            if server_socket is not None:
                try:
                    server_socket.close()
                except Exception:
                    pass

    def _ensure_worker_unlocked(self) -> Optional[MatchProcessInfo]:
        info = self._process_info
        if info is not None:
            if info.is_active and info.socket_conn is not None and _is_process_alive(info.process):
                return info
            self._terminate_worker(info)
            self._process_info = None

        new_info = self._create_worker()
        self._process_info = new_info
        return new_info

    @staticmethod
    def _build_screenshot_context(screenshot: np.ndarray) -> Tuple[int, int, Tuple[int, ...], str]:
        ptr = 0
        try:
            ptr = int(screenshot.__array_interface__.get("data", (0,))[0] or 0)
        except Exception:
            ptr = 0
        shape = tuple(int(v) for v in screenshot.shape)
        dtype = str(screenshot.dtype)
        return (int(id(screenshot)), ptr, shape, dtype)

    @staticmethod
    def _parse_location(raw: Any) -> Optional[Tuple[int, int, int, int]]:
        if not isinstance(raw, (list, tuple)) or len(raw) != 4:
            return None
        try:
            return (int(raw[0]), int(raw[1]), int(raw[2]), int(raw[3]))
        except Exception:
            return None

    def _request_match_locked(
        self,
        screenshot: np.ndarray,
        template: np.ndarray,
        confidence_threshold: float,
    ) -> Tuple[bool, float, Optional[Tuple[int, int, int, int]]]:
        context = self._build_screenshot_context(screenshot)

        for attempt in range(2):
            info = self._ensure_worker_unlocked()
            if info is None or info.socket_conn is None:
                raise RuntimeError("match_worker_unavailable")

            send_screenshot = (attempt == 1) or (context != self._last_screenshot_context)
            request_payload = {
                "command": "MATCH_TEMPLATE",
                "screenshot_id": int(context[0]),
                "template": template,
                "confidence": float(confidence_threshold),
            }
            if send_screenshot:
                request_payload["screenshot"] = screenshot

            with info.io_lock:
                if not _send_message(info.socket_conn, request_payload):
                    self._terminate_worker(info)
                    self._process_info = None
                    self._last_screenshot_context = None
                    continue

                response = _recv_message(info.socket_conn, timeout=self._match_timeout)
                if response is None:
                    self._terminate_worker(info)
                    self._process_info = None
                    self._last_screenshot_context = None
                    continue

            info.last_used = time.time()

            if not response.get("success"):
                error = str(response.get("error") or "match_worker_error")
                if not send_screenshot and error in {"screenshot_missing", "screenshot_stale"}:
                    continue
                raise RuntimeError(error)

            if send_screenshot:
                self._last_screenshot_context = context

            matched = bool(response.get("matched", False))
            try:
                confidence = float(response.get("confidence", 0.0) or 0.0)
            except Exception:
                confidence = 0.0
            location = self._parse_location(response.get("location"))
            return matched, confidence, location

        raise RuntimeError("match_worker_transport_error")

    def match_template(
        self,
        screenshot: np.ndarray,
        template: np.ndarray,
        confidence_threshold: float,
    ) -> Tuple[bool, float, Optional[Tuple[int, int, int, int]]]:
        if screenshot is None or template is None:
            raise RuntimeError("invalid_match_inputs")
        np = _get_np()
        if not isinstance(screenshot, np.ndarray) or not isinstance(template, np.ndarray):
            raise RuntimeError("invalid_match_inputs")
        if screenshot.size <= 0 or template.size <= 0:
            return False, 0.0, None

        with self._lock:
            if self._is_shutdown:
                raise RuntimeError("match_pool_shutdown")
            return self._request_match_locked(
                screenshot=screenshot,
                template=template,
                confidence_threshold=float(confidence_threshold),
            )

    def clear_runtime(self) -> bool:
        with self._lock:
            info = self._process_info
            self._last_screenshot_context = None
            if self._is_shutdown or info is None or info.socket_conn is None:
                return True
            with info.io_lock:
                if not _send_message(info.socket_conn, {"command": "CLEAR_CACHE"}):
                    self._terminate_worker(info)
                    self._process_info = None
                    return False
                response = _recv_message(info.socket_conn, timeout=2.0)
                if response is None:
                    self._terminate_worker(info)
                    self._process_info = None
                    return False
                return bool(response.get("success"))

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            info = self._process_info
            if self._is_shutdown or info is None or info.socket_conn is None:
                return {"available": False}

            with info.io_lock:
                if not _send_message(info.socket_conn, {"command": "STATS"}):
                    return {"available": False}
                response = _recv_message(info.socket_conn, timeout=2.0)
                if not isinstance(response, dict):
                    return {"available": False}
                return {
                    "available": True,
                    "process_id": info.process_id,
                    "pid": int(getattr(info.process, "pid", 0) or 0),
                    "response": response,
                }

    def shutdown(self) -> None:
        with self._lock:
            self._is_shutdown = True
            info = self._process_info
            self._process_info = None
            self._last_screenshot_context = None
        self._terminate_worker(info)


_global_multiprocess_match_pool: Optional[MultiProcessMatchPool] = None
_global_match_pool_lock = threading.Lock()


def get_multiprocess_match_pool() -> MultiProcessMatchPool:
    global _global_multiprocess_match_pool
    if _global_multiprocess_match_pool is None:
        with _global_match_pool_lock:
            if _global_multiprocess_match_pool is None:
                _global_multiprocess_match_pool = MultiProcessMatchPool()
    return _global_multiprocess_match_pool


def get_existing_multiprocess_match_pool() -> Optional[MultiProcessMatchPool]:
    return _global_multiprocess_match_pool


def match_template_subprocess(
    screenshot: np.ndarray,
    template: np.ndarray,
    confidence_threshold: float,
) -> Tuple[bool, float, Optional[Tuple[int, int, int, int]]]:
    pool = get_multiprocess_match_pool()
    return pool.match_template(screenshot, template, confidence_threshold)


def clear_match_subprocess_runtime() -> bool:
    pool = get_existing_multiprocess_match_pool()
    if pool is None:
        return True
    return pool.clear_runtime()


def cleanup_orphan_match_subprocesses(main_pid: Optional[int] = None) -> int:
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return cleanup_worker_processes(
        worker_flags=("--match-worker", "--match-worker-standalone"),
        project_root=project_root,
        main_pid=main_pid,
    )


def cleanup_match_subprocess() -> None:
    global _global_multiprocess_match_pool
    with _global_match_pool_lock:
        pool = _global_multiprocess_match_pool
        _global_multiprocess_match_pool = None
    if pool is not None:
        pool.shutdown()
    cleanup_orphan_match_subprocesses(main_pid=os.getpid())


atexit.register(cleanup_match_subprocess)
