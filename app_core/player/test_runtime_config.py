import json

from app_core.config_store import _build_default_config
from app_core.player.package import PLAYER_PACKAGE_SCHEMA_VERSION
from app_core.player.memory_store import clear_player_memory_store, put_player_memory_file
from app_core.player.runtime_config import (
    RUNTIME_CONFIG_FILENAME,
    apply_player_runtime_config,
    apply_player_ui_hotkeys,
    load_packaged_runtime_config,
    snapshot_export_runtime_config,
)
from ui.export_parts.assembler import build_manifest_and_ui_files


def test_snapshot_keeps_engine_and_input_drops_bindings():
    snapshot = snapshot_export_runtime_config(
        {
            "execution_mode": "foreground_py",
            "screenshot_engine": "dx.d3d11",
            "foreground_mouse_driver_backend": "interception",
            "foreground_keyboard_driver_backend": "logitech",
            "foreground_py_backend": "normal.hd",
            "bound_windows": [{"hwnd": 123, "title": "阴阳师"}],
            "target_window_title": "阴阳师",
            "custom_width": 1280,
            "custom_height": 720,
        }
    )
    assert snapshot["screenshot_engine"] == "dx.d3d11"
    assert snapshot["execution_mode"] == "foreground_py"
    assert snapshot["foreground_mouse_driver_backend"] == "interception"
    assert snapshot["foreground_keyboard_driver_backend"] == "logitech"
    assert snapshot["foreground_py_backend"] == "normal.hd"
    assert snapshot["custom_width"] == 1280
    assert snapshot["custom_height"] == 720
    assert "bound_windows" not in snapshot
    assert "target_window_title" not in snapshot


def test_snapshot_keeps_player_hotkeys_drops_editor_only_keys():
    snapshot = snapshot_export_runtime_config(
        {
            "start_task_hotkey": "F6",
            "stop_task_hotkey": "F7",
            "pause_workflow_hotkey": "XBUTTON1",
            "record_hotkey": "F12",
            "replay_hotkey": "F8",
            "close_listen_hotkey": "F7",
        }
    )
    assert snapshot["start_task_hotkey"] == "F6"
    assert snapshot["stop_task_hotkey"] == "F7"
    assert snapshot["pause_workflow_hotkey"] == "XBUTTON1"
    assert "record_hotkey" not in snapshot
    assert "replay_hotkey" not in snapshot
    assert "close_listen_hotkey" not in snapshot


def test_snapshot_strips_machine_local_ahk_paths():
    snapshot = snapshot_export_runtime_config(
        {
            "screenshot_engine": "wgc",
            "ibinputsimulator_driver": "Logitech",
            "ibinputsimulator_ahk_path": r"C:\Users\某人\AutoHotkey\AutoHotkey.exe",
            "ibinputsimulator_ahk_dir": r"D:\tools\ibinputsimulator",
        }
    )
    assert snapshot["screenshot_engine"] == "wgc"
    assert snapshot["ibinputsimulator_driver"] == "Logitech"
    assert "ibinputsimulator_ahk_path" not in snapshot
    assert "ibinputsimulator_ahk_dir" not in snapshot


def test_apply_overlays_hotkeys_onto_defaults():
    defaults = _build_default_config()
    merged = apply_player_runtime_config(
        defaults,
        {
            "start_task_hotkey": "CTRL+F9",
            "stop_task_hotkey": "CTRL+F10",
            "pause_workflow_hotkey": "CTRL+F11",
        },
    )
    assert merged["start_task_hotkey"] == "CTRL+F9"
    assert merged["stop_task_hotkey"] == "CTRL+F10"
    assert merged["pause_workflow_hotkey"] == "CTRL+F11"


def test_build_manifest_seeds_ui_hotkeys_from_runtime_config():
    files = build_manifest_and_ui_files(
        app_name="阴阳师",
        description="",
        ui={"title": "阴阳师"},
        runtime_config={
            "start_task_hotkey": "F6",
            "stop_task_hotkey": "F7",
            "pause_workflow_hotkey": "XBUTTON1",
        },
    )
    ui = json.loads(files["ui.json"].decode("utf-8"))
    assert ui["start_hotkey"] == "F6"
    assert ui["stop_hotkey"] == "F7"
    assert ui["pause_hotkey"] == "XBUTTON1"
    runtime = json.loads(files[RUNTIME_CONFIG_FILENAME].decode("utf-8"))
    assert runtime["start_task_hotkey"] == "F6"
    assert "ibinputsimulator_ahk_path" not in runtime
    assert "ibinputsimulator_ahk_dir" not in runtime


