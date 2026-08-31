import json
import logging
import os
import time
from collections.abc import Mapping
from copy import deepcopy

from app_core.config_sections import CONFIG_SCHEMA_VERSION, DEFAULT_HOTKEYS, apply_sections
from app_core.scheduling.store import OLD_SCHEDULE_KEYS, apply_schedule_schema, default_control_schedule_dict, default_main_schedule_dict
from app_core.user_data_migration import migrate_default_user_data
from utils.app_paths import get_config_path
from utils.window.hwnd_utils import normalize_bound_windows_hwnds


def _config_file() -> str:
    return get_config_path()

_DEFAULT_CONFIG = {
    "target_window_title": None,
    "execution_mode": "background_sendmessage",
    "foreground_mouse_driver_backend": "interception",
    "foreground_keyboard_driver_backend": "interception",
    "foreground_py_backend": "pyautogui",
    "ibinputsimulator_driver": "Logitech",
    "ibinputsimulator_driver_arg": "",
    "ibinputsimulator_ahk_path": "",
    "ibinputsimulator_ahk_dir": "",
    "operation_mode": "auto",
    "custom_width": 0,
    "custom_height": 0,
    "screenshot_format": "bmp",
    "screenshot_engine": "wgc",
    "plugin_reg_code": "",
    "plugin_dir": "",
    "binding_method": "enhanced",
    "window_binding_mode": "single",
    "bound_windows": [],
    "enable_canvas_grid": True,
    "enable_card_snap": True,
    "enable_parameter_panel_snap": True,
    "enable_floating_status_window": True,
    "enable_connection_line_animation": True,
    "close_behavior": "ask",
    "close_behavior_remember": False,
    **DEFAULT_HOTKEYS,
    "main_schedule": default_main_schedule_dict(),
    "control_schedule": default_control_schedule_dict(),
    "multi_window_delay": 500,
    "recent_workflows": [],
}

_REMOVED_CONFIG_KEYS = (
    "start_hotkey",
    "stop_hotkey",
    "foreground_driver_backend",
) + OLD_SCHEDULE_KEYS


def _build_default_config() -> dict:
    """Return fresh defaults so mutable values are never shared."""
    return deepcopy(_DEFAULT_CONFIG)


def _repair_factory_hotkey_collision(config: dict) -> None:
    """Fix the known factory clash: pause and record both defaulted to F11."""
    pause = str(config.get("pause_workflow_hotkey") or "").strip().upper()
    record = str(config.get("record_hotkey") or "").strip().upper()
    if pause != "F11" or record != "F11":
        return
    replacement = DEFAULT_HOTKEYS["record_hotkey"]
    taken = {
        str(config.get(key) or "").strip().upper()
        for key in DEFAULT_HOTKEYS
        if key != "record_hotkey"
    }
    if replacement.upper() not in taken:
        config["record_hotkey"] = replacement


def _normalize_config(config: Mapping, *, prefer: str = "section") -> dict:
    """Fill current-schema defaults and drop removed keys. Does not mutate *config*."""
    if not isinstance(config, Mapping):
        raise ValueError("配置文件根节点必须是 JSON 对象")

    normalized = deepcopy(dict(config))
    for key in _REMOVED_CONFIG_KEYS:
        normalized.pop(key, None)
    for key, value in _build_default_config().items():
        normalized.setdefault(key, value)
    _repair_factory_hotkey_collision(normalized)
    apply_schedule_schema(normalized)
    normalize_bound_windows_hwnds(normalized.get("bound_windows"))
    normalize_bound_windows_hwnds(normalized.get("active_bound_windows"))
    from utils.capture.engine_ids import migrate_screenshot_engine

    normalized["screenshot_engine"] = migrate_screenshot_engine(
        normalized.get("screenshot_engine")
    )
    return apply_sections(normalized, prefer=prefer)


def load_config() -> dict:
    try:
        migration = migrate_default_user_data()
        if migration.copied:
            logging.info("已迁移旧版用户数据: %s", ", ".join(migration.copied))
    except Exception as migration_error:
        logging.warning("用户数据迁移失败，继续使用当前用户目录: %s", migration_error)

    defaults = _build_default_config()

    def _repair_corrupted_config_file(cause: Exception):
        config_file = _config_file()
        if os.path.exists(config_file):
            backup_path = f"{config_file}.corrupt.{int(time.time())}.bak"
            try:
                os.replace(config_file, backup_path)
                logging.warning(f"检测到配置文件损坏，已备份到: {backup_path}")
            except OSError as backup_err:
                raise RuntimeError(f"备份损坏配置文件失败: {backup_err}") from backup_err
        save_config(defaults)
        logging.info(f"已重建默认配置文件: {config_file}")

    config_file = _config_file()
    if os.path.exists(config_file):
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                loaded_config = json.load(f)
            normalized = _normalize_config(loaded_config)
            needs_rewrite = any(key in loaded_config for key in _REMOVED_CONFIG_KEYS) or any(
                key not in loaded_config for key in _DEFAULT_CONFIG
            ) or int(loaded_config.get("schema_version") or 0) < CONFIG_SCHEMA_VERSION
            if needs_rewrite:
                save_config(normalized)
            return normalized
        except (json.JSONDecodeError, UnicodeDecodeError, OSError, TypeError, ValueError) as e:
            logging.error(f"无法加载配置文件 {config_file}: {e}")
            _repair_corrupted_config_file(e)

    return defaults


def save_config(config_to_save: Mapping):
    """Persist a config atomically, leaving the caller's mapping untouched."""
    config_to_save = _normalize_config(config_to_save, prefer="flat")
    config_file = _config_file()

    config_dir = os.path.dirname(config_file)
    if config_dir:
        os.makedirs(config_dir, exist_ok=True)

    tmp_path = f"{config_file}.tmp.{os.getpid()}.{int(time.time() * 1000)}"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(config_to_save, f, indent=4, ensure_ascii=False)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(tmp_path, config_file)
        logging.info(f"配置已保存到 {config_file}")
    except OSError as e:
        raise RuntimeError(f"无法保存配置文件 {config_file}: {e}") from e
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
