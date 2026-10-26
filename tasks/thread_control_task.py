import logging
from typing import Any, Dict, Optional, Tuple

from task_workflow.thread_start import validate_thread_target


logger = logging.getLogger(__name__)

TASK_TYPE = "线程控制"
TASK_NAME = "线程控制"


def get_params_definition() -> Dict[str, Dict[str, Any]]:
    return {
        "control_action": {
            "label": "控制动作",
            "type": "combo",
            "default": "暂停线程",
            "options": ["暂停线程", "恢复线程", "停止线程", "启动/重启线程", "从指定卡片启动线程"],
            "tooltip": "线程控制动作类型",
        },
        "target_thread": {
            "label": "目标线程",
            "type": "combo",
            "default": "当前线程",
            "options": ["当前线程", "全部线程", "自定义多个线程"],
            "widget_hint": "thread_target_selector",
            "tooltip": "可选择当前、全部或单个线程；自定义多个线程时按名称勾选。参数保存为当前线程、全部线程、单个起点编号的数字字符串或非空数字字符串列表",
        },
        "start_card_id": {
            "label": "指定卡片",
            "type": "combo",
            "default": None,
            "options": ["请选择指定卡片"],
            "widget_hint": "workflow_card_selector",
            "tooltip": "仅在“从指定卡片启动线程”时生效；多个目标只显示共同可达卡片",
            "condition": {"param": "control_action", "value": "从指定卡片启动线程"},
        },
    }


def execute_task(
    params: Dict[str, Any],
    counters: Dict[str, int],
    execution_mode: str,
    target_hwnd: Optional[int],
    window_region=None,
    card_id: Optional[int] = None,
    **kwargs,
) -> Tuple[bool, str, Optional[int], str]:
    try:
        stop_checker = kwargs.get("stop_checker")
        if stop_checker is not None and stop_checker():
            return True, "停止工作流", None, "已收到停止请求"
        action = params.get("control_action", "暂停线程")
        target_thread = params.get("target_thread", "当前线程")
        validate_thread_target(target_thread)
        start_card_id = params.get("start_card_id") if action == "从指定卡片启动线程" else None
        if start_card_id is not None and (isinstance(start_card_id, bool) or not isinstance(start_card_id, int) or start_card_id < 0):
            raise ValueError("指定卡片必须是非负整数编号")
        executor = kwargs.get("executor")
        session = getattr(executor, "thread_session", None)
        if session is None:
            raise ValueError("线程控制需要多线程会话，请配置至少两个线程起点")
        success, message = session.control_thread(
            action=action,
            target_thread=target_thread,
            start_card_id=start_card_id,
            source_executor=executor,
        )
    except Exception as exc:
        logger.error("线程控制执行失败: %s", exc, exc_info=True)
        return False, "执行下一步", None, str(exc)
    logger.info("[线程控制] 动作=%s，目标=%s，成功=%s，详情=%s", action, target_thread, success, message)
    return success, "执行下一步", None, message
