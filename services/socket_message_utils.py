# -*- coding: utf-8 -*-
"""Socket message helpers shared by subprocess pools/workers."""

from __future__ import annotations

import os
import pickle
import socket
import struct
from typing import Any, Callable, Dict, Optional, Tuple


def read_socket_max_message_bytes(
    env_name: str,
    default_mb: int,
    min_mb: int,
    max_mb: int,
) -> int:
    raw_value = os.getenv(env_name, str(int(default_mb)))
    try:
        size_mb = int(raw_value)
    except Exception:
        size_mb = int(default_mb)
    size_mb = max(int(min_mb), min(int(max_mb), int(size_mb)))
    return int(size_mb) * 1024 * 1024


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
    try:
        payload = pickle.dumps(data, protocol=4)
        if max_message_bytes is not None:
            max_bytes = max(1, int(max_message_bytes))
            if len(payload) <= 0 or len(payload) > max_bytes:
                return None, "invalid_size"
        return payload, "ok"
    except Exception:
        return None, "encode_error"


def send_message(
    sock: socket.socket,
    data: Dict[str, Any],
    *,
    max_message_bytes: Optional[int] = None,
    logger: Optional[Any] = None,
) -> bool:
    payload = None
    header = None
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

        header = struct.pack("!I", len(payload))
        sock.sendall(header)
        sock.sendall(payload)
        return True
    except Exception as exc:
        _log_socket_error(logger, f"send_message_failed: {exc}")
        return False
    finally:
        if payload is not None:
            del payload
        if header is not None:
            del header


def recv_message_bytes_with_status(
    sock: socket.socket,
    timeout: float = 10.0,
    max_message_bytes: int = 64 * 1024 * 1024,
) -> Tuple[Optional[bytes], str]:
    length_buf = None
    data_buf = None
    view = None
    try:
        sock.settimeout(timeout)
        length_buf = bytearray(4)
        view = memoryview(length_buf)
        read_len = 0
        while read_len < 4:
            chunk_size = sock.recv_into(view[read_len:], 4 - read_len)
            if not chunk_size:
                return None, "closed"
            read_len += chunk_size
        del view
        view = None

        size = struct.unpack("!I", bytes(length_buf))[0]
        if size <= 0 or size > int(max_message_bytes):
            return None, "invalid_size"
        del length_buf
        length_buf = None

        data_buf = bytearray(size)
        view = memoryview(data_buf)
        read_len = 0
        while read_len < size:
            chunk_size = sock.recv_into(view[read_len:], min(65536, size - read_len))
            if not chunk_size:
                return None, "closed"
            read_len += chunk_size

        return bytes(data_buf), "ok"
    except socket.timeout:
        return None, "timeout"
    except Exception:
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
    payload_bytes, status = recv_message_bytes_with_status(
        sock=sock,
        timeout=timeout,
        max_message_bytes=max_message_bytes,
    )
    if status != "ok" or payload_bytes is None:
        return None, status

    try:
        data = pickle.loads(payload_bytes)
    except Exception:
        return None, "decode_error"
    finally:
        del payload_bytes

    if isinstance(data, dict):
        return data, "ok"
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
    return None


def is_cancel_requested(cancel_checker: Optional[Callable[[], bool]]) -> bool:
    if cancel_checker is None:
        return False
    try:
        return bool(cancel_checker())
    except Exception:
        return False
