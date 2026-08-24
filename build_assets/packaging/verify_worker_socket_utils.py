# -*- coding: utf-8 -*-
"""Packaged worker verify socket helpers."""

from __future__ import annotations

import socket
import sys
from pathlib import Path
from typing import Dict

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from services.socket_message_utils import (
    recv_message_with_status as recv_socket_message_with_status,
    send_message as send_socket_message,
)

_MAX_VERIFY_MESSAGE_BYTES = 32 * 1024 * 1024


def send_verify_message(sock: socket.socket, payload: Dict) -> None:
    if not send_socket_message(sock, payload):
        raise RuntimeError("send_message_failed")


def recv_verify_message(sock: socket.socket, timeout_sec: float) -> Dict:
    data, status = recv_socket_message_with_status(
        sock=sock,
        timeout=timeout_sec,
        max_message_bytes=_MAX_VERIFY_MESSAGE_BYTES,
    )
    if status == "ok" and isinstance(data, dict):
        return data
    if status == "timeout":
        raise RuntimeError("socket_timeout")
    if status == "closed":
        raise RuntimeError("socket_closed")
    if status == "invalid_size":
        raise RuntimeError("invalid_payload_size")
    if status == "invalid_payload":
        raise RuntimeError("invalid_payload_type")
    if status == "decode_error":
        raise RuntimeError("invalid_payload_decode")
    raise RuntimeError(f"socket_recv_error:{status}")
