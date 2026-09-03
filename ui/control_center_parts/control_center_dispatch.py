from __future__ import annotations

from collections import deque
from typing import Any, Callable, Deque, Iterable, List, Mapping, Optional, Set, Tuple

CONTROL_CENTER_DEAD_HWND_MESSAGE = "目标窗口已失效"


def is_runner_occupying_window(runner: Any) -> bool:
    if runner is None:
        return False
    if getattr(runner, "_task_completed_emitted", False):
        return False
    if getattr(runner, "_thread_start_requested", False):
        return True
    return bool(getattr(runner, "is_running", False))


def collect_busy_window_ids(window_runners: Optional[Mapping[Any, Any]]) -> Set[str]:
    busy: Set[str] = set()
    for window_id, runners in (window_runners or {}).items():
        items = runners if isinstance(runners, list) else [runners]
        if any(is_runner_occupying_window(runner) for runner in items):
            busy.add(str(window_id))
    return busy


def partition_serial_dispatch(
    queue: Iterable[Any],
    busy_window_ids: Optional[Iterable[str]],
) -> Tuple[Any, Deque[Any]]:
    busy = {str(window_id) for window_id in (busy_window_ids or [])}
    leftover: Deque[Any] = deque()
    chosen = None
    for runner in queue:
        if runner is None:
            continue
        window_id = str(getattr(runner, "window_id", "") or "")
        if chosen is None and (not window_id or window_id not in busy):
            chosen = runner
            continue
        leftover.append(runner)
    return chosen, leftover


def runner_target_hwnd(runner: Any) -> int:
    hwnd = getattr(runner, "hwnd", 0) or 0
    if not hwnd:
        info = getattr(runner, "window_info", None) or {}
        if isinstance(info, dict):
            hwnd = info.get("hwnd") or 0
    try:
        return int(hwnd)
    except (TypeError, ValueError):
        return 0


def collect_dead_running_window_ids(
    window_runners: Optional[Mapping[Any, Any]],
    is_alive: Callable[[int], bool],
) -> List[str]:
    dead: List[str] = []
    for window_id, runners in (window_runners or {}).items():
        items = runners if isinstance(runners, list) else [runners]
        occupying = [runner for runner in items if is_runner_occupying_window(runner)]
        if not occupying:
            continue
        hwnd = runner_target_hwnd(occupying[0])
        if hwnd and not is_alive(hwnd):
            dead.append(str(window_id))
    return dead


def select_unnotified_ids(
    candidate_ids: Optional[Iterable[Any]],
    already_notified: Optional[Iterable[Any]],
) -> List[str]:
    seen_notified = {str(item) for item in (already_notified or [])}
    selected: List[str] = []
    seen_new: Set[str] = set()
    for item in candidate_ids or []:
        window_id = str(item)
        if not window_id or window_id in seen_notified or window_id in seen_new:
            continue
        seen_new.add(window_id)
        selected.append(window_id)
    return selected


def format_runner_runtime_alert(kind: str, title_or_card: Any, message: Any) -> str:
    text = str(message or "").strip()
    label = str(title_or_card if title_or_card is not None else "").strip()
    if str(kind or "").strip().lower() == "error":
        if label:
            return f"错误[{label}]: {text}".rstrip()
        return f"错误: {text}".rstrip()
    if label:
        return f"{label}: {text}".rstrip()
    return text
