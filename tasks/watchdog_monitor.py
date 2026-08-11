# -*- coding: utf-8 -*-
"""
附加条件 - 监测指定卡片的执行状态
新架构：作为被监控卡片的附加条件（modifier），同步检查而非异步轮询
"""

import logging
import time
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

# 任务类型标识
TASK_TYPE = "附加条件"

# 全局监控状态存储
# 格式: {workflow_id: {condition_card_id: {target_card_id: {count, first_time, last_check_time, monitoring_type, triggered_count}}}}
_MONITOR_STATES = {}



def get_params_definition() -> Dict[str, Dict[str, Any]]:
    """获取附加条件的参数定义"""
    return {
        "---monitor_condition---": {"type": "separator", "label": "触发条件"},
        "monitor_type": {
            "label": "监控类型",
            "type": "select",
            "options": ["监控失败", "监控成功"],
            "default": "监控失败",
            "tooltip": "监控失败：持续失败时触发\n监控成功：持续成功时触发"
        },

        "monitor_mode": {
            "label": "监控模式",
            "type": "select",
            "options": ["按次数", "按持续时间", "按次数和时间"],
            "default": "按次数",
            "tooltip": "选择如何判断监控条件：次数、持续时间，或两者都满足"
        },

        "count_threshold": {
            "label": "次数阈值",
            "type": "int",
            "default": 5,
            "min": 1,
            "max": 100,
            "tooltip": "被监控卡片累计失败/成功多少次后触发",
            "condition": {"param": "monitor_mode", "value": ["按次数", "按次数和时间"], "operator": "in"}
        },

        "duration_threshold": {
            "label": "持续时间阈值",
            "type": "int",
            "default": 60,
            "min": 1,
            "max": 3600,
            "tooltip": "被监控卡片持续失败/成功多长时间后触发",
            "condition": {"param": "monitor_mode", "value": ["按持续时间", "按次数和时间"], "operator": "in"}
        },

        "duration_unit": {
            "label": "时间单位",
            "type": "select",
            "options": ["秒", "分钟"],
            "default": "秒",
            "tooltip": "持续时间阈值的单位",
            "condition": {"param": "monitor_mode", "value": ["按持续时间", "按次数和时间"], "operator": "in"}
        },

        "---monitor_action---": {"type": "separator", "label": "触发动作"},
        "action_on_trigger": {
            "label": "触发后动作",
            "type": "select",
            "options": ["跳转到指定卡片", "停止工作流"],
            "default": "跳转到指定卡片",
            "tooltip": "监控条件满足时的动作：跳转到指定卡片或直接停止工作流"
        },

        "jump_target_card_id": {
            "label": "跳转目标卡片",
            "type": "int",
            "widget_hint": "card_selector",
            "default": None,
            "tooltip": "监控触发后，被监控卡片将跳转到此卡片\n如果不设置，监控触发时将终止工作流",
            "condition": {"param": "action_on_trigger", "value": "跳转到指定卡片"}
        },

        "reset_after_trigger": {
            "label": "触发后重置监控",
            "type": "bool",
            "default": True,
            "tooltip": "触发动作后是否重置监控状态（次数和时间归零）"
        },

        "---trigger_limit---": {"type": "separator", "label": "触发次数限制"},
        "enable_trigger_limit": {
            "label": "启用触发次数限制",
            "type": "bool",
            "default": False,
            "tooltip": "启用后，附加条件最多触发指定次数，达到次数后即使满足条件也不再触发"
        },

        "max_trigger_count": {
            "label": "最大触发次数",
            "type": "int",
            "default": 1,
            "min": 1,
            "max": 1000,
            "tooltip": "附加条件最多可以触发多少次（达到此次数后将不再触发）",
            "condition": {"param": "enable_trigger_limit", "value": True}
        },

        # 隐藏参数：标记目标卡片是否支持计数器
        "target_supports_counter": {
            "type": "hidden",
            "default": False,
            "tooltip": "内部参数：标记被监控卡片是否支持计数器功能"
        },

        "---counter_reset---": {
            "type": "separator",
            "label": "计数器重置（可选）",
            "condition": {"param": "target_supports_counter", "value": True}
        },
        "enable_counter_reset": {
            "label": "启用计数器重置",
            "type": "bool",
            "default": False,
            "tooltip": "如果被监控卡片是计数器类型，触发后是否重置其计数器",
            "condition": {"param": "target_supports_counter", "value": True}
        },

        "counter_reset_value": {
            "label": "重置计数器到",
            "type": "int",
            "default": 0,
            "tooltip": "将计数器重置到的数值（通常为0）",
            "condition": [
                {"param": "target_supports_counter", "value": True},
                {"param": "enable_counter_reset", "value": True, "operator": "and"}
            ]
        },

    }


