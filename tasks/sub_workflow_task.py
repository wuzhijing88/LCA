# -*- coding: utf-8 -*-
"""
子工作流任务 - 引用并执行外部工作流文件
支持将完整工作流封装为单个卡片，实现模块化复用

限制：
1. 子工作流内的跳转只能在子工作流内部生效
2. 子工作流的起点只能有一个
3. 子工作流不能嵌套（子工作流内不能包含子工作流卡片）
4. 子工作流有独立的上下文，不与父工作流共享
"""
import json
import logging
import os
import threading
import time
from typing import Dict, Any, Tuple, Optional, Set

from tasks.task_utils import (
    handle_failure_action,
    handle_success_action,
)
from utils.sub_workflow_path import resolve_sub_workflow_path
from utils.thread_start_utils import THREAD_START_TASK_TYPE, is_thread_start_task_type

logger = logging.getLogger(__name__)

TASK_NAME = '子工作流'
SUPPORTED_CONNECTION_TYPES = frozenset({"sequential", "success", "failure", "random"})


def _build_sub_workflow_runtime_id(
    parent_workflow_context: Any,
    workflow_filepath: Optional[str],
    parent_card_id: Optional[int],
    execution_token: Optional[str] = None,
) -> str:
    parent_workflow_id = str(getattr(parent_workflow_context, "workflow_id", "") or "default").strip() or "default"
    normalized_parent_card_id = _normalize_card_id(parent_card_id)
    if normalized_parent_card_id is None:
        raise ValueError(f"父工作流卡片ID无效: {parent_card_id!r}")
    normalized_workflow_filepath = os.path.abspath(os.path.normpath(str(workflow_filepath or "").strip())) if workflow_filepath else "inline"
    runtime_id = f"{parent_workflow_id}::sub::{normalized_parent_card_id}::{normalized_workflow_filepath}"

    normalized_token = str(execution_token or "").strip()
    if normalized_token:
        runtime_id = f"{runtime_id}::run::{normalized_token}"
    return runtime_id


def _normalize_card_id(card_id: Any) -> Optional[int]:
    """将卡片ID标准化为int，非法值返回None。"""
    if card_id is None or isinstance(card_id, bool):
        return None
    if isinstance(card_id, int):
        return card_id
    if isinstance(card_id, float):
        if card_id.is_integer():
            return int(card_id)
        return None

    text = str(card_id).strip()
    if not text:
        return None
    try:
        if "." in text or "e" in text.lower():
            as_float = float(text)
            if as_float.is_integer():
                return int(as_float)
            return None
        return int(text)
    except (TypeError, ValueError):
        return None


def _normalize_connection_type(conn_type: Any) -> str:
    text = str(conn_type or "sequential").strip().lower()
    if not text:
        return "sequential"
    return text


def _sanitize_connections(connections: Any) -> list:
    """清洗连接数据，统一ID类型并过滤非法连接。"""
    if not isinstance(connections, list):
        logger.warning(f"[子工作流] connections 数据格式错误: {type(connections)}")
        return []

    sanitized = []
    for conn in connections:
        if not isinstance(conn, dict):
            logger.warning(f"[子工作流] 跳过无效连接条目: {type(conn)}")
            continue

        start_id = _normalize_card_id(conn.get("start_card_id"))
        end_id = _normalize_card_id(conn.get("end_card_id"))
        conn_type = _normalize_connection_type(conn.get("type", "sequential"))

        if conn_type not in SUPPORTED_CONNECTION_TYPES:
            logger.warning(f"[子工作流] 跳过未知连接类型: {conn_type}")
            continue
        if start_id is None or end_id is None:
            logger.warning(
                f"[子工作流] 跳过无效连接ID: start={conn.get('start_card_id')}, end={conn.get('end_card_id')}"
            )
            continue

        normalized_conn = dict(conn)
        normalized_conn["start_card_id"] = start_id
        normalized_conn["end_card_id"] = end_id
        normalized_conn["type"] = conn_type
        sanitized.append(normalized_conn)

    return sanitized


