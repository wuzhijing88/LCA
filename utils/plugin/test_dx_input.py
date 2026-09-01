# -*- coding: utf-8 -*-
from utils.input_simulation.mode_utils import is_dx_input_mode
from utils.plugin.dx_input import PluginDxInput
from utils.plugin.runtime import LoopbackTransport, PluginClient, PluginRpc
from utils.plugin.session import INPUT_BIND_DISPLAYS, PluginSession


class _FakeHandler:
    def __init__(self, bind_ok=None):
        self.binds = []
        self.calls = []
        self._bind_ok = bind_ok

    def __call__(self, payload):
        method = payload["method"]
        args = payload.get("args") or {}
        mid = payload["id"]
        if method == "bind":
            rec = (
                int(args["display_hwnd"]),
                int(args["input_hwnd"]),
                str(args["display"]),
                str(args["mouse"]),
                str(args["keypad"]),
                int(args["mode"]),
            )
            self.binds.append(rec)
            ok = True if self._bind_ok is None else bool(self._bind_ok(rec))
            return {"id": mid, "ok": True, "result": {"ok": ok}}
        if method == "move_to":
            self.calls.append(("move_to", int(args["x"]), int(args["y"])))
            return {"id": mid, "ok": True, "result": True}
        if method == "mouse_click":
            self.calls.append(("click", args.get("button")))
            return {"id": mid, "ok": True, "result": True}
        if method == "mouse_double_click":
            self.calls.append(("double", args.get("button")))
            return {"id": mid, "ok": True, "result": True}
        if method == "mouse_down":
            self.calls.append(("down", args.get("button")))
            return {"id": mid, "ok": True, "result": True}
        if method == "mouse_up":
            self.calls.append(("up", args.get("button")))
            return {"id": mid, "ok": True, "result": True}
        if method == "wheel":
            self.calls.append(("wheel", int(args["delta"])))
            return {"id": mid, "ok": True, "result": True}
        if method == "key_down":
            self.calls.append(("key_down", int(args["vk_code"])))
            return {"id": mid, "ok": True, "result": True}
        if method == "key_up":
            self.calls.append(("key_up", int(args["vk_code"])))
            return {"id": mid, "ok": True, "result": True}
        if method == "key_press":
            self.calls.append(("key_press", int(args["vk_code"])))
            return {"id": mid, "ok": True, "result": True}
        if method == "key_press_str":
            self.calls.append(("key_press_str", str(args.get("text")), int(args.get("delay") or 0)))
            return {"id": mid, "ok": True, "result": True}
        return {"id": mid, "ok": True, "result": True}


def _make_client(handler):
    return PluginClient(rpc=PluginRpc(LoopbackTransport(handler)))


def test_dx_input_mode_aliases():
    assert is_dx_input_mode("background_dx")
    assert is_dx_input_mode("background_op_dx")
    assert not is_dx_input_mode("background_sendmessage")
    assert not is_dx_input_mode("foreground_driver")


def test_plugin_dx_input_binds_dx_and_clicks_client_coords():
    handler = _FakeHandler()
    client = _make_client(handler)
    dx = PluginDxInput(9, display="dx.d3d11", client=client)
    assert dx.click(10, 20, button="left", clicks=1, duration=0)
    assert handler.binds
    assert all(item[2] in INPUT_BIND_DISPLAYS for item in handler.binds)
    assert handler.binds[0] == (9, 9, "normal", "dx", "dx", 0)
    assert handler.calls == [("move_to", 10, 20), ("click", "left")]
    client.close()


def test_plugin_dx_input_retries_split_hwnds_as_equal():
    def bind_ok(rec):
        if rec[0] != rec[1]:
            raise RuntimeError("无法分离绑定: 大漠 BindWindowEx 不支持独立 input_hwnd")
        return True

    handler = _FakeHandler(bind_ok=bind_ok)
    client = _make_client(handler)
    dx = PluginDxInput(9, display="normal", client=client, input_hwnd=99)
    assert dx.click(3, 4, button="left", clicks=1, duration=0)
    assert any(item[:3] == (9, 9, "normal") for item in handler.binds)
    assert all(item[2] in INPUT_BIND_DISPLAYS for item in handler.binds)
    assert handler.calls == [("move_to", 3, 4), ("click", "left")]
    client.close()


