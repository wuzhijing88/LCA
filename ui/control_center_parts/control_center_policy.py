from __future__ import annotations

from typing import Any, Mapping, Optional

from utils.capture.engine_ids import (
    is_supported_screenshot_engine,
    normalize_screenshot_engine,
)

DEFAULT_CONTROL_CENTER_SCREENSHOT_ENGINE = "wgc"

CONTROL_CENTER_FOREGROUND_BLOCK_MESSAGE = (
    "前台模式不能使用中控。\n\n"
    "中控会同时操作多个窗口，前台键鼠会互相抢焦点。\n"
    "请在全局设置中将执行模式改为后台后再打开中控。"
)


def control_center_allows_execution_mode(mode: Optional[str]) -> bool:
    return not str(mode or "").strip().lower().startswith("foreground")


def resolve_control_center_execution_mode(
    source: Any = None,
    *,
    config: Optional[Mapping[str, Any]] = None,
) -> str:
    if isinstance(source, str) and source.strip():
        return source.strip()
    if source is not None:
        current = getattr(source, "current_execution_mode", None)
        if str(current or "").strip():
            return str(current).strip()
        getter = getattr(source, "_get_configured_execution_mode", None)
        if callable(getter):
            try:
                configured = getter()
            except Exception:
                configured = None
            if str(configured or "").strip():
                return str(configured).strip()
        parent = getattr(source, "parent_window", None)
        if parent is not None and parent is not source:
            return resolve_control_center_execution_mode(parent, config=config)
        parent_config = getattr(source, "config", None)
        if isinstance(parent_config, Mapping):
            config = parent_config
        elif callable(getattr(source, "_get_parent_config", None)):
            try:
                config = source._get_parent_config()
            except Exception:
                config = config
    if isinstance(config, Mapping):
        return str(config.get("execution_mode") or "").strip()
    return ""


def resolve_control_center_screenshot_engine(
    source: Any = None,
    *,
    config: Optional[Mapping[str, Any]] = None,
) -> str:
    candidates: list[Any] = []
    if isinstance(source, str):
        candidates.append(source)
    elif source is not None:
        runtime = getattr(source, "_runtime_config", None)
        if isinstance(runtime, Mapping):
            candidates.append(runtime.get("screenshot_engine"))
        getter = getattr(source, "_get_parent_config", None)
        if callable(getter):
            try:
                parent_config = getter()
            except Exception:
                parent_config = None
            if isinstance(parent_config, Mapping):
                candidates.append(parent_config.get("screenshot_engine"))
        parent = getattr(source, "parent_window", None)
        if parent is not None and parent is not source:
            parent_cfg = getattr(parent, "config", None)
            if isinstance(parent_cfg, Mapping):
                candidates.append(parent_cfg.get("screenshot_engine"))
    if isinstance(config, Mapping):
        candidates.append(config.get("screenshot_engine"))

    for raw in candidates:
        engine = normalize_screenshot_engine(raw)
        if is_supported_screenshot_engine(engine):
            return engine
    return DEFAULT_CONTROL_CENTER_SCREENSHOT_ENGINE
