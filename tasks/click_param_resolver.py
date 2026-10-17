# -*- coding: utf-8 -*-
"""
点击参数解析器
统一处理按钮、动作、次数、间隔、自动释放与按下持续时间。
"""

from __future__ import annotations
import random
import math
from typing import Any, Dict, Optional, Tuple

from utils.input.input_timing import (
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


def _log(logger_obj: Any, level: str, message: str) -> None:
    if logger_obj is None:
        return
    fn = getattr(logger_obj, level, None)
    if callable(fn):
        fn(message)


def safe_integer(value: Any) -> int:
    result = int(value)
    if isinstance(value, bool) or result != float(value):
        raise ValueError("输入参数必须是整数")
    return result


def safe_positive_int(value: Any) -> int:
    result = safe_integer(value)
    if result <= 0:
        raise ValueError("点击次数必须是正整数")
    return result


def safe_non_negative_float(value: Any) -> float:
    result = float(value)
    if isinstance(value, bool) or not math.isfinite(result) or result < 0:
        raise ValueError("点击时间必须是非负有限数值")
    return result


def normalize_button(button: Any) -> str:
    text = str(button).strip().lower()
    if text not in _BUTTON_MAP:
        raise ValueError(f"不支持的鼠标按钮：{button!r}")
    return _BUTTON_MAP[text]


def normalize_click_action(click_action: Any) -> str:
    if not isinstance(click_action, str) or click_action not in _ALLOWED_CLICK_ACTIONS:
        raise ValueError(f"不支持的点击动作：{click_action!r}")
    return click_action


def resolve_click_params(
    params: Dict[str, Any],
    *,
    button_key: str,
    clicks_key: str,
    interval_key: str,
    action_key: str,
    auto_release_key: str,
    hold_duration_key: str,
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
    button = normalize_button(params.get(button_key, default_button))
    clicks = safe_positive_int(params.get(clicks_key, default_clicks))
    interval = safe_non_negative_float(params.get(interval_key, default_interval))
    click_action = normalize_click_action(params.get(action_key, default_action))
    auto_release = params.get(auto_release_key, default_auto_release)
    if not isinstance(auto_release, bool):
        raise ValueError("自动弹起参数必须是布尔值")

    hold_duration = 0.0
    # 统一规则：仅按下 + 自动弹起 时，按“固定/随机持续时间”执行，
    # 且不受完整点击内置随机影响。
    if auto_release and click_action == "仅按下":
        if hold_mode_key and hold_min_key and hold_max_key:
            hold_mode = params.get(hold_mode_key, "固定持续时间")
            if hold_mode == "随机持续时间":
                hold_min = safe_non_negative_float(params.get(hold_min_key, default_hold_min))
                hold_max = safe_non_negative_float(params.get(hold_max_key, default_hold_max))
                if hold_max < hold_min:
                    raise ValueError("随机持续时间的最大值不能小于最小值")
                hold_duration = random.uniform(hold_min, hold_max)
                if log_hold_mode:
                    _log(
                        logger_obj,
                        "info",
                        f"[{mode_label}] 持续时间模式: 随机 ({hold_min:.2f}-{hold_max:.2f}秒)，实际: {hold_duration:.3f}秒",
                    )
            elif hold_mode == "固定持续时间":
                hold_duration = safe_non_negative_float(
                    params.get(hold_duration_key, default_hold_duration),
                )
                if log_hold_mode:
                    _log(logger_obj, "info", f"[{mode_label}] 持续时间模式: 固定 ({hold_duration:.3f}秒)")
            else:
                raise ValueError(f"不支持的持续时间模式：{hold_mode!r}")
        else:
            hold_duration = safe_non_negative_float(
                params.get(hold_duration_key, default_hold_duration),
            )
            if log_hold_mode:
                _log(logger_obj, "info", f"[{mode_label}] 持续时间模式: 固定 ({hold_duration:.3f}秒)")

    return button, clicks, interval, click_action, auto_release, hold_duration
