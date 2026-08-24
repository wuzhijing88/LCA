import pickle
import socket

import numpy as np

from services.ipc_codec import decode_message, encode_message
from services.socket_message_utils import recv_message_with_status, send_message


def test_codec_round_trips_worker_payload_types():
    source = {
        "cards": {1: {"shape": (2, 3), "raw": b"abc"}},
        "array": np.arange(6, dtype=np.uint8).reshape(2, 3),
        "values": {1, 2},
    }

    decoded = decode_message(encode_message(source))

    assert decoded["cards"] == source["cards"]
    assert decoded["values"] == source["values"]
    assert np.array_equal(decoded["array"], source["array"])


def test_socket_message_round_trip_uses_safe_codec():
    left, right = socket.socketpair()
    try:
        assert send_message(left, {"type": "ping", "payload": b"ok"})
        message, status = recv_message_with_status(right, timeout=1.0)
    finally:
        left.close()
        right.close()

    assert status == "ok"
    assert message == {"type": "ping", "payload": b"ok"}


def test_pickle_payload_is_rejected_without_deserialization():
    left, right = socket.socketpair()
    try:
        payload = pickle.dumps({"type": "legacy"})
        left.sendall(len(payload).to_bytes(4, "big") + payload)
        message, status = recv_message_with_status(right, timeout=1.0)
    finally:
        left.close()
        right.close()

    assert message is None
    assert status == "decode_error"
