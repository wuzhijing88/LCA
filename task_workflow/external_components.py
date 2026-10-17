# -*- coding: utf-8 -*-
"""Client for the isolated generic external-component host."""

from __future__ import annotations

import os
import math
import secrets
import socket
import subprocess
import threading
import time
from typing import Any, Callable, Dict, Optional

from app_core.runtime.process_tree import terminate_process_tree
from app_core.runtime.worker_entry import build_worker_launch_command, build_worker_process_env
from services.socket_message_utils import recv_message, recv_message_with_status, send_message
from services.worker_process_cleanup import register_worker_process, unregister_worker_process
from utils.app_paths import get_app_root


WORKER_FLAG = "--external-component-worker"
DEFAULT_CALL_TIMEOUT = 30.0


class ExternalComponentError(RuntimeError):
    pass


class ExternalComponentManager:
    def __init__(self, *, stop_checker: Optional[Callable[[], bool]] = None) -> None:
        self._stop_checker = stop_checker
        self._process: Optional[subprocess.Popen] = None
        self._socket: Optional[socket.socket] = None
        self._token = secrets.token_hex(32)
        self._request_id = 0
        self._lock = threading.RLock()

    def _start(self, timeout: float) -> None:
        if self._process is not None and self._process.poll() is None and self._socket is not None:
            return
        self._teardown()
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        process = None
        connection = None
        try:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            server.settimeout(timeout)
            port = int(server.getsockname()[1])
            command = build_worker_launch_command(
                WORKER_FLAG,
                "task_workflow.external_component_worker",
                "--external-component-worker-standalone",
                ["--port", str(port), "--token", self._token],
                project_root=get_app_root(),
            )
            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            process = subprocess.Popen(
                command,
                cwd=get_app_root(),
                env=build_worker_process_env(project_root=get_app_root(), include_plugin_attach=False),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags,
            )
            register_worker_process(process, WORKER_FLAG)
            connection, _ = server.accept()
            ready = recv_message(connection, timeout=timeout)
            if not isinstance(ready, dict) or ready.get("type") != "ready" or ready.get("token") != self._token:
                raise ExternalComponentError("外部组件宿主启动握手失败")
            self._process = process
            self._socket = connection
            process = None
            connection = None
        except Exception as exc:
            if process is not None:
                try:
                    terminate_process_tree(process, wait_timeout=2.0, force=True)
                except Exception:
                    pass
                try:
                    unregister_worker_process(process)
                except Exception:
                    pass
            if isinstance(exc, ExternalComponentError):
                raise
            raise ExternalComponentError(f"外部组件宿主启动失败: {exc}") from exc
        finally:
            try:
                if connection is not None:
                    connection.close()
            finally:
                server.close()

    def _request(self, command: str, *, timeout: Any = DEFAULT_CALL_TIMEOUT, **payload: Any) -> Any:
        if timeout is None:
            wait_seconds = DEFAULT_CALL_TIMEOUT
        else:
            if isinstance(timeout, bool):
                raise ValueError("组件超时必须是大于 0 的有限秒数")
            try:
                wait_seconds = float(timeout)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError("组件超时必须是大于 0 的有限秒数") from exc
            if not math.isfinite(wait_seconds) or wait_seconds <= 0:
                raise ValueError("组件超时必须是大于 0 的有限秒数")
        with self._lock:
            self._start(wait_seconds)
            assert self._socket is not None
            assert self._process is not None
            self._request_id += 1
            request_id = self._request_id
            request = {
                "command": str(command),
                "request_id": request_id,
                "token": self._token,
                **payload,
            }
            if not send_message(self._socket, request):
                self._teardown()
                raise ExternalComponentError("无法向外部组件宿主发送请求")
            deadline = time.monotonic() + wait_seconds
            while True:
                if callable(self._stop_checker) and self._stop_checker():
                    self._teardown()
                    raise ExternalComponentError("已停止")
                if self._process.poll() is not None:
                    return_code = self._process.returncode
                    self._teardown()
                    raise ExternalComponentError(f"外部组件宿主异常退出，退出码={return_code}")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._teardown()
                    raise ExternalComponentError(f"外部组件调用超时: {wait_seconds:g} 秒")
                response, status = recv_message_with_status(
                    self._socket,
                    timeout=min(0.2, remaining),
                    max_message_bytes=0xFFFFFFFF,
                )
                if status == "timeout":
                    continue
                if status != "ok" or response is None:
                    return_code = self._process.poll()
                    self._teardown()
                    if return_code is not None:
                        raise ExternalComponentError(f"外部组件宿主异常退出，退出码={return_code}")
                    raise ExternalComponentError(f"外部组件宿主连接断开: {status}")
                if response.get("type") != "response" or response.get("request_id") != request_id:
                    self._teardown()
                    raise ExternalComponentError("外部组件宿主返回了无效响应")
                if not bool(response.get("success")):
                    raise ExternalComponentError(str(response.get("error") or "外部组件调用失败"))
                return response.get("result")

    def load(self, component_type: Any, target: Any, *, calling_convention: Any = None, timeout: Any = 10) -> Dict[str, Any]:
        result = self._request(
            "LOAD",
            timeout=timeout,
            component_type=component_type,
            target=target,
            options={} if calling_convention is None else {"calling_convention": calling_convention},
        )
        if not isinstance(result, dict) or not result.get("handle"):
            raise ExternalComponentError("外部组件宿主没有返回有效句柄")
        return result

    def call(
        self,
        handle: Any,
        member: Any,
        *args: Any,
        timeout: Any = DEFAULT_CALL_TIMEOUT,
        kwargs: Optional[Dict[str, Any]] = None,
        arg_types: Any = None,
        return_type: Any = None,
        action: str = "call",
        process_timeout: Any = None,
        stdin: Any = None,
        cwd: Any = None,
        env: Any = None,
        encoding: Any = None,
    ) -> Any:
        return self._request(
            "CALL",
            timeout=timeout,
            handle=handle,
            member=member,
            args=list(args),
            kwargs=dict(kwargs or {}),
            options={key: value for key, value in {
                "call_timeout": timeout,
                "arg_types": arg_types,
                "return_type": return_type,
                "action": action,
                "process_timeout": process_timeout,
                "stdin": stdin,
                "cwd": cwd,
                "env": env,
                "encoding": encoding,
            }.items() if value is not None},
        )

    def close(self, handle: Any = None, *, timeout: Any = 5) -> int:
        if self._process is None or self._process.poll() is not None or self._socket is None:
            return 0
        return int(self._request("CLOSE", timeout=timeout, handle=handle) or 0)

    def shutdown(self) -> None:
        with self._lock:
            if self._process is not None and self._process.poll() is None and self._socket is not None:
                try:
                    self._request("SHUTDOWN", timeout=2.0)
                except Exception:
                    pass
            self._teardown()

    def _teardown(self) -> None:
        sock, process = self._socket, self._process
        self._socket = None
        self._process = None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        if process is not None:
            try:
                if process.poll() is None:
                    terminate_process_tree(process, wait_timeout=2.0, force=True)
            except Exception:
                pass
            try:
                unregister_worker_process(process)
            except Exception:
                pass

    def __enter__(self) -> "ExternalComponentManager":
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        self.shutdown()


__all__ = ["ExternalComponentError", "ExternalComponentManager"]
