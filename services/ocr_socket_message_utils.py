# -*- coding: utf-8 -*-
"""OCR socket IPC helpers with explicit unpickler cleanup."""

from __future__ import annotations

import io
import pickle
import socket
from typing import Any, Optional

from services.socket_message_utils import (
    read_socket_max_message_bytes,
    recv_message_bytes_with_status as recv_socket_message_bytes_with_status,
    send_message as send_socket_message,
)


def _get_max_message_bytes() -> int:
    return read_socket_max_message_bytes(
        env_name="OCR_SOCKET_MAX_MESSAGE_MB",
        default_mb=128,
        min_mb=4,
        max_mb=512,
    )


def send_message(sock: socket.socket, data: dict, logger: Optional[Any] = None) -> bool:
    max_bytes = _get_max_message_bytes()
    return send_socket_message(
        sock,
        data,
        max_message_bytes=max_bytes,
        logger=logger,
    )


def recv_message(sock: socket.socket, timeout: float = 10.0, logger: Optional[Any] = None):
    data_bytes = None
    result = None
    unpickler = None
    buffer = None
    max_bytes = _get_max_message_bytes()
    try:
        data_bytes, status = recv_socket_message_bytes_with_status(
            sock=sock,
            timeout=timeout,
            max_message_bytes=max_bytes,
        )
        if status == "timeout" or status == "closed":
            return None
        if status != "ok" or data_bytes is None:
            if logger is not None and status == "invalid_size":
                try:
                    logger.error(
                        f"接收消息失败: 消息长度非法 (max={max_bytes})"
                    )
                except Exception:
                    pass
            return None

        buffer = io.BytesIO(data_bytes)
        unpickler = pickle.Unpickler(buffer)
        result = unpickler.load()
        return result
    except socket.timeout:
        return None
    except Exception as exc:
        if logger is not None:
            try:
                logger.error(f"接收消息失败: {exc}")
            except Exception:
                pass
        return None
    finally:
        if buffer is not None:
            try:
                buffer.close()
            except Exception:
                pass
            del buffer
        if unpickler is not None:
            try:
                if hasattr(unpickler, "memo"):
                    unpickler.memo.clear()
            except Exception:
                pass
            del unpickler
        if data_bytes is not None:
            del data_bytes
