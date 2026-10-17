"""Helpers for normalizing execution modes in native input paths."""

from collections.abc import Mapping
from typing import Optional, Tuple

SUPPORTED_IB_DRIVERS = {
    "Logitech",
    "Razer",
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
    if driver not in SUPPORTED_IB_DRIVERS:
        raise ValueError(f"不支持的 IbInputSimulator 驱动: {driver!r}")
    return driver


def _normalize_backend_token(value: object) -> str:
    return str(value).strip().lower()


def require_foreground_backend(value: object) -> str:
    backend = _normalize_backend_token(value)
    if backend not in SUPPORTED_FOREGROUND_BACKENDS:
        raise ValueError(f"不支持的前台驱动: {value!r}")
    return backend


def require_foreground_py_backend(value: object) -> str:
    backend = _normalize_backend_token(value)
    if backend not in SUPPORTED_FOREGROUND_PY_BACKENDS:
        raise ValueError(f"不支持的前台二输入方式: {value!r}")
    return backend


def parse_foreground_backends(config: Optional[Mapping] = None) -> Tuple[str, str]:
    values = dict(config or {})
    mouse_raw = values.get("foreground_mouse_driver_backend", _DEFAULT_FOREGROUND_BACKEND)
    keyboard_raw = values.get("foreground_keyboard_driver_backend", _DEFAULT_FOREGROUND_BACKEND)
    return (
        require_foreground_backend(mouse_raw),
        require_foreground_backend(keyboard_raw),
    )


def parse_foreground_py_backend(config: Optional[Mapping] = None) -> str:
    values = dict(config or {})
    raw = values.get("foreground_py_backend", _DEFAULT_FOREGROUND_PY_BACKEND)
    return require_foreground_py_backend(raw)


def _read_main_config() -> dict:
    """Always read through the process-wide provider; config_store caches by file signature."""
    from utils.runtime_config import get_runtime_config

    return get_runtime_config()


def parse_background_options(config: Mapping) -> Tuple[bool, bool]:
    """读取原生后台输入选项；显式无效值直接报错。"""
    values = tuple(config.get(key, False) for key in (
        "background_hierarchy_broadcast", "background_fake_active"
    ))
    if any(not isinstance(value, bool) for value in values):
        raise ValueError("层级广播和后台假激活配置必须是布尔值")
    return values


def physical_mouse_block_targets(config: Mapping, hwnd: int, execution_mode: str) -> tuple:
    """关闭或非原生后台时不读取绑定列表，也不进入屏蔽组件。"""
    enabled = config.get("background_block_physical_mouse", False)
    if not isinstance(enabled, bool):
        raise ValueError("屏蔽物理鼠标配置必须是布尔值")
    if not enabled or execution_mode not in {"background_sendmessage", "background_postmessage"}:
        return ()
    if is_plugin_input_backend(config):
        return ()
    from utils.window.hwnd_utils import as_hwnd

    windows = config.get("bound_windows", [])
    if not isinstance(windows, list):
        raise ValueError("屏蔽物理鼠标的绑定窗口必须是列表")
    targets = set()
    for window in windows:
        if not isinstance(window, dict):
            raise ValueError("屏蔽物理鼠标的绑定窗口记录必须是字典")
        active = window.get("enabled", True)
        if not isinstance(active, bool):
            raise ValueError("屏蔽物理鼠标的绑定窗口启用状态必须是布尔值")
        if active:
            target = as_hwnd(window.get("hwnd"))
            if not target:
                raise ValueError("屏蔽物理鼠标的绑定窗口句柄无效")
            targets.add(target)
    if as_hwnd(hwnd) not in targets:
        raise ValueError("屏蔽物理鼠标仅允许向已启用的绑定窗口输入")
    return tuple(sorted(targets))


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


def is_plugin_input_backend(config: Optional[Mapping] = None) -> bool:
    values = dict(_read_main_config() if config is None else config)
    backend = values.get("input_backend")
    if backend not in {"native", "plugin"}:
        raise ValueError(f"输入后端缺失或无效：{backend!r}")
    return backend == "plugin"


# 大漠绑定后按窗口客户区坐标后台收发消息，前台驱动/激活/屏幕坐标换算都不适用
PLUGIN_EXECUTION_MODE = "background_sendmessage"


def resolve_execution_mode(config: Optional[Mapping] = None) -> str:
    """配置里的执行模式经插件后端归一：键鼠走插件时任何前台模式都按后台执行。"""
    values = dict(config or {})
    mode = str(values.get("execution_mode") or "").strip()
    if is_plugin_input_backend(values) and is_foreground_mode(mode):
        return PLUGIN_EXECUTION_MODE
    return mode


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