def test_apply_player_ui_hotkeys_prefers_packaged_over_ui_defaults():
    ui = apply_player_ui_hotkeys(
        {"start_hotkey": "F9", "stop_hotkey": "F10", "pause_hotkey": "F11"},
        {"start_task_hotkey": "F6", "stop_task_hotkey": "F7", "pause_workflow_hotkey": "XBUTTON1"},
    )
    assert ui["start_hotkey"] == "F6"
    assert ui["stop_hotkey"] == "F7"
    assert ui["pause_hotkey"] == "XBUTTON1"


def test_snapshot_reads_nested_execution_section():
    snapshot = snapshot_export_runtime_config(
        {
            "execution": {
                "screenshot_engine": "printwindow",
                "execution_mode": "background_sendmessage",
            }
        }
    )
    assert snapshot["screenshot_engine"] == "printwindow"
    assert snapshot["execution_mode"] == "background_sendmessage"


def test_apply_overlays_packaged_runtime_and_keeps_bindings():
    defaults = _build_default_config()
    defaults["bound_windows"] = [{"hwnd": 9, "title": "已绑定"}]
    defaults["target_window_title"] = "已绑定"
    merged = apply_player_runtime_config(
        defaults,
        {
            "screenshot_engine": "gdi",
            "execution_mode": "foreground_driver",
            "foreground_mouse_driver_backend": "logitech",
        },
    )
    assert merged["screenshot_engine"] == "gdi"
    assert merged["execution_mode"] == "foreground_driver"
    assert merged["foreground_mouse_driver_backend"] == "logitech"
    assert merged["bound_windows"] == [{"hwnd": 9, "title": "已绑定"}]
    assert merged["target_window_title"] == "已绑定"


def test_apply_empty_packaged_runtime_keeps_current_config():
    defaults = _build_default_config()
    merged = apply_player_runtime_config(defaults, {})
    assert merged["screenshot_engine"] == defaults["screenshot_engine"]
    assert merged["execution_mode"] == defaults["execution_mode"]


def test_build_manifest_includes_runtime_json():
    files = build_manifest_and_ui_files(
        app_name="阴阳师",
        description="",
        ui={"title": "阴阳师"},
        runtime_config={
            "screenshot_engine": "dx.d3d11",
            "execution_mode": "foreground_py",
            "bound_windows": [{"hwnd": 1}],
        },
    )
    assert RUNTIME_CONFIG_FILENAME in files
    payload = json.loads(files[RUNTIME_CONFIG_FILENAME].decode("utf-8"))
    assert payload["screenshot_engine"] == "dx.d3d11"
    assert payload["execution_mode"] == "foreground_py"
    assert "bound_windows" not in payload
    manifest = json.loads(files["manifest.json"].decode("utf-8"))
    assert manifest["schema_version"] == PLAYER_PACKAGE_SCHEMA_VERSION
    assert "license" not in manifest


def test_load_player_package_reads_runtime_json(tmp_path):
    from app_core.player.loader import load_player_package
    from app_core.player.memory_store import clear_player_memory_store
    from app_core.player.secure_package import seal_package_files

    clear_player_memory_store()
    files = build_manifest_and_ui_files(
        app_name="阴阳师",
        description="",
        ui={"title": "阴阳师"},
        runtime_config={"screenshot_engine": "dx.d3d11", "execution_mode": "foreground_py"},
    )
    files["workflows/main.json"] = json.dumps(
        {"cards": [{"id": 1, "task_type": "线程起点", "parameters": {}}], "connections": []}
    ).encode("utf-8")
    seal_package_files(files, tmp_path, bind_id=bytes(range(16)))
    try:
        package = load_player_package(tmp_path)
        assert package.runtime_config["screenshot_engine"] == "dx.d3d11"
        assert package.runtime_config["execution_mode"] == "foreground_py"
    finally:
        clear_player_memory_store()


def test_snapshot_export_runtime_config_drops_plugin_reg_code():
    snap = snapshot_export_runtime_config(
        {"screenshot_engine": "dx.d3d11", "plugin_reg_code": "abc"}
    )
    assert "plugin_reg_code" not in snap


def test_load_packaged_runtime_config_from_memory():
    clear_player_memory_store()
    try:
        put_player_memory_file(
            RUNTIME_CONFIG_FILENAME,
            json.dumps({"screenshot_engine": "gdi", "bound_windows": [{"hwnd": 1}]}).encode("utf-8"),
        )
        loaded = load_packaged_runtime_config()
        assert loaded["screenshot_engine"] == "gdi"
        assert "bound_windows" not in loaded
    finally:
        clear_player_memory_store()
