"""Cancellable HTTP and strict chat-completions SSE decoding."""

from __future__ import annotations

import codecs
import io
import json
import threading
import urllib.error
from typing import Any, Callable

from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QObject, QTimer, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

MAX_STREAM_BYTES = 4 * 1024 * 1024
MAX_EVENT_BYTES = 256 * 1024
MAX_TOOL_CALLS = 32


class AIRequestCancelled(InterruptedError):
    def __init__(self):
        super().__init__("AI 请求已停止")


class AICancellation:
    def __init__(self):
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    def check(self) -> None:
        if self._event.is_set():
            raise AIRequestCancelled()


def request_http(request, *, timeout: int, cancel: AICancellation,
                 consume: Callable[[bytes], None], max_bytes: int) -> None:
    cancel.check()
    if type(timeout) is not int or timeout <= 0:
        raise ValueError("AI 网络请求超时必须为正整数秒")
    if QCoreApplication.instance() is None:
        raise RuntimeError("AI 网络请求需要已启动的应用程序")
    url = QUrl(request.full_url)
    if url.scheme() not in {"http", "https"} or not url.host() or url.userInfo():
        raise ValueError("AI 请求地址必须是有效的 HTTP 或 HTTPS 地址，不能包含账号密码")
    manager = QNetworkAccessManager()
    network_request = QNetworkRequest(url)
    network_request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                                 QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
    for name, value in request.header_items():
        network_request.setRawHeader(name.encode("ascii"), value.encode("utf-8"))
    reply = manager.sendCustomRequest(network_request, request.get_method().encode("ascii"), request.data or b"")
    reply.setReadBufferSize(64 * 1024)
    loop = QEventLoop(manager)
    timer = QTimer(manager)
    timer.setInterval(25)
    deadline = QTimer(manager)
    deadline.setSingleShot(True)
    errors: list[BaseException] = []
    received = 0
    error_body = bytearray()

    def fail(exc):
        if not errors:
            errors.append(exc)
        reply.abort()
        loop.quit()

    def poll():
        try:
            cancel.check()
        except AIRequestCancelled as exc:
            fail(exc)

    def drain():
        nonlocal received
        if errors:
            return
        try:
            cancel.check()
            chunk = bytes(reply.readAll())
            received += len(chunk)
            if received > max_bytes:
                raise RuntimeError("AI 网络响应超过大小上限")
            status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            if status is not None and int(status) >= 300:
                error_body.extend(chunk[:max(0, 2000 - len(error_body))])
            elif chunk:
                content_type = bytes(reply.rawHeader("Content-Type")).decode("ascii", errors="replace")
                if request.get_method() == "POST" and content_type.split(";", 1)[0].strip().lower() != "text/event-stream":
                    raise RuntimeError("AI 服务不支持流式响应（text/event-stream），不能降级为普通请求")
                consume(chunk)
        except BaseException as exc:
            fail(exc)

    def timed_out():
        fail(TimeoutError("等待 AI 服务超时"))

    connections = (
        reply.readyRead.connect(drain),
        reply.finished.connect(loop.quit),
        timer.timeout.connect(poll),
        deadline.timeout.connect(timed_out),
    )
    timer.start()
    deadline.start(timeout * 1000)
    try:
        if not reply.isFinished():
            loop.exec()
        drain()
        cancel.check()
        if errors:
            raise errors[0]
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        if status is not None and int(status) >= 300:
            raise urllib.error.HTTPError(request.full_url, int(status), "请求失败", {}, io.BytesIO(error_body))
        if reply.error() != QNetworkReply.NetworkError.NoError:
            raise RuntimeError(f"AI 网络请求失败：{reply.errorString()}")
        if status != 200:
            raise RuntimeError(f"AI 网络响应状态无效：{status}")
    finally:
        timer.stop()
        deadline.stop()
        disconnected = [QObject.disconnect(connection) for connection in connections]
        if not reply.isFinished():
            reply.abort()
        reply.deleteLater()
        manager.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        if not all(disconnected):
            raise RuntimeError("AI 网络请求清理失败：信号连接未完整解除")


def repository_opener(cancel: AICancellation):
    def open_request(request, timeout):
        data = bytearray()
        request_http(request, timeout=timeout, cancel=cancel, consume=data.extend,
                     max_bytes=40 * 1024 * 1024)
        return io.BytesIO(data)
    return open_request


