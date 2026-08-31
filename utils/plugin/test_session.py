from utils.plugin.session import INPUT_BIND_DISPLAYS, PluginSession


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