def _normalize_cards(cards: Any) -> Tuple[Optional[list], Optional[str]]:
    """清洗卡片数据，统一ID类型并检测重复ID。"""
    if not isinstance(cards, list):
        return None, f"cards 数据格式错误: {type(cards)}"

    normalized_cards = []
    invalid_indexes = []
    duplicate_ids = []
    seen_ids = set()

    for index, card in enumerate(cards):
        if not isinstance(card, dict):
            invalid_indexes.append(index)
            continue
        card_id = _normalize_card_id(card.get("id"))
        if card_id is None:
            invalid_indexes.append(index)
            continue
        if card_id in seen_ids:
            duplicate_ids.append(card_id)
            continue
        seen_ids.add(card_id)
        normalized_card = dict(card)
        normalized_card["id"] = card_id
        normalized_cards.append(normalized_card)

    if invalid_indexes:
        return None, f"子工作流卡片数据无效（缺少或非法ID），索引: {invalid_indexes}"
    if duplicate_ids:
        return None, f"子工作流卡片ID重复: {sorted(set(duplicate_ids))}"
    return normalized_cards, None


def _is_start_task_type(task_type: Any) -> bool:
    """统一判定线程起点类型。"""
    return is_thread_start_task_type(task_type)


def get_params_definition() -> Dict[str, Dict[str, Any]]:
    """获取子工作流任务的参数定义"""
    return {
        "workflow_file": {
            "label": "工作流文件",
            "type": "file",
            "file_filter": "工作流文件 (*.json);;所有文件 (*)",
            "tooltip": "选择要执行的工作流文件（.json）",
            "required": True
        },

        # 执行设置
        "---exec_settings---": {
            "type": "separator",
            "label": "执行设置"
        },
        "inherit_window": {
            "type": "bool",
            "label": "继承目标窗口",
            "default": True,
            "tooltip": "子工作流是否使用主工作流的目标窗口"
        },

        # 执行后操作
        "---post_exec---": {
            "type": "separator",
            "label": "执行后操作"
        },
        "on_success": {
            "type": "select",
            "label": "成功时",
            "options": ["执行下一步", "继续执行本步骤", "跳转到步骤", "停止工作流"],
            "default": "执行下一步",
            "tooltip": "子工作流执行成功时的操作"
        },
        "success_jump_target_id": {
            "type": "int",
            "label": "成功跳转目标",
            "required": False,
            "widget_hint": "card_selector",
            "condition": {"param": "on_success", "value": "跳转到步骤"},
            "tooltip": "成功时跳转到的卡片"
        },
        "on_failure": {
            "type": "select",
            "label": "失败时",
            "options": ["执行下一步", "继续执行本步骤", "跳转到步骤", "停止工作流"],
            "default": "执行下一步",
            "tooltip": "子工作流执行失败时的操作"
        },
        "failure_jump_target_id": {
            "type": "int",
            "label": "失败跳转目标",
            "required": False,
            "widget_hint": "card_selector",
            "condition": {"param": "on_failure", "value": "跳转到步骤"},
            "tooltip": "失败时跳转到的卡片"
        }
    }


def _extract_parent_workflow_file(kwargs: Dict[str, Any]) -> Optional[str]:
    """从执行上下文提取主工作流文件路径。"""
    explicit_path = str(kwargs.get("parent_workflow_file") or "").strip()
    if explicit_path:
        return explicit_path

    executor = kwargs.get("executor")
    if executor is not None:
        workflow_filepath = str(getattr(executor, "workflow_filepath", "") or "").strip()
        if workflow_filepath:
            return workflow_filepath

    return None


def _resolve_sub_workflow_display_name(workflow_data: Dict[str, Any], workflow_file: str) -> str:
    """解析子工作流展示名，优先使用工作流内名称，其次回退到文件名。"""
    if isinstance(workflow_data, dict):
        for key in ("name", "workflow_name", "title"):
            candidate = str(workflow_data.get(key) or "").strip()
            if candidate:
                return candidate

    filename = os.path.basename(str(workflow_file or "").strip())
    display_name, _ = os.path.splitext(filename)
    return display_name or "子工作流"


def _handle_success(params: Dict[str, Any], card_id: Optional[int]) -> Tuple[bool, str, Optional[int]]:
    """统一复用任务动作解析，避免子工作流成功收口缺失。"""
    return handle_success_action(params, card_id)


def _handle_failure(params: Dict[str, Any], card_id: Optional[int], error_msg: str = "") -> Tuple[bool, str, Optional[int]]:
    """统一复用任务动作解析，保留原失败收口签名。"""
    return handle_failure_action(params, card_id)