def get_monitor_state(workflow_id: str, monitor_card_id: int, target_card_id: int, monitor_type: str) -> Dict[str, Any]:
    """获取监控状态"""
    if workflow_id not in _MONITOR_STATES:
        _MONITOR_STATES[workflow_id] = {}
    if monitor_card_id not in _MONITOR_STATES[workflow_id]:
        _MONITOR_STATES[workflow_id][monitor_card_id] = {}
    if target_card_id not in _MONITOR_STATES[workflow_id][monitor_card_id]:
        _MONITOR_STATES[workflow_id][monitor_card_id][target_card_id] = {
            "count": 0,
            "first_time": None,
            "last_check_time": time.time(),
            "monitoring_type": monitor_type,
            "triggered_count": 0  # 新增：已触发次数
        }
    return _MONITOR_STATES[workflow_id][monitor_card_id][target_card_id]


def reset_monitor_state(workflow_id: str, monitor_card_id: int, target_card_id: int, monitor_type: str, keep_triggered_count: bool = False):
    """重置监控状态

    Args:
        workflow_id: 工作流ID
        monitor_card_id: 监控卡片ID
        target_card_id: 目标卡片ID
        monitor_type: 监控类型
        keep_triggered_count: 是否保留已触发次数（用于触发次数限制功能）
    """
    if workflow_id in _MONITOR_STATES:
        if monitor_card_id in _MONITOR_STATES[workflow_id]:
            if target_card_id in _MONITOR_STATES[workflow_id][monitor_card_id]:
                # 保存已触发次数
                old_triggered_count = _MONITOR_STATES[workflow_id][monitor_card_id][target_card_id].get("triggered_count", 0)

                _MONITOR_STATES[workflow_id][monitor_card_id][target_card_id] = {
                    "count": 0,
                    "first_time": None,
                    "last_check_time": time.time(),
                    "monitoring_type": monitor_type,
                    "triggered_count": old_triggered_count if keep_triggered_count else 0
                }
                logger.info(f"[附加条件 {monitor_card_id}] 已重置监控状态（保留触发次数: {keep_triggered_count}）")


def update_execution_record(workflow_id: str, condition_card_id: int, target_card_id: int,
                            current_result: bool, monitor_type: str):
    """更新执行记录"""
    state = get_monitor_state(workflow_id, condition_card_id, target_card_id, monitor_type)
    current_time = time.time()

    # 检查当前结果是否符合监控类型
    is_monitoring_failure = (monitor_type == "监控失败")
    should_count = (not current_result) if is_monitoring_failure else current_result

    # 详细日志
    logger.warning(f"[附加条件逻辑] 附加条件 {condition_card_id} -> 卡片 {target_card_id}")
    logger.warning(f"[附加条件逻辑] monitor_type='{monitor_type}', 卡片执行结果={current_result}")
    logger.warning(f"[附加条件逻辑] is_monitoring_failure={is_monitoring_failure}, should_count={should_count}")

    if should_count:
        # 符合监控条件（失败或成功）
        state["count"] += 1
        if state["first_time"] is None:
            state["first_time"] = current_time

        type_str = "失败" if is_monitoring_failure else "成功"
        logger.warning(f"[附加条件计数] 记录{type_str}: 卡片 {target_card_id} {type_str}次数 {state['count']}")
        logger.debug(f"[附加条件 {condition_card_id}] 记录{type_str}: 卡片 {target_card_id} {type_str}次数 {state['count']}")
    else:
        # 不符合监控条件，重置状态
        state["count"] = 0
        state["first_time"] = None
        type_str = "成功" if is_monitoring_failure else "失败"
        logger.warning(f"[附加条件重置] 卡片 {target_card_id} 执行{type_str}，重置监控计数")
        logger.debug(f"[附加条件 {condition_card_id}] 卡片 {target_card_id} 执行{type_str}，重置监控")

    state["last_check_time"] = current_time
    state["monitoring_type"] = monitor_type


