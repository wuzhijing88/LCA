from utils.plugin.session import INPUT_BIND_DISPLAYS, PluginSession, get_shared_plugin_client


class FakeClient:
    def __init__(self):
        self.binds = []
        self.frames = {(10, "gdi2"): object()}

    def bind(self, display_hwnd, input_hwnd, display, mouse, keypad, mode):
        self.binds.append((display_hwnd, input_hwnd, display, mouse, keypad, mode))
        return display == "gdi2"

    def capture_bgr(self, hwnd, display, input_hwnd=0):
        return self.frames.get((hwnd, display))


def test_capture_binds_normal_mouse_then_grabs():
    client = FakeClient()
    session = PluginSession(client=client)
    assert session.capture_bgr(10, "gdi2", input_hwnd=10) is client.frames[(10, "gdi2")]
    assert client.binds[0] == (10, 10, "gdi2", "normal", "normal", 0)


def test_dx_input_uses_non_hook_displays():
    assert INPUT_BIND_DISPLAYS == ("normal", "gdi", "gdi2")
    assert all(not item.startswith("dx") and not item.startswith("opengl") for item in INPUT_BIND_DISPLAYS)


def test_timeout_abandons_all_shared_clients(monkeypatch):
    import time

    from utils.plugin import session as session_mod

    class _Client:
        def __init__(self, hang=False):
            self.hang = hang

        def bind(self, *args, **kwargs):
            if self.hang:
                time.sleep(2.0)
            return True

    created = []

    def _factory():
        client = _Client(hang=len(created) == 0)
        created.append(client)
        return client

    killed = []
    monkeypatch.setattr(session_mod, "_create_plugin_client", _factory)
    monkeypatch.setattr(session_mod, "terminate_plugin_host", lambda: killed.append(True))
    session_mod.close_shared_plugin_client()
    try:
        sess_a = get_shared_plugin_client(11)
        sess_b = get_shared_plugin_client(22)
        client_b = sess_b._client
        assert sess_a._client is created[0]
        assert client_b is created[1]
        assert sess_a.ensure_input_bind(11, "normal", mouse="dx", keypad="dx", timeout=0.3) is False
        assert killed
        later_b = get_shared_plugin_client(22)
        assert later_b._client is not client_b
    finally:
        session_mod.close_shared_plugin_client()
