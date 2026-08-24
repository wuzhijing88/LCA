from typing import Any, Dict, Optional, Tuple

from task_workflow.thread_window_binding import (
    THREAD_WINDOW_LIMIT_PARAM,
    THREAD_WINDOW_LIMIT_TASK_TYPE,
)

TASK_TYPE = THREAD_WINDOW_LIMIT_TASK_TYPE
TASK_NAME = THREAD_WINDOW_LIMIT_TASK_TYPE


def get_params_definition() -> Dict[str, Dict[str, Any]]:
    return {
        THREAD_WINDOW_LIMIT_PARAM: {
            "label": "执行窗口",
            "type": "combo",
            "required": False,
            "default": None,
            "widget_hint": "bound_window_selector",
            "tooltip": "放在线程起点前面；不选则使用默认窗口。",
        }
    }


def execute_task(
    params: Dict[str, Any],
    counters: Dict[str, int],
    execution_mode: str,
    target_hwnd: Optional[int],
    window_region=None,
    card_id: Optional[int] = None,
    **kwargs,
) -> Tuple[bool, str, Optional[int]]:
    return True, "执行下一步", None