def execute_task(params: Dict[str, Any], counters: Dict[str, int],
                execution_mode='foreground', **kwargs) -> Tuple[bool, str, Optional[int]]:
    """
    执行子工作流任务

    Args:
        params: 任务参数
        counters: 全局计数器字典
        execution_mode: 执行模式
        **kwargs: 其他参数（card_id, target_hwnd, images_dir, stop_checker等）

    Returns:
        Tuple[bool, str, Optional[int]]: (是否成功, 动作, 跳转目标ID)
    """
    card_id = _normalize_card_id(kwargs.get('card_id'))
    logger.info(f"[子工作流] 开始执行 - 卡片ID: {card_id}")

    if card_id is None:
        logger.error("[子工作流] 父工作流卡片ID无效")
        return _handle_failure(params, card_id, "父工作流卡片ID无效")

    # 获取工作流文件路径
    workflow_file = params.get('workflow_file')
    parent_workflow_file = _extract_parent_workflow_file(kwargs)

    if not workflow_file:
        logger.error("[子工作流] 未指定工作流文件")
        return _handle_failure(params, card_id, "未指定工作流文件")

    resolved_workflow_file = resolve_sub_workflow_path(
        workflow_file,
        parent_workflow_file=parent_workflow_file,
    )
    if not resolved_workflow_file:
        logger.error(f"[子工作流] 工作流文件不存在，解析失败: {workflow_file}")
        if parent_workflow_file:
            logger.error(f"[子工作流] 主工作流路径: {parent_workflow_file}")
        return _handle_failure(params, card_id, f"文件不存在: {workflow_file}")

    if os.path.normcase(os.path.normpath(str(workflow_file))) != os.path.normcase(
        os.path.normpath(resolved_workflow_file)
    ):
        logger.info(
            f"[子工作流] 已智能修正路径: 原始='{workflow_file}' -> 解析='{resolved_workflow_file}'"
        )
    workflow_file = resolved_workflow_file

    try:
        # 加载工作流文件
        logger.info(f"[子工作流] 加载工作流文件: {workflow_file}")
        with open(workflow_file, 'r', encoding='utf-8') as f:
            workflow_data = json.load(f)
        from task_workflow.workflow_sanitize import sanitize_workflow_data

        sanitize_workflow_data(workflow_data)

        # 验证工作流格式
        if 'cards' not in workflow_data:
            # 检查是否是 .module 格式（包含 workflow 字段）
            if 'workflow' in workflow_data:
                workflow_data = workflow_data['workflow']
            else:
                logger.error("[子工作流] 工作流文件格式错误：缺少 cards 字段")
                return _handle_failure(params, card_id, "工作流文件格式错误")

        cards, card_error = _normalize_cards(workflow_data.get('cards', []))
        if card_error:
            logger.error(f"[子工作流] {card_error}")
            return _handle_failure(params, card_id, card_error)

        connections = _sanitize_connections(workflow_data.get('connections', []))

        logger.info(f"[子工作流] 加载成功 - {len(cards)} 个卡片, {len(connections)} 个连接")

        if not cards:
            logger.warning("[子工作流] 工作流为空，视为成功")
            return _handle_success(params, card_id)

        # 【限制3】检查子工作流中是否包含子工作流卡片（禁止嵌套）
        nested_sub_workflows = [c for c in cards if c.get('task_type') == '子工作流']
        if nested_sub_workflows:
            nested_ids = [c.get('id') for c in nested_sub_workflows]
            logger.error(f"[子工作流] 检测到嵌套子工作流（卡片ID: {nested_ids}），子工作流不允许嵌套")
            return _handle_failure(params, card_id, f"子工作流不允许嵌套，发现嵌套卡片: {nested_ids}")

        # 【限制2】检查线程起点数量（必须且只能有一个）
        start_cards = [c for c in cards if _is_start_task_type(c.get('task_type'))]
        if len(start_cards) != 1:
            start_ids = [c.get('id') for c in start_cards]
            logger.error(f"[子工作流] 线程起点数量异常（卡片ID: {start_ids}），子工作流必须且只能有一个线程起点")
            return _handle_failure(params, card_id, f"子工作流必须且只能有一个{THREAD_START_TASK_TYPE}，当前数量: {len(start_cards)}")

        # 构建子工作流内的有效卡片ID集合（用于跳转验证）
        valid_card_ids = {card['id'] for card in cards}

        sub_workflow_name = _resolve_sub_workflow_display_name(workflow_data, workflow_file)

        # 执行子工作流
        success = _execute_sub_workflow(
            cards=cards,
            connections=connections,
            counters=counters,
            execution_mode=execution_mode,
            parent_card_id=card_id,
            inherit_window=params.get('inherit_window', True),
            sub_workflow_name=sub_workflow_name,
            valid_card_ids=valid_card_ids,
            workflow_filepath=workflow_file,
            **kwargs
        )

        if success:
            logger.info(f"[子工作流] 执行成功: {os.path.basename(workflow_file)}")
            return _handle_success(params, card_id)
        else:
            logger.error(f"[子工作流] 执行失败: {os.path.basename(workflow_file)}")
            return _handle_failure(params, card_id, "子工作流执行失败")

    except json.JSONDecodeError as e:
        logger.error(f"[子工作流] JSON解析错误: {e}")
        return _handle_failure(params, card_id, f"JSON解析错误: {e}")
    except Exception as e:
        logger.error(f"[子工作流] 执行异常: {e}", exc_info=True)
        return _handle_failure(params, card_id, f"执行异常: {e}")


