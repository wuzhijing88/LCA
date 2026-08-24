# -*- coding: utf-8 -*-
from dataclasses import dataclass, field
from typing import List

from .text import CHECK_INTERVAL_UNITS, DURATION_UNITS, INTERVAL_UNITS, UNIT_MINUTES, UNIT_SECONDS

ACTION_START = "start"
ACTION_STOP = "stop"
ACTION_TIMED_PAUSE = "timed_pause"
ACTION_RANDOM_PAUSE = "random_pause"

REPEAT_ONCE = "once"
REPEAT_DAILY = "daily"

START_MODE_DAILY = "daily"
START_MODE_INTERVAL = "interval"

ACTION_PRIORITY = {
    ACTION_START: 1,
    ACTION_TIMED_PAUSE: 2,
    ACTION_STOP: 3,
}

MAIN_SCHEDULE_KEY = "main_schedule"
CONTROL_SCHEDULE_KEY = "control_schedule"

__all__ = [
    "ACTION_PRIORITY",
    "ACTION_RANDOM_PAUSE",
    "ACTION_START",
    "ACTION_STOP",
    "ACTION_TIMED_PAUSE",
    "CHECK_INTERVAL_UNITS",
    "CONTROL_SCHEDULE_KEY",
    "DURATION_UNITS",
    "INTERVAL_UNITS",
    "MAIN_SCHEDULE_KEY",
    "REPEAT_DAILY",
    "REPEAT_ONCE",
    "START_MODE_DAILY",
    "START_MODE_INTERVAL",
    "ClockPolicy",
    "RandomPausePolicy",
    "ScheduleBundle",
    "StartPolicy",
    "TimedPausePolicy",
]


@dataclass
class ClockPolicy:
    enabled: bool = False
    hour: int = 9
    minute: int = 0
    repeat: str = REPEAT_DAILY
    window_ids: List[str] = field(default_factory=list)


@dataclass
class StartPolicy(ClockPolicy):
    mode: str = START_MODE_DAILY
    interval_value: int = 30
    interval_unit: str = UNIT_MINUTES


@dataclass
class TimedPausePolicy(ClockPolicy):
    hour: int = 12
    duration_value: int = 10
    duration_unit: str = UNIT_MINUTES


@dataclass
class RandomPausePolicy:
    enabled: bool = False
    probability: int = 20
    check_interval_value: int = 30
    check_interval_unit: str = UNIT_SECONDS
    min_value: int = 60
    min_unit: str = UNIT_SECONDS
    max_value: int = 120
    max_unit: str = UNIT_SECONDS
    window_ids: List[str] = field(default_factory=list)


@dataclass
class ScheduleBundle:
    start: StartPolicy = field(default_factory=StartPolicy)
    stop: ClockPolicy = field(default_factory=lambda: ClockPolicy(hour=17, minute=0))
    timed_pause: TimedPausePolicy = field(default_factory=TimedPausePolicy)
    random_pause: RandomPausePolicy = field(default_factory=RandomPausePolicy)

    def any_clock_enabled(self) -> bool:
        return bool(self.start.enabled or self.stop.enabled or self.timed_pause.enabled)
