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
    except FileNotFoundError:
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
    "background_hierarchy_broadcast": False,
    "background_fake_active": False,
    "background_block_physical_mouse": False,
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
    "plugin_bind_auto_detect": True,
    "plugin_public": [],
    "plugin_reg_code": "",
    "plugin_extra_code": "",
    "binding_method": "enhanced",
    "window_binding_mode": "single",
    "bound_windows": [],
    "enable_canvas_grid": True,
    "enable_card_snap": True,
    "enable_parameter_panel_snap": True,
    "enable_connection_line_animation": True,
    "enable_execution_log_on_run": True,
    "confirm_partial_window_failure": True,
    "close_behavior": "ask",
    "close_behavior_remember": False,
    **DEFAULT_HOTKEYS,
    "main_schedule": default_main_schedule_dict(),
    "control_schedule": default_control_schedule_dict(),
    "multi_window_delay": 500,
    "recent_workflows": [],
    "child_session": None,
}

_REMOVED_CONFIG_KEYS = (
    "start_hotkey",
    "stop_hotkey",
    "foreground_driver_backend",
    "plugin_dir",  # 插件目录固定为安装目录 tools/plugin，不再可配置
    "theme_pack",
) + OLD_SCHEDULE_KEYS

_EXECUTION_MODES = (
    "foreground_driver",
    "foreground_py",
    "background_sendmessage",
    "background_postmessage",
)
_INPUT_BACKENDS = ("native", "plugin")
_OPERATION_MODES = ("auto", "standard_window")
_SCREENSHOT_FORMATS = ("bmp", "png", "jpg", "jpeg")


def _build_default_config() -> dict:
    """Return fresh defaults so mutable values are never shared."""
    from utils.child_session.settings import default_child_session_config

    defaults = deepcopy(_DEFAULT_CONFIG)
    defaults["child_session"] = default_child_session_config()
    return defaults


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
        normalize_plugin_public,
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
    _require_bool(config, "confirm_partial_window_failure")

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
    for key in (
        "background_hierarchy_broadcast",
        "background_fake_active",
        "background_block_physical_mouse",
        "plugin_input_display_follow",
        "plugin_text_ime",
        "plugin_fake_active",
        "plugin_bind_auto_detect",
    ):
        _require_bool(config, key)
    config["plugin_public"] = list(normalize_plugin_public(config.get("plugin_public")))
    for key in ("plugin_reg_code", "plugin_extra_code"):
        _require_str(config, key)

    if config["input_backend"] == "plugin":
        if not is_plugin_screenshot_engine(engine):
            raise ValueError(f"插件执行模式必须使用插件截图引擎，不能使用 {engine!r}")
        if engine not in plugin_display_options_for_kind(kind):
            raise ValueError(f"插件截图引擎 {engine!r} 不属于绑定方式 {kind!r}")
        # 插件键鼠只能按后台消息执行；原生模式单独保存在 native_execution_mode。
        from utils.input_simulation.mode_utils import PLUGIN_EXECUTION_MODE

        config["execution_mode"] = PLUGIN_EXECUTION_MODE
    else:
        from utils.capture.engine_ids import is_native_screenshot_engine

        if not is_native_screenshot_engine(engine):
            raise ValueError(f"原生执行模式必须使用原生截图引擎，不能使用 {engine!r}")
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
    # Flat keys are the only truth; rebuild section mirrors before defaults.
    normalized = apply_sections(normalized)
    for key, value in _build_default_config().items():
        normalized.setdefault(key, value)
    apply_schedule_schema(normalized)
    normalize_bound_windows_hwnds(normalized.get("bound_windows"))
    _validate_execution_settings(normalized)
    from utils.child_session.settings import default_child_session_config, normalize_child_session_config

    if "child_session" not in normalized or normalized.get("child_session") is None:
        normalized["child_session"] = default_child_session_config()
    else:
        normalized["child_session"] = normalize_child_session_config(normalized.get("child_session"))
    return apply_sections(normalized)


def load_config() -> dict:
    """读取并规范化主配置；返回的字典由调用方独占，可自由修改。"""
    defaults = _build_default_config()

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
            raise RuntimeError(f"无法加载配置文件 {config_file}: {e}") from e

    return defaults


def _replace_config_file(tmp_path: str, config_file: str) -> None:
    """Windows 上目标文件刚被写入时，替换可能短暂返回拒绝访问。"""
    delay_seconds = 0.02
    last_error = None
    for _attempt in range(8):
        try:
            os.replace(tmp_path, config_file)
            return
        except OSError as exc:
            last_error = exc
            if getattr(exc, "winerror", None) not in (5, 32):
                raise
            time.sleep(delay_seconds)
            delay_seconds = min(delay_seconds * 2, 0.2)
    raise last_error


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
        _replace_config_file(tmp_path, config_file)
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
