import logging
import re
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

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
            "options": ["当前线程", "全部线程"],
            "widget_hint": "thread_target_selector",
            "tooltip": "自动读取当前工作流所有线程起点",
        },
        "start_card_id": {
            "label": "指定卡片",
            "type": "combo",
            "default": None,
            "options": ["使用线程默认起点"],
            "widget_hint": "workflow_card_selector",
            "tooltip": "仅在“从指定卡片启动线程”时生效；自动读取目标线程可达卡片",
            "condition": {"param": "control_action", "value": "从指定卡片启动线程"},
            "conditions": [
                {"param": "control_action", "value": "从指定卡片启动线程"},
                {"param": "control_action", "value": "从指定卡片开始"},
            ],
        },
    }


def _parse_start_card_id(raw_value: Any) -> Optional[int]:
    if raw_value is None:
        return None
    if isinstance(raw_value, bool):
        return None

    if isinstance(raw_value, int):
        return raw_value if raw_value >= 0 else None

    text = str(raw_value).strip()
    if not text:
        return None

    if text in {"使用线程默认起点", "默认起点", "none", "None", "-1"}:
        return None

    try:
        value = int(text)
    except Exception:
        match = re.search(r"ID\s*[:：]\s*(-?\d+)", text)
        if not match:
            match = re.search(r"\(\s*ID\s*[:：]\s*(-?\d+)\s*\)", text)
        if not match:
            return None
        try:
            value = int(match.group(1))
        except Exception:
            return None

    if value < 0:
        return None
    return value


def _normalize_action(action: Any) -> str:
    text = str(action or "").strip()
    return {
        "启动/重启线程": "restart",
        "启动线程": "start",
        "暂停线程": "pause",
        "恢复线程": "resume",
        "停止线程": "stop",
        "重启线程": "restart",
        "从指定卡片启动线程": "start_from_card",
        "启动/重启": "restart",
        "启动": "start",
        "暂停": "pause",
        "恢复": "resume",
        "停止": "stop",
        "重启": "restart",
        "从指定卡片开始": "start_from_card",
        "start": "start",
        "pause": "pause",
        "resume": "resume",
        "stop": "stop",
        "restart": "restart",
        "start_from_card": "start_from_card",
    }.get(text, str(text).lower())


def _resolve_existing_card_id(executor: Any, card_id: Any) -> Optional[Any]:
    cards_data = getattr(executor, "cards_data", None)
    if not isinstance(cards_data, dict):
        return None

    candidates = [card_id]
    try:
        candidates.append(int(card_id))
    except Exception:
        pass
    try:
        candidates.append(str(card_id))
    except Exception:
        pass

    for candidate in candidates:
        if candidate in cards_data:
            return candidate
    return None


def _control_single_thread(
    action: str,
    executor: Any,
    start_card_id: Optional[int],
) -> Tuple[bool, str, str, Optional[int]]:
    if executor is None:
        return False, "未找到执行器，已跳过线程控制", "执行下一步", None

    action_key = _normalize_action(action)

    if action_key == "pause":
        try:
            executor.pause()
            return True, "单线程已暂停", "执行下一步", None
        except Exception as exc:
            return False, f"单线程暂停失败: {exc}", "执行下一步", None

    if action_key == "resume":
        try:
            executor.resume()
            return True, "单线程已恢复", "执行下一步", None
        except Exception as exc:
            return False, f"单线程恢复失败: {exc}", "执行下一步", None

    if action_key == "stop":
        stop_fn = getattr(executor, "request_stop", None)
        if not callable(stop_fn):
            return False, "执行器不支持停止控制", "执行下一步", None
        try:
            stop_fn(force=False)
            return True, "单线程已请求停止", "执行下一步", None
        except Exception as exc:
            return False, f"单线程停止失败: {exc}", "执行下一步", None

    if action_key in {"start", "restart", "start_from_card"}:
        if action_key == "start_from_card":
            target = start_card_id
            if target is None:
                return True, "未提供指定卡片，已跳过", "执行下一步", None
        else:
            target = getattr(executor, "start_card_id", None)
            if target is None:
                return True, "未找到工作流起始卡片，已跳过", "执行下一步", None

        existing_id = _resolve_existing_card_id(executor, target)
        if existing_id is None:
            return True, f"目标卡片不存在: {target}，已跳过", "执行下一步", None

        return True, f"单线程跳转到卡片 {existing_id}", "跳转到步骤", existing_id

    return True, f"未知动作 {action}，已跳过", "执行下一步", None


def execute_task(
    params: Dict[str, Any],
    counters: Dict[str, int],
    execution_mode: str,
    target_hwnd: Optional[int],
    window_region=None,
    card_id: Optional[int] = None,
    **kwargs,
) -> Tuple[bool, str, Optional[int]]:
    stop_checker = kwargs.get("stop_checker")
    try:
        if callable(stop_checker) and stop_checker():
            logger.warning("[线程控制] 检测到停止请求，跳过线程控制动作")
            return True, "停止工作流", None
    except Exception:
        pass

    action = str(params.get("control_action") or "暂停线程").strip()
    target_thread = str(params.get("target_thread") or "当前线程").strip()
    start_card_id = _parse_start_card_id(params.get("start_card_id"))

    executor = kwargs.get("executor")
    session = getattr(executor, "thread_session", None) if executor is not None else None
    if session is None:
        single_ok, single_message, single_action, single_next_card_id = _control_single_thread(
            action=action,
            executor=executor,
            start_card_id=start_card_id,
        )
        if single_ok:
            logger.info("当前不是多线程会话，线程控制卡按单线程模式处理: %s", single_message)
        else:
            logger.warning("当前不是多线程会话，线程控制卡按单线程模式处理失败: %s", single_message)
        if not single_ok:
            logger.warning("单线程控制执行失败: %s", single_message)
        return True, single_action, single_next_card_id

    try:
        success, message = session.control_thread(
            action=action,
            target_thread=target_thread,
            start_card_id=start_card_id,
            source_executor=executor,
        )
    except Exception as exc:
        logger.error("线程控制执行异常: %s", exc, exc_info=True)
        return True, "执行下一步", None

    logger.info(
        "[线程控制] action=%s, target=%s, start_card_id=%s, success=%s, message=%s",
        action,
        target_thread,
        start_card_id,
        success,
        message,
    )
    if not success:
        logger.warning("线程控制命令未成功执行，但不终止当前工作流: %s", message)
    return True, "执行下一步", None
