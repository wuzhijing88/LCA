"""
随机跳转任务模块
用于在工作流中实现随机分支跳转
"""
import logging
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)
TASK_NAME = '随机跳转'
DEFAULT_BRANCH_WEIGHT = 1


def _normalize_target_key(target_card_id: Any) -> Optional[str]:
    try:
        return str(int(str(target_card_id).strip()))
    except (TypeError, ValueError):
        return None


def normalize_branch_weight(weight: Any) -> int:
    try:
        normalized = int(weight)
    except (TypeError, ValueError):
        return DEFAULT_BRANCH_WEIGHT
    return max(DEFAULT_BRANCH_WEIGHT, normalized)


def normalize_branch_weights(raw_weights: Any) -> Dict[str, int]:
    if not isinstance(raw_weights, dict):
        return {}
    normalized: Dict[str, int] = {}
    for target_card_id, weight in raw_weights.items():
        target_key = _normalize_target_key(target_card_id)
        if target_key is None:
            continue
        normalized[target_key] = normalize_branch_weight(weight)
    return normalized


def get_branch_weight(raw_weights: Any, target_card_id: Any) -> int:
    target_key = _normalize_target_key(target_card_id)
    if target_key is None:
        return DEFAULT_BRANCH_WEIGHT
    normalized = normalize_branch_weights(raw_weights)
    return normalized.get(target_key, DEFAULT_BRANCH_WEIGHT)


def set_branch_weight(raw_weights: Any, target_card_id: Any, weight: Any) -> Dict[str, int]:
    target_key = _normalize_target_key(target_card_id)
    normalized = normalize_branch_weights(raw_weights)
    if target_key is None:
        return normalized
    normalized[target_key] = normalize_branch_weight(weight)
    return normalized


def prune_branch_weights(raw_weights: Any, valid_target_ids: Any) -> Dict[str, int]:
    normalized = normalize_branch_weights(raw_weights)
    valid_keys = set()
    if isinstance(valid_target_ids, (list, tuple, set)):
        for target_card_id in valid_target_ids:
            target_key = _normalize_target_key(target_card_id)
            if target_key is not None:
                valid_keys.add(target_key)
    return {target_key: weight for target_key, weight in normalized.items() if target_key in valid_keys}


def get_params_definition() -> Dict[str, Any]:
    """返回此任务的参数定义"""
    return {
        "random_weights": {
            "label": "随机跳转权重",
            "type": "hidden",
            "default": {}
        },
        "connected_targets": {
            "label": "随机跳转目标列表",
            "type": "textarea",
            "default": "未连接任何目标卡片\n\n请从右侧紫色端口拖拽连线到目标卡片",
            "tooltip": "显示当前连接的所有可能跳转目标，可为每条分支单独设置权重",
            "readonly": True,
            "height": 120
        }
    }


def execute_task(params: Dict[str, Any], counters: Dict[str, int],
                execution_mode='foreground', **kwargs) -> Tuple[bool, str, Optional[int]]:
    """
    执行随机跳转任务

    随机跳转的实际逻辑在 executor.py 的 _find_next_card 方法中实现。
    此任务本身只是一个标记，表示成功执行。

    Returns:
        Tuple[bool, str, Optional[int]]: (成功标志, 动作, 下一个卡片ID)
        - success: True 表示成功
        - action: '执行下一步' 让 executor 查找连接
        - next_card_id: None 让 executor 通过 random 连接查找
    """
    logger.info("执行随机跳转任务 - 将从连接的输出中随机选择")

    # 随机跳转本身不需要做任何操作
    # 随机选择逻辑在 executor 的 _find_next_card 中实现

    return True, '执行下一步', None