def check_trigger_condition(state: Dict[str, Any], monitor_mode: str,
                            count_threshold: int, duration_threshold: int, monitor_type: str) -> Tuple[bool, str]:
    """检查是否满足触发条件"""
    current_time = time.time()
    count = state["count"]
    first_time = state["first_time"]
    type_str = "失败" if monitor_type == "监控失败" else "成功"

    logger.debug(f"[触发条件检查] 模式={monitor_mode}, count={count}, 阈值={count_threshold}, first_time={first_time}")

    if monitor_mode == "按次数":
        if count >= count_threshold:
            logger.info(f"[触发条件检查] 按次数触发: {count} >= {count_threshold}")
            return True, f"{type_str}次数({count})达到阈值({count_threshold})"
        else:
            logger.debug(f"[触发条件检查] 次数未达阈值: {count} < {count_threshold}")

    elif monitor_mode == "按持续时间":
        if first_time is not None:
            duration = current_time - first_time
            if duration >= duration_threshold:
                logger.info(f"[触发条件检查] 按时间触发: {duration:.1f} >= {duration_threshold}")
                return True, f"持续{type_str}时间({duration:.1f}秒)达到阈值({duration_threshold}秒)"
            else:
                logger.debug(f"[触发条件检查] 时间未达阈值: {duration:.1f} < {duration_threshold}")
        else:
            logger.debug(f"[触发条件检查] first_time为None，无法检查时间")

    elif monitor_mode == "按次数和时间":
        if count >= count_threshold:
            if first_time is not None:
                duration = current_time - first_time
                if duration >= duration_threshold:
                    logger.info(f"[触发条件检查] 按次数和时间触发: count={count}/{count_threshold}, duration={duration:.1f}/{duration_threshold}")
                    return True, f"{type_str}次数({count})和持续时间({duration:.1f}秒)都达到阈值"
                else:
                    logger.debug(f"[触发条件检查] 时间未达: {duration:.1f} < {duration_threshold}")
            else:
                logger.debug(f"[触发条件检查] first_time为None，无法检查时间")
        else:
            logger.debug(f"[触发条件检查] 次数未达: {count} < {count_threshold}")

    logger.debug(f"[触发条件检查] 未满足触发条件")
    return False, ""


def execute_card(card_id: int, parameters: Dict[str, Any], context: Any, **kwargs) -> Tuple[bool, str]:
    """
    执行附加条件逻辑 - 返回监控配置（附加条件模式）

    新架构：附加条件作为被监控卡片的modifier
    - 附加条件不再独立执行循环，而是将自己注册为被监控卡片的监控器
    - 每次被监控卡片执行后，执行器会自动检查监控条件
    - 这样附加条件和被监控卡片视为一个整体同时运行

    Args:
        card_id: 当前附加条件卡片的ID
        parameters: 卡片参数
        context: 工作流上下文
        **kwargs: 其他参数，包括connections

    Returns:
        (成功标志, 监控配置信息)
    """
    try:
        # 获取连接信息，找出被监控的卡片
        connections = kwargs.get('connections', [])
        logger.info(f"[附加条件 {card_id}] 收到 {len(connections)} 个连接")

        # 查找从当前卡片出发的sequential连接
        target_card_id = None
        for conn in connections:
            logger.debug(f"[附加条件 {card_id}] 检查连接: {conn.get('start_card_id')} -> {conn.get('end_card_id')} (type: {conn.get('type')})")
            if conn.get('start_card_id') == card_id and conn.get('type') == 'sequential':
                target_card_id = conn.get('end_card_id')
                logger.info(f"[附加条件 {card_id}] 找到被监控卡片: {target_card_id}")
                break

        if target_card_id is None:
            msg = "未连接被监控卡片，请通过蓝色输出端连接目标卡片"
            logger.warning(f"[附加条件 {card_id}] {msg}")
            return True, msg

        # 获取参数
        monitor_type = parameters.get("monitor_type", "监控失败")
        monitor_mode = parameters.get("monitor_mode", "按次数")
        count_threshold = parameters.get("count_threshold", 5)
        duration_threshold = parameters.get("duration_threshold", 60)
        duration_unit = parameters.get("duration_unit", "秒")

        # 将时间阈值转换为秒
        if duration_unit == "分钟":
            duration_threshold_seconds = duration_threshold * 60
        else:
            duration_threshold_seconds = duration_threshold

        action_on_trigger = parameters.get("action_on_trigger", "跳转到指定卡片")
        jump_target_card_id = parameters.get("jump_target_card_id", None)
        reset_after_trigger = parameters.get("reset_after_trigger", True)
        enable_trigger_limit = parameters.get("enable_trigger_limit", False)
        max_trigger_count = parameters.get("max_trigger_count", 1)
        enable_counter_reset = parameters.get("enable_counter_reset", False)
        counter_reset_value = parameters.get("counter_reset_value", 0)
        show_log = True

        logger.info(f"[附加条件 {card_id}] 参数 - 触发动作: {action_on_trigger}, 跳转目标: {jump_target_card_id}")
        logger.info(f"[附加条件 {card_id}] 时间阈值: {duration_threshold}{duration_unit} ({duration_threshold_seconds}秒)")

        # 获取工作流ID
        workflow_id = str(context.workflow_id) if hasattr(context, 'workflow_id') else "default"

        # 【新架构】构建监控配置对象，传递给执行器
        monitor_config = {
            "monitor_card_id": card_id,
            "target_card_id": target_card_id,
            "monitor_type": monitor_type,
            "monitor_mode": monitor_mode,
            "count_threshold": count_threshold,
            "duration_threshold": duration_threshold_seconds,
            "duration_unit": duration_unit,
            "action_on_trigger": action_on_trigger,
            "jump_target_card_id": jump_target_card_id,
            "reset_after_trigger": reset_after_trigger,
            "enable_trigger_limit": enable_trigger_limit,
            "max_trigger_count": max_trigger_count,
            "enable_counter_reset": enable_counter_reset,
            "counter_reset_value": counter_reset_value,
            "show_log": show_log,
            "workflow_id": workflow_id
        }

        # 将监控配置注册到上下文中
        if not hasattr(context, '_monitor_configs'):
            context._monitor_configs = {}
        context._monitor_configs[target_card_id] = monitor_config

        logger.info(f"[附加条件 {card_id}] 已注册监控配置到被监控卡片 {target_card_id}")

        msg = f"附加条件已建立：监控卡片 {target_card_id}"
        return True, msg

    except Exception as e:
        error_msg = f"附加条件执行失败: {str(e)}"
        logger.error(f"[附加条件 {card_id}] {error_msg}", exc_info=True)
        return False, error_msg


