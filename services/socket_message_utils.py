# -*- coding: utf-8 -*-
"""Socket message helpers shared by subprocess pools/workers."""

from __future__ import annotations

import math
import os
import select
import socket
import struct
import threading
import weakref
from typing import Any, Dict, Optional, Tuple

from services.ipc_codec import (
    InvalidIpcPayloadError,
    IpcCodecError,
    decode_message,
    encode_message,
)


_SOCKET_LOCKS_GUARD = threading.Lock()
_SOCKET_SEND_LOCKS: "weakref.WeakKeyDictionary[socket.socket, Any]" = weakref.WeakKeyDictionary()
_SOCKET_RECV_LOCKS: "weakref.WeakKeyDictionary[socket.socket, Any]" = weakref.WeakKeyDictionary()


class SocketMessageError(RuntimeError):
    def __init__(self, status: str):
        self.status = str(status)
        super().__init__(f"socket message failed: {self.status}")


def _get_socket_lock(
    sock: socket.socket,
    registry: "weakref.WeakKeyDictionary[socket.socket, Any]",
) -> Any:
    with _SOCKET_LOCKS_GUARD:
        lock = registry.get(sock)
        if lock is None:
            lock = threading.RLock()
            registry[sock] = lock
        return lock


def _validate_message_limit(max_message_bytes: int) -> int:
    if isinstance(max_message_bytes, bool) or not isinstance(max_message_bytes, int):
        raise TypeError("max_message_bytes must be an integer")
    if max_message_bytes <= 0 or max_message_bytes > 0xFFFFFFFF:
        raise ValueError("max_message_bytes must be between 1 and 4294967295")
    return max_message_bytes


def _validate_timeout(timeout: float) -> float:
    if isinstance(timeout, bool):
        raise TypeError("timeout must be a finite positive number")
    value = float(timeout)
    if not math.isfinite(value) or value <= 0:
        raise ValueError("timeout must be a finite positive number")
    return value


def _abort_socket(sock: socket.socket) -> None:
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        sock.close()
    except OSError:
        pass


def read_socket_max_message_bytes(
    env_name: str,
    default_mb: int,
    min_mb: int,
    max_mb: int,
) -> int:
    normalized_env_name = str(env_name or "").strip()
    if not normalized_env_name:
        raise ValueError("env_name cannot be empty")
    for name, value in (
        ("default_mb", default_mb),
        ("min_mb", min_mb),
        ("max_mb", max_mb),
    ):
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{name} must be an integer")
    if min_mb <= 0 or max_mb < min_mb:
        raise ValueError("message size bounds are invalid")
    if default_mb < min_mb or default_mb > max_mb:
        raise ValueError("default_mb must be within the configured bounds")

    raw_value = os.getenv(normalized_env_name)
    if raw_value is None:
        size_mb = default_mb
    else:
        try:
            size_mb = int(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"{normalized_env_name} must be an integer, got {raw_value!r}"
            ) from exc
        if size_mb < min_mb or size_mb > max_mb:
            raise ValueError(
                f"{normalized_env_name} must be between {min_mb} and {max_mb} MB"
            )

    try:
        return _validate_message_limit(size_mb * 1024 * 1024)
    except (TypeError, ValueError) as exc:
        raise ValueError("configured socket message size is unsupported") from exc


def _log_socket_error(logger: Optional[Any], message: str) -> None:
    if logger is None:
        return
    try:
        logger.error(message)
    except Exception:
        pass


def _serialize_message_payload(
    data: Any,
    *,
    max_message_bytes: Optional[int] = None,
) -> Tuple[Optional[bytes], str]:
    max_bytes = (
        _validate_message_limit(max_message_bytes)
        if max_message_bytes is not None
        else 0xFFFFFFFF
    )
    try:
        payload = encode_message(data)
        if len(payload) <= 0 or len(payload) > max_bytes:
            return None, "invalid_size"
        return payload, "ok"
    except (IpcCodecError, TypeError, ValueError):
        return None, "encode_error"


def send_message(
    sock: socket.socket,
    data: Dict[str, Any],
    *,
    max_message_bytes: Optional[int] = None,
    logger: Optional[Any] = None,
) -> bool:
    if not isinstance(data, dict):
        raise TypeError("socket message payload must be a dictionary")
    if not callable(getattr(sock, "sendall", None)):
        raise TypeError("sock must provide sendall()")
    if max_message_bytes is not None:
        _validate_message_limit(max_message_bytes)

    payload = None
    packet = None
    try:
        payload, status = _serialize_message_payload(
            data,
            max_message_bytes=max_message_bytes,
        )
        if status != "ok" or payload is None:
            if status == "invalid_size":
                _log_socket_error(
                    logger,
                    f"send_message_failed: invalid payload size (max={int(max_message_bytes or 0)})",
                )
            else:
                _log_socket_error(logger, "send_message_failed: encode_error")
            return False

        packet = struct.pack("!I", len(payload)) + payload
        send_lock = _get_socket_lock(sock, _SOCKET_SEND_LOCKS)
        with send_lock:
            sock.sendall(packet)
        return True
    except Exception as exc:
        _log_socket_error(logger, f"send_message_failed: {exc}")
        return False
    finally:
        if payload is not None:
            del payload
        if packet is not None:
            del packet