class ChatStreamDecoder:
    def __init__(self, emit: Callable[[dict], None]):
        self._emit = emit
        self._decoder = codecs.getincrementaldecoder("utf-8")("strict")
        self._buffer = ""
        self._data: list[str] = []
        self._event_size = 0
        self._bytes = 0
        self._done = False
        self._finish = None
        self._content: list[str] = []
        self._calls: dict[int, dict] = {}

    def feed(self, chunk: bytes) -> None:
        self._bytes += len(chunk)
        if self._bytes > MAX_STREAM_BYTES:
            raise RuntimeError("AI 回复超过大小上限")
        try:
            self._buffer += self._decoder.decode(chunk)
        except UnicodeDecodeError as exc:
            raise RuntimeError("AI 流式响应不是有效 UTF-8") from exc
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._line(line.removesuffix("\r"))
        if len(self._buffer.encode("utf-8")) > MAX_EVENT_BYTES:
            raise RuntimeError("AI 流式事件超过大小上限")

    def _line(self, line: str) -> None:
        if not line:
            if self._data:
                data = "\n".join(self._data)
                self._data.clear()
                self._event_size = 0
                self._event(data)
            return
        if line.startswith(":"):
            return
        field, separator, value = line.partition(":")
        if field not in {"data", "event", "id", "retry"}:
            raise RuntimeError("AI 服务没有返回有效的 SSE 流，不能按普通 JSON 降级读取")
        if field == "data":
            if value.startswith(" "):
                value = value[1:]
            self._event_size += len(value.encode("utf-8"))
            if self._event_size > MAX_EVENT_BYTES:
                raise RuntimeError("AI 流式事件超过大小上限")
            self._data.append(value)

    def _event(self, data: str) -> None:
        if self._done:
            raise RuntimeError("AI 流式结束后仍返回数据")
        if data == "[DONE]":
            self._done = True
            return
        try:
            payload = json.loads(data)
            if not isinstance(payload, dict) or "error" in payload:
                raise ValueError("服务返回错误")
            choices = payload["choices"]
            if choices == [] and isinstance(payload.get("usage"), dict):
                return
            if not isinstance(choices, list) or len(choices) != 1:
                raise ValueError("必须返回一条回复")
            choice = choices[0]
            if not isinstance(choice, dict) or type(choice.get("index")) is not int or choice["index"] != 0 or self._finish is not None:
                raise ValueError("回复索引或结束状态无效")
            delta = choice["delta"]
            if not isinstance(delta, dict):
                raise ValueError("增量格式无效")
            text = delta.get("content")
            if text is not None:
                if not isinstance(text, str):
                    raise ValueError("回复增量必须是文本")
                self._content.append(text)
                if text:
                    self._emit({"type": "content", "text": text})
            if delta.get("refusal"):
                raise ValueError("模型拒绝了本次请求")
            calls = delta.get("tool_calls", [])
            if not isinstance(calls, list):
                raise ValueError("工具调用格式无效")
            for fragment in calls:
                self._tool_fragment(fragment)
            reason = choice.get("finish_reason")
            if reason is not None:
                if reason not in {"stop", "tool_calls"}:
                    raise ValueError(f"回复未完整结束：{reason}")
                self._finish = reason
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(f"AI 流式事件无效：{exc}") from exc

    def _tool_fragment(self, fragment: Any) -> None:
        if not isinstance(fragment, dict):
            raise ValueError("工具增量必须是对象")
        index = fragment["index"]
        if type(index) is not int or not 0 <= index < MAX_TOOL_CALLS:
            raise ValueError("工具调用索引无效或数量超限")
        call = self._calls.setdefault(index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
        if fragment.get("type", "function") != "function":
            raise ValueError("不支持的工具调用类型")
        function = fragment.get("function", {})
        if not isinstance(function, dict):
            raise ValueError("工具函数格式无效")
        for key, target in (("id", call), ("name", call["function"]), ("arguments", call["function"])):
            part = fragment.get(key) if key == "id" else function.get(key)
            if part is not None:
                if not isinstance(part, str):
                    raise ValueError("工具增量字段必须是文本")
                target[key] += part

    def finish(self) -> dict:
        try:
            self._buffer += self._decoder.decode(b"", final=True)
        except UnicodeDecodeError as exc:
            raise RuntimeError("AI 流式响应在 UTF-8 字符中途断开") from exc
        if self._buffer or self._data or not self._done or self._finish is None:
            raise RuntimeError("AI 流式响应提前断开，未收到完整结束标记")
        calls = [self._calls[index] for index in sorted(self._calls)]
        if bool(calls) != (self._finish == "tool_calls"):
            raise RuntimeError("AI 工具调用与结束状态不一致")
        identifiers = set()
        for call in calls:
            if not call["id"] or call["id"] in identifiers or not call["function"]["name"]:
                raise RuntimeError("AI 工具调用缺少名称、标识或标识重复")
            identifiers.add(call["id"])
        text = "".join(self._content)
        if not text.strip() and not calls:
            raise RuntimeError("AI 返回了空内容")
        return {"content": text, "tool_calls": calls}
