import pytest

from task_workflow import window_adapter


def test_window_binding_round_trip_and_resolve(monkeypatch):
    adapter = window_adapter.WindowAdapter()
    binding = window_adapter.WindowBinding(hwnd=10, title="Target", bind_id="id-1")
    monkeypatch.setattr(window_adapter, "resolve_bound_window_hwnd", lambda _mapping: 20)

    resolved = adapter.resolve(binding)

    assert resolved.hwnd == 20
    assert resolved.title == "Target"
    assert resolved.bind_id == "id-1"


def test_window_adapter_registry_rejects_unknown_adapter():
    with pytest.raises(KeyError, match="unknown window adapter"):
        window_adapter.get_window_adapter("missing")


def test_window_adapter_registration():
    class Custom(window_adapter.WindowAdapter):
        name = "custom-test"

    custom = Custom()
    window_adapter.register_window_adapter(custom)

    assert window_adapter.get_window_adapter("custom-test") is custom