def _execute_sub_workflow(cards: list, connections: list, counters: Dict,
                         execution_mode: str, parent_card_id: Optional[int],
                         inherit_window: bool = True, sub_workflow_name: str = "",
                         valid_card_ids: Set[int] = None,
                         workflow_filepath: Optional[str] = None,
                         **kwargs) -> bool:
    """
    执行子工作流内部逻辑

    Args:
        cards: 卡片列表
        connections: 连接列表
        counters: 计数器（父工作流的，但子工作流使用独立副本）
        execution_mode: 执行模式
        parent_card_id: 父卡片ID
        inherit_window: 是否继承目标窗口
        valid_card_ids: 子工作流内有效的卡片ID集合（用于跳转验证）
        **kwargs: 其他参数

    Returns:
        bool: 执行是否成功
    """
    sub_workflow_context = None
    sub_workflow_id = None
    parent_workflow_context = kwargs.get('workflow_context')
    previous_context = None
    context_switched = False
    parent_executor = kwargs.get('executor')
    stop_checker = kwargs.get('stop_checker')
    if parent_executor is None:
        raise RuntimeError("父工作流执行器不可用")

    try:
        # 导入任务模块
        from tasks import get_task_modules

        # 【限制4】创建子工作流独立的上下文
        from task_workflow.workflow_context import (
            get_current_workflow_context,
            get_workflow_context,
            set_current_workflow_context,
        )

        if parent_workflow_context is None:
            context_getter = getattr(parent_executor, "_get_workflow_context", None)
            if not callable(context_getter):
                raise RuntimeError("父工作流执行器缺少上下文入口")
            parent_workflow_context = context_getter()

        if parent_workflow_context is None:
            raise RuntimeError("父工作流上下文不可用")

        if callable(stop_checker) and stop_checker():
            logger.info("[子工作流] 执行前检测到停止请求")
            return False

        sub_workflow_id = _build_sub_workflow_runtime_id(
            parent_workflow_context=parent_workflow_context,
            workflow_filepath=workflow_filepath,
            parent_card_id=parent_card_id,
            execution_token=f"{threading.get_ident()}-{time.monotonic_ns()}",
        )

        sub_workflow_context = get_workflow_context(sub_workflow_id)
        sub_workflow_context.clear()
        logger.info("[子工作流] 创建独立上下文")

        previous_context = get_current_workflow_context()
        set_current_workflow_context(sub_workflow_context)
        context_switched = True
        logger.debug("[子工作流] 已切换当前上下文到子工作流上下文")

        # 【限制4】执行参数继承父链路，但子工作流执行上下文、计数器和步数限制保持独立
        target_hwnd = kwargs.get('target_hwnd') if inherit_window else None
        images_dir = kwargs.get('images_dir', 'images')
        pause_checker = kwargs.get('pause_checker')

        if valid_card_ids is None:
            valid_card_ids = {card['id'] for card in cards}
        else:
            invalid_card_ids = [
                card_id
                for card_id in valid_card_ids
                if _normalize_card_id(card_id) is None
            ]
            if invalid_card_ids:
                raise RuntimeError(f"子工作流有效卡片ID无效: {invalid_card_ids}")
            normalized_valid_card_ids = {
                normalized_id
                for normalized_id in (_normalize_card_id(card_id) for card_id in valid_card_ids)
                if normalized_id is not None
            }
            if not normalized_valid_card_ids:
                raise RuntimeError("子工作流有效卡片ID集合为空")
            valid_card_ids = normalized_valid_card_ids

        card_map = {card['id']: card for card in cards}
        start_type_cards = [card for card in cards if _is_start_task_type(card.get('task_type'))]
        if not start_type_cards:
            raise RuntimeError(f"子工作流缺少{THREAD_START_TASK_TYPE}")

        start_card_id = start_type_cards[0]['id']
        logger.info(f"[子工作流] 从卡片 {start_card_id} 开始执行，无固定步数限制")

        from task_workflow.runtime_factory import create_inprocess_runtime

        sub_executor = create_inprocess_runtime(
            {
                "session_mode": "single",
                "cards_data": card_map,
                "connections_data": connections,
                "target_window_title": getattr(parent_executor, 'target_window_title', None),
                "execution_mode": execution_mode,
                "start_card_id": start_card_id,
                "images_dir": images_dir,
                "target_hwnd": target_hwnd,
                "workflow_id": sub_workflow_id,
                "workflow_filepath": workflow_filepath,
                "workflow_context": sub_workflow_context,
                "allowed_card_ids": valid_card_ids,
                "disallowed_task_types": {TASK_NAME},
                "max_execution_steps": None,
                "default_step_log_scope": "sub",
                "default_step_log_name": sub_workflow_name,
                "external_stop_checker": stop_checker if callable(stop_checker) else None,
                "external_pause_checker": pause_checker if callable(pause_checker) else None,
                "cleanup_runtime_image_on_finish": False,
                "clear_runtime_state_on_start": False,
                "infinite_loop_guard_enabled": True,
            },
            task_modules=get_task_modules(),
        )
        if not isinstance(counters, dict):
            raise TypeError("子工作流计数器格式无效")
        child_counters = getattr(sub_executor, '_persistent_counters', None)
        if not isinstance(child_counters, dict):
            raise TypeError("子工作流执行器计数器格式无效")
        child_counters.update(dict(counters))

        if parent_executor is not None and hasattr(parent_executor, 'step_log'):
            try:
                sub_executor.step_log.connect(parent_executor.step_log.emit)
            except Exception as exc:
                logger.debug(f"[子工作流] 绑定步骤日志透传失败: {exc}")
        if (
            parent_executor is not None
            and hasattr(parent_executor, 'show_warning')
            and hasattr(sub_executor, 'show_warning')
        ):
            try:
                sub_executor.show_warning.connect(parent_executor.show_warning.emit)
            except Exception as exc:
                logger.debug(f"[子工作流] 绑定警告弹窗透传失败: {exc}")

        if callable(stop_checker) and stop_checker():
            logger.info("[子工作流] 执行前检测到停止请求")
            return False

        sub_executor.run()
        sub_execution_succeeded = bool(sub_executor._last_execution_success)
        logger.info(
            f"[子工作流] 执行完成，结果: {'成功' if sub_execution_succeeded else '失败'}"
        )
        return sub_execution_succeeded

    except Exception as e:
        logger.error(f"[子工作流] 内部执行异常: {e}", exc_info=True)
        return False
    finally:
        if context_switched:
            try:
                from task_workflow.workflow_context import set_current_workflow_context
                set_current_workflow_context(previous_context)
                logger.debug("[子工作流] 已恢复父工作流上下文")
            except Exception as exc:
                logger.warning(f"[子工作流] 恢复父工作流上下文失败: {exc}")

        if sub_workflow_context is not None and sub_workflow_context is not previous_context:
            try:
                if sub_workflow_id:
                    from task_workflow.workflow_context import clear_workflow_context

                    clear_workflow_context(sub_workflow_id)
                else:
                    sub_workflow_context.clear()
            except Exception as exc:
                logger.debug(f"[子工作流] 清理子工作流上下文失败: {exc}")
