from __future__ import annotations

import logging
import os
import time
from typing import Any, Callable, Iterable, List, Mapping, Optional

logger = logging.getLogger(__name__)

CONTROL_CENTER_SHUTDOWN_BLOCK_MESSAGE = (
    "中控仍在停止任务，请稍后再启动。\n\n"
    "关闭中控后需要等窗口任务退出，立刻启动可能撞上未释放的截图或 OCR。"
)

CONTROL_CENTER_RUNNING_BLOCK_MESSAGE = (
    "中控正在执行任务，请等待中控任务完成或停止后再从主窗口启动。\n\n"
    "中控和主窗口的执行器不能同时运行，否则可能导致程序卡死。"
)

CONTROL_CENTER_SHUTDOWN_TIMEOUT_MS = 8000
CONTROL_CENTER_SHUTDOWN_POLL_MS = 150


class ControlCenterShutdownSession:
    def __init__(self, orphans: Optional[Iterable[Any]] = None):
        self.active = True
        self.orphans: List[Any] = [item for item in (orphans or []) if item is not None]
        self.started_at = time.monotonic()

    @property
    def elapsed_ms(self) -> int:
        return int(max(0.0, (time.monotonic() - self.started_at) * 1000))

    def mark_finished(self) -> None:
        self.active = False


def shutdown_blocks_execution(session: Any) -> bool:
    return session is not None and bool(getattr(session, "active", False))


def collect_close_runners(window_runners: Optional[Mapping[Any, Any]]) -> List[Any]:
    collected: List[Any] = []
    for runners in (window_runners or {}).values():
        items = runners if isinstance(runners, list) else [runners]
        for runner in items:
            if runner is not None:
                collected.append(runner)
    return collected


def filter_alive_runners(
    runners: Optional[Iterable[Any]],
    is_alive: Callable[[Any], bool],
) -> List[Any]:
    alive: List[Any] = []
    for runner in runners or []:
        if runner is None:
            continue
        try:
            if is_alive(runner):
                alive.append(runner)
        except Exception:
            continue
    return alive


def decide_shutdown_completion(
    running_count: int,
    elapsed_ms: int,
    timeout_ms: int = CONTROL_CENTER_SHUTDOWN_TIMEOUT_MS,
) -> str:
    if int(running_count or 0) <= 0:
        return "finished_clean"
    if int(elapsed_ms or 0) >= int(timeout_ms):
        return "finished_orphan"
    return "wait"


def should_finish_shutdown(
    running_count: int,
    elapsed_ms: int,
    timeout_ms: int = CONTROL_CENTER_SHUTDOWN_TIMEOUT_MS,
) -> bool:
    return decide_shutdown_completion(running_count, elapsed_ms, timeout_ms) != "wait"


def control_center_blocks_main_window_start(
    control_center: Any = None,
    shutdown_session: Any = None,
) -> Optional[str]:
    if shutdown_blocks_execution(shutdown_session):
        return CONTROL_CENTER_SHUTDOWN_BLOCK_MESSAGE
    checker = getattr(control_center, "is_any_task_running", None)
    try:
        running = bool(checker()) if callable(checker) else False
    except Exception:
        running = False
    if running:
        return CONTROL_CENTER_RUNNING_BLOCK_MESSAGE
    return None


def cleanup_control_center_shared_runtime() -> None:
    try:
        from app_core.runtime.runtime_image_cleanup import cleanup_yolo_runtime_on_stop

        cleanup_yolo_runtime_on_stop(release_engine=True, compact_memory=True)
    except Exception as exc:
        logger.warning("关闭中控时清理 YOLO 失败: %s", exc)
    try:
        from services.screenshot_pool import cleanup_screenshot_engines_on_stop

        cleanup_screenshot_engines_on_stop(keep_current_engine=True)
    except Exception as exc:
        logger.warning("关闭中控时清理截图失败: %s", exc)
    try:
        from services.multiprocess_ocr_pool import cleanup_ocr_services_on_stop

        cleanup_ocr_services_on_stop()
    except Exception as exc:
        logger.warning("关闭中控时清理 OCR 失败: %s", exc)
    try:
        from app_core.runtime.runtime_image_cleanup import cleanup_runtime_image_memory

        cleanup_runtime_image_memory(
            reason="control_center_close",
            cleanup_screenshot_engines=False,
            cleanup_template_cache=True,
        )
    except Exception as exc:
        logger.warning("关闭中控时清理图片缓存失败: %s", exc)
    os.environ.pop("MULTI_WINDOW_MODE", None)
