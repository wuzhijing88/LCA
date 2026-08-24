from app_core.config_store import _normalize_config


def test_config_normalization_is_non_mutating_and_removes_legacy_keys():
    source = {
        "start_hotkey": "F1",
        "foreground_driver_backend": "legacy",
        "bound_windows": [],
    }

    normalized = _normalize_config(source)

    assert source["start_hotkey"] == "F1"
    assert "start_hotkey" not in normalized
    assert "foreground_driver_backend" not in normalized
    assert normalized["start_task_hotkey"] == "F9"
    assert "main_schedule" in normalized
    assert "control_schedule" in normalized


def test_config_normalization_returns_fresh_mutable_defaults():
    first = _normalize_config({})
    second = _normalize_config({})

    first["recent_workflows"].append("one.json")

    assert second["recent_workflows"] == []
