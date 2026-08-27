# -*- coding: utf-8 -*-
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional

from .text import UNIT_MINUTES, duration_to_seconds, interval_to_seconds, normalize_unit, unit_label
from .models import (
    ACTION_PRIORITY,
    ACTION_START,
    ACTION_STOP,
    ACTION_TIMED_PAUSE,
    REPEAT_DAILY,
    REPEAT_ONCE,
    START_MODE_INTERVAL,
    ClockPolicy,
    ScheduleBundle,
    StartPolicy,
    TimedPausePolicy,
)

MAX_WAKE_SECONDS = 30


@dataclass
class ClockRuntime:
    executed: bool = False
    last_exec_date: Optional[datetime] = None
    next_fire_at: Optional[datetime] = None

    def reset(self) -> None:
        self.executed = False
        self.last_exec_date = None
        self.next_fire_at = None


def is_interval_start(policy: StartPolicy, allow_interval: bool) -> bool:
    return bool(allow_interval and policy.mode == START_MODE_INTERVAL)


def _as_date(value):
    if value is None:
        return None
    return value.date() if hasattr(value, "date") else value


def is_daily_due(now: datetime, hour: int, minute: int, executed: bool, last_exec_date) -> bool:
    if executed and _as_date(last_exec_date) == now.date():
        return False
    return now.hour == hour and now.minute == minute


def is_armed_due(now: datetime, next_fire_at: Optional[datetime]) -> bool:
    return next_fire_at is not None and now >= next_fire_at


def next_daily_fire(
    now: datetime,
    hour: int,
    minute: int,
    executed: bool,
    last_exec_date,
    repeat: str,
) -> Optional[datetime]:
    if repeat == REPEAT_ONCE and executed:
        return None
    today_slot = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    already_today = executed and _as_date(last_exec_date) == now.date()
    in_slot = now.hour == hour and now.minute == minute
    if in_slot and not already_today:
        return today_slot
    if already_today or (not in_slot and now >= today_slot):
        return today_slot + timedelta(days=1)
    return today_slot


def next_interval_fire(now: datetime, interval_seconds: int, next_fire_at: Optional[datetime]) -> datetime:
    if next_fire_at is None:
        return now + timedelta(seconds=max(60, int(interval_seconds)))
    return next_fire_at


def compute_next_fire(
    policy: ClockPolicy,
    runtime: ClockRuntime,
    now: datetime,
    *,
    allow_interval: bool = False,
) -> Optional[datetime]:
    if not policy.enabled:
        return None
    if isinstance(policy, StartPolicy) and is_interval_start(policy, allow_interval):
        return next_interval_fire(
            now,
            interval_to_seconds(policy.interval_value, policy.interval_unit),
            runtime.next_fire_at,
        )
    if runtime.next_fire_at is not None:
        return runtime.next_fire_at
    return next_daily_fire(
        now,
        policy.hour,
        policy.minute,
        runtime.executed,
        runtime.last_exec_date,
        policy.repeat,
    )


def arm_policy_runtime(
    policy: ClockPolicy,
    runtime: ClockRuntime,
    now: datetime,
    *,
    allow_interval: bool = False,
    force: bool = False,
) -> None:
    if not policy.enabled:
        if force:
            runtime.reset()
        return
    if isinstance(policy, StartPolicy) and is_interval_start(policy, allow_interval):
        if force or runtime.next_fire_at is None:
            runtime.next_fire_at = now + timedelta(
                seconds=interval_to_seconds(policy.interval_value, policy.interval_unit)
            )
        return
    if force or runtime.next_fire_at is None:
        runtime.next_fire_at = next_daily_fire(
            now,
            policy.hour,
            policy.minute,
            runtime.executed,
            runtime.last_exec_date,
            policy.repeat,
        )


