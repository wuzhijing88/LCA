# -*- coding: utf-8 -*-

UNIT_SECONDS = "seconds"
UNIT_MINUTES = "minutes"
UNIT_HOURS = "hours"

DURATION_UNITS = (UNIT_SECONDS, UNIT_MINUTES, UNIT_HOURS)
INTERVAL_UNITS = (UNIT_MINUTES, UNIT_HOURS)
CHECK_INTERVAL_UNITS = (UNIT_SECONDS, UNIT_MINUTES)

_UNIT_ALIASES = {
    "seconds": UNIT_SECONDS,
    "second": UNIT_SECONDS,
    "s": UNIT_SECONDS,
    "sec": UNIT_SECONDS,
    "\u79d2": UNIT_SECONDS,
    "minutes": UNIT_MINUTES,
    "minute": UNIT_MINUTES,
    "min": UNIT_MINUTES,
    "m": UNIT_MINUTES,
    "\u5206\u949f": UNIT_MINUTES,
    "hours": UNIT_HOURS,
    "hour": UNIT_HOURS,
    "h": UNIT_HOURS,
    "hr": UNIT_HOURS,
    "\u5c0f\u65f6": UNIT_HOURS,
}

_UNIT_LABELS = {
    UNIT_SECONDS: "\u79d2",
    UNIT_MINUTES: "\u5206\u949f",
    UNIT_HOURS: "\u5c0f\u65f6",
}


def normalize_unit(value, default=UNIT_MINUTES, allowed=None):
    raw = str(value or "").strip()
    key = _UNIT_ALIASES.get(raw) or _UNIT_ALIASES.get(raw.lower())
    if key is None:
        key = default
    if allowed and key not in allowed:
        return default
    return key


def unit_label(value, default=UNIT_MINUTES) -> str:
    key = normalize_unit(value, default=default)
    return _UNIT_LABELS.get(key, _UNIT_LABELS[default])


def duration_to_seconds(value, unit: str) -> int:
    try:
        amount = max(1, int(value))
    except (TypeError, ValueError):
        amount = 1
    key = normalize_unit(unit, default=UNIT_SECONDS)
    if key == UNIT_HOURS:
        return amount * 3600
    if key == UNIT_MINUTES:
        return amount * 60
    return amount


def interval_to_seconds(value, unit: str) -> int:
    try:
        amount = max(1, int(value))
    except (TypeError, ValueError):
        amount = 1
    key = normalize_unit(unit, default=UNIT_MINUTES, allowed=INTERVAL_UNITS)
    if key == UNIT_HOURS:
        return amount * 3600
    return amount * 60
