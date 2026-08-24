# -*- coding: utf-8 -*-
"""
点击参数解析器
统一处理按钮、动作、次数、间隔、自动释放与按下持续时间。
"""

from __future__ import annotations
import random
from typing import Any, Dict, Optional, Tuple

from .task_utils import coerce_bool
from utils.input_timing import (
    DEFAULT_CLICK_HOLD_SECONDS,
    DEFAULT_DOUBLE_CLICK_INTERVAL_SECONDS,
    DEFAULT_RANDOM_CLICK_HOLD_MAX_SECONDS,
    DEFAULT_RANDOM_CLICK_HOLD_MIN_SECONDS,
)


_BUTTON_MAP = {
    "左键": "left",
    "右键": "right",
    "中键": "middle",
    "left": "left",
    "right": "right",
    "middle": "middle",
}

_ALLOWED_CLICK_ACTIONS = {"完整点击", "双击", "仅按下", "仅松开"}
_ACTION_ALIASES = {
    "按下": "仅按下",
    "松开": "仅松开",
    "弹起": "仅松开",
    "释放": "仅松开",
    "down": "仅按下",
    "up": "仅松开",
    "press": "仅按下",
    "release": "仅松开",
}


def _read_with_fallback(
    params: Dict[str, Any],
    primary_key: str,
    fallback_key: Optional[str],
    default_value: Any,
) -> Any:
    if primary_key in params:
        return params.get(primary_key, default_value)
    if fallback_key:
        return params.get(fallback_key, default_value)
    return default_value


def _log(logger_obj: Any, level: str, message: str) -> None:
    if logger_obj is None:
        return
    fn = getattr(logger_obj, level, None)
    if callable(fn):
        fn(message)


def safe_positive_int(value: Any, default: int = 1) -> int:
    try:
        result = int(value)
    except Exception:
        result = int(default)
    return result if result > 0 else int(default)


def safe_non_negative_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except Exception:
        result = float(default)
    return result if result >= 0 else float(default)


def normalize_button(button: Any, default: str = "left") -> str:
    text = str(button or "").strip().lower()
    return _BUTTON_MAP.get(text, default)


def normalize_click_action(click_action: Any, default: str = "完整点击") -> str:
    text = str(click_action or "").strip()
    alias = _ACTION_ALIASES.get(text)
    if alias:
        return alias
    alias_lower = _ACTION_ALIASES.get(text.lower())
    if alias_lower:
        return alias_lower
    return text if text in _ALLOWED_CLICK_ACTIONS else default


def resolve_click_params(
    params: Dict[str, Any],
    *,
    button_key: str,
    clicks_key: str,
    interval_key: str,
    action_key: str,
    fallback_action_key: Optional[str] = None,
    auto_release_key: str,
    hold_duration_key: str,
    fallback_button_key: Optional[str] = None,
    fallback_clicks_key: Optional[str] = None,
    fallback_interval_key: Optional[str] = None,
    hold_mode_key: Optional[str] = None,
    hold_min_key: Optional[str] = None,
    hold_max_key: Optional[str] = None,
    default_button: str = "左键",
    default_clicks: int = 1,
    default_interval: float = DEFAULT_DOUBLE_CLICK_INTERVAL_SECONDS,
    default_action: str = "完整点击",
    default_auto_release: bool = True,
    default_hold_duration: float = DEFAULT_CLICK_HOLD_SECONDS,
    default_hold_min: float = DEFAULT_RANDOM_CLICK_HOLD_MIN_SECONDS,
    default_hold_max: float = DEFAULT_RANDOM_CLICK_HOLD_MAX_SECONDS,
    mode_label: str = "点击",
    logger_obj: Any = None,
    log_hold_mode: bool = False,
) -> Tuple[str, int, float, str, bool, float]:
    button_raw = _read_with_fallback(params, button_key, fallback_button_key, default_button)
    clicks_raw = _read_with_fallback(params, clicks_key, fallback_clicks_key, default_clicks)
    interval_raw = _read_with_fallback(params, interval_key, fallback_interval_key, default_interval)

    button = normalize_button(button_raw, default="left")
    clicks = safe_positive_int(clicks_raw, default_clicks)
    interval = safe_non_negative_float(interval_raw, default_interval)

    action_raw = params.get(action_key)
    if isinstance(action_raw, str):
        action_raw = action_raw.strip()
    if action_raw in (None, "") and fallback_action_key:
        fallback_action_raw = params.get(fallback_action_key)
        if isinstance(fallback_action_raw, str):
            fallback_action_raw = fallback_action_raw.strip()
        if fallback_action_raw not in (None, ""):
            action_raw = fallback_action_raw
    if action_raw in (None, ""):
        action_raw = default_action
    click_action = normalize_click_action(action_raw, default_action)

    auto_release = coerce_bool(params.get(auto_release_key, default_auto_release))

    hold_duration = 0.0
    # 统一规则：仅按下 + 自动弹起 时，按“固定/随机持续时间”执行，
    # 且不受完整点击内置随机影响。
    if auto_release and click_action == "仅按下":
        if hold_mode_key and hold_min_key and hold_max_key:
            hold_mode = str(params.get(hold_mode_key, "固定持续时间") or "固定持续时间").strip()
            if hold_mode == "随机持续时间":
                hold_min = safe_non_negative_float(params.get(hold_min_key, default_hold_min), default_hold_min)
                hold_max = safe_non_negative_float(params.get(hold_max_key, default_hold_max), default_hold_max)
                if hold_max < hold_min:
                    hold_min, hold_max = hold_max, hold_min
                hold_duration = random.uniform(hold_min, hold_max)
                if log_hold_mode:
                    _log(
                        logger_obj,
                        "info",
                        f"[{mode_label}] 持续时间模式: 随机 ({hold_min:.2f}-{hold_max:.2f}秒)，实际: {hold_duration:.3f}秒",
                    )
            else:
                hold_duration = safe_non_negative_float(
                    params.get(hold_duration_key, default_hold_duration),
                    default_hold_duration,
                )
                if log_hold_mode:
                    _log(logger_obj, "info", f"[{mode_label}] 持续时间模式: 固定 ({hold_duration:.3f}秒)")
        else:
            hold_duration = safe_non_negative_float(
                params.get(hold_duration_key, default_hold_duration),
                default_hold_duration,
            )
            if log_hold_mode:
                _log(logger_obj, "info", f"[{mode_label}] 持续时间模式: 固定 ({hold_duration:.3f}秒)")

    return button, clicks, interval, click_action, auto_release, hold_duration
