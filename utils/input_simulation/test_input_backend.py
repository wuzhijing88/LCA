from utils.input_simulation.mode_utils import is_plugin_input_backend


def test_is_plugin_input_backend_from_config():
    assert is_plugin_input_backend({"input_backend": "plugin"})
    assert not is_plugin_input_backend({"input_backend": "native"})
    assert is_plugin_input_backend({"execution_mode": "background_dx"})
    assert not is_plugin_input_backend({"execution_mode": "background_sendmessage"})


def test_standard_window_uses_plugin_input_in_foreground(monkeypatch):
    from utils.input_simulation.standard_window import StandardWindowInputSimulator

    monkeypatch.setattr(
        "app_core.config_store.load_config",
        lambda: {"input_backend": "plugin", "execution_mode": "foreground_driver"},
    )
    window = StandardWindowInputSimulator(
        hwnd=1, use_foreground=True, execution_mode="foreground_driver"
    )
    assert window._using_plugin_dx() is True