def recv_message_bytes_with_status(
    sock: socket.socket,
    timeout: float = 10.0,
    max_message_bytes: int = 64 * 1024 * 1024,
) -> Tuple[Optional[bytes], str]:
    timeout_value = _validate_timeout(timeout)
    max_bytes = _validate_message_limit(max_message_bytes)
    if not callable(getattr(sock, "recv_into", None)):
        raise TypeError("sock must provide recv_into()")

    length_buf = None
    data_buf = None
    view = None
    recv_lock = _get_socket_lock(sock, _SOCKET_RECV_LOCKS)
    with recv_lock:
        def _recv_available(target_view: memoryview, max_bytes: int) -> Tuple[int, str]:
            try:
                readable, _, _ = select.select([sock], [], [], timeout_value)
            except (OSError, TypeError, ValueError):
                return 0, "error"
            if not readable:
                return 0, "timeout"
            try:
                received = sock.recv_into(target_view, max_bytes)
            except (BlockingIOError, socket.timeout):
                return 0, "timeout"
            except OSError:
                return 0, "error"
            if not received:
                return 0, "closed"
            return int(received), "ok"

        try:
            length_buf = bytearray(4)
            view = memoryview(length_buf)
            read_len = 0
            while read_len < 4:
                chunk_size, status = _recv_available(view[read_len:], 4 - read_len)
                if status != "ok":
                    if status == "timeout" and read_len == 0:
                        return None, "timeout"
                    if read_len > 0 or status == "error":
                        _abort_socket(sock)
                    if status == "timeout":
                        return None, "partial_timeout"
                    if status == "closed" and read_len > 0:
                        return None, "truncated"
                    return None, status
                read_len += chunk_size
            del view
            view = None

            size = struct.unpack("!I", bytes(length_buf))[0]
            if size <= 0 or size > max_bytes:
                _abort_socket(sock)
                return None, "invalid_size"
            del length_buf
            length_buf = None

            data_buf = bytearray(size)
            view = memoryview(data_buf)
            read_len = 0
            while read_len < size:
                chunk_size, status = _recv_available(
                    view[read_len:],
                    min(65536, size - read_len),
                )
                if status != "ok":
                    _abort_socket(sock)
                    if status == "timeout":
                        return None, "partial_timeout"
                    if status == "closed":
                        return None, "truncated"
                    return None, status
                read_len += chunk_size

            return bytes(data_buf), "ok"
        except (OSError, ValueError):
            _abort_socket(sock)
            return None, "error"
        finally:
            if view is not None:
                del view
            if length_buf is not None:
                del length_buf
            if data_buf is not None:
                del data_buf


def recv_message_with_status(
    sock: socket.socket,
    timeout: float = 10.0,
    max_message_bytes: int = 64 * 1024 * 1024,
) -> Tuple[Optional[Dict[str, Any]], str]:
    recv_lock = _get_socket_lock(sock, _SOCKET_RECV_LOCKS)
    with recv_lock:
        payload_bytes, status = recv_message_bytes_with_status(
            sock=sock,
            timeout=timeout,
            max_message_bytes=max_message_bytes,
        )
        if status != "ok" or payload_bytes is None:
            return None, status

        try:
            data = decode_message(payload_bytes)
        except InvalidIpcPayloadError:
            _abort_socket(sock)
            return None, "invalid_payload"
        except (IpcCodecError, TypeError, ValueError):
            _abort_socket(sock)
            return None, "decode_error"
        finally:
            del payload_bytes

        if isinstance(data, dict):
            return data, "ok"
        _abort_socket(sock)
        return None, "invalid_payload"


def recv_message(
    sock: socket.socket,
    timeout: float = 10.0,
    max_message_bytes: int = 64 * 1024 * 1024,
) -> Optional[Dict[str, Any]]:
    data, status = recv_message_with_status(
        sock=sock,
        timeout=timeout,
        max_message_bytes=max_message_bytes,
    )
    if status == "ok":
        return data
    if status in {"timeout", "closed"}:
        return None
    raise SocketMessageError(status)
