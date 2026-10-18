"""Standard-library-only script worker and reentrant local RPC protocol.

This file is also shipped as source for execution by the private interpreter.
"""

from __future__ import annotations

import ast
import base64
import builtins
import contextlib
import importlib
import json
import os
import queue
import socket
import struct
import sys
import threading
import time
import types
from pathlib import Path

MAX_MESSAGE = 64 * 1024 * 1024


class RemoteError(RuntimeError):
    def __init__(self, message, lineno=None):
        super().__init__(message)
        self.lineno = lineno


class ScriptOutcome(Exception):
    def __init__(self, success, detail=""):
        self.success, self.detail = success, detail
        super().__init__(detail)


def send_packet(connection, message):
    data = json.dumps(message, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    if len(data) > MAX_MESSAGE:
        raise RemoteError("脚本通信数据超过 64 MB")
    connection.sendall(struct.pack("!I", len(data)) + data)


def receive_packet(connection):
    def read(size):
        chunks = bytearray()
        while len(chunks) < size:
            part = connection.recv(min(size - len(chunks), 1024 * 1024))
            if not part:
                raise EOFError("脚本进程通信已断开")
            chunks.extend(part)
        return chunks

    size = struct.unpack("!I", read(4))[0]
    if size > MAX_MESSAGE:
        raise RemoteError("脚本通信数据超过 64 MB")
    return json.loads(read(size))


class RemoteObject:
    def __init__(self, channel, handle, name="", kind="object"):
        self._channel = channel
        self._handle = handle
        self._remote_name = name
        self._remote_kind = kind

    @property
    def __name__(self):
        return self._remote_name

    def _operation(self, operation, *args, **kwargs):
        return self._channel.call("object", self._handle, operation, args, kwargs)

    def __call__(self, *args, **kwargs):
        return self._operation("call", *args, **kwargs)

    def __getattr__(self, name):
        return self._operation("getattr", name)

    def __getitem__(self, key):
        return self._operation("getitem", key)

    def __bool__(self):
        return self._operation("bool")

    def __len__(self):
        return self._operation("len")

    def __iter__(self):
        iterator = self._operation("iter")
        while True:
            try:
                yield iterator._operation("next")
            except StopIteration:
                return

    def __repr__(self):
        return self._operation("repr")

    def __del__(self):
        channel = self.__dict__.get("_channel")
        if channel is not None:
            channel.release(self._handle)


class Channel:
    def __init__(
        self,
        connection,
        handler,
        *,
        threaded=False,
        before_request=None,
        request_context=None,
    ):
        self.connection, self.handler = connection, handler
        self.threaded = threaded
        self.before_request = before_request
        self.request_context = request_context
        self.incoming = queue.Queue()
        self.closed = threading.Event()
        self.cancel_reason = ""
        self.failure = ""
        self._lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._local = threading.local()
        self._pending = {}
        self._objects = {}
        self._counter = 0
        self._threads = set()
        self._reader = threading.Thread(
            target=self._read, name="lca-script-rpc-reader", daemon=True
        )

    def start(self):
        self._reader.start()

    def send(self, message):
        if self.closed.is_set():
            raise RemoteError(self.cancel_reason or "脚本进程通信已关闭")
        with self._write_lock:
            send_packet(self.connection, message)

    def encode(self, value):
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        if isinstance(value, RemoteObject) and value._channel is self:
            return {"t": "back", "id": value._handle}
        if isinstance(value, bytes):
            return {"t": "bytes", "v": base64.b64encode(value).decode("ascii")}
        if isinstance(value, complex):
            return {"t": "complex", "v": [value.real, value.imag]}
        if value is Ellipsis:
            return {"t": "ellipsis"}
        if isinstance(value, (list, tuple, set)):
            return {
                "t": type(value).__name__,
                "v": [self.encode(item) for item in value],
            }
        if isinstance(value, dict):
            return {
                "t": "dict",
                "v": [
                    [self.encode(key), self.encode(item)] for key, item in value.items()
                ],
            }
        if isinstance(value, slice):
            return {"t": "slice", "v": [value.start, value.stop, value.step]}
        if (
            isinstance(value, (type, types.BuiltinFunctionType))
            and value.__module__ == "builtins"
        ):
            name = getattr(value, "__name__", "")
            if getattr(builtins, name, None) is value:
                return {"t": "builtin", "v": name}
        if type(value).__module__ == "numpy" and type(value).__name__ == "ndarray":
            if value.dtype.hasobject:
                raise RemoteError("脚本通信不接受包含 Python 对象的数组")
            return {
                "t": "array",
                "shape": value.shape,
                "dtype": value.dtype.str,
                "v": base64.b64encode(value.tobytes()).decode("ascii"),
            }
        with self._lock:
            handle = id(value)
            if handle not in self._objects:
                if len(self._objects) >= 8192:
                    raise RemoteError(
                        "脚本同时持有的通信对象超过 8192 个，请释放不用的结果"
                    )
                self._objects[handle] = [value, 0]
            self._objects[handle][1] += 1
        function = isinstance(value, (types.FunctionType, types.MethodType))
        code = value.__code__ if function else None
        return {
            "t": "ref",
            "id": handle,
            "name": value.__name__ if function else "",
            "kind": "callback"
            if code is not None and code.co_filename == "<script>"
            else "object",
        }

    def decode(self, value):
        if not isinstance(value, dict):
            return value
        kind = value["t"]
        if kind == "bytes":
            return base64.b64decode(value["v"])
        if kind == "complex":
            return complex(*value["v"])
        if kind == "ellipsis":
            return Ellipsis
        if kind == "dict":
            return {self.decode(key): self.decode(item) for key, item in value["v"]}
        if kind in {"list", "tuple", "set"}:
            return {"list": list, "tuple": tuple, "set": set}[kind](
                self.decode(item) for item in value["v"]
            )
        if kind == "slice":
            return slice(*value["v"])
        if kind == "builtin":
            return getattr(builtins, value["v"])
        if kind == "array":
            np = importlib.import_module("numpy")
            dtype = np.dtype(value["dtype"])
            if dtype.hasobject:
                raise RemoteError("脚本通信不接受包含 Python 对象的数组")
            return (
                np.frombuffer(base64.b64decode(value["v"]), dtype=dtype)
                .reshape(value["shape"])
                .copy()
            )
        if kind == "back":
            with self._lock:
                return self._objects[value["id"]][0]
        if kind == "ref":
            return RemoteObject(self, value["id"], value["name"], value["kind"])
        raise RemoteError("脚本通信收到未知的数据类型")

    def release(self, handle):
        if not self.closed.is_set():
            try:
                self.send({"type": "release", "id": handle})
            except (OSError, RemoteError):
                pass

    def call(self, operation, *args):
        with self._lock:
            self._counter += 1
            ident = self._counter
            messages = queue.Queue()
            self._pending[ident] = messages
        try:
            self.send(
                {
                    "type": "request",
                    "id": ident,
                    "route": getattr(self._local, "route", None),
                    "op": operation,
                    "args": self.encode(args),
                }
            )
            while not self.closed.is_set():
                try:
                    response = messages.get(timeout=0.1)
                except queue.Empty:
                    continue
                if response["type"] == "request":
                    self.handle(response)
                    continue
                if "error" in response:
                    error = response["error"]
                    if error["type"] == "ScriptOutcome":
                        raise ScriptOutcome(error["success"], error["detail"])
                    cls = getattr(builtins, error["type"], RemoteError)
                    if not isinstance(cls, type) or not issubclass(cls, Exception):
                        cls = RemoteError
                    if cls is RemoteError:
                        raise RemoteError(error["message"], error.get("line"))
                    raise cls(error["message"])
                return self.decode(response["value"])
            raise RemoteError(self.cancel_reason or "脚本进程通信已关闭")
        finally:
            with self._lock:
                self._pending.pop(ident, None)

    def _read(self):
        try:
            while not self.closed.is_set():
                message = receive_packet(self.connection)
                kind = message["type"]
                if kind == "release":
                    with self._lock:
                        record = self._objects.get(message["id"])
                        if record is not None:
                            record[1] -= 1
                            if record[1] <= 0:
                                self._objects.pop(message["id"], None)
                    continue
                with self._lock:
                    destination = self._pending.get(
                        message.get("route") if kind == "request" else message.get("id")
                    )
                if destination is not None:
                    destination.put(message)
                elif kind == "request" and self.threaded:

                    def run(request=message):
                        try:
                            self.handle(request)
                        finally:
                            with self._lock:
                                self._threads.discard(threading.current_thread())

                    thread = threading.Thread(
                        target=run, name="lca-script-callback", daemon=True
                    )
                    with self._lock:
                        self._threads.add(thread)
                    thread.start()
                elif kind == "request":
                    self.incoming.put(message)
                else:
                    raise RemoteError("脚本通信返回无效消息")
        except Exception as exc:  # noqa: BLE001 -- a protocol failure must wake every pending caller
            self.failure = str(exc)
        finally:
            self.closed.set()

    def handle(self, message):
        if self.request_context is not None:
            return self.request_context.copy().run(self._handle, message)
        return self._handle(message)

    def _handle(self, message):
        previous = getattr(self._local, "route", None)
        self._local.route = message["id"]
        response = {"type": "response", "id": message["id"]}
        try:
            if self.before_request is not None and message["op"] == "object":
                self.before_request()
            args = self.decode(message["args"])
            if message["op"] == "object":
                handle, operation, values, options = args
                with self._lock:
                    target = self._objects[handle][0]
                operations = {
                    "call": lambda: target(*values, **options),
                    "getattr": lambda: getattr(target, *values),
                    "getitem": lambda: target[values[0]],
                    "bool": lambda: bool(target),
                    "len": lambda: len(target),
                    "iter": lambda: iter(target),
                    "next": lambda: next(target),
                    "repr": lambda: repr(target),
                }
                result = operations[operation]()
            else:
                result = self.handler(message["op"], *args)
            response["value"] = self.encode(result)
        except BaseException as exc:  # noqa: BLE001 -- transfer script exceptions across the process boundary
            line = getattr(exc, "lineno", None)
            tb = exc.__traceback__
            while tb is not None:
                if tb.tb_frame.f_code.co_filename == "<script>":
                    line = tb.tb_lineno
                tb = tb.tb_next
            response["error"] = {
                "type": type(exc).__name__,
                "message": str(exc),
                "line": line,
                "success": getattr(exc, "success", False),
                "detail": getattr(exc, "detail", ""),
            }
        finally:
            self._local.route = previous
        try:
            self.send(response)
        except (OSError, RemoteError):
            self.closed.set()

    def close(self):
        self.closed.set()
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.connection.close()
        if (
            self._reader.ident is not None
            and self._reader is not threading.current_thread()
        ):
            self._reader.join()
        with self._lock:
            threads = list(self._threads)
        for thread in threads:
            if thread is not threading.current_thread():
                thread.join()
        self._objects.clear()
        self._pending.clear()


def tree_payload(node):
    if isinstance(node, ast.AST):
        return {
            "node": type(node).__name__,
            "fields": {
                name: tree_payload(value) for name, value in ast.iter_fields(node)
            },
            "attributes": {
                name: getattr(node, name)
                for name in node._attributes
                if hasattr(node, name)
            },
        }
    if isinstance(node, list):
        return [tree_payload(item) for item in node]
    return node


def restore_tree(value):
    if isinstance(value, list):
        return [restore_tree(item) for item in value]
    if not isinstance(value, dict):
        return value
    cls = getattr(ast, value["node"])
    fields = {name: restore_tree(item) for name, item in value["fields"].items()}
    if "type_params" in cls._fields:
        fields["type_params"] = []
    return cls(**fields, **value["attributes"])


def worker_main():
    port = int(sys.argv[1])
    token = os.environ.pop("LCA_SCRIPT_TOKEN")
    connection = socket.create_connection(("127.0.0.1", port), timeout=15)
    connection.settimeout(None)
    connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    send_packet(connection, {"type": "ready", "token": token})
    namespace = {"__name__": "__main__", "__builtins__": builtins.__dict__}

    def dispatch(operation, *args):
        if operation == "callback":
            return namespace[args[0]]
        raise RemoteError("脚本工作进程收到未知请求")

    channel = Channel(connection, dispatch, threaded=True)
    channel.start()
    image_api = None
    try:
        payload = channel.call("initialize")
        namespace.update(payload["namespace"])
        package = types.ModuleType("lca_runtime")
        package.__path__ = [str(Path(__file__).parent)]
        sys.modules["lca_runtime"] = package
        pure = importlib.import_module("lca_runtime.script_pure")
        for name, function in payload["local_functions"].items():
            namespace[name] = getattr(pure, function)
        image_module = importlib.import_module("lca_runtime.script_image")
        image_api = image_module.ImageApi(
            lambda path: channel.call("resource", path),
            lambda: channel.call("capture"),
        )
        namespace["图像"] = image_api
        last_check = threading.local()

        def guard():
            now = time.monotonic()
            if now - getattr(last_check, "time", 0) >= 0.05:
                channel.call("guard")
                last_check.time = now

        guard.loop = guard
        namespace.update(
            _lca_guard=guard, __guard=guard, __iter_count=pure.script_for_iterable
        )
        sdk = types.ModuleType("lca_sdk")
        sdk.__dict__.update(
            {
                name: value
                for name, value in namespace.items()
                if not name.startswith("_")
            }
        )
        sdk.截帧 = lambda: channel.call("capture")
        sdk.读取资源 = lambda path: channel.call("resource", path)
        sdk.上下文 = payload["context"]
        sys.modules["lca_sdk"] = sdk

        class Output:
            def __init__(self):
                self.pending = ""

            def write(self, text):
                self.pending += str(text)
                while "\n" in self.pending or len(self.pending) > 4000:
                    if "\n" in self.pending[:4000]:
                        line, self.pending = self.pending.split("\n", 1)
                    else:
                        line, self.pending = self.pending[:4000], self.pending[4000:]
                    channel.call("log", line)
                return len(text)

            def flush(self):
                if self.pending:
                    text, self.pending = self.pending, ""
                    channel.call("log", text)

        output = Output()

        def trace(frame, event, arg):
            if frame.f_code.co_filename != "<script>":
                return None
            if event == "line":
                values = {}
                for name in payload["debug_names"]:
                    if name in frame.f_locals:
                        try:
                            values[name] = repr(frame.f_locals[name])[:512]
                        except Exception:  # noqa: BLE001 -- user-defined repr may fail; report an unknown value
                            values[name] = "<无法读取>"
                channel.call("debug", frame.f_lineno, values)
            return trace

        result = {"success": True, "detail": ""}
        try:
            if payload["debug"]:
                sys.settrace(trace)
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                exec(  # noqa: S102 -- this is the custom-script execution entry point
                    compile(restore_tree(payload["tree"]), "<script>", "exec"),
                    namespace,
                    namespace,
                )
                output.flush()
        except ScriptOutcome as outcome:
            result = {"success": outcome.success, "detail": outcome.detail}
        except BaseException as exc:  # noqa: BLE001 -- report all script exits to the host
            line = getattr(exc, "lineno", None)
            tb = exc.__traceback__
            while tb is not None:
                if tb.tb_frame.f_code.co_filename == "<script>":
                    line = tb.tb_lineno
                tb = tb.tb_next
            if isinstance(exc, ModuleNotFoundError) and exc.name:
                module = exc.name.split(".")[0]
                if module == "task_workflow":
                    detail = (
                        "task_workflow 是 LCA 内部模块，独立环境不能直接导入。"
                        "请改用 from lca_sdk import 读取资源, 截帧；"
                        "资源读取调用 读取资源(路径)，截图调用 截帧()。"
                    )
                elif module == "utils":
                    detail = (
                        f"独立环境找不到模块“{exc.name}”。"
                        "LCA 截图请改用 from lca_sdk import 截帧，再调用 截帧()；"
                        "模板匹配可使用 cv2.matchTemplate()。"
                    )
                else:
                    detail = (
                        f"找不到模块“{exc.name}”，请核对导入名称和环境依赖；"
                        "需要安装时，在“环境设置”的“安装依赖”页填写对应的安装包名称。"
                    )
                result = {"error": "运行失败：" + detail, "line": line}
            else:
                result = {"error": f"运行失败：{type(exc).__name__}：{exc}", "line": line}
        finally:
            sys.settrace(None)
        channel.call("finished", result)
        channel.closed.wait(10)
    finally:
        if image_api is not None:
            image_api.close()
        channel.close()


if __name__ == "__main__":
    worker_main()
