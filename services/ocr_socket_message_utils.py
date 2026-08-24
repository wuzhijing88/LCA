# -*- coding: utf-8 -*-
"""Strict OCR/workflow socket IPC adapter."""

from __future__ import annotations

import socket
from typing import Any, Dict, Optional

from services.socket_message_utils import (
    SocketMessageError,
    read_socket_max_message_bytes,
    recv_message as recv_socket_message,
    send_message as send_socket_message,
)


MAX_OCR_SOCKET_MESSAGE_BYTES = read_socket_max_message_bytes(
    env_name="OCR_SOCKET_MAX_MESSAGE_MB",
    default_mb=128,
    min_mb=4,
    max_mb=512,
)


def send_message(sock: socket.socket, data: dict, logger: Optional[Any] = None) -> bool:
    return send_socket_message(
        sock,
        data,
        max_message_bytes=MAX_OCR_SOCKET_MESSAGE_BYTES,
        logger=logger,
    )


def recv_message(
    sock: socket.socket,
    timeout: float = 10.0,
    logger: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    try:
        return recv_socket_message(
            sock=sock,
            timeout=timeout,
            max_message_bytes=MAX_OCR_SOCKET_MESSAGE_BYTES,
        )
    except SocketMessageError as exc:
        if logger is not None:
            try:
                logger.error("接收消息失败: status=%s", exc.status)
            except Exception:
                pass
        raise
