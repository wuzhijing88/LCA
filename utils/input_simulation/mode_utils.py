"""Helpers for normalizing execution modes in native input paths."""

import os
import re
from collections.abc import Mapping
from typing import Optional, Tuple

from utils.app_paths import get_config_path


_CONFIG_CACHE_PATH: Optional[str] = None
_CONFIG_CACHE_MTIME: Optional[float] = None
_CONFIG_CACHE_DATA: dict = {}

SUPPORTED_IB_DRIVERS = {
    "Logitech",
    "Razer",
}

_IB_DRIVER_ALIASES = {
    "logitech": "Logitech",
    "razer": "Razer",
}

SUPPORTED_FOREGROUND_BACKENDS = {
    "interception",
    "ibinputsimulator",
}

SUPPORTED_FOREGROUND_PY_BACKENDS = {
    "pyautogui",
    "normal.hd",
}

_DEFAULT_FOREGROUND_BACKEND = "interception"
_DEFAULT_FOREGROUND_PY_BACKEND = "pyautogui"
_DEFAULT_IB_DRIVER = "Logitech"


def normalize_ib_driver_name(driver: Optional[str]) -> str:
    raw = str(driver or "").strip()
    if not raw:
        return _DEFAULT_IB_DRIVER
    if raw in SUPPORTED_IB_DRIVERS:
        return raw
    key = re.sub(r"[\s_\-]+", "", raw).lower()
    mapped = _IB_DRIVER_ALIASES.get(key)
    if mapped is None:
        raise ValueError(f"不支持的 IbInputSimulator 驱动: {driver!r}")
    return mapped


def _normalize_backend_token(value: object) -> str:
    raw = str(value or "").strip().lower().replace("_", ".")
    if raw in {"normal.hd", "normalhd", "normal.hd."}:
        return "normal.hd"
    return str(value or "").strip().lower()


def require_foreground_backend(value: object) -> str:
    backend = _normalize_backend_token(value)
    # 旧配置可能把 normal.hd 写在驱动字段里；驱动下拉已移除，回落到默认驱动。
    if backend == "normal.hd":
        return _DEFAULT_FOREGROUND_BACKEND
    if backend not in SUPPORTED_FOREGROUND_BACKENDS:
        raise ValueError(f"不支持的前台驱动: {value!r}")
    return backend


def require_foreground_py_backend(value: object) -> str:
    backend = _normalize_backend_token(value)
    if backend in {"", "pyautogui", "py", "python"}:
        return "pyautogui"
    if backend == "normal.hd":
        return "normal.hd"
    if backend not in SUPPORTED_FOREGROUND_PY_BACKENDS:
        raise ValueError(f"不支持的前台二输入方式: {value!r}")
    return backend


def parse_foreground_backends(config: Optional[Mapping] = None) -> Tuple[str, str]:
    values = dict(config or {})
    mouse_raw = values.get("foreground_mouse_driver_backend")
    keyboard_raw = values.get("foreground_keyboard_driver_backend")
    if mouse_raw is None or str(mouse_raw).strip() == "":
        mouse_raw = _DEFAULT_FOREGROUND_BACKEND
    if keyboard_raw is None or str(keyboard_raw).strip() == "":
        keyboard_raw = _DEFAULT_FOREGROUND_BACKEND
    return (
        require_foreground_backend(mouse_raw),
        require_foreground_backend(keyboard_raw),
    )


def parse_foreground_py_backend(config: Optional[Mapping] = None) -> str:
    values = dict(config or {})
    raw = values.get("foreground_py_backend")
    if raw is None or str(raw).strip() == "":
        # 兼容：曾把 normal.hd 配在前台一驱动字段
        mouse = str(values.get("foreground_mouse_driver_backend") or "").strip().lower()
        keyboard = str(values.get("foreground_keyboard_driver_backend") or "").strip().lower()
        if mouse in {"normal.hd", "normal_hd"} or keyboard in {"normal.hd", "normal_hd"}:
            return "normal.hd"
        return _DEFAULT_FOREGROUND_PY_BACKEND
    return require_foreground_py_backend(raw)


