from utils.plugin.capture import capture_window_plugin


def test_capture_window_plugin_rejects_native_engine():
    assert capture_window_plugin(1, "wgc") is None
