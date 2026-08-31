from pathlib import Path

import numpy as np
import pytest

from utils.plugin.protocol import FRAME_MAP_SIZE, write_bgr_frame
from utils.plugin.runtime import (
    LoopbackTransport,
    PluginClient,
    PluginRpc,
    find_plugin_dir,
    launch_host_command,
)


def test_launch_host_command_has_no_reg_code():
    cmd = launch_host_command(Path("C:/tools/plugin/PluginHost.exe"), "lca-plugin-9")
    joined = " ".join(cmd)
    assert cmd[-2:] == ["--pipe", "lca-plugin-9"]
    assert "reg" not in joined.lower()
    assert "secret" not in joined


def test_rpc_init_and_capture(monkeypatch, tmp_path):
    image = np.full((2, 2, 3), 7, dtype=np.uint8)
    buf = bytearray(FRAME_MAP_SIZE)
    write_bgr_frame(memoryview(buf), image)

    def handler(payload):
        method = payload["method"]
        if method == "init":
            assert payload["args"]["reg_code"] == "secret"
            return {"id": payload["id"], "ok": True, "result": {}}
        if method == "bind":
            return {"id": payload["id"], "ok": True, "result": {"ok": True}}
        if method == "capture":
            return {
                "id": payload["id"],
                "ok": True,
                "result": {"width": 2, "height": 2, "stride": 6},
            }
        return {"id": payload["id"], "ok": False, "error": method}

    rpc = PluginRpc(LoopbackTransport(handler), frame_buf=memoryview(buf))
    client = PluginClient(rpc=rpc)
    client.init(plugin_dir=str(tmp_path), reg_code="secret")
    assert client.bind(10, 10, "gdi2", "normal", "normal", 0) is True
    frame = client.capture_bgr(10, "gdi2", 10)
    assert frame is not None
    assert frame.shape == (2, 2, 3)
    assert int(frame[0, 0, 0]) == 7


def test_rpc_error_raises():
    def handler(payload):
        return {"id": payload["id"], "ok": False, "error": "未填写插件注册码"}

    rpc = PluginRpc(LoopbackTransport(handler))
    with pytest.raises(RuntimeError, match="注册码"):
        rpc.call("init", plugin_dir="x", reg_code="")


def test_find_plugin_dir_prefers_config(monkeypatch, tmp_path):
    chosen = tmp_path / "chosen"
    chosen.mkdir()
    monkeypatch.delenv("LCA_PLUGIN_DIR", raising=False)
    monkeypatch.setattr(
        "utils.plugin.runtime._read_plugin_config",
        lambda: {"plugin_dir": str(chosen), "plugin_reg_code": ""},
    )
    assert find_plugin_dir() == chosen.resolve()
