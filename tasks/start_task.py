# tasks/start_task.py
from typing import Any, Dict, Optional, Tuple

from utils.thread_start_utils import THREAD_START_TASK_TYPE

TASK_TYPE = THREAD_START_TASK_TYPE


def get_params_definition() -> Dict[str, Dict[str, Any]]:
    """线程起点没有运行参数，后继步骤由工作流连线决定。"""
    return {}


def execute_task(
    params: Dict[str, Any],
    counters: Dict[str, int],
    execution_mode: str,
    target_hwnd: Optional[int],
    window_region=None,
    card_id: Optional[int] = None,
    **kwargs,
) -> Tuple[bool, str, Optional[int]]:
    """完成入口标记，并让执行器沿顺序连线选择下一张卡片。"""
    return True, "执行下一步", None
