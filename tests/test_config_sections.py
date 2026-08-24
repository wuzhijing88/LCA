from app_core.config_sections import CONFIG_SCHEMA_VERSION, apply_sections, execution_settings


def test_sections_keep_legacy_flat_keys_compatible():
    config = {
        "execution_mode": "foreground",
        "screenshot_engine": "gdi",
        "multi_window_delay": 250,
    }

    normalized = apply_sections(config)

    assert normalized["schema_version"] == CONFIG_SCHEMA_VERSION
    assert normalized["execution"]["execution_mode"] == "foreground"
    assert normalized["execution_mode"] == "foreground"


def test_section_value_wins_during_schema_migration():
    config = {
        "execution_mode": "foreground",
        "execution": {"execution_mode": "background_sendmessage"},
    }

    assert apply_sections(config)["execution_mode"] == "background_sendmessage"


def test_session_only_active_windows_are_not_persisted():
    normalized = apply_sections({"active_bound_windows": [{"hwnd": 10}]})

    assert "active_bound_windows" not in normalized
    assert execution_settings(normalized).screenshot_engine == "wgc"
