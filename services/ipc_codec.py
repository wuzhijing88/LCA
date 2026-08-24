"""Versioned, non-executable codec for local worker IPC."""

from __future__ import annotations

import base64
import json
import math
from enum import Enum
from pathlib import Path
from typing import Any


PROTOCOL_NAME = "lca-worker-ipc"
PROTOCOL_VERSION = 1
_TYPE_KEY = "__lca_type__"


class IpcCodecError(ValueError):
    pass


class InvalidIpcPayloadError(IpcCodecError):
    pass


def _encode(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise IpcCodecError("non-finite floats are not supported")
        return value
    if isinstance(value, Enum):
        return {_TYPE_KEY: "enum", "value": _encode(value.value)}
    if isinstance(value, Path):
        return {_TYPE_KEY: "path", "value": str(value)}
    if isinstance(value, bytes):
        return {
            _TYPE_KEY: "bytes",
            "data": base64.b64encode(value).decode("ascii"),
        }
    if isinstance(value, (bytearray, memoryview)):
        return {
            _TYPE_KEY: "bytes",
            "data": base64.b64encode(bytes(value)).decode("ascii"),
        }
    if isinstance(value, tuple):
        return {_TYPE_KEY: "tuple", "items": [_encode(item) for item in value]}
    if isinstance(value, (set, frozenset)):
        return {_TYPE_KEY: "set", "items": [_encode(item) for item in value]}
    if isinstance(value, list):
        return [_encode(item) for item in value]
    if isinstance(value, dict):
        return {
            _TYPE_KEY: "dict",
            "items": [[_encode(key), _encode(item)] for key, item in value.items()],
        }

    module_name = type(value).__module__
    class_name = type(value).__name__
    if module_name == "numpy" and class_name == "ndarray":
        return {
            _TYPE_KEY: "ndarray",
            "dtype": str(value.dtype),
            "shape": list(value.shape),
            "data": base64.b64encode(value.tobytes(order="C")).decode("ascii"),
        }
    raise IpcCodecError(f"unsupported IPC value: {module_name}.{class_name}")


def _decode(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, list):
        return [_decode(item) for item in value]
    if not isinstance(value, dict):
        raise IpcCodecError(f"invalid encoded value: {type(value).__name__}")

    kind = value.get(_TYPE_KEY)
    if kind == "bytes":
        try:
            return base64.b64decode(value["data"], validate=True)
        except (KeyError, TypeError, ValueError) as exc:
            raise IpcCodecError("invalid bytes payload") from exc
    if kind == "tuple":
        return tuple(_decode(item) for item in value.get("items", []))
    if kind == "set":
        return set(_decode(item) for item in value.get("items", []))
    if kind == "path":
        return Path(str(value.get("value", "")))
    if kind == "enum":
        return _decode(value.get("value"))
    if kind == "dict":
        decoded: dict[Any, Any] = {}
        for pair in value.get("items", []):
            if not isinstance(pair, list) or len(pair) != 2:
                raise IpcCodecError("invalid dictionary item")
            decoded[_decode(pair[0])] = _decode(pair[1])
        return decoded
    if kind == "ndarray":
        try:
            import numpy as np

            raw = base64.b64decode(value["data"], validate=True)
            array = np.frombuffer(raw, dtype=str(value["dtype"]))
            return array.reshape(tuple(int(part) for part in value["shape"])).copy()
        except (ImportError, KeyError, TypeError, ValueError) as exc:
            raise IpcCodecError("invalid ndarray payload") from exc
    raise IpcCodecError(f"unknown IPC type tag: {kind!r}")


def encode_message(data: dict[str, Any]) -> bytes:
    if not isinstance(data, dict):
        raise TypeError("IPC message must be a dictionary")
    envelope = {
        "protocol": PROTOCOL_NAME,
        "version": PROTOCOL_VERSION,
        "payload": _encode(data),
    }
    try:
        return json.dumps(
            envelope,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise IpcCodecError("failed to encode IPC message") from exc


def decode_message(payload: bytes) -> dict[str, Any]:
    try:
        envelope = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IpcCodecError("invalid IPC JSON") from exc
    if not isinstance(envelope, dict):
        raise IpcCodecError("IPC envelope must be an object")
    if envelope.get("protocol") != PROTOCOL_NAME:
        raise IpcCodecError("unexpected IPC protocol")
    if envelope.get("version") != PROTOCOL_VERSION:
        raise IpcCodecError("unsupported IPC protocol version")
    message = _decode(envelope.get("payload"))
    if not isinstance(message, dict):
        raise InvalidIpcPayloadError("IPC payload must decode to a dictionary")
    return message


__all__ = [
    "IpcCodecError",
    "InvalidIpcPayloadError",
    "PROTOCOL_NAME",
    "PROTOCOL_VERSION",
    "decode_message",
    "encode_message",
]
