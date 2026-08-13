import json
import logging
import os
import time
from collections.abc import Mapping
from copy import deepcopy

from utils.app_paths import get_config_path

CONFIG_FILE = get_config_path()

_DEFAULT_CONFIG = {
    "target_window_title": None,
    "execution_mode": "background_sendmessage",
    "foreground_mouse_driver_backend": "interception",
    "foreground_keyboard_driver_backend": "interception",
    "ibinputsimulator_driver": "Logitech",
    "ibinputsimulator_driver_arg": "",
    "ibinputsimulator_ahk_path": "",
    "ibinputsimulator_ahk_dir": "",
    "operation_mode": "auto",
    "custom_width": 0,
    "custom_height": 0,
    "screenshot_format": "bmp",
    "screenshot_engine": "wgc",
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
    "start_task_hotkey": "F9",
    "stop_task_hotkey": "F10",
    "schedule_mode": "fixed_time",
    "schedule_interval_value": 5,
    "schedule_interval_unit": "分钟",
    "multi_window_delay": 500,
    "recent_workflows": [],
}

_REMOVED_CONFIG_KEYS = (
    "start_hotkey",
    "stop_hotkey",
    "foreground_driver_backend",
)


def _build_default_config() -> dict:
    """Return fresh defaults so mutable values are never shared."""
    return deepcopy(_DEFAULT_CONFIG)


def _normalize_config(config: Mapping) -> dict:
    """Fill current-schema defaults and drop removed keys. Does not mutate *config*."""
    if not isinstance(config, Mapping):
        raise ValueError("配置文件根节点必须是 JSON 对象")

    normalized = deepcopy(dict(config))
    for key in _REMOVED_CONFIG_KEYS:
        normalized.pop(key, None)
    for key, value in _build_default_config().items():
        normalized.setdefault(key, value)
    return normalized


def load_config() -> dict:
    defaults = _build_default_config()

    def _repair_corrupted_config_file(cause: Exception):
        if os.path.exists(CONFIG_FILE):
            backup_path = f"{CONFIG_FILE}.corrupt.{int(time.time())}.bak"
            try:
                os.replace(CONFIG_FILE, backup_path)
                logging.warning(f"检测到配置文件损坏，已备份到: {backup_path}")
            except OSError as backup_err:
                raise RuntimeError(f"备份损坏配置文件失败: {backup_err}") from backup_err
        save_config(defaults)
        logging.info(f"已重建默认配置文件: {CONFIG_FILE}")

    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                loaded_config = json.load(f)
            normalized = _normalize_config(loaded_config)
            needs_rewrite = any(key in loaded_config for key in _REMOVED_CONFIG_KEYS) or any(
                key not in loaded_config for key in _DEFAULT_CONFIG
            )
            if needs_rewrite:
                save_config(normalized)
            return normalized
        except (json.JSONDecodeError, UnicodeDecodeError, OSError, TypeError, ValueError) as e:
            logging.error(f"无法加载配置文件 {CONFIG_FILE}: {e}")
            _repair_corrupted_config_file(e)

    return defaults


def save_config(config_to_save: Mapping):
    """Persist a config atomically, leaving the caller's mapping untouched."""
    config_to_save = _normalize_config(config_to_save)

    config_dir = os.path.dirname(CONFIG_FILE)
    if config_dir:
        os.makedirs(config_dir, exist_ok=True)

    tmp_path = f"{CONFIG_FILE}.tmp.{os.getpid()}.{int(time.time() * 1000)}"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(config_to_save, f, indent=4, ensure_ascii=False)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(tmp_path, CONFIG_FILE)
        logging.info(f"配置已保存到 {CONFIG_FILE}")
    except OSError as e:
        raise RuntimeError(f"无法保存配置文件 {CONFIG_FILE}: {e}") from e
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
