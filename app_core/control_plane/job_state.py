from enum import Enum
from typing import Any, Iterable, Optional


class JobState(Enum):
    """中控作业状态。暂停是一等状态，不是执行器上的临时标记。"""

    UNASSIGNED = "未分配"
    READY = "就绪"
    IDLE = "等待开始"
    STARTING = "正在启动"
    RUNNING = "正在运行"
    PAUSED = "已暂停"
    STOPPING = "正在停止"
    STOPPED = "已中断"
    COMPLETED = "已完成"
    FAILED = "执行失败"


ACTIVE_JOB_STATES = frozenset(
    {
        JobState.IDLE,
        JobState.STARTING,
        JobState.RUNNING,
        JobState.PAUSED,
        JobState.STOPPING,
    }
)

TERMINAL_JOB_STATES = frozenset(
    {
        JobState.STOPPED,
        JobState.COMPLETED,
        JobState.FAILED,
    }
)

RESTARTABLE_JOB_STATES = frozenset(
    {
        JobState.READY,
        JobState.STOPPED,
        JobState.COMPLETED,
        JobState.FAILED,
    }
)

JOB_TRANSITIONS = {
    JobState.UNASSIGNED: {JobState.READY},
    JobState.READY: {JobState.UNASSIGNED, JobState.IDLE, JobState.STARTING},
    JobState.IDLE: {JobState.STARTING, JobState.STOPPED, JobState.READY, JobState.FAILED},
    JobState.STARTING: {JobState.RUNNING, JobState.FAILED, JobState.STOPPING, JobState.STOPPED},
    JobState.RUNNING: {
        JobState.PAUSED,
        JobState.STOPPING,
        JobState.COMPLETED,
        JobState.FAILED,
        JobState.STOPPED,
    },
    JobState.PAUSED: {JobState.RUNNING, JobState.STOPPING, JobState.STOPPED, JobState.FAILED},
    JobState.STOPPING: {JobState.STOPPED, JobState.FAILED},
    JobState.STOPPED: {JobState.IDLE, JobState.STARTING, JobState.READY, JobState.UNASSIGNED},
    JobState.COMPLETED: {JobState.IDLE, JobState.STARTING, JobState.READY, JobState.UNASSIGNED},
    JobState.FAILED: {JobState.IDLE, JobState.STARTING, JobState.READY, JobState.UNASSIGNED},
}

DEFAULT_JOB_STEPS = {
    JobState.UNASSIGNED: "请先分配工作流",
    JobState.READY: "等待开始",
    JobState.IDLE: "工作流已加入调度队列",
    JobState.STARTING: "正在启动工作流",
    JobState.RUNNING: "工作流运行中",
    JobState.PAUSED: "工作流已暂停",
    JobState.STOPPING: "正在停止工作流",
    JobState.STOPPED: "工作流已中断",
    JobState.COMPLETED: "工作流已完成",
    JobState.FAILED: "工作流执行失败",
}

_STATUS_ALIASES = {
    "未分配": JobState.UNASSIGNED,
    "就绪": JobState.READY,
    "等待开始": JobState.IDLE,
    "正在启动": JobState.STARTING,
    "正在运行": JobState.RUNNING,
    "暂停中": JobState.PAUSED,
    "已暂停": JobState.PAUSED,
    "正在停止": JobState.STOPPING,
    "已中断": JobState.STOPPED,
    "已完成": JobState.COMPLETED,
    "完成": JobState.COMPLETED,
    "失败": JobState.FAILED,
    "执行失败": JobState.FAILED,
}


def can_transition(current: JobState, new_state: JobState) -> bool:
    if current == new_state:
        return True
    return new_state in JOB_TRANSITIONS.get(current, set())


def parse_job_state(value: Any) -> Optional[JobState]:
    if isinstance(value, JobState):
        return value
    if value is None:
        return None
    raw = getattr(value, "value", value)
    text = str(raw or "").strip()
    if not text:
        return None
    aliased = _STATUS_ALIASES.get(text)
    if aliased is not None:
        return aliased
    for state in JobState:
        if state.value == text or state.name == text:
            return state
    return None


def default_step_for(state: JobState) -> str:
    return DEFAULT_JOB_STEPS.get(state, state.value)


def aggregate_runner_states(states: Iterable[Any]) -> Optional[JobState]:
    """多个 Runner 合成一个作业状态。进行中优先于终态。"""
    parsed = []
    for item in states or []:
        state = parse_job_state(item)
        if state is not None:
            parsed.append(state)
    if not parsed:
        return None
    if any(state == JobState.STOPPING for state in parsed):
        return JobState.STOPPING
    if any(state == JobState.RUNNING for state in parsed):
        return JobState.RUNNING
    if any(state == JobState.STARTING for state in parsed):
        return JobState.STARTING
    if any(state == JobState.PAUSED for state in parsed):
        return JobState.PAUSED
    if any(state == JobState.IDLE for state in parsed):
        return JobState.IDLE
    if any(state == JobState.FAILED for state in parsed):
        return JobState.FAILED
    if any(state == JobState.STOPPED for state in parsed):
        return JobState.STOPPED
    if all(state == JobState.COMPLETED for state in parsed):
        return JobState.COMPLETED
    return parsed[-1]


_LEADING_STEP_PRIORITY = {
    JobState.RUNNING: 0,
    JobState.STARTING: 1,
    JobState.PAUSED: 2,
    JobState.IDLE: 3,
    JobState.STOPPING: 4,
}


def pick_leading_runner_step(entries: Iterable[Any]) -> Optional[str]:
    """多 Runner 同时汇报步骤时，取主导状态那条，避免后写覆盖。"""
    best_step = None
    best_rank = 999
    for item in entries or []:
        if isinstance(item, (tuple, list)) and len(item) >= 2:
            state, step = item[0], item[1]
        else:
            continue
        parsed = parse_job_state(state)
        if parsed is None:
            continue
        text = str(step or "").strip()
        if not text:
            continue
        rank = _LEADING_STEP_PRIORITY.get(parsed, 50)
        if rank < best_rank:
            best_rank = rank
            best_step = text
    return best_step
