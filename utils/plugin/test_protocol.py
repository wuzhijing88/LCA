import numpy as np

from utils.plugin.protocol import (
    FRAME_MAGIC,
    FRAME_MAP_SIZE,
    feed_messages,
    map_name,
    pack_message,
    pipe_name,
    read_bgr_frame,
    write_bgr_frame,
)


def test_pipe_and_map_names():
    assert pipe_name(1234) == "lca-plugin-1234"
    assert map_name(1234) == r"Local\lca-plugin-frame-1234"


def test_pack_and_feed_json_messages():
    first = pack_message({"id": 1, "method": "init", "args": {"reg_code": "x"}})
    second = pack_message({"id": 1, "ok": True, "result": {}})
    blob = first + second[:6]
    messages, rest = feed_messages(blob)
    assert messages == [{"id": 1, "method": "init", "args": {"reg_code": "x"}}]
    more, leftover = feed_messages(rest + second[6:])
    assert more == [{"id": 1, "ok": True, "result": {}}]
    assert leftover == b""


def test_bgr_frame_roundtrip():
    image = np.zeros((2, 3, 3), dtype=np.uint8)
    image[0, 1] = (1, 2, 3)
    buf = bytearray(FRAME_MAP_SIZE)
    width, height, stride = write_bgr_frame(memoryview(buf), image)
    assert (width, height, stride) == (3, 2, 9)
    assert int.from_bytes(buf[0:4], "little") == FRAME_MAGIC
    out = read_bgr_frame(memoryview(buf))
    assert out is not None
    assert out.shape == (2, 3, 3)
    assert tuple(out[0, 1]) == (1, 2, 3)