def migrate_legacy_normal_hd_config(config: Optional[Mapping] = None) -> dict:
    """把误放在前台一驱动里的 normal.hd 迁到前台二输入方式。"""
    result = dict(config or {})
    mouse = _normalize_backend_token(result.get("foreground_mouse_driver_backend"))
    keyboard = _normalize_backend_token(result.get("foreground_keyboard_driver_backend"))
    had_hd = mouse == "normal.hd" or keyboard == "normal.hd"
    if had_hd:
        if not str(result.get("foreground_py_backend") or "").strip():
            result["foreground_py_backend"] = "normal.hd"
        if mouse == "normal.hd":
            result["foreground_mouse_driver_backend"] = _DEFAULT_FOREGROUND_BACKEND
        if keyboard == "normal.hd":
            result["foreground_keyboard_driver_backend"] = _DEFAULT_FOREGROUND_BACKEND
        if str(result.get("execution_mode") or "").strip().lower() == "foreground_driver":
            result["execution_mode"] = "foreground_py"
    result.setdefault("foreground_py_backend", _DEFAULT_FOREGROUND_PY_BACKEND)
    return result


def _read_main_config() -> dict:
    global _CONFIG_CACHE_PATH, _CONFIG_CACHE_MTIME, _CONFIG_CACHE_DATA
    from app_core.config_store import load_config

    config_path = get_config_path()
    try:
        mtime = os.path.getmtime(config_path)
    except OSError:
        mtime = None

    if (
        _CONFIG_CACHE_PATH == config_path
        and _CONFIG_CACHE_MTIME == mtime
        and isinstance(_CONFIG_CACHE_DATA, dict)
        and _CONFIG_CACHE_DATA
    ):
        return _CONFIG_CACHE_DATA

    data = load_config()
    _CONFIG_CACHE_PATH = config_path
    _CONFIG_CACHE_MTIME = mtime
    _CONFIG_CACHE_DATA = data
    return data


def normalize_execution_mode(execution_mode: Optional[str]) -> str:
    if not execution_mode:
        return ""
    mode = execution_mode.strip().lower()
    if mode.startswith("foreground"):
        return "foreground"
    if mode.startswith("background"):
        return "background"
    return mode


def is_foreground_mode(execution_mode: Optional[str]) -> bool:
    return normalize_execution_mode(execution_mode) == "foreground"


def is_background_mode(execution_mode: Optional[str]) -> bool:
    return normalize_execution_mode(execution_mode) == "background"


def is_dx_input_mode(execution_mode: Optional[str]) -> bool:
    return str(execution_mode or "").strip().lower() in {"background_dx", "background_op_dx"}


def get_ibinputsimulator_config() -> Tuple[str, str, str, str]:
    config = _read_main_config()
    driver = normalize_ib_driver_name(config.get("ibinputsimulator_driver", _DEFAULT_IB_DRIVER))
    driver_arg = str(config.get("ibinputsimulator_driver_arg", "") or "").strip()
    ahk_path = str(config.get("ibinputsimulator_ahk_path", "") or "").strip()
    ahk_dir = str(config.get("ibinputsimulator_ahk_dir", "") or "").strip()
    return driver, driver_arg, ahk_path, ahk_dir


def get_foreground_driver(execution_mode: Optional[str]) -> str:
    mouse_backend, keyboard_backend = get_foreground_driver_backends(execution_mode)
    if mouse_backend == keyboard_backend:
        return mouse_backend
    return "mixed"


def get_foreground_driver_backends(execution_mode: Optional[str]) -> Tuple[str, str]:
    mode = (execution_mode or "").strip().lower()
    if mode == "foreground_py":
        backend = parse_foreground_py_backend(_read_main_config())
        return backend, backend
    return parse_foreground_backends(_read_main_config())


def requires_interception_driver(
    execution_mode: Optional[str],
    mouse_backend: Optional[str] = None,
    keyboard_backend: Optional[str] = None,
) -> bool:
    mode = (execution_mode or "").strip().lower()
    if mode == "foreground_py":
        return False
    if mode not in ("foreground_driver", "foreground"):
        return False

    if mouse_backend is None and keyboard_backend is None:
        resolved_mouse_backend, resolved_keyboard_backend = get_foreground_driver_backends(mode)
        return "interception" in (resolved_mouse_backend, resolved_keyboard_backend)

    resolved_mouse_backend = str(mouse_backend or "").strip().lower()
    resolved_keyboard_backend = str(keyboard_backend or "").strip().lower()
    return "interception" in (resolved_mouse_backend, resolved_keyboard_backend)
