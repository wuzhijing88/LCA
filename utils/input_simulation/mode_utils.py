"""
Helpers for normalizing execution modes in native input paths.
"""

import json
import os
import re
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


def normalize_ib_driver_name(driver: Optional[str]) -> str:
    raw = str(driver or "").strip()
    if raw in SUPPORTED_IB_DRIVERS:
        return raw
    if not raw:
        return "Logitech"
    key = re.sub(r"[\s_\-]+", "", raw).lower()
    return _IB_DRIVER_ALIASES.get(key, "Logitech")

SUPPORTED_FOREGROUND_BACKENDS = {
    "interception",
    "ibinputsimulator",
}


def _normalize_foreground_backend(value: Optional[str], default: str = "interception") -> str:
    backend = str(value or default).strip().lower()
    if backend not in SUPPORTED_FOREGROUND_BACKENDS:
        return default
    return backend


def _read_main_config() -> dict:
    global _CONFIG_CACHE_PATH, _CONFIG_CACHE_MTIME, _CONFIG_CACHE_DATA

    config_path = get_config_path()
    if not config_path:
        return {}

    try:
        mtime = os.path.getmtime(config_path)
    except Exception:
        return {}

    if (
        _CONFIG_CACHE_PATH == config_path
        and _CONFIG_CACHE_MTIME == mtime
        and isinstance(_CONFIG_CACHE_DATA, dict)
    ):
        return _CONFIG_CACHE_DATA

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                data = {}
    except Exception:
        data = {}

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


def get_ibinputsimulator_config() -> Tuple[str, str, str, str]:
    config = _read_main_config()

    driver = normalize_ib_driver_name(config.get("ibinputsimulator_driver", "Logitech"))

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
        return "pyautogui", "pyautogui"

    if mode in ("foreground_driver", "foreground"):
        config = _read_main_config()
        legacy_backend = _normalize_foreground_backend(
            config.get("foreground_driver_backend", "interception"),
            default="interception",
        )
        mouse_backend = _normalize_foreground_backend(
            config.get("foreground_mouse_driver_backend", legacy_backend),
            default=legacy_backend,
        )
        keyboard_backend = _normalize_foreground_backend(
            config.get("foreground_keyboard_driver_backend", legacy_backend),
            default=legacy_backend,
        )
        return mouse_backend, keyboard_backend

    return "interception", "interception"


def requires_interception_driver(
    execution_mode: Optional[str],
    mouse_backend: Optional[str] = None,
    keyboard_backend: Optional[str] = None,
) -> bool:
    mode = (execution_mode or "").strip().lower()
    if mode == "interception":
        return True
    if mode == "foreground_py":
        return False
    if mode not in ("foreground_driver", "foreground"):
        return False

    if mouse_backend is None and keyboard_backend is None:
        resolved_mouse_backend, resolved_keyboard_backend = get_foreground_driver_backends(mode)
        return "interception" in (resolved_mouse_backend, resolved_keyboard_backend)

    base_backend = str(mouse_backend or keyboard_backend or "interception").strip().lower()
    resolved_mouse_backend = str(mouse_backend or base_backend).strip().lower()
    resolved_keyboard_backend = str(keyboard_backend or base_backend).strip().lower()
    return "interception" in (resolved_mouse_backend, resolved_keyboard_backend)
