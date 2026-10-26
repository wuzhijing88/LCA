"""卡片执行结果的唯一协议与校验。"""

from typing import Any, Optional


STEP_ACTIONS = frozenset(("执行下一步", "跳转到步骤", "继续执行本步骤", "停止工作流"))


def validate_step_action(action: Any) -> str:
    if not isinstance(action, str) or action not in STEP_ACTIONS:
        raise ValueError(f"无效的步骤动作: {action!r}")
    return action


def validate_card_target(value: Any) -> Optional[int]:
    if value is not None and (type(value) is not int or value < 0):
        raise ValueError(f"卡片目标必须是非负整数或空值: {value!r}")
    return value


def validate_task_result(result: Any) -> tuple[bool, str, Optional[int], str]:
    """接收 (success, action, target[, detail])，只补齐可选说明字段。"""
    if not isinstance(result, tuple) or len(result) not in (3, 4):
        raise TypeError("任务结果必须是包含 3 或 4 项的元组")
    success, action, target = result[:3]
    if type(success) is not bool:
        raise TypeError("任务结果的成功状态必须是布尔值")
    validate_step_action(action)
    validate_card_target(target)
    if action == "跳转到步骤" and target is None:
        raise ValueError("跳转到步骤必须指定目标卡片")
    detail = result[3] if len(result) == 4 else ""
    if not isinstance(detail, str):
        raise TypeError("任务结果的说明必须是文本")
    return success, action, target, detail
