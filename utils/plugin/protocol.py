# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import struct
from typing import Any, Optional

import numpy as np

PIPE_PREFIX = "lca-plugin-"
FRAME_MAGIC = 0x3146504C
FRAME_HEADER_SIZE = 16
FRAME_MAP_SIZE = 64 * 1024 * 1024


def pipe_name(pid: int) -> str:
    return f"{PIPE_PREFIX}{int(pid)}"


def map_name(pid: int) -> str:
    return rf"Local\lca-plugin-frame-{int(pid)}"


def pack_message(payload: dict) -> bytes:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return struct.pack("<I", len(raw)) + raw


def feed_messages(buffer: bytes) -> tuple[list[dict[str, Any]], bytes]:
    messages: list[dict[str, Any]] = []
    view = bytes(buffer or b"")
    while len(view) >= 4:
        size = struct.unpack_from("<I", view, 0)[0]
        if size < 0 or len(view) < 4 + size:
            break
        payload = json.loads(view[4 : 4 + size].decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("plugin message must be an object")
        messages.append(payload)
        view = view[4 + size :]
    return messages, view


def write_bgr_frame(buf: memoryview, image: np.ndarray) -> tuple[int, int, int]:
    if image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
        raise ValueError("frame must be uint8 BGR")
    height, width, _ = image.shape
    stride = int(width) * 3
    needed = FRAME_HEADER_SIZE + stride * int(height)
    if needed > FRAME_MAP_SIZE:
        raise ValueError("frame exceeds 64MiB map")
    struct.pack_into("<iiii", buf, 0, FRAME_MAGIC, int(width), int(height), stride)
    dest = np.frombuffer(buf, dtype=np.uint8, offset=FRAME_HEADER_SIZE, count=stride * height)
    dest[:] = np.ascontiguousarray(image).reshape(-1)
    return int(width), int(height), stride


def read_bgr_frame(buf: memoryview) -> Optional[np.ndarray]:
    if len(buf) < FRAME_HEADER_SIZE:
        return None
    magic, width, height, stride = struct.unpack_from("<iiii", buf, 0)
    if magic != FRAME_MAGIC or width <= 0 or height <= 0 or stride < width * 3:
        return None
    needed = FRAME_HEADER_SIZE + stride * height
    if needed > len(buf):
        return None
    raw = np.frombuffer(buf, dtype=np.uint8, offset=FRAME_HEADER_SIZE, count=stride * height)
    frame = raw.reshape((height, stride))[:, : width * 3].reshape((height, width, 3))
    return np.ascontiguousarray(frame)
