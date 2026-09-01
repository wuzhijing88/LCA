from app_core.config_store import _normalize_config
from app_core.player.runtime_config import snapshot_export_runtime_config


def test_normalize_migrates_legacy_plugin_engine():
    cfg = _normalize_config({"screenshot_engine": "normal.wgc"})
    assert cfg["screenshot_engine"] == "gdi2"
    assert cfg["plugin_reg_code"] == ""
    assert cfg["plugin_dir"] == ""


def test_normalize_migrates_legacy_engine_in_execution_section():
    cfg = _normalize_config({"execution": {"screenshot_engine": "normal.wgc"}})
    assert cfg["screenshot_engine"] == "gdi2"
    assert cfg["execution"]["screenshot_engine"] == "gdi2"


def test_normalize_keeps_native_engine():
    cfg = _normalize_config({"screenshot_engine": "wgc", "plugin_reg_code": "secret"})
    assert cfg["screenshot_engine"] == "wgc"
    assert cfg["plugin_reg_code"] == "secret"


def test_export_runtime_omits_plugin_secrets():
    snap = snapshot_export_runtime_config(
        {
            "screenshot_engine": "gdi2",
            "execution_mode": "background_dx",
            "plugin_reg_code": "secret",
            "plugin_dir": "C:\\plugin",
        }
    )
    assert snap["screenshot_engine"] == "gdi2"
    assert "plugin_reg_code" not in snap
    assert "plugin_dir" not in snap


def test_migrate_background_dx_to_plugin_input_backend():
    cfg = _normalize_config({"execution_mode": "background_dx"})
    assert cfg["input_backend"] == "plugin"
    assert cfg["plugin_mouse"] == "dx"
    assert cfg["plugin_keypad"] == "dx"
    assert cfg["execution_mode"] == "background_sendmessage"


def test_defaults_include_plugin_input_fields():
    cfg = _normalize_config({})
    assert cfg["input_backend"] == "native"
    assert cfg["plugin_mouse"] == "normal"
    assert cfg["plugin_keypad"] == "normal"
    assert cfg["plugin_input_display"] == "normal"
    assert cfg["plugin_bind_mode"] == 0


def test_export_runtime_keeps_input_backend_omits_reg_code():
    snap = snapshot_export_runtime_config(
        {
            "screenshot_engine": "plugin.gdi",
            "input_backend": "plugin",
            "plugin_mouse": "dx2",
            "plugin_keypad": "dx",
            "plugin_input_display": "gdi2",
            "plugin_bind_mode": 101,
            "plugin_reg_code": "secret",
        }
    )
    assert snap["input_backend"] == "plugin"
    assert snap["plugin_mouse"] == "dx2"
    assert snap["plugin_bind_mode"] == 101
    assert "plugin_reg_code" not in snap
