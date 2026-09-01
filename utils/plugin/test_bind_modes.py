import pytest

from utils.plugin.bind_modes import (
    PLUGIN_BIND_MODE_PRESETS,
    PLUGIN_INPUT_DISPLAYS,
    PLUGIN_KEYPAD_MODES,
    PLUGIN_MOUSE_MODES,
    normalize_plugin_bind_mode,
    normalize_plugin_keypad,
    normalize_plugin_mouse,
)


def test_plugin_mouse_keypad_include_common_dm_modes():
    for item in ("normal", "windows", "windows2", "windows3", "dx", "dx2"):
        assert item in PLUGIN_MOUSE_MODES
    for item in ("normal", "windows", "dx"):
        assert item in PLUGIN_KEYPAD_MODES
    assert "plugin.gdi" in PLUGIN_INPUT_DISPLAYS
    assert "gdi2" in PLUGIN_INPUT_DISPLAYS
    assert 0 in PLUGIN_BIND_MODE_PRESETS


def test_normalize_plugin_bind_params():
    assert normalize_plugin_mouse("DX") == "dx"
    assert normalize_plugin_keypad("Windows") == "windows"
    assert normalize_plugin_bind_mode("101") == 101
    with pytest.raises(ValueError):
        normalize_plugin_mouse("not-a-mode")
    with pytest.raises(ValueError):
        normalize_plugin_bind_mode(-1)
