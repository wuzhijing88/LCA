# -*- coding: utf-8 -*-
from typing import Any, Mapping

from .text import (
    CHECK_INTERVAL_UNITS,
    DURATION_UNITS,
    INTERVAL_UNITS,
    UNIT_MINUTES,
    UNIT_SECONDS,
    normalize_unit,
)
from .models import (
    CONTROL_SCHEDULE_KEY,
    MAIN_SCHEDULE_KEY,
    REPEAT_DAILY,
    REPEAT_ONCE,
    START_MODE_DAILY,
    START_MODE_INTERVAL,
    ClockPolicy,
    RandomPausePolicy,
    ScheduleBundle,
    StartPolicy,
    TimedPausePolicy,
)

OLD_SCHEDULE_KEYS = (
    "timer_enabled",
    "stop_hour",
    "stop_minute",
    "stop_repeat",
    "enable_schedule",
    "schedule_mode",
    "schedule_hour",
    "schedule_minute",
    "schedule_repeat",
    "schedule_interval_value",
    "schedule_interval_unit",
    "timed_pause_enabled",
    "timed_pause_hour",
    "timed_pause_minute",
    "timed_pause_repeat",
    "timed_pause_duration_value",
    "timed_pause_duration_unit",
    "pause_enabled",
    "pause_probability",
    "pause_check_interval",
    "pause_check_interval_unit",
    "pause_min_value",
    "pause_min_unit",
    "pause_max_value",
    "pause_max_unit",
    "cc_schedule_enabled",
    "cc_schedule_hour",
    "cc_schedule_minute",
    "cc_schedule_repeat",
    "cc_schedule_window_ids",
    "cc_stop_enabled",
    "cc_stop_hour",
    "cc_stop_minute",
    "cc_stop_repeat",
    "cc_stop_window_ids",
    "cc_timed_pause_enabled",
    "cc_timed_pause_hour",
    "cc_timed_pause_minute",
    "cc_timed_pause_repeat",
    "cc_timed_pause_duration_value",
    "cc_timed_pause_duration_unit",
    "cc_timed_pause_window_ids",
    "cc_random_pause_enabled",
    "cc_random_pause_window_ids",
    "cc_pause_probability",
    "cc_pause_check_interval",
    "cc_pause_check_interval_unit",
    "cc_pause_min_value",
    "cc_pause_min_unit",
    "cc_pause_max_value",
    "cc_pause_max_unit",
)


