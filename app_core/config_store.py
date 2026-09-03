import json
import logging
import os
import threading
import time
from collections.abc import Mapping
from copy import deepcopy
from typing import Optional

from app_core.config_sections import CONFIG_SCHEMA_VERSION, DEFAULT_HOTKEYS, apply_sections
from app_core.scheduling.store import OLD_SCHEDULE_KEYS, apply_schedule_schema, default_control_schedule_dict, default_main_schedule_dict
from utils.app_paths import get_config_path
from utils.runtime_config import set_runtime_config_provider
from utils.window.hwnd_utils import normalize_bound_windows_hwnds


def _config_file() -> str:
    return get_config_path()


# load_config() 是热路径（输入模拟、插件绑定每次动作都会读），按文件签名缓存规范化结果；
# 文件被任何进程改写后签名变化，下一次读取自动刷新。
_cache_lock = threading.Lock()
_cache_signature: Optional[tuple] = None
_cache_value: Optional[dict] = None


def _file_signature(config_file: str) -> Optional[tuple]:
    try:
        stat = os.stat(config_file)
    except OSError:
        return None
    return (config_file, stat.st_mtime_ns, stat.st_size)


def _cached_config(signature: Optional[tuple]) -> Optional[dict]:
    if signature is None:
        return None
    with _cache_lock:
        if _cache_signature == signature and _cache_value is not None:
            return deepcopy(_cache_value)
    return None


def _store_cache(signature: Optional[tuple], config: dict) -> None:
    global _cache_signature, _cache_value
    if signature is None:
        return
    with _cache_lock:
        _cache_signature = signature
        _cache_value = deepcopy(config)


def _invalidate_cache() -> None:
    global _cache_signature, _cache_value
    with _cache_lock:
        _cache_signature = None
        _cache_value = None

_DEFAULT_CONFIG = {
    "target_window_title": None,
    "execution_mode": "background_sendmessage",
    "native_execution_mode": "background_sendmessage",
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
    "input_backend": "native",
    "plugin_mouse": "normal",
    "plugin_keypad": "normal",
    "plugin_input_display": "normal",
    "plugin_input_display_follow": True,
    "plugin_bind_kind": "basic",
    "plugin_bind_mode": 0,
    "plugin_text_ime": False,
    "plugin_fake_active": False,
    "plugin_reg_code": "",
    "plugin_extra_code": "",
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
    "plugin_dir",  # 插件目录固定为安装目录 tools/plugin，不再可配置
) + OLD_SCHEDULE_KEYS

_EXECUTION_MODES = (
    "foreground_driver",
    "foreground_py",
    "background_sendmessage",
    "background_postmessage",
)
_INPUT_BACKENDS = ("native", "plugin")
_OPERATION_MODES = ("auto", "standard_window", "emulator_window")
_SCREENSHOT_FORMATS = ("bmp", "png", "jpg", "jpeg")


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


def _require_choice(config: dict, key: str, options: tuple, *, lower: bool = True) -> None:
    raw = config.get(key)
    value = str(raw if raw is not None else "").strip()
    if lower:
        value = value.lower()
    if value not in options:
        raise ValueError(f"配置项 {key} 的值无效: {raw!r}（允许: {', '.join(map(str, options))}）")
    config[key] = value


def _require_bool(config: dict, key: str) -> None:
    raw = config.get(key)
    if not isinstance(raw, bool):
        raise ValueError(f"配置项 {key} 必须是布尔值: {raw!r}")


def _require_str(config: dict, key: str) -> None:
    raw = config.get(key)
    if raw is None:
        config[key] = ""
        return
    if not isinstance(raw, str):
        raise ValueError(f"配置项 {key} 必须是字符串: {raw!r}")