def check_monitor_trigger(monitor_config: Dict[str, Any], target_card_result: bool, context: Any) -> Optional[Dict[str, Any]]:
    """
    检查附加条件是否触发（由执行器在被监控卡片执行后调用）

    Args:
        monitor_config: 监控配置
        target_card_result: 被监控卡片的执行结果
        context: 工作流上下文

    Returns:
        如果触发，返回触发动作字典 {"action": "jump"|"stop", "target_card_id": int}
        否则返回 None
    """
    try:
        # 【闪退修复】使用.get()方法替代直接访问，防止KeyError闪退
        condition_card_id = monitor_config.get("monitor_card_id")
        target_card_id = monitor_config.get("target_card_id")
        monitor_type = monitor_config.get("monitor_type")
        monitor_mode = monitor_config.get("monitor_mode")

        # 【闪退修复】添加必填字段验证，防止None值导致后续错误
        if not all([condition_card_id, target_card_id, monitor_type, monitor_mode]):
            logger.error(f"[附加条件检查] 监控配置缺少必填字段: monitor_card_id={condition_card_id}, target_card_id={target_card_id}, monitor_type={monitor_type}, monitor_mode={monitor_mode}")
            return None

        # 修复：确保count_threshold和duration_threshold是整数类型
        count_threshold_raw = monitor_config.get("count_threshold", 1)
        duration_threshold_raw = monitor_config.get("duration_threshold", 60)
        count_threshold = int(count_threshold_raw) if isinstance(count_threshold_raw, (str, int, float)) else 1
        duration_threshold = int(duration_threshold_raw) if isinstance(duration_threshold_raw, (str, int, float)) else 60

        action_on_trigger = monitor_config.get("action_on_trigger", "stop_workflow")
        jump_target_card_id = monitor_config.get("jump_target_card_id")
        reset_after_trigger = monitor_config.get("reset_after_trigger", False)
        enable_trigger_limit = monitor_config.get("enable_trigger_limit", False)
        max_trigger_count = monitor_config.get("max_trigger_count", 1)
        enable_counter_reset = monitor_config.get("enable_counter_reset", False)
        counter_reset_value = monitor_config.get("counter_reset_value", 0)
        show_log = True
        workflow_id = monitor_config.get("workflow_id", 0)
        duration_unit = monitor_config.get("duration_unit", "秒")

        # 更新执行记录
        update_execution_record(workflow_id, condition_card_id, target_card_id, target_card_result, monitor_type)

        # 获取当前监控状态
        state = get_monitor_state(workflow_id, condition_card_id, target_card_id, monitor_type)

        # 检查是否已达到触发次数限制
        triggered_count = state.get("triggered_count", 0)
        if enable_trigger_limit and triggered_count >= max_trigger_count:
            # 已达到最大触发次数，不再触发
            if show_log and triggered_count == max_trigger_count:
                # 只在刚达到限制时显示一次日志
                logger.warning(f"[附加条件 {condition_card_id}] 已达到最大触发次数限制({max_trigger_count}次)，不再触发")
            return None

        # 定期输出监控状态日志
        if show_log:
            type_str = "失败" if monitor_type == "监控失败" else "成功"
            current_time = time.time()

            if monitor_mode == "按次数":
                status = f"{type_str}次数: {state['count']}/{count_threshold}"
            elif monitor_mode == "按持续时间":
                if state['first_time']:
                    duration = current_time - state['first_time']
                    if duration_unit == "分钟":
                        status = f"持续{type_str}: {duration/60:.1f}/{count_threshold}分钟"
                    else:
                        status = f"持续{type_str}: {duration:.1f}/{count_threshold}秒"
                else:
                    opposite_str = "失败" if monitor_type == "监控成功" else "成功"
                    status = f"监控中（最后执行{opposite_str}）"
            else:  # 按次数和时间
                duration_str = ""
                if state['first_time']:
                    duration = current_time - state['first_time']
                    if duration_unit == "分钟":
                        duration_str = f", 时间: {duration/60:.1f}/{count_threshold}分钟"
                    else:
                        duration_str = f", 时间: {duration:.1f}/{count_threshold}秒"
                status = f"次数: {state['count']}/{count_threshold}{duration_str}"

            # 如果启用了触发次数限制，在状态中显示已触发次数
            if enable_trigger_limit:
                status += f" [已触发: {triggered_count}/{max_trigger_count}]"

            logger.info(f"[附加条件检查] 附加条件 {condition_card_id} -> 卡片 {target_card_id} - {status}")

        # 检查是否满足触发条件
        should_trigger, trigger_reason = check_trigger_condition(
            state, monitor_mode, count_threshold, duration_threshold, monitor_type
        )

        if should_trigger:
            # 触发条件满足
            logger.warning(f"[附加条件触发] 附加条件 {condition_card_id}: {trigger_reason}")

            # 增加触发次数计数
            state["triggered_count"] = state.get("triggered_count", 0) + 1
            current_triggered_count = state["triggered_count"]

            # 显示触发次数信息
            if enable_trigger_limit:
                logger.warning(f"[附加条件触发] 第 {current_triggered_count}/{max_trigger_count} 次触发")

            # 重置监控状态（如果需要）
            if reset_after_trigger:
                # 如果启用了触发次数限制，重置时保留已触发次数
                reset_monitor_state(workflow_id, condition_card_id, target_card_id, monitor_type,
                                   keep_triggered_count=enable_trigger_limit)

            # 重置计数器（如果启用）
            if enable_counter_reset:
                if hasattr(context, 'reset_counter'):
                    context.reset_counter(target_card_id, counter_reset_value)
                    logger.info(f"[附加条件触发] 已重置卡片 {target_card_id} 的计数器到 {counter_reset_value}")

            # 返回触发动作
            if action_on_trigger == "停止工作流":
                return {
                    "action": "stop",
                    "reason": trigger_reason
                }
            else:  # 跳转到指定卡片
                # 修复: 确保jump_target_card_id是有效的整数,不能是None
                if jump_target_card_id is not None and isinstance(jump_target_card_id, int) and jump_target_card_id >= 0:
                    return {
                        "action": "jump",
                        "target_card_id": jump_target_card_id,
                        "reason": trigger_reason
                    }
                else:
                    logger.warning(f"[附加条件触发] 跳转目标无效或未设置: {jump_target_card_id}，不执行跳转")
                    return None

        return None

    except Exception as e:
        logger.error(f"检查附加条件触发时失败: {e}", exc_info=True)
        return None


# 向后兼容
execute_task = execute_card
run = execute_card