def collect_due_actions(
    bundle: ScheduleBundle,
    runtimes: Dict[str, ClockRuntime],
    now: datetime,
    *,
    allow_interval_start: bool = False,
) -> List[str]:
    due: List[str] = []
    start_runtime = runtimes.get(ACTION_START) or ClockRuntime()
    if bundle.start.enabled:
        if is_interval_start(bundle.start, allow_interval_start):
            if is_armed_due(now, start_runtime.next_fire_at):
                due.append(ACTION_START)
        elif is_armed_due(now, start_runtime.next_fire_at) or (
            start_runtime.next_fire_at is None
            and is_daily_due(
                now,
                bundle.start.hour,
                bundle.start.minute,
                start_runtime.executed,
                start_runtime.last_exec_date,
            )
        ):
            due.append(ACTION_START)

    stop_runtime = runtimes.get(ACTION_STOP) or ClockRuntime()
    if bundle.stop.enabled and (
        is_armed_due(now, stop_runtime.next_fire_at)
        or (
            stop_runtime.next_fire_at is None
            and is_daily_due(
                now,
                bundle.stop.hour,
                bundle.stop.minute,
                stop_runtime.executed,
                stop_runtime.last_exec_date,
            )
        )
    ):
        due.append(ACTION_STOP)

    pause_runtime = runtimes.get(ACTION_TIMED_PAUSE) or ClockRuntime()
    if bundle.timed_pause.enabled and (
        is_armed_due(now, pause_runtime.next_fire_at)
        or (
            pause_runtime.next_fire_at is None
            and is_daily_due(
                now,
                bundle.timed_pause.hour,
                bundle.timed_pause.minute,
                pause_runtime.executed,
                pause_runtime.last_exec_date,
            )
        )
    ):
        due.append(ACTION_TIMED_PAUSE)
    return due


def arbitrate(due_actions: Iterable[str]) -> Optional[str]:
    actions = [action for action in due_actions if action in ACTION_PRIORITY]
    if not actions:
        return None
    return max(actions, key=lambda action: ACTION_PRIORITY[action])


def consume_action(
    action: str,
    policy: ClockPolicy,
    runtime: ClockRuntime,
    now: datetime,
    *,
    allow_interval: bool = False,
) -> bool:
    """Mark this minute/interval consumed. Return True if the policy should disable itself."""
    if isinstance(policy, StartPolicy) and is_interval_start(policy, allow_interval):
        runtime.next_fire_at = now + timedelta(
            seconds=interval_to_seconds(policy.interval_value, policy.interval_unit)
        )
        runtime.executed = False
        runtime.last_exec_date = now
        return False

    runtime.executed = True
    runtime.last_exec_date = now
    if policy.repeat == REPEAT_ONCE:
        policy.enabled = False
        runtime.next_fire_at = None
        return True
    runtime.next_fire_at = next_daily_fire(
        now,
        policy.hour,
        policy.minute,
        runtime.executed,
        runtime.last_exec_date,
        policy.repeat,
    )
    return False


def soonest_wake(
    bundle: ScheduleBundle,
    runtimes: Dict[str, ClockRuntime],
    now: datetime,
    *,
    allow_interval_start: bool = False,
) -> Optional[datetime]:
    candidates = []
    mapping = (
        (bundle.start, runtimes.get(ACTION_START) or ClockRuntime(), allow_interval_start),
        (bundle.stop, runtimes.get(ACTION_STOP) or ClockRuntime(), False),
        (bundle.timed_pause, runtimes.get(ACTION_TIMED_PAUSE) or ClockRuntime(), False),
    )
    for policy, runtime, allow_interval in mapping:
        nxt = compute_next_fire(policy, runtime, now, allow_interval=allow_interval)
        if nxt is not None:
            candidates.append(nxt)
    if not candidates:
        return None
    return min(candidates)


def wake_delay_ms(next_at: Optional[datetime], now: datetime, max_seconds: int = MAX_WAKE_SECONDS) -> int:
    if next_at is None:
        return 0
    delta_ms = int((next_at - now).total_seconds() * 1000)
    if delta_ms <= 0:
        return 1
    return min(delta_ms, max(1000, int(max_seconds) * 1000))


def format_clock_label(policy: ClockPolicy, *, allow_interval: bool = False) -> str:
    if isinstance(policy, StartPolicy) and is_interval_start(policy, allow_interval):
        return "\u6bcf{value}{unit}".format(
            value=policy.interval_value,
            unit=unit_label(policy.interval_unit, default=UNIT_MINUTES),
        )
    return f"{int(policy.hour):02d}:{int(policy.minute):02d}"


def format_next_fire(next_at: Optional[datetime]) -> str:
    if next_at is None:
        return ""
    return next_at.strftime("%H:%M")