def _validate_execution_settings(config: dict) -> None:
    """Strictly validate execution keys; legacy or unknown values are errors."""
    from utils.capture.engine_ids import is_supported_screenshot_engine
    from utils.input_simulation.mode_utils import (
        normalize_ib_driver_name,
        require_foreground_backend,
        require_foreground_py_backend,
    )
    from utils.plugin.bind_modes import (
        normalize_plugin_bind_kind,
        normalize_plugin_bind_mode,
        normalize_plugin_keypad,
        normalize_plugin_mouse,
        plugin_bind_mode_options_for_kind,
        plugin_display_options_for_kind,
        plugin_keypad_options_for_kind,
        plugin_mouse_options_for_kind,
    )
    from utils.capture.engine_ids import is_plugin_screenshot_engine

    _require_choice(config, "execution_mode", _EXECUTION_MODES)
    _require_choice(config, "native_execution_mode", _EXECUTION_MODES)
    _require_choice(config, "input_backend", _INPUT_BACKENDS)
    _require_choice(config, "operation_mode", _OPERATION_MODES)
    _require_choice(config, "screenshot_format", _SCREENSHOT_FORMATS)

    engine = str(config.get("screenshot_engine") or "").strip().lower()
    if not is_supported_screenshot_engine(engine):
        raise ValueError(f"配置项 screenshot_engine 的值无效: {config.get('screenshot_engine')!r}")
    config["screenshot_engine"] = engine

    config["foreground_mouse_driver_backend"] = require_foreground_backend(
        config.get("foreground_mouse_driver_backend")
    )
    config["foreground_keyboard_driver_backend"] = require_foreground_backend(
        config.get("foreground_keyboard_driver_backend")
    )
    config["foreground_py_backend"] = require_foreground_py_backend(
        config.get("foreground_py_backend")
    )
    config["ibinputsimulator_driver"] = normalize_ib_driver_name(config.get("ibinputsimulator_driver"))
    for key in ("ibinputsimulator_driver_arg", "ibinputsimulator_ahk_path", "ibinputsimulator_ahk_dir"):
        _require_str(config, key)

    kind = normalize_plugin_bind_kind(config.get("plugin_bind_kind"))
    config["plugin_bind_kind"] = kind
    mouse = normalize_plugin_mouse(config.get("plugin_mouse"))
    if mouse not in plugin_mouse_options_for_kind(kind):
        raise ValueError(f"插件鼠标模式 {mouse!r} 不属于绑定方式 {kind!r}")
    config["plugin_mouse"] = mouse
    keypad = normalize_plugin_keypad(config.get("plugin_keypad"))
    if keypad not in plugin_keypad_options_for_kind(kind):
        raise ValueError(f"插件键盘模式 {keypad!r} 不属于绑定方式 {kind!r}")
    config["plugin_keypad"] = keypad
    display = str(config.get("plugin_input_display") or "").strip().lower()
    if display not in plugin_display_options_for_kind(kind):
        raise ValueError(f"插件图显 {config.get('plugin_input_display')!r} 不属于绑定方式 {kind!r}")
    config["plugin_input_display"] = display
    bind_mode = normalize_plugin_bind_mode(config.get("plugin_bind_mode"))
    if bind_mode not in plugin_bind_mode_options_for_kind(kind):
        raise ValueError(f"插件绑定 mode {bind_mode!r} 不属于绑定方式 {kind!r}")
    config["plugin_bind_mode"] = bind_mode
    for key in ("plugin_input_display_follow", "plugin_text_ime", "plugin_fake_active"):
        _require_bool(config, key)
    for key in ("plugin_reg_code", "plugin_extra_code"):
        _require_str(config, key)

    if config["input_backend"] == "plugin":
        if is_plugin_screenshot_engine(engine) and engine not in plugin_display_options_for_kind(kind):
            raise ValueError(f"插件截图引擎 {engine!r} 不属于绑定方式 {kind!r}")
        # 插件键鼠只能按后台消息执行；原生模式单独保存在 native_execution_mode。
        from utils.input_simulation.mode_utils import PLUGIN_EXECUTION_MODE

        config["execution_mode"] = PLUGIN_EXECUTION_MODE
    else:
        config["native_execution_mode"] = config["execution_mode"]


def _normalize_config(config: Mapping) -> dict:
    """Fill defaults, drop removed keys, validate strictly. Does not mutate *config*.

    Raises ValueError for any invalid or legacy value instead of guessing.
    """
    if not isinstance(config, Mapping):
        raise ValueError("配置文件根节点必须是 JSON 对象")

    normalized = deepcopy(dict(config))
    for key in _REMOVED_CONFIG_KEYS:
        normalized.pop(key, None)
    # Flat keys are the only truth; lift section-only values before defaults.
    normalized = apply_sections(normalized)
    for key, value in _build_default_config().items():
        normalized.setdefault(key, value)
    _repair_factory_hotkey_collision(normalized)
    apply_schedule_schema(normalized)
    normalize_bound_windows_hwnds(normalized.get("bound_windows"))
    _validate_execution_settings(normalized)
    return apply_sections(normalized)


def load_config() -> dict:
    """读取并规范化主配置；返回的字典由调用方独占，可自由修改。"""
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
    signature = _file_signature(config_file)
    cached = _cached_config(signature)
    if cached is not None:
        return cached

    if signature is not None:
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                loaded_config = json.load(f)
            normalized = _normalize_config(loaded_config)
            needs_rewrite = any(key in loaded_config for key in _REMOVED_CONFIG_KEYS) or any(
                key not in loaded_config for key in _DEFAULT_CONFIG
            ) or int(loaded_config.get("schema_version") or 0) < CONFIG_SCHEMA_VERSION
            if needs_rewrite:
                # 回写后文件签名变化，交给下一次读取重新建立缓存
                save_config(normalized)
            else:
                _store_cache(signature, normalized)
            return normalized
        except (json.JSONDecodeError, UnicodeDecodeError, OSError, TypeError, ValueError) as e:
            logging.error(f"无法加载配置文件 {config_file}: {e}")
            _repair_corrupted_config_file(e)

    return defaults


def save_config(config_to_save: Mapping):
    """Persist a config atomically, leaving the caller's mapping untouched."""
    config_to_save = _normalize_config(config_to_save)
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
        _invalidate_cache()
        logging.info(f"配置已保存到 {config_file}")
    except OSError as e:
        raise RuntimeError(f"无法保存配置文件 {config_file}: {e}") from e
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass


# 让 utils 层通过 utils.runtime_config 拿到规范化后的配置，而不必反向导入本模块。
# 用 lambda 延迟解析 load_config，保证测试中对本模块属性的替换也能生效。
set_runtime_config_provider(lambda: load_config())