def _coerce_bool(value, default=False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


def _coerce_int(value, default: int, min_value: int, max_value: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = int(default)
    return max(min_value, min(max_value, parsed))


def _normalize_repeat(value, default: str = REPEAT_DAILY) -> str:
    mode = str(value or "").strip().lower()
    if mode not in {REPEAT_ONCE, REPEAT_DAILY}:
        return default
    return mode


def _normalize_unit(value, allowed, default: str) -> str:
    return normalize_unit(value, default=default, allowed=allowed)


def normalize_window_ids(value) -> list:
    if value is None:
        return []
    if isinstance(value, bool):
        return []
    if isinstance(value, (str, int)):
        raw_items = [value]
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        return []

    normalized = []
    seen = set()
    for item in raw_items:
        window_id = str(item).strip()
        if not window_id:
            continue
        lowered = window_id.lower()
        if lowered in {"false", "none", "null", "no", "否", "0", "all", "全部"}:
            continue
        try:
            canonical = str(int(window_id))
        except (TypeError, ValueError):
            canonical = window_id
        if canonical in seen:
            continue
        seen.add(canonical)
        normalized.append(canonical)
    return normalized


def default_main_bundle() -> ScheduleBundle:
    return ScheduleBundle()


def default_control_bundle() -> ScheduleBundle:
    return ScheduleBundle()


def default_main_schedule_dict() -> dict:
    return dump_bundle(default_main_bundle(), include_windows=False)


def default_control_schedule_dict() -> dict:
    return dump_bundle(default_control_bundle(), include_windows=True)


def _parse_clock(data: Any, defaults: ClockPolicy) -> ClockPolicy:
    if not isinstance(data, Mapping):
        return ClockPolicy(
            enabled=defaults.enabled,
            hour=defaults.hour,
            minute=defaults.minute,
            repeat=defaults.repeat,
            window_ids=list(defaults.window_ids),
        )
    return ClockPolicy(
        enabled=_coerce_bool(data.get("enabled"), defaults.enabled),
        hour=_coerce_int(data.get("hour"), defaults.hour, 0, 23),
        minute=_coerce_int(data.get("minute"), defaults.minute, 0, 59),
        repeat=_normalize_repeat(data.get("repeat"), defaults.repeat),
        window_ids=normalize_window_ids(data.get("window_ids", defaults.window_ids)),
    )


def _parse_start(data: Any, defaults: StartPolicy, allow_interval: bool) -> StartPolicy:
    clock = _parse_clock(data, defaults)
    if not isinstance(data, Mapping):
        mode = START_MODE_DAILY
        interval_value = defaults.interval_value
        interval_unit = defaults.interval_unit
    else:
        raw_mode = str(data.get("mode") or defaults.mode or START_MODE_DAILY).strip().lower()
        mode = START_MODE_INTERVAL if raw_mode == START_MODE_INTERVAL else START_MODE_DAILY
        if not allow_interval:
            mode = START_MODE_DAILY
        interval_value = _coerce_int(data.get("interval_value"), defaults.interval_value, 1, 999999)
        interval_unit = _normalize_unit(data.get("interval_unit"), INTERVAL_UNITS, defaults.interval_unit)
    return StartPolicy(
        enabled=clock.enabled,
        hour=clock.hour,
        minute=clock.minute,
        repeat=clock.repeat,
        window_ids=clock.window_ids,
        mode=mode,
        interval_value=interval_value,
        interval_unit=interval_unit,
    )


def _parse_timed_pause(data: Any, defaults: TimedPausePolicy) -> TimedPausePolicy:
    clock = _parse_clock(data, defaults)
    if not isinstance(data, Mapping):
        duration_value = defaults.duration_value
        duration_unit = defaults.duration_unit
    else:
        duration_value = _coerce_int(data.get("duration_value"), defaults.duration_value, 1, 999999)
        duration_unit = _normalize_unit(data.get("duration_unit"), DURATION_UNITS, defaults.duration_unit)
    return TimedPausePolicy(
        enabled=clock.enabled,
        hour=clock.hour,
        minute=clock.minute,
        repeat=clock.repeat,
        window_ids=clock.window_ids,
        duration_value=duration_value,
        duration_unit=duration_unit,
    )


def _parse_random_pause(data: Any, defaults: RandomPausePolicy) -> RandomPausePolicy:
    if not isinstance(data, Mapping):
        return RandomPausePolicy()
    return RandomPausePolicy(
        enabled=_coerce_bool(data.get("enabled"), defaults.enabled),
        probability=_coerce_int(data.get("probability"), defaults.probability, 0, 100),
        check_interval_value=_coerce_int(
            data.get("check_interval_value"), defaults.check_interval_value, 1, 86400
        ),
        check_interval_unit=_normalize_unit(
            data.get("check_interval_unit"), CHECK_INTERVAL_UNITS, defaults.check_interval_unit
        ),
        min_value=_coerce_int(data.get("min_value"), defaults.min_value, 1, 86400),
        min_unit=_normalize_unit(data.get("min_unit"), DURATION_UNITS, defaults.min_unit),
        max_value=_coerce_int(data.get("max_value"), defaults.max_value, 1, 86400),
        max_unit=_normalize_unit(data.get("max_unit"), DURATION_UNITS, defaults.max_unit),
        window_ids=normalize_window_ids(data.get("window_ids", defaults.window_ids)),
    )


def load_bundle(data: Any, *, allow_interval_start: bool = False) -> ScheduleBundle:
    defaults = ScheduleBundle()
    if not isinstance(data, Mapping):
        bundle = ScheduleBundle()
        if not allow_interval_start:
            bundle.start.mode = START_MODE_DAILY
        return bundle
    start = _parse_start(data.get("start"), defaults.start, allow_interval_start)
    stop = _parse_clock(data.get("stop"), defaults.stop)
    timed_pause = _parse_timed_pause(data.get("timed_pause"), defaults.timed_pause)
    random_pause = _parse_random_pause(data.get("random_pause"), defaults.random_pause)
    return ScheduleBundle(start=start, stop=stop, timed_pause=timed_pause, random_pause=random_pause)


def dump_bundle(bundle: ScheduleBundle, *, include_windows: bool = True) -> dict:
    def clock_dict(policy: ClockPolicy, extra=None):
        payload = {
            "enabled": bool(policy.enabled),
            "hour": int(policy.hour),
            "minute": int(policy.minute),
            "repeat": policy.repeat,
        }
        if include_windows:
            payload["window_ids"] = list(policy.window_ids)
        if extra:
            payload.update(extra)
        return payload

    start_extra = {
        "mode": bundle.start.mode,
        "interval_value": int(bundle.start.interval_value),
        "interval_unit": _normalize_unit(bundle.start.interval_unit, INTERVAL_UNITS, UNIT_MINUTES),
    }
    return {
        "start": clock_dict(bundle.start, start_extra),
        "stop": clock_dict(bundle.stop),
        "timed_pause": clock_dict(
            bundle.timed_pause,
            {
                "duration_value": int(bundle.timed_pause.duration_value),
                "duration_unit": _normalize_unit(
                    bundle.timed_pause.duration_unit, DURATION_UNITS, UNIT_MINUTES
                ),
            },
        ),
        "random_pause": {
            "enabled": bool(bundle.random_pause.enabled),
            "probability": int(bundle.random_pause.probability),
            "check_interval_value": int(bundle.random_pause.check_interval_value),
            "check_interval_unit": _normalize_unit(
                bundle.random_pause.check_interval_unit, CHECK_INTERVAL_UNITS, UNIT_SECONDS
            ),
            "min_value": int(bundle.random_pause.min_value),
            "min_unit": _normalize_unit(bundle.random_pause.min_unit, DURATION_UNITS, UNIT_SECONDS),
            "max_value": int(bundle.random_pause.max_value),
            "max_unit": _normalize_unit(bundle.random_pause.max_unit, DURATION_UNITS, UNIT_SECONDS),
            **({"window_ids": list(bundle.random_pause.window_ids)} if include_windows else {}),
        },
    }


def apply_schedule_schema(config: dict) -> dict:
    for key in OLD_SCHEDULE_KEYS:
        config.pop(key, None)
    config[MAIN_SCHEDULE_KEY] = dump_bundle(
        load_bundle(config.get(MAIN_SCHEDULE_KEY), allow_interval_start=False),
        include_windows=False,
    )
    config[CONTROL_SCHEDULE_KEY] = dump_bundle(
        load_bundle(config.get(CONTROL_SCHEDULE_KEY), allow_interval_start=True),
        include_windows=True,
    )
    return config


def load_main_bundle(config: Mapping) -> ScheduleBundle:
    return load_bundle((config or {}).get(MAIN_SCHEDULE_KEY), allow_interval_start=False)


def load_control_bundle(config: Mapping) -> ScheduleBundle:
    return load_bundle((config or {}).get(CONTROL_SCHEDULE_KEY), allow_interval_start=True)


def write_main_bundle(config: dict, bundle: ScheduleBundle) -> None:
    config[MAIN_SCHEDULE_KEY] = dump_bundle(bundle, include_windows=False)


def write_control_bundle(config: dict, bundle: ScheduleBundle) -> None:
    config[CONTROL_SCHEDULE_KEY] = dump_bundle(bundle, include_windows=True)
