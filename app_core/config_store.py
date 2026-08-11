import json
import logging
import os
import time
from utils.app_paths import get_config_path

CONFIG_FILE = get_config_path()

def _build_default_config() -> dict:
    return {
        "target_window_title": None,
        "execution_mode": "background_sendmessage",
        "foreground_driver_backend": "interception",
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
        "binding_method": "enhanced",
        "enable_canvas_grid": True,
        "enable_card_snap": True,
        "enable_parameter_panel_snap": True,
        "enable_floating_status_window": True,
        "close_behavior": "ask",
        "close_behavior_remember": False,
        "start_task_hotkey": "F9",
        "stop_task_hotkey": "F10",
        "schedule_mode": "fixed_time",
        "schedule_interval_value": 5,
        "schedule_interval_unit": "分钟",
        "recent_workflows": [],
    }


def load_config() -> dict:
    defaults = _build_default_config()

    def _repair_corrupted_config_file(cause: Exception):
        try:
            if os.path.exists(CONFIG_FILE):
                backup_path = f"{CONFIG_FILE}.corrupt.{int(time.time())}.bak"
                try:
                    os.replace(CONFIG_FILE, backup_path)
                    logging.warning(f"检测到配置文件损坏，已备份到: {backup_path}")
                except OSError as backup_err:
                    logging.warning(f"备份损坏配置文件失败，将直接覆盖: {backup_err}")
            save_config(dict(defaults))
            logging.info(f"已重建默认配置文件: {CONFIG_FILE}")
        except Exception as repair_err:
            logging.error(f"修复配置文件失败 {CONFIG_FILE}: {repair_err} (原始错误: {cause})")

    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                loaded_config = json.load(f)
            if "start_hotkey" in loaded_config and "start_task_hotkey" not in loaded_config:
                loaded_config["start_task_hotkey"] = loaded_config["start_hotkey"]
                logging.info(f"迁移旧配置：start_hotkey -> start_task_hotkey = {loaded_config['start_hotkey']}")

            if "stop_hotkey" in loaded_config and "stop_task_hotkey" not in loaded_config:
                loaded_config["stop_task_hotkey"] = loaded_config["stop_hotkey"]
                logging.info(f"迁移旧配置：stop_hotkey -> stop_task_hotkey = {loaded_config['stop_hotkey']}")

            defaults.update(loaded_config)
            defaults.setdefault("foreground_mouse_driver_backend", defaults.get("foreground_driver_backend", "interception"))
            defaults.setdefault("foreground_keyboard_driver_backend", defaults.get("foreground_driver_backend", "interception"))
            defaults.setdefault("enable_canvas_grid", True)
            defaults.setdefault("enable_card_snap", True)
            defaults.setdefault("enable_parameter_panel_snap", True)
            defaults.setdefault("enable_floating_status_window", True)
            return defaults
        except (json.JSONDecodeError, IOError) as e:
            logging.error(f"无法加载配置文件 {CONFIG_FILE}: {e}")
            _repair_corrupted_config_file(e)

    return defaults


def save_config(config_to_save: dict):
    try:
        config_to_save.setdefault("target_window_title", None)
        config_to_save.setdefault("execution_mode", "background_sendmessage")
        config_to_save.setdefault("foreground_driver_backend", "interception")
        config_to_save.setdefault("foreground_mouse_driver_backend", config_to_save.get("foreground_driver_backend", "interception"))
        config_to_save.setdefault("foreground_keyboard_driver_backend", config_to_save.get("foreground_driver_backend", "interception"))
        config_to_save.setdefault("ibinputsimulator_driver", "Logitech")
        config_to_save.setdefault("ibinputsimulator_driver_arg", "")
        config_to_save.setdefault("ibinputsimulator_ahk_path", "")
        config_to_save.setdefault("ibinputsimulator_ahk_dir", "")
        config_to_save.setdefault("operation_mode", "auto")
        config_to_save.setdefault("custom_width", 0)
        config_to_save.setdefault("custom_height", 0)
        config_to_save.setdefault("screenshot_format", "bmp")
        config_to_save.setdefault("binding_method", "enhanced")
        config_to_save.setdefault("enable_canvas_grid", True)
        config_to_save.setdefault("enable_card_snap", True)
        config_to_save.setdefault("enable_parameter_panel_snap", True)
        config_to_save.setdefault("enable_floating_status_window", True)
        config_to_save.setdefault("close_behavior", "ask")
        config_to_save.setdefault("close_behavior_remember", False)
        config_to_save.setdefault("start_task_hotkey", "F9")
        config_to_save.setdefault("stop_task_hotkey", "F10")
        config_to_save.setdefault("schedule_mode", "fixed_time")
        config_to_save.setdefault("schedule_interval_value", 5)
        config_to_save.setdefault("schedule_interval_unit", "分钟")
        config_to_save.setdefault("recent_workflows", [])

        if "start_hotkey" in config_to_save:
            logging.info("清理旧配置键：start_hotkey (保留 start_task_hotkey)")
            del config_to_save["start_hotkey"]

        if "stop_hotkey" in config_to_save:
            logging.info("清理旧配置键：stop_hotkey (保留 stop_task_hotkey)")
            del config_to_save["stop_hotkey"]

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
        finally:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass
    except IOError as e:
        logging.error(f"无法保存配置文件 {CONFIG_FILE}: {e}")