class ScheduleEngine:
    def __init__(self, bundle: Optional[ScheduleBundle] = None, *, allow_interval_start: bool = False):
        self.allow_interval_start = allow_interval_start
        self.runtimes: Dict[str, ClockRuntime] = {
            ACTION_START: ClockRuntime(),
            ACTION_STOP: ClockRuntime(),
            ACTION_TIMED_PAUSE: ClockRuntime(),
        }
        self.bundle = bundle or ScheduleBundle()
        self._arm_clocks(datetime.now(), force=True)

    def replace_bundle(self, bundle: ScheduleBundle, now: Optional[datetime] = None) -> None:
        moment = now or datetime.now()
        # 未传入 now 表示按墙钟重载配置：钟点/间隔没变则保住下一格，避免点确定就重等或同分钟再打一次。
        # 测试传入 now 则按该时刻重新武装，不保留。
        keep = self._reusable_runtimes(bundle) if now is None else {}
        self.bundle = bundle
        for runtime in self.runtimes.values():
            runtime.reset()
        self._arm_clocks(moment, force=True)
        for action, snapshot in keep.items():
            runtime = self.runtimes[action]
            runtime.next_fire_at = snapshot[0]
            runtime.executed = snapshot[1]
            runtime.last_exec_date = snapshot[2]

    def _same_clock_policy(self, old: ClockPolicy, new: ClockPolicy, allow_interval: bool) -> bool:
        old_interval = isinstance(old, StartPolicy) and is_interval_start(old, allow_interval)
        new_interval = isinstance(new, StartPolicy) and is_interval_start(new, allow_interval)
        if old_interval != new_interval:
            return False
        if old.enabled != new.enabled:
            return False
        if old_interval:
            return (
                int(old.interval_value) == int(new.interval_value)
                and normalize_unit(old.interval_unit, default=UNIT_MINUTES)
                == normalize_unit(new.interval_unit, default=UNIT_MINUTES)
            )
        return (
            int(old.hour) == int(new.hour)
            and int(old.minute) == int(new.minute)
            and str(old.repeat) == str(new.repeat)
        )

    def _reusable_runtimes(self, new_bundle: ScheduleBundle) -> Dict[str, tuple]:
        keep: Dict[str, tuple] = {}
        mapping = (
            (ACTION_START, self.bundle.start, new_bundle.start, self.allow_interval_start),
            (ACTION_STOP, self.bundle.stop, new_bundle.stop, False),
            (ACTION_TIMED_PAUSE, self.bundle.timed_pause, new_bundle.timed_pause, False),
        )
        for action, old, new, allow_interval in mapping:
            if not self._same_clock_policy(old, new, allow_interval):
                continue
            runtime = self.runtimes[action]
            keep[action] = (runtime.next_fire_at, runtime.executed, runtime.last_exec_date)
        return keep

    def _arm_clocks(self, now: datetime, *, force: bool = False) -> None:
        mapping = (
            (self.bundle.start, self.runtimes[ACTION_START], self.allow_interval_start),
            (self.bundle.stop, self.runtimes[ACTION_STOP], False),
            (self.bundle.timed_pause, self.runtimes[ACTION_TIMED_PAUSE], False),
        )
        for policy, runtime, allow_interval in mapping:
            arm_policy_runtime(policy, runtime, now, allow_interval=allow_interval, force=force)

    def due_actions(self, now: datetime) -> List[str]:
        return collect_due_actions(
            self.bundle,
            self.runtimes,
            now,
            allow_interval_start=self.allow_interval_start,
        )

    def take_due(self, now: datetime) -> Optional[str]:
        due = self.due_actions(now)
        winner = arbitrate(due)
        for action in due:
            policy = self.policy_for(action)
            runtime = self.runtimes[action]
            consume_action(
                action,
                policy,
                runtime,
                now,
                allow_interval=self.allow_interval_start and action == ACTION_START,
            )
        return winner

    def policy_for(self, action: str) -> ClockPolicy:
        if action == ACTION_START:
            return self.bundle.start
        if action == ACTION_STOP:
            return self.bundle.stop
        if action == ACTION_TIMED_PAUSE:
            return self.bundle.timed_pause
        raise KeyError(action)

    def next_wake(self, now: datetime) -> Optional[datetime]:
        return soonest_wake(
            self.bundle,
            self.runtimes,
            now,
            allow_interval_start=self.allow_interval_start,
        )

    def next_fire_for(self, action: str, now: datetime) -> Optional[datetime]:
        policy = self.policy_for(action)
        allow_interval = self.allow_interval_start and action == ACTION_START
        return compute_next_fire(policy, self.runtimes[action], now, allow_interval=allow_interval)
