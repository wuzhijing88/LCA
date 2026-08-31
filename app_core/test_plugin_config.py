from app_core.config_store import _normalize_config
from app_core.player.runtime_config import snapshot_export_runtime_config


def test_normalize_migrates_legacy_plugin_engine():
    cfg = _normalize_config({"screenshot_engine": "normal.wgc"})
    assert cfg["screenshot_engine"] == "gdi2"
    assert cfg["plugin_reg_code"] == ""
    assert cfg["plugin_dir"] == ""


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
