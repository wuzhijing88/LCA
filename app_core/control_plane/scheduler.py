import uuid
from collections.abc import MutableMapping
from typing import Any, Dict, Iterable, List, Optional, Sequence

from utils.window.hwnd_utils import as_hwnd

from .job_models import CommandResult, Job, JobSnapshot
from .job_state import (
    ACTIVE_JOB_STATES,
    JobState,
    RESTARTABLE_JOB_STATES,
    aggregate_runner_states,
    can_transition,
    default_step_for,
    parse_job_state,
)


def wrap_assignment_record(window_info: Optional[Dict[str, Any]], workflows: Any) -> Dict[str, Any]:
    items = workflows
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list):
        items = []
    return {
        "title": str((window_info or {}).get("title") or ""),
        "workflows": [
            {
                "file_path": str(item.get("file_path") or ""),
                "name": str(item.get("name") or ""),
            }
            for item in items
            if isinstance(item, dict)
        ],
    }


def unwrap_assignment_record(payload: Any) -> Dict[str, Any]:
    if isinstance(payload, dict) and isinstance(payload.get("workflows"), list):
        return {
            "workflows": payload.get("workflows") or [],
            "title": str(payload.get("title") or ""),
        }
    return {"workflows": [], "title": ""}


def ensure_bind_id(window_info: Optional[Dict[str, Any]]) -> str:
    if not isinstance(window_info, dict):
        return ""
    bind_id = str(window_info.get("bind_id") or "").strip()
    if bind_id:
        return bind_id
    bind_id = str(uuid.uuid4())
    window_info["bind_id"] = bind_id
    return bind_id


def resolve_target_job_id(window_info: Optional[Dict[str, Any]], row: Optional[int] = None) -> str:
    bind_id = ensure_bind_id(window_info)
    if bind_id:
        return bind_id
    if row is None:
        return ""
    return str(row)


class AssignmentMap(MutableMapping):
    """中控表格仍用字典接口读写分配，实际数据在调度器里。"""

    def __init__(self, scheduler: "JobScheduler"):
        self._scheduler = scheduler

    def __getitem__(self, key):
        job = self._scheduler.get_job(str(key or ""))
        if job is None:
            raise KeyError(key)
        return job.assignments

    def __setitem__(self, key, value):
        self._scheduler.set_assignments(str(key or ""), value)

    def __delitem__(self, key):
        self._scheduler.set_assignments(str(key or ""), [])

    def __iter__(self):
        return iter(self._scheduler.assigned_job_ids())

    def __len__(self):
        return len(self._scheduler.assigned_job_ids())

    def __contains__(self, key):
        job = self._scheduler.get_job(str(key or ""))
        return bool(job and job.assignments)

    def get(self, key, default=None):
        job = self._scheduler.get_job(str(key or ""))
        if job is None or not job.assignments:
            return default
        return job.assignments