def test_plugin_dx_input_falls_back_when_preferred_display_fails():
    handler = _FakeHandler(bind_ok=lambda rec: rec[2] not in {"normal", "dx.d3d9"})
    client = _make_client(handler)
    session = PluginSession(client=client)
    assert session.ensure_input_bind(5, "dx.d3d9", mouse="dx", keypad="dx")
    assert handler.binds
    last = handler.binds[-1]
    assert last[2] == "gdi"
    assert last[3:] == ("dx", "dx", 0)
    assert all(item[2] in INPUT_BIND_DISPLAYS for item in handler.binds)
    assert all(not str(item[2]).startswith("dx") for item in handler.binds)
    client.close()


def test_ensure_input_bind_times_out_instead_of_hanging(monkeypatch):
    import time

    from utils.plugin import session as session_mod

    class _SlowClient:
        def bind(self, display_hwnd, input_hwnd, display, mouse, keypad, mode):
            time.sleep(2.0)
            return True

    killed = []
    monkeypatch.setattr(session_mod, "terminate_plugin_host", lambda: killed.append(True))
    session_mod.close_shared_plugin_client()
    try:
        sess = PluginSession(client=_SlowClient())
        assert sess.ensure_input_bind(7, "normal", mouse="dx", keypad="dx", timeout=0.3) is False
        assert killed
    finally:
        session_mod.close_shared_plugin_client()


def test_plugin_dx_input_rebuilds_client_after_timeout(monkeypatch):
    import time

    from utils.plugin import dx_input as dx_mod
    from utils.plugin import session as session_mod

    created = []
    factory_calls = [0]

    class _Client:
        def __init__(self, hang_after=0):
            self.binds = 0
            self.hang_after = hang_after
            created.append(self)

        def bind(self, *args, **kwargs):
            self.binds += 1
            if self.hang_after and self.binds > self.hang_after:
                time.sleep(2.0)
            return True

        def move_to(self, x, y):
            return True

    def _factory():
        factory_calls[0] += 1
        return _Client(hang_after=1 if factory_calls[0] == 1 else 0)

    original_bind = PluginSession.ensure_input_bind

    def _short_bind(self, *args, **kwargs):
        kwargs["timeout"] = 0.3
        return original_bind(self, *args, **kwargs)

    monkeypatch.setattr(session_mod, "_create_plugin_client", _factory)
    monkeypatch.setattr(session_mod, "terminate_plugin_host", lambda: None)
    monkeypatch.setattr(session_mod.PluginSession, "ensure_input_bind", _short_bind)
    monkeypatch.setattr(dx_mod, "is_plugin_runtime_available", lambda: True)
    session_mod.close_shared_plugin_client()
    try:
        dx = PluginDxInput(9, display="normal")
        assert dx._ready() is True
        first = dx._client
        assert first is created[0]
        assert dx._ready() is False
        assert dx._client is None
        assert dx._ready() is True
        assert dx._client is not first
        assert dx._client is created[1]
    finally:
        session_mod.close_shared_plugin_client()


def test_plugin_dx_input_hold_click_and_keys():
    handler = _FakeHandler()
    client = _make_client(handler)
    dx = PluginDxInput(4, display="dx", client=client)
    assert dx.click(1, 2, button="right", clicks=1, duration=0.0, interval=0)
    assert dx.key_down(13)
    assert dx.key_up(13)
    assert dx.wheel(3, 4, -120)
    assert ("down", "right") not in handler.calls
    assert ("key_down", 13) in handler.calls
    assert ("key_up", 13) in handler.calls
    assert ("wheel", -120) in handler.calls
    assert all(item[2] in INPUT_BIND_DISPLAYS for item in handler.binds)
    client.close()
