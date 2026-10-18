"""Connect an isolated Python script to the current LCA command host."""

from __future__ import annotations

import contextvars
import os
import queue
import secrets
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from app_core.runtime.process_tree import terminate_process_tree
from app_core.script_dependencies import resolve_script_environment
from app_core.script_environments import EnvironmentManager, clean_python_env
from app_core.script_process_job import ProcessJob
from services.worker_process_cleanup import (
    register_worker_process,
    unregister_worker_process,
)
from task_workflow.script_process_worker import (
    Channel,
    RemoteObject,
    receive_packet,
    tree_payload,
)

WORKER_FLAG = "--isolated-script-worker"


def worker_source_path():
    from utils.app_paths import get_app_root, is_packaged_runtime

    if is_packaged_runtime():
        path = Path(get_app_root()) / "resources" / "script_runtime" / "worker.py"
    else:
        path = Path(__file__).with_name("script_process_worker.py")
    if not path.is_file():
        raise ValueError("缺少独立脚本工作进程文件：" + str(path))
    return path


class _Rendered:
    def __init__(self, text):
        self.text = text

    def __repr__(self):
        return self.text


class ScriptProcess:
    def __init__(self, namespace, host, guard, tree, debug_names, log):
        self.namespace, self.host, self.guard = namespace, host, guard
        self.tree, self.debug_names, self.log = tree, debug_names, log
        self.process = None
        self.channel = None
        self._lease = None
        self._monitor = None
        self._shutdown = threading.Event()
        self._stopped = threading.Event()
        self._result = None
        self._monitor_error = None
        self._output = None
        self._job = None
        self._request_context = contextvars.copy_context()

    @staticmethod
    def is_user_callback(value, names):
        return (
            isinstance(value, RemoteObject)
            and value._remote_kind == "callback"
            and value._remote_name in names
        )

    def callback(self, name):
        return self.channel.call("callback", name)

    def _dispatch(self, operation, *args):
        if operation == "finished":
            self._result = args[0]
            return None
        if self._stopped.is_set():
            raise ValueError("已停止")
        if operation == "initialize":
            from task_workflow import script_pure

            values = {
                name: value
                for name, value in self.namespace.items()
                if name not in {"__builtins__", "__guard", "_lca_guard", "__iter_count", "图像"}
            }
            context = {
                name: self.host.context.get(name)
                for name in (
                    "target_hwnd",
                    "execution_mode",
                    "images_dir",
                    "sounds_dir",
                    "dicts_dir",
                    "yolo_dir",
                    "replays_dir",
                    "plugins_dir",
                    "card_id",
                )
            }
            return {
                "tree": tree_payload(self.tree),
                "namespace": values,
                "context": context,
                "debug": self.host.context.get("debugger") is not None,
                "debug_names": sorted(self.debug_names),
                "local_functions": {
                    name: helper
                    for name, value in values.items()
                    for helper, function in vars(script_pure).items()
                    if helper.startswith("script_") and value is function
                },
            }
        if operation == "guard":
            return self.guard()
        if operation == "log":
            self.log(args[0])
            return None
        if operation == "debug":
            debugger = self.host.context.get("debugger")
            if debugger is None:
                raise ValueError("脚本调试器未启动")
            if not debugger.before_line(
                args[0], {name: _Rendered(value) for name, value in args[1].items()}
            ):
                raise ValueError("已停止")
            return None
        self.guard()
        if operation == "resource":
            from task_workflow.script_resources import read_resource_bytes

            data = read_resource_bytes(
                args[0],
                **{
                    key: self.host.context.get(key) or ""
                    for key in (
                        "images_dir",
                        "sounds_dir",
                        "dicts_dir",
                        "yolo_dir",
                        "replays_dir",
                        "plugins_dir",
                    )
                },
            )
            if data is None:
                raise ValueError("资源不存在：" + str(args[0]))
            return data
        if operation == "capture":
            from utils.capture.screenshot_helper import capture_window_frame

            hwnd = self.host.context.get("target_hwnd")
            if not hwnd:
                raise ValueError("截帧需要先绑定窗口")
            frame = capture_window_frame(hwnd)
            if frame is None:
                raise ValueError("窗口截图失败")
            return frame
        raise ValueError("未知的独立脚本请求：" + operation)

    def _watch(self):
        try:
            while not self._shutdown.wait(0.05):
                if self.host.should_stop():
                    self._stopped.set()
                    if self.channel is not None:
                        self.channel.cancel_reason = "已停止"
                    if self._job is not None:
                        self._job.close()
                    if self.process is not None and self.process.poll() is None:
                        terminate_process_tree(self.process, wait_timeout=3, force=True)
                    if self.channel is not None:
                        self.channel.closed.set()
                    return
        except Exception as exc:  # noqa: BLE001 -- propagate checker errors to the script thread
            self._monitor_error = exc
            self._stopped.set()
            if self.channel is not None:
                self.channel.closed.set()

    def run(self):
        from task_workflow.script_sandbox import ScriptError

        manager = EnvironmentManager(
            stop_checker=self.host.should_stop, progress=self.log
        )
        self._lease = manager.prepare(
            resolve_script_environment(
                self.host.context["script_environment"], self.tree, progress=self.log
            ),
        )
        python = self._lease.__enter__()
        self.guard()
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        connection = None
        try:
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            server.settimeout(0.2)
            token = secrets.token_hex(32)
            env = clean_python_env(python)
            env["LCA_SCRIPT_TOKEN"] = token
            self._output = tempfile.TemporaryFile()  # noqa: SIM115 -- owned until close(), including command-host cleanup
            self._job = ProcessJob()
            self.process = subprocess.Popen(
                [
                    str(python),
                    "-X",
                    "utf8",
                    "-I",
                    "-u",
                    str(worker_source_path()),
                    str(server.getsockname()[1]),
                ],
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=self._output,
                stderr=self._output,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if self.process.poll() is None:
                self._job.assign(self.process)
                register_worker_process(self.process, WORKER_FLAG)
            self._monitor = threading.Thread(
                target=self._watch, name="lca-script-process-monitor", daemon=True
            )
            self._monitor.start()
            deadline = time.monotonic() + 20
            while connection is None:
                manager.check_stop()
                if self.process.poll() is not None:
                    raise ScriptError("独立脚本进程启动失败：" + self._read_output())
                if time.monotonic() > deadline:
                    raise ScriptError("独立脚本进程启动超时")
                try:
                    connection, _ = server.accept()
                except TimeoutError:
                    continue
            connection.settimeout(3)
            hello = receive_packet(connection)
            if hello.get("type") != "ready" or not secrets.compare_digest(
                str(hello.get("token", "")), token
            ):
                raise ScriptError("独立脚本进程身份校验失败")
            connection.settimeout(None)
            connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self.channel = Channel(
                connection,
                self._dispatch,
                before_request=self.guard,
                request_context=self._request_context,
            )
            self.channel.start()
            connection = None
            while self._result is None:
                if self._monitor_error is not None:
                    raise ScriptError("脚本停止监控失败：" + str(self._monitor_error))
                if self._stopped.is_set():
                    raise ScriptError("已停止")
                try:
                    request = self.channel.incoming.get(timeout=0.05)
                except queue.Empty:
                    if self._stopped.is_set() or self.host.should_stop():
                        raise ScriptError("已停止") from None
                    if self.channel.closed.is_set() or self.process.poll() is not None:
                        raise ScriptError(
                            "独立脚本进程异常退出：" + self._read_output()
                        )
                    continue
                self.channel.handle(request)
            if "error" in self._result:
                raise ScriptError(
                    self._result["error"], lineno=self._result.get("line")
                )
            return bool(self._result["success"]), str(self._result["detail"])
        finally:
            server.close()
            if connection is not None:
                connection.close()

    def _read_output(self):
        if self._output is None:
            return ""
        self._output.seek(0, os.SEEK_END)
        self._output.seek(max(0, self._output.tell() - 16000))
        return self._output.read().decode("utf-8", errors="replace")

    def close(self):
        self._shutdown.set()
        if self._monitor is not None and self._monitor.ident is not None:
            self._monitor.join()
        errors = []
        try:
            if self.channel is not None:
                self.channel.close()
        except Exception as exc:  # noqa: BLE001 -- release the other owned resources before reporting failure
            errors.append(str(exc))
        try:
            if self._job is not None:
                self._job.close()
        except Exception as exc:  # noqa: BLE001 -- terminate the worker even if job cleanup reports failure
            errors.append(str(exc))
        try:
            if self.process is not None:
                if self.process.poll() is None:
                    terminate_process_tree(self.process, wait_timeout=3, force=True)
                if self.process.poll() is not None:
                    unregister_worker_process(self.process)
        except Exception as exc:  # noqa: BLE001 -- release the environment lease even if process cleanup fails
            errors.append(str(exc))
        try:
            if self._output is not None:
                self._output.close()
        except Exception as exc:  # noqa: BLE001 -- release the environment lease even if output cleanup fails
            errors.append(str(exc))
        try:
            if self._lease is not None:
                self._lease.__exit__(None, None, None)
        except Exception as exc:  # noqa: BLE001 -- preserve all cleanup failures for the user
            errors.append(str(exc))
        if errors:
            raise ValueError("独立脚本资源释放失败：" + "；".join(errors))
