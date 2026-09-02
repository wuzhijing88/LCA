from pathlib import Path

import numpy as np
import pytest

from utils.plugin.protocol import FRAME_MAP_SIZE, write_bgr_frame
from utils.plugin.runtime import (
    LoopbackTransport,
    PluginClient,
    PluginRpc,
    ensure_plugin_rpc,
    find_plugin_dir,
    launch_host_command,
    should_cool_down,
    terminate_plugin_host,
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


def test_concurrent_captures_keep_own_frames():
    import threading
    import time

    frames = {
        11: np.full((2, 2, 3), 11, dtype=np.uint8),
        22: np.full((2, 2, 3), 22, dtype=np.uint8),
    }
    buf = bytearray(FRAME_MAP_SIZE)

    def handler(payload):
        if payload["method"] == "capture":
            hwnd = int(payload["args"]["hwnd"])
            write_bgr_frame(memoryview(buf), frames[hwnd])
            return {"id": payload["id"], "ok": True, "result": {}}
        return {"id": payload["id"], "ok": True, "result": {}}

    rpc = PluginRpc(LoopbackTransport(handler), frame_buf=memoryview(buf))
    original_call = rpc.call

    def delayed_call(method, **args):
        result = original_call(method, **args)
        if method == "capture":
            time.sleep(0.05)
        return result

    rpc.call = delayed_call
    client = PluginClient(rpc=rpc)
    got = {}

    def worker(hwnd):
        got[hwnd] = client.capture_bgr(hwnd, "gdi2", hwnd)

    threads = [threading.Thread(target=worker, args=(hwnd,)) for hwnd in (11, 22)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert int(got[11][0, 0, 0]) == 11
    assert int(got[22][0, 0, 0]) == 22


def test_rpc_error_raises():
    def handler(payload):
        return {"id": payload["id"], "ok": False, "error": "未填写插件注册码"}

    rpc = PluginRpc(LoopbackTransport(handler))
    with pytest.raises(RuntimeError, match="注册码"):
        rpc.call("init", plugin_dir="x", reg_code="")


def _touch_runtime(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for name in ("PluginHost.exe", "dm.dll", "RegDll.dll"):
        (directory / name).write_bytes(b"x")
    return directory


def test_find_plugin_dir_uses_app_root_tools_plugin(monkeypatch, tmp_path):
    root = tmp_path / "install"
    plugin = _touch_runtime(root / "tools" / "plugin")
    other = _touch_runtime(tmp_path / "other")
    monkeypatch.setenv("LCA_PLUGIN_DIR", str(other))
    monkeypatch.setattr(
        "utils.plugin.runtime._read_plugin_config",
        lambda: {"plugin_dir": str(other), "plugin_reg_code": ""},
    )
    monkeypatch.setattr("utils.plugin.runtime.get_app_root", lambda: str(root))
    assert find_plugin_dir() == plugin.resolve()


def test_find_plugin_dir_ignores_config_and_env_when_install_missing(monkeypatch, tmp_path):
    root = tmp_path / "install"
    root.mkdir()
    other = _touch_runtime(tmp_path / "other")
    monkeypatch.setenv("LCA_PLUGIN_DIR", str(other))
    monkeypatch.setattr(
        "utils.plugin.runtime._read_plugin_config",
        lambda: {"plugin_dir": str(other), "plugin_reg_code": ""},
    )
    monkeypatch.setattr("utils.plugin.runtime.get_app_root", lambda: str(root))
    assert find_plugin_dir() is None


def test_find_plugin_dir_rejects_incomplete_install_dir(monkeypatch, tmp_path):
    root = tmp_path / "install"
    incomplete = root / "tools" / "plugin"
    incomplete.mkdir(parents=True)
    (incomplete / "PluginHost.exe").write_bytes(b"x")
    monkeypatch.delenv("LCA_PLUGIN_DIR", raising=False)
    monkeypatch.setattr(
        "utils.plugin.runtime._read_plugin_config",
        lambda: {"plugin_dir": "", "plugin_reg_code": ""},
    )
    monkeypatch.setattr("utils.plugin.runtime.get_app_root", lambda: str(root))
    assert find_plugin_dir() is None


def test_ensure_plugin_rpc_rejects_empty_reg_code_before_launch(monkeypatch):
    import utils.plugin.runtime as runtime

    terminate_plugin_host()
    monkeypatch.setattr(runtime, "_COOLDOWN_HITS", 0)
    monkeypatch.setattr(runtime, "_COOLDOWN_UNTIL", 0.0)
    monkeypatch.setattr(runtime, "is_plugin_runtime_available", lambda: True)
    monkeypatch.setattr(runtime, "find_plugin_dir", lambda: Path("C:/tools/plugin"))
    monkeypatch.setattr(
        runtime,
        "_read_plugin_config",
        lambda: {"plugin_dir": "C:/tools/plugin", "plugin_reg_code": "   "},
    )
    popen_calls = []

    def fake_popen(*_args, **_kwargs):
        popen_calls.append(1)
        raise AssertionError("PluginHost.exe must not start for empty reg code")

    monkeypatch.setattr(runtime.subprocess, "Popen", fake_popen)

    with pytest.raises(RuntimeError, match="未填写插件注册码"):
        ensure_plugin_rpc()
    assert popen_calls == []
    assert runtime._COOLDOWN_HITS == 0
    assert should_cool_down() is False


def test_attach_host_job_closes_handle_when_assign_fails(monkeypatch):
    import utils.plugin.runtime as runtime

    job_handle = object()
    closed = []

    class FakeKernel32:
        def CloseHandle(self, handle):
            closed.append(handle)
            return True

    monkeypatch.setattr(runtime, "_create_kill_on_close_job", lambda: job_handle)

    def fail_assign(_job, _proc):
        raise OSError("assign failed")

    monkeypatch.setattr(runtime, "_assign_process_to_job", fail_assign)
    monkeypatch.setattr(runtime, "_kernel32", lambda: FakeKernel32())

    result = runtime._attach_host_job(type("Proc", (), {"pid": 1})())
    assert result is None
    assert closed == [job_handle]