class JobScheduler:
    """中控控制面：作业主键是 bind_id，HWND 只是执行租约。"""

    def __init__(self):
        self._jobs: Dict[str, Job] = {}
        self._hwnd_index: Dict[str, str] = {}

    def assignments_view(self) -> AssignmentMap:
        return AssignmentMap(self)

    def get_job(self, job_id: str) -> Optional[Job]:
        key = str(job_id or "").strip()
        if not key:
            return None
        return self._jobs.get(key)

    def snapshot(self, job_id: str) -> Optional[JobSnapshot]:
        job = self.get_job(job_id)
        return job.snapshot() if job else None

    def list_jobs(self) -> List[JobSnapshot]:
        return [job.snapshot() for job in self._jobs.values()]

    def assigned_job_ids(self) -> List[str]:
        return [job.job_id for job in self._jobs.values() if job.assignments]

    def upsert_job(
        self,
        job_id: str,
        *,
        title: str = "",
        hwnd: Optional[int] = None,
    ) -> Job:
        key = str(job_id or "").strip()
        if not key:
            raise ValueError("job_id is required")
        job = self._jobs.get(key)
        if job is None:
            job = Job(job_id=key, title=title, hwnd=hwnd)
            self._jobs[key] = job
        else:
            if title:
                job.title = title
            if hwnd is not None:
                self._bind_hwnd_alias(job, hwnd)
        if hwnd:
            self._hwnd_index[str(hwnd)] = key
        return job

    def ensure_job(self, window_info: Optional[Dict[str, Any]], row: Optional[int] = None) -> Job:
        job_id = resolve_target_job_id(window_info, row)
        hwnd = as_hwnd((window_info or {}).get("hwnd")) or None
        title = str((window_info or {}).get("title") or "")
        return self.upsert_job(job_id, title=title, hwnd=hwnd)

    def sync_targets(self, windows: Optional[Sequence[Any]]) -> List[JobSnapshot]:
        snapshots = []
        for window_info in windows or []:
            if not isinstance(window_info, dict):
                continue
            snapshots.append(self.ensure_job(window_info).snapshot())
        return snapshots

    def set_assignments(self, job_id: str, workflows: Any) -> Job:
        key = str(job_id or "").strip()
        job = self.get_job(key) or self.upsert_job(key)
        if workflows is None:
            job.assignments = []
        elif isinstance(workflows, dict):
            job.assignments = [workflows]
        elif isinstance(workflows, list):
            job.assignments = workflows
        else:
            job.assignments = []
        self.sync_assignment_state(key)
        return job

    def sync_assignment_state(self, job_id: str) -> Optional[JobSnapshot]:
        job = self.get_job(job_id)
        if job is None or job.is_active:
            return job.snapshot() if job else None
        if job.assignments:
            if job.state == JobState.UNASSIGNED:
                self._apply_state(job, JobState.READY)
        elif job.state in {JobState.READY, JobState.IDLE, *RESTARTABLE_JOB_STATES}:
            self._apply_state(job, JobState.UNASSIGNED)
        return job.snapshot()

    def request_start(self, job_id: str) -> CommandResult:
        job = self.get_job(job_id)
        if job is None:
            return CommandResult(ok=False, job_id=str(job_id or ""), reason="missing_job")
        if not job.assignments:
            return CommandResult(ok=False, job_id=job.job_id, reason="unassigned", snapshot=job.snapshot())
        if job.state in ACTIVE_JOB_STATES:
            if job.state == JobState.IDLE:
                return CommandResult(ok=True, job_id=job.job_id, state=job.state, snapshot=job.snapshot())
            return CommandResult(ok=False, job_id=job.job_id, reason="already_active", snapshot=job.snapshot())
        if not can_transition(job.state, JobState.IDLE):
            return CommandResult(ok=False, job_id=job.job_id, reason="invalid_state", snapshot=job.snapshot())
        self._apply_state(job, JobState.IDLE)
        return CommandResult(ok=True, job_id=job.job_id, state=job.state, snapshot=job.snapshot())

    def request_stop(self, job_id: str) -> CommandResult:
        job = self.get_job(job_id)
        if job is None:
            return CommandResult(ok=False, job_id=str(job_id or ""), reason="missing_job")
        if job.state == JobState.IDLE:
            self._apply_state(job, JobState.STOPPED)
            return CommandResult(ok=True, job_id=job.job_id, state=job.state, snapshot=job.snapshot())
        if job.state not in ACTIVE_JOB_STATES:
            return CommandResult(ok=False, job_id=job.job_id, reason="not_running", snapshot=job.snapshot())
        if not can_transition(job.state, JobState.STOPPING):
            return CommandResult(ok=False, job_id=job.job_id, reason="invalid_state", snapshot=job.snapshot())
        self._apply_state(job, JobState.STOPPING)
        return CommandResult(ok=True, job_id=job.job_id, state=job.state, snapshot=job.snapshot())

    def revert_unstarted(self, job_id: str) -> Optional[JobSnapshot]:
        """启动命令已发出但执行面没建起来时，回到就绪。"""
        job = self.get_job(job_id)
        if job is None:
            return None
        if job.state not in {JobState.IDLE, JobState.STARTING}:
            return job.snapshot()
        target = JobState.READY if job.assignments else JobState.UNASSIGNED
        self._apply_state(job, target)
        return job.snapshot()

    def finalize_orphaned_stop(self, job_id: str) -> Optional[JobSnapshot]:
        """没有可停的 Runner 时，把卡住的活跃作业收成已中断。

        IDLE 不收：启动命令刚发出、Runner 可能还没登记。
        """
        job = self.get_job(job_id)
        if job is None:
            return None
        if job.state == JobState.IDLE:
            return job.snapshot()
        if job.state in {JobState.STOPPING, JobState.STARTING, JobState.RUNNING, JobState.PAUSED}:
            self._apply_state(job, JobState.STOPPED)
        return job.snapshot()

    def request_pause(self, job_id: str) -> CommandResult:
        return self._request_simple_transition(job_id, JobState.PAUSED, allowed_from={JobState.RUNNING})

    def request_resume(self, job_id: str) -> CommandResult:
        return self._request_simple_transition(job_id, JobState.RUNNING, allowed_from={JobState.PAUSED})

    def can_pause(self, job_id: str) -> bool:
        job = self.get_job(job_id)
        return bool(job and can_transition(job.state, JobState.PAUSED) and job.state == JobState.RUNNING)

    def can_resume(self, job_id: str) -> bool:
        job = self.get_job(job_id)
        return bool(job and job.state == JobState.PAUSED)

    def apply_runner_state(
        self,
        job_id: str,
        state: Any,
        step: str = "",
        *,
        force: bool = False,
        error: str = "",
    ) -> Optional[JobSnapshot]:
        parsed = parse_job_state(state)
        job = self.get_job(job_id)
        if job is None or parsed is None:
            return job.snapshot() if job else None
        if not force and not can_transition(job.state, parsed):
            return job.snapshot()
        self._apply_state(job, parsed, step=step, error=error)
        return job.snapshot()

    def apply_status_text(
        self,
        job_id: str,
        status_text: str,
        step_text: Optional[str] = None,
        *,
        force: bool = False,
    ) -> Optional[JobSnapshot]:
        return self.apply_runner_state(
            job_id,
            status_text,
            step=str(step_text or ""),
            force=force,
        )

    def apply_runner_states(
        self,
        job_id: str,
        states: Iterable[Any],
        step: str = "",
    ) -> Optional[JobSnapshot]:
        job = self.get_job(job_id)
        aggregated = aggregate_runner_states(states)
        if job is None or aggregated is None:
            return job.snapshot() if job else None
        if job.state in {JobState.STOPPING, JobState.STOPPED} and aggregated in {
            JobState.IDLE,
            JobState.STARTING,
            JobState.RUNNING,
            JobState.PAUSED,
        }:
            return job.snapshot()
        keep_step = job.state == aggregated and not str(step or "").strip()
        self._apply_state(job, aggregated, step=step, keep_step=keep_step)
        return job.snapshot()

    def refresh_hwnd(self, job_id: str, hwnd: Any) -> Optional[JobSnapshot]:
        job = self.get_job(job_id)
        if job is None:
            return None
        self._bind_hwnd_alias(job, as_hwnd(hwnd) or None)
        return job.snapshot()

    def match_saved_key(self, saved_key: Any) -> str:
        """恢复分配时只认已存在的 bind_id。"""
        key = str(saved_key or "").strip()
        if key and key in self._jobs:
            return key
        return ""

    def resolve_job_id(self, token: Any) -> str:
        key = str(token or "").strip()
        if not key:
            return ""
        if key in self._jobs:
            return key
        hwnd = as_hwnd(key)
        if hwnd:
            mapped = self._hwnd_index.get(str(hwnd), "")
            if mapped:
                return mapped
        return ""

    def canonicalize_ids(self, tokens: Optional[Iterable[Any]]) -> List[str]:
        resolved: List[str] = []
        seen = set()
        for token in tokens or []:
            key = str(token or "").strip()
            if not key or key in seen or key not in self._jobs:
                continue
            seen.add(key)
            resolved.append(key)
        return resolved

    def matches_filter(
        self,
        job_id: str,
        filter_ids: Optional[Iterable[Any]],
        hwnd: Any = None,
    ) -> bool:
        if filter_ids is None:
            return True
        tokens = {str(item).strip() for item in filter_ids if str(item).strip()}
        if not tokens:
            return True
        key = str(job_id or "").strip()
        if key and key in tokens:
            return True
        resolved = {self.resolve_job_id(item) for item in tokens}
        if key and key in resolved:
            return True
        job = self.get_job(key)
        hwnd_value = as_hwnd(hwnd if hwnd is not None else (job.hwnd if job else 0))
        return bool(hwnd_value and str(hwnd_value) in tokens)

    def export_assignments(self) -> Dict[str, List[Dict[str, str]]]:
        exported: Dict[str, List[Dict[str, str]]] = {}
        for job in self._jobs.values():
            if not job.assignments:
                continue
            exported[job.job_id] = [
                {
                    "file_path": str(item.get("file_path") or ""),
                    "name": str(item.get("name") or ""),
                }
                for item in job.assignments
                if isinstance(item, dict)
            ]
        return exported

    def _request_simple_transition(
        self,
        job_id: str,
        new_state: JobState,
        *,
        allowed_from: set,
    ) -> CommandResult:
        job = self.get_job(job_id)
        if job is None:
            return CommandResult(ok=False, job_id=str(job_id or ""), reason="missing_job")
        if job.state not in allowed_from:
            return CommandResult(ok=False, job_id=job.job_id, reason="invalid_state", snapshot=job.snapshot())
        if not can_transition(job.state, new_state):
            return CommandResult(ok=False, job_id=job.job_id, reason="invalid_state", snapshot=job.snapshot())
        self._apply_state(job, new_state)
        return CommandResult(ok=True, job_id=job.job_id, state=job.state, snapshot=job.snapshot())

    def _apply_state(
        self,
        job: Job,
        new_state: JobState,
        step: str = "",
        error: str = "",
        *,
        keep_step: bool = False,
    ) -> None:
        job.state = new_state
        explicit_step = str(step or "").strip()
        if explicit_step:
            job.step = explicit_step
        elif not keep_step:
            job.step = default_step_for(new_state)
        if error:
            job.last_error = str(error)
        elif new_state != JobState.FAILED:
            job.last_error = ""

    def _bind_hwnd_alias(self, job: Job, hwnd: Optional[int]) -> None:
        job.hwnd = hwnd
        if hwnd:
            self._hwnd_index[str(hwnd)] = job.job_id
