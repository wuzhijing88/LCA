# -*- coding: utf-8 -*-
"""
AI工具任务 - 连续指令执行卡片。
"""

import atexit
import base64
import hashlib
import json
import logging
import os
import queue
import re
import subprocess
import sys
import threading
import time
from collections import deque
from typing import Any, Dict, List, Optional, Tuple

import cv2

from services.ai.command_routing import (
    command_requires_tool_execution as _command_requires_tool_execution,
    normalize_text_for_match as _shared_normalize_text_for_match,
)
from services.ai.direct_client import (
    request_text_response as _request_text_response,
)
from services.ai.message_builder import (
    normalize_text_messages as _normalize_text_messages,
)
from services.ai.provider_config import (
    OPENAI_API_PROTOCOL_CHAT_COMPLETIONS,
    OPENAI_API_PROTOCOL_OPTIONS,
    OPENAI_API_PROTOCOL_RESPONSES,
    OPENAI_API_URL_MODE_BASE,
    OPENAI_API_URL_MODE_OPTIONS,
    OPENAI_DEFAULT_BASE_URL,
    OPENAI_PROVIDER_MODE_OFFICIAL,
    OPENAI_PROVIDER_MODE_OPTIONS,
    normalize_ai_api_protocol as _normalize_ai_api_protocol,
    normalize_ai_api_url_mode as _normalize_ai_api_url_mode,
    normalize_ai_provider_mode as _normalize_ai_provider_mode,
    resolve_ai_api_base_url as _resolve_ai_api_base_url,
)
from services.ai.response_utils import (
    parse_json_from_text as _parse_json_from_text,
)
from tasks.task_utils import (
    handle_success_action,
    get_standard_action_params,
    merge_params_definitions,
    resolve_step_action_result,
)
from utils.input_timing import (
    DEFAULT_CLICK_HOLD_SECONDS,
    DEFAULT_DOUBLE_CLICK_INTERVAL_SECONDS,
)
from utils.worker_entry import build_main_worker_command

logger = logging.getLogger(__name__)

TASK_TYPE = "AI工具"
TASK_NAME = "AI工具"
_RUNTIME_PARAMETER_CACHE: Dict[str, Dict[str, str]] = {}
_AI_PROTOCOL_SUPPORT_CACHE: Dict[str, Tuple[bool, str]] = {}
_MCP_TOOL_CLIENT = None
_MCP_TOOL_CLIENT_LOCK = threading.Lock()
DEFAULT_TEMPERATURE = 0.1
AI_IMAGE_MAX_BYTES = 4 * 1024 * 1024
AI_IMAGE_JPEG_QUALITIES = (95, 90, 85, 80, 75, 70, 65, 60)
CONTINUOUS_COMMAND_MAX_STEPS = 2
CONTINUOUS_COMMAND_HARD_MAX_STEPS = 2
CONTINUOUS_COMMAND_MAX_ROUNDS = 12
CONTINUOUS_COMMAND_WAIT_SECONDS = 0.5
CONTINUOUS_COMMAND_MAX_INLINE_WAIT_SECONDS = 2.0
DEFAULT_DIRECT_CHAT_TIMEOUT_SECONDS = 20.0
DEFAULT_CONTINUOUS_COMMAND_TIMEOUT_SECONDS = 60.0
MIN_AI_TIMEOUT_SECONDS = 5.0


def _normalize_runtime_card_key(card_id: Optional[int]) -> str:
    if card_id is None:
        return ""
    return str(card_id).strip()


def _set_runtime_parameter_value(param_name: str, value: str, card_id: Optional[int], executor: Any) -> None:
    card_key = _normalize_runtime_card_key(card_id)
    if not card_key or not param_name:
        return
    runtime_values = _RUNTIME_PARAMETER_CACHE.setdefault(card_key, {})
    runtime_values[param_name] = value
    if executor and hasattr(executor, "param_updated"):
        try:
            executor.param_updated.emit(card_id, param_name, value)
        except Exception as exc:
            logger.debug("AI工具: 更新运行时参数失败 %s: %s", param_name, exc)


def _compose_runtime_panel_text(card_id: Optional[int]) -> str:
    card_key = _normalize_runtime_card_key(card_id)
    if not card_key:
        return ""
    runtime_values = _RUNTIME_PARAMETER_CACHE.get(card_key) or {}
    status_text = str(runtime_values.get("runtime_status") or "").strip()
    trace_text = str(runtime_values.get("execution_trace_body") or "").strip()
    lines: List[str] = []
    if status_text:
        lines.append(f"当前状态：{status_text}")
    if trace_text:
        lines.append(trace_text)
    return "\n\n".join(lines).strip()


def _sync_runtime_panel(card_id: Optional[int], executor: Any) -> None:
    _set_runtime_parameter_value("execution_trace", _compose_runtime_panel_text(card_id), card_id, executor)


def _update_runtime_parameter(param_name: str, value: Any, card_id: Optional[int], executor: Any) -> None:
    text_value = "" if value is None else str(value)
    if param_name in {"runtime_status", "execution_trace_body"}:
        _set_runtime_parameter_value(param_name, text_value, card_id, None)
        _sync_runtime_panel(card_id, executor)
        return
    _set_runtime_parameter_value(param_name, text_value, card_id, executor)


def _clear_runtime_parameters(card_id: Optional[int], executor: Any) -> None:
    card_key = _normalize_runtime_card_key(card_id)
    if not card_key:
        return
    _RUNTIME_PARAMETER_CACHE[card_key] = {}
    for param_name in ("runtime_status", "execution_trace_body", "response_format_hint"):
        _update_runtime_parameter(param_name, "", card_id, executor)


def _append_runtime_trace(text: str, card_id: Optional[int], executor: Any) -> None:
    if not text:
        return
    card_key = _normalize_runtime_card_key(card_id)
    if not card_key:
        return
    current = ((_RUNTIME_PARAMETER_CACHE.get(card_key) or {}).get("execution_trace_body") or "").strip()
    merged = f"{current}\n{text}".strip() if current else text.strip()
    _update_runtime_parameter("execution_trace_body", merged, card_id, executor)


def _update_runtime_output(display_text: str, card_id: Optional[int], executor: Any) -> None:
    _update_runtime_parameter("response_format_hint", display_text, card_id, executor)
    if card_id is not None:
        try:
            from task_workflow.workflow_context import get_workflow_context
            context = get_workflow_context()
            context.set_card_data(card_id, "ai_output_text", display_text)
        except Exception as exc:
            logger.debug("AI工具: 保存AI输出内容失败: %s", exc)


def _normalize_type_step_payload(step: Dict[str, Any]) -> Tuple[str, bool]:
    text_value = step.get("text")
    if text_value is None:
        text_value = step.get("content", "")
    text = str(text_value or "")
    press_enter = _coerce_bool(step.get("press_enter_after_text", False))
    if text.endswith("\r\n"):
        text = text[:-2]
        press_enter = True
    elif text.endswith("\n") or text.endswith("\r"):
        text = text[:-1]
        press_enter = True
    return text, press_enter


def _normalize_chat_history_messages(value: Any) -> List[Dict[str, str]]:
    if isinstance(value, list):
        return _normalize_text_messages(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except Exception:
            return []
        return _normalize_text_messages(parsed)
    return []


def _coerce_ai_timeout_seconds(value: Any, default: float) -> float:
    try:
        timeout = float(value)
    except Exception:
        timeout = float(default)
    if timeout <= 0:
        timeout = float(default)
    return max(float(MIN_AI_TIMEOUT_SECONDS), timeout)


def _resolve_direct_chat_timeout_seconds(params: Dict[str, Any]) -> float:
    if "chat_timeout_seconds" in (params or {}):
        return _coerce_ai_timeout_seconds(
            params.get("chat_timeout_seconds"),
            DEFAULT_DIRECT_CHAT_TIMEOUT_SECONDS,
        )
    if "timeout_seconds" in (params or {}):
        return _coerce_ai_timeout_seconds(
            params.get("timeout_seconds"),
            DEFAULT_DIRECT_CHAT_TIMEOUT_SECONDS,
        )
    return float(DEFAULT_DIRECT_CHAT_TIMEOUT_SECONDS)


def _resolve_continuous_command_timeout_seconds(params: Dict[str, Any]) -> float:
    if "tool_timeout_seconds" in (params or {}):
        return _coerce_ai_timeout_seconds(
            params.get("tool_timeout_seconds"),
            DEFAULT_CONTINUOUS_COMMAND_TIMEOUT_SECONDS,
        )
    if "timeout_seconds" in (params or {}):
        return _coerce_ai_timeout_seconds(
            params.get("timeout_seconds"),
            DEFAULT_CONTINUOUS_COMMAND_TIMEOUT_SECONDS,
        )
    return float(DEFAULT_CONTINUOUS_COMMAND_TIMEOUT_SECONDS)


def get_params_definition() -> Dict[str, Dict[str, Any]]:
    """参数定义"""
    params = {
        "---ai---": {"type": "separator", "label": "AI配置"},
        "provider_mode": {
            "label": "供应商模式",
            "type": "select",
            "options": OPENAI_PROVIDER_MODE_OPTIONS,
            "default": OPENAI_PROVIDER_MODE_OPTIONS[0],
            "tooltip": "统一按兼容接口处理；可连接 OpenAI 官方，也可连接兼容服务。",
        },
        "api_base_url": {
            "label": "API地址",
            "type": "text",
            "default": "",
            "tooltip": "默认留空时使用 OpenAI 官方接口基地址；填写后按你提供的兼容服务地址请求。",
        },
        "api_protocol": {
            "label": "协议",
            "type": "select",
            "options": OPENAI_API_PROTOCOL_OPTIONS,
            "default": OPENAI_API_PROTOCOL_RESPONSES,
            "tooltip": "手动选择实际协议；如果服务端文档写的是 responses 或 openai-responses，就选 responses。",
        },
        "api_url_mode": {
            "label": "地址类型",
            "type": "select",
            "options": OPENAI_API_URL_MODE_OPTIONS,
            "default": OPENAI_API_URL_MODE_BASE,
            "tooltip": "完整请求地址=按你填写的地址原样请求；接口基地址=按所选协议补 /responses 或 /chat/completions。",
        },
        "api_key": {
            "label": "API Key",
            "type": "text",
            "default": "",
            "tooltip": "留空则读取环境变量 OPENAI_API_KEY",
        },
        "model": {
            "label": "模型",
            "type": "text",
            "default": "gpt-4.1-mini",
            "tooltip": "官方或兼容供应商的模型名称",
        },
        "chat_timeout_seconds": {
            "label": "对话超时(秒)",
            "type": "float",
            "default": DEFAULT_DIRECT_CHAT_TIMEOUT_SECONDS,
            "min": MIN_AI_TIMEOUT_SECONDS,
            "max": 180.0,
            "decimals": 1,
            "tooltip": "普通对话模式的单次请求超时时间。",
        },
        "tool_timeout_seconds": {
            "label": "执行超时(秒)",
            "type": "float",
            "default": DEFAULT_CONTINUOUS_COMMAND_TIMEOUT_SECONDS,
            "min": MIN_AI_TIMEOUT_SECONDS,
            "max": 180.0,
            "decimals": 1,
            "tooltip": "执行模式会带截图做规划，请设置得比普通对话更长。",
        },
        "command_prompt": {
            "label": "执行指令",
            "type": "textarea",
            "default": "",
            "tooltip": "输入需要执行的指令，例如：在QQ输入框输入并发送一段话。支持 ${变量名} / ${全局:变量名}（或 ${global:变量名}）",
        },
        "enable_ai_cli_dialog": {
            "label": "启用真实CLI窗口",
            "type": "bool",
            "default": False,
            "tooltip": "开启后，运行时会启动真实的 cmd 控制台窗口，实时显示 AI 过程与最终输出。",
        },
        "execution_trace": {
            "label": "执行状态",
            "type": "textarea",
            "default": "",
            "placeholder": "等待执行...",
            "readonly": True,
            "save_to_workflow": False,
            "tooltip": "顶部显示当前状态，下面显示连续执行过程中的规划与执行轨迹",
        },

        "response_format_hint": {
            "label": "最终输出",
            "type": "textarea",
            "default": "",
            "placeholder": "等待AI输出...",
            "readonly": True,
            "save_to_workflow": False,
            "tooltip": "显示AI最终返回内容或最终执行结果",
        },
        "use_recognition_region": {
            "label": "仅识别区域",
            "type": "bool",
            "default": False,
        },
        "image_region_selector": {
            "label": "框选区域",
            "type": "button",
            "widget_hint": "image_region_selector",
            "param_prefix": "recognition_region",
            "button_text": "点击框选识别区域",
            "tooltip": "点击后在目标窗口上框选识别区域",
            "condition": {"param": "use_recognition_region", "value": True},
        },
        "recognition_region_x": {
            "label": "识别区域X",
            "type": "hidden",
            "default": 0,
        },
        "recognition_region_y": {
            "label": "识别区域Y",
            "type": "hidden",
            "default": 0,
        },
        "recognition_region_width": {
            "label": "识别区域宽度",
            "type": "hidden",
            "default": 0,
        },
        "recognition_region_height": {
            "label": "识别区域高度",
            "type": "hidden",
            "default": 0,
        },
    }

    merged = merge_params_definitions(params, get_standard_action_params())
    if "---post_execution---" in merged:
        merged["---post_execution---"]["label"] = "结果跳转"
    return merged


def _encode_image_to_base64(image) -> Tuple[Optional[str], Optional[str]]:
    if image is None:
        return None, None
    if len(image.shape) == 3 and image.shape[2] == 4:
        image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)

    smallest_payload: Optional[bytes] = None
    encode_flag = int(cv2.IMWRITE_JPEG_QUALITY)
    for quality in AI_IMAGE_JPEG_QUALITIES:
        ok, buf = cv2.imencode(".jpg", image, [encode_flag, int(quality)])
        if not ok:
            continue
        payload = buf.tobytes()
        if len(payload) <= AI_IMAGE_MAX_BYTES:
            return base64.b64encode(payload).decode("ascii"), "image/jpeg"
        if smallest_payload is None or len(payload) < len(smallest_payload):
            smallest_payload = payload

    if smallest_payload is not None:
        raise RuntimeError("截图数据过大，请缩小识别区域或窗口范围后重试")
    return None, None


def _save_snapshot_image(image, snapshot_path: str) -> bool:
    if image is None or not snapshot_path:
        return False
    try:
        if len(image.shape) == 3 and image.shape[2] == 4:
            image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
        return bool(cv2.imwrite(snapshot_path, image))
    except Exception:
        return False


def _build_command_prompt(command_text: str, width: int, height: int, max_steps: int) -> str:
    max_steps = max(1, int(max_steps or 1))
    base = (
        "你是自动化执行规划助手。请根据用户指令和截图生成可执行计划。\n"
        "只输出严格JSON，格式: {\"steps\": [...]}。\n"
        f"坐标系: 左上(0,0)，右下({width - 1},{height - 1})，单位像素，space=window。\n"
        f"最多 {max_steps} 步。\n"
        "仅允许action类型: click/type/key/wait（不要使用task）。每一步必须包含action字段。\n"
        "所有字段必须直接放在step顶层，不要嵌套click/type/key对象。\n"
        "click字段: coordinate_mode(客户区坐标), button(左键/右键/中键), click_action(完整点击/双击/仅按下/仅松开), clicks, interval, hold_duration, position_mode(精准坐标)。\n"
        "所有click步骤必须包含reason字段，写明为什么能确定是这个点。\n"
        "若点击的是截图中可见的文字目标/按钮/列表项/选项，必须额外包含target_text字段，内容必须是截图里实际看到的文本。\n"
        "这类可见目标click步骤必须优先返回x1,y1,x2,y2或bbox，不要只给估算点x/y。如果同时给bbox和x/y，bbox必须能覆盖目标。\n"
        "只有点击空白输入框等无明确文字的区域时，才允许只给x/y，但仍必须提供reason。\n"
        "type字段: text(不能为空), press_enter_after_text。\n"
        "key字段: key(不能为空), press_count, single_key_interval。\n"
        "wait字段: seconds。\n"
        "若使用归一化坐标(0-1000或0-1024或0-1)，必须在step顶层添加scale字段(1000/1024/1)。未提供scale时一律按像素坐标处理。\n"
        "如果用户指令要求先找到某个文字目标再点击，只有在截图中确认看到该文字后才能输出click步骤；看不见就输出 {\"steps\": [], \"error\": \"未找到目标\"}，不要猜坐标。\n"
        "如果用户指令包含“如果当前已经是目标就跳过，否则切换到目标”这类条件逻辑，且截图中能确认当前已经在目标页面/会话，可不输出目标点击步骤；但必须在JSON顶层额外输出decision和reason，例如 decision=\"target_already_active\"，reason写明当前为什么判定已是目标。\n"
        f"用户指令: {command_text}"
    )
    return base


def _build_continuous_command_prompt(
    command_text: str,
    width: int,
    height: int,
    max_steps: int,
    round_index: int,
    max_rounds: int,
    history_text: str,
) -> str:
    history_block = history_text.strip() or "无"
    return (
        "你是自动化执行的大脑，MCP 只是动作执行器。"
        "每一轮你都必须先根据当前截图复核上一步是否达成预期，再决定当前阶段能确定执行的最短动作链。"
        "不要提前输出未来多步计划，不要让执行器替你思考。\n"
        "先分析用户指令包含哪些阶段；如果目标是“先打开某界面/切换某页签，再查找并点击最终目标”，"
        "就先输出当前截图下能确认执行的前置步骤，等下一轮看到新界面后再继续。\n"
        "只输出严格JSON，格式: "
        "{\"status\":\"running|completed|failed\",\"phase\":\"...\",\"reason\":\"...\","
        "\"progress\":\"...\",\"expected_result\":\"...\",\"completion_signal\":\"...\",\"steps\":[...]}。\n"
        f"当前第 {round_index} 轮，总上限 {max_rounds} 轮。\n"
        f"本轮最多输出 {max_steps} 步；只有当前阶段内可确定的短链动作才允许合并输出。\n"
        f"坐标系: 左上(0,0)，右下({width - 1},{height - 1})，单位像素，space=window。\n"
        "仅允许action类型: click/type/key/wait。每一步必须包含action字段。\n"
        "click字段要求如下：点击可见目标时必须提供target_text与x1,y1,x2,y2或bbox，并写明reason；"
        "不要猜坐标。\n"
        "type字段要求如下：text 只填写要输入的正文，不要把 \\n 或回车字符直接拼进 text；"
        "如果输入后还需要提交、打开网页或发送消息，必须额外设置 press_enter_after_text=true。\n"
        "当 status=running 时，steps 必须只包含当前阶段可确定的短链动作；"
        "expected_result 要写出执行后下一轮截图里应该看到什么，用于你下一轮自我验证。\n"
        "连续模式下，多步仅允许以下安全组合："
        "1) 点击已看见的输入框后立刻输入；"
        "2) 单个 click/key/type 动作后补一个短 wait 用于界面稳定。"
        f"wait 必须是短等待，秒数大于 0 且不超过 {CONTINUOUS_COMMAND_MAX_INLINE_WAIT_SECONDS:g} 秒。"
        "禁止在一次输出里连续点击两个不同目标，禁止先点一个目标再猜下一个目标。\n"
        "如果本轮是在执行前置步骤，例如按键打开背包、点击进入某页面、切换标签、展开面板或进入目标区域，应返回 status=\"running\"，"
        "并在 reason 里写清这是为下一阶段查找最终目标做准备。\n"
        "如果任务涉及聊天回复、消息发送、文本输入、填写内容，除非历史已经明确说明输入框已通过点击获得焦点，"
        "否则在任何 type 动作之前，你都必须先输出一个点击可见输入框的 click 步骤，不能假设输入框已聚焦。\n"
        "如果任务是在列表/背包/网格中查找并点击某个目标，且当前选中的不是目标，你必须继续点击未尝试过的可见候选来排查；"
        "这类候选排查步骤必须提供候选本身的 bbox/x1,y1,x2,y2，不接受只给中心点；系统会按范围和第几行第几个槽位联合去重；"
        "禁止重复点击已经尝试过的候选；只有在明确说明当前页所有可见候选都已尝试完、且仍未找到目标时，才允许返回 failed。\n"
        "前置步骤里的弹窗按钮、页签、入口按钮同样禁止原样重复点击；如果上一轮已经点过同一目标且下一轮截图没有达到预期，"
        "你必须改判为该动作未生效并重新规划其他可见动作，或直接返回 failed，不能再次输出同一点击。\n"
        "如果当前截图已经表明任务完成，返回 "
        "{\"status\":\"completed\",\"reason\":\"...\",\"steps\":[]}。\n"
        "如果当前截图无法继续且看不到下一步目标，返回 "
        "{\"status\":\"failed\",\"reason\":\"...\",\"steps\":[]}。\n"
        "最近执行历史如下。你必须利用这些历史判断：上一步是否成功、当前处于哪个阶段、下一步是否需要重规划，并避免重复执行已尝试动作：\n"
        f"{history_block}\n"
        f"用户目标: {command_text}"
    )


def _normalize_text_for_match(value: Any) -> str:
    text = _shared_normalize_text_for_match(value)
    if not text:
        return ""
    text = text.replace("“", "").replace("”", "").replace("‘", "").replace("’", "")
    text = text.replace("\"", "").replace("'", "")
    return text


def _clean_command_target_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = text.replace("“", "").replace("”", "").replace("‘", "").replace("’", "")
    text = text.replace("\"", "").replace("'", "")
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"^(一下|那个|这个|一下子)", "", text)
    text = re.sub(r"^[，,、；;：:]+", "", text)
    text = re.sub(r"(，|,|、|；|;|：|:)?(并且|并|然后|再|后再|之后|接着)+$", "", text)
    text = re.sub(r"[，,、；;：:]+$", "", text)
    return text.strip()


def _extract_command_click_target(command_text: str) -> str:
    text = str(command_text or "").strip()
    if not text:
        return ""
    cleaned = text.replace("“", "").replace("”", "").replace("‘", "").replace("’", "")
    cleaned = cleaned.replace('\"', '').replace("'", '')
    normalized = re.sub(r"\s+", "", cleaned)
    find_markers = ("找到", "找")
    click_markers = ("点击", "点")
    for marker in find_markers:
        pos = normalized.find(marker)
        if pos < 0:
            continue
        tail = normalized[pos + len(marker):]
        for click_marker in click_markers:
            click_pos = tail.find(click_marker)
            if click_pos <= 0:
                continue
            target = _clean_command_target_text(tail[:click_pos])
            if target:
                return target
    if normalized.startswith("点击") or normalized.startswith("点"):
        tail = normalized[2:] if normalized.startswith("点击") else normalized[1:]
        split_markers = ("并且", "然后", "后再", "之后", "接着", "后", "并", "，", ",", "。")
        end_pos = len(tail)
        for split_marker in split_markers:
            marker_pos = tail.find(split_marker)
            if marker_pos >= 0:
                end_pos = min(end_pos, marker_pos)
        target = _clean_command_target_text(tail[:end_pos])
        if target:
            return target
    return ""


def _step_has_visual_anchor(step: Dict[str, Any]) -> bool:
    if all(key in step for key in ("x1", "y1", "x2", "y2")):
        return True
    bbox_val = step.get("bbox")
    return isinstance(bbox_val, (list, tuple)) and len(bbox_val) >= 4


def _step_has_bbox_anchor(step: Dict[str, Any]) -> bool:
    return _extract_click_region(step) is not None


def _step_mentions_target(step: Dict[str, Any], target_text: str) -> bool:
    expected = _normalize_text_for_match(target_text)
    if not expected:
        return True
    for key in ("target_text", "reason", "description", "label", "message"):
        actual = _normalize_text_for_match(step.get(key))
        if actual and expected in actual:
            return True
    return False


def _step_is_exploratory_search_click(step: Dict[str, Any], expected_target: str) -> bool:
    if not isinstance(step, dict):
        return False
    action = str(step.get("action") or step.get("task") or "").strip().lower()
    if action != "click":
        return False
    if not _step_has_visual_anchor(step):
        return False
    merged_text = " ".join(
        str(step.get(key) or "").strip()
        for key in ("target_text", "reason", "description", "label", "message")
    )
    normalized = _normalize_text_for_match(merged_text)
    target = _normalize_text_for_match(expected_target)
    if not normalized:
        return False
    search_markers = ("候选", "疑似", "查看名称", "确认名称", "排查", "继续查找", "未到目标", "不是目标", "切换查看")
    if any(marker in normalized for marker in search_markers):
        return True
    if target and target in normalized and any(marker in normalized for marker in ("确认", "查看", "核对", "名称")):
        return True
    return False


def _extract_prerequisite_targets(command_text: str, expected_target: str) -> List[str]:
    def _sanitize_candidate(value: Any) -> str:
        cleaned = _clean_command_target_text(value)
        if not cleaned:
            return ""
        cleaned = re.sub(r"^[,，。；;、]+", "", cleaned)
        cleaned = re.sub(r"[,，。；;、]+$", "", cleaned)
        cleaned = re.sub(r"^(打开|进入|切换到|切换至|切换|查看|点击|选择)", "", cleaned)
        cleaned = re.sub(r"(打开|进入|切换到|切换至|切换|查看|找到|查找|寻找|点击|选择|并且|并|然后|后|再)+$", "", cleaned)
        return cleaned.strip()

    text = str(command_text or "").strip()
    if not text:
        return []
    normalized = _normalize_text_for_match(text)
    normalized_expected = _normalize_text_for_match(expected_target)
    if normalized_expected:
        target_pos = normalized.find(normalized_expected)
        if target_pos > 0:
            normalized = normalized[:target_pos]
    if not normalized:
        return []
    raw_candidates: List[str] = []
    patterns = (
        r"点击(.+?)(?:打开|进入|切换|展开|查看|后|然后|再|并|并且|$)",
        r"打开(.+?)(?:后|然后|再|并|并且|$)",
        r"进入(.+?)(?:后|然后|再|并|并且|$)",
        r"切换(?:到|至)?(.+?)(?:页签|标签|页面|界面|页|后|然后|再|并|并且|$)",
        r"查看(.+?)(?:后|然后|再|并|并且|$)",
        r"在(.+?)(?:里|中|内)(?:找|查找|寻找|查看|点击|选择)",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, normalized):
            value = _sanitize_candidate(match.group(1))
            if value:
                raw_candidates.append(value)
    expanded: List[str] = []
    split_pattern = r"[的里中内页签标签页面界面]+"
    for candidate in raw_candidates:
        for item in re.split(split_pattern, candidate):
            item = _sanitize_candidate(item)
            if len(item) >= 2:
                expanded.append(item)
        cleaned_candidate = _sanitize_candidate(candidate)
        if len(cleaned_candidate) >= 2:
            expanded.append(cleaned_candidate)
    result: List[str] = []
    seen: set[str] = set()
    for item in expanded:
        normalized_item = _normalize_text_for_match(item)
        if (
            len(normalized_item) < 2
            or normalized_item == normalized_expected
            or normalized_item in seen
        ):
            continue
        seen.add(normalized_item)
        result.append(item)
    return result


def _extract_prerequisite_keys(command_text: str, expected_target: str) -> List[str]:
    text = str(command_text or "").strip()
    if not text:
        return []
    normalized = _normalize_text_for_match(text)
    normalized_expected = _normalize_text_for_match(expected_target)
    if normalized_expected:
        target_pos = normalized.find(normalized_expected)
        if target_pos > 0:
            normalized = normalized[:target_pos]
    if not normalized:
        return []
    result: List[str] = []
    seen: set[str] = set()
    patterns = (
        r"按([a-z0-9]+)键",
        r"按键([a-z0-9]+)",
        r"按([f][0-9]{1,2})",
        r"按([a-z])打开",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, normalized):
            key_name = str(match.group(1) or "").strip().lower()
            if key_name and key_name not in seen:
                seen.add(key_name)
                result.append(key_name)
    return result


def _step_is_prerequisite_click(step: Dict[str, Any], command_text: str, expected_target: str) -> bool:
    if not isinstance(step, dict):
        return False
    action = str(step.get("action") or step.get("task") or "").strip().lower()
    if action != "click":
        return False
    if not _step_has_visual_anchor(step):
        return False
    merged_text = " ".join(
        str(step.get(key) or "").strip()
        for key in ("target_text", "reason", "description", "label", "message")
    )
    normalized_step_text = _normalize_text_for_match(merged_text)
    if not normalized_step_text:
        return False
    prerequisite_targets = _extract_prerequisite_targets(command_text, expected_target)
    if not prerequisite_targets:
        return False
    for target in prerequisite_targets:
        normalized_target = _normalize_text_for_match(target)
        if normalized_target and (
            normalized_target in normalized_step_text or normalized_step_text in normalized_target
        ):
            return True
    return False


def _step_is_prerequisite_key(step: Dict[str, Any], command_text: str, expected_target: str) -> bool:
    if not isinstance(step, dict):
        return False
    action = str(step.get("action") or step.get("task") or "").strip().lower()
    if action != "key":
        return False
    expected_keys = _extract_prerequisite_keys(command_text, expected_target)
    if not expected_keys:
        return False
    key_name = str(step.get("key") or "").strip().lower()
    if not key_name or key_name not in expected_keys:
        return False
    merged_text = " ".join(
        str(step.get(k) or "").strip()
        for k in ("reason", "description", "label", "message")
    )
    normalized_text = _normalize_text_for_match(merged_text)
    prerequisite_targets = _extract_prerequisite_targets(command_text, expected_target)
    open_markers = ("打开", "进入", "切换", "背包", "页签", "标签", "界面")
    if any(marker in normalized_text for marker in open_markers):
        return True
    return any(_normalize_text_for_match(target) in normalized_text for target in prerequisite_targets)


def _step_is_prerequisite_non_click(
    step: Dict[str, Any],
    plan_obj: Dict[str, Any],
) -> bool:
    if not isinstance(step, dict):
        return False
    action = str(step.get("action") or step.get("task") or "").strip().lower()
    if action not in {"key", "type", "wait"}:
        return False
    reason_text = str(step.get("reason") or step.get("description") or step.get("message") or "").strip()
    if not reason_text:
        return False
    if action == "key" and not str(step.get("key") or "").strip():
        return False
    if action == "type":
        text_value = str(step.get("text") or step.get("content") or "").strip()
        if not text_value:
            return False
    if action == "wait":
        try:
            wait_seconds = float(step.get("seconds", 0.0) or 0.0)
        except Exception:
            return False
        if wait_seconds <= 0:
            return False
    return bool(
        _extract_command_response_field(plan_obj, "phase", "stage", "expected_result", "expected", "verification")
    )


def _command_requires_input_focus(command_text: str) -> bool:
    normalized = _normalize_text_for_match(command_text)
    if not normalized:
        return False
    type_markers = ("回复", "发送", "输入", "键入", "填写", "发消息", "发一条", "发一句")
    scene_markers = ("聊天", "群聊", "消息", "输入框", "文本框", "回复框", "对话框")
    if any(marker in normalized for marker in type_markers) and any(marker in normalized for marker in scene_markers):
        return True
    browser_type_markers = ("输入", "键入", "填写")
    browser_scene_markers = ("地址栏", "搜索栏", "网址栏", "url栏", "浏览器")
    return any(marker in normalized for marker in browser_type_markers) and any(marker in normalized for marker in browser_scene_markers)


def _step_is_input_box_click(step: Dict[str, Any]) -> bool:
    if not isinstance(step, dict):
        return False
    action = str(step.get("action") or step.get("task") or "").strip().lower()
    if action != "click":
        return False
    merged_text = " ".join(
        str(step.get(key) or "").strip()
        for key in ("target_text", "reason", "description", "label", "message")
    )
    normalized = _normalize_text_for_match(merged_text)
    if not normalized:
        return False
    markers = (
        "输入框", "文本框", "编辑框", "消息框", "回复框", "聊天输入", "消息输入", "对话输入",
        "地址栏", "搜索栏", "网址栏", "url栏", "浏览器地址栏",
    )
    return any(marker in normalized for marker in markers)


def _resolve_continuous_max_plan_steps(value: Any) -> int:
    try:
        resolved = int(value or CONTINUOUS_COMMAND_MAX_STEPS)
    except Exception:
        resolved = CONTINUOUS_COMMAND_MAX_STEPS
    return max(1, min(resolved, CONTINUOUS_COMMAND_HARD_MAX_STEPS))


def _validate_continuous_round_steps(
    steps: List[Dict[str, Any]],
    max_plan_steps: int,
) -> str:
    action_steps: List[Tuple[str, Dict[str, Any]]] = []
    for step in steps or []:
        if not isinstance(step, dict):
            continue
        action = str(step.get("action") or step.get("task") or "").strip().lower()
        if action in {"click", "type", "key", "wait"}:
            action_steps.append((action, step))
    if not action_steps:
        return ""
    if len(action_steps) > max_plan_steps:
        return f"连续执行单轮最多允许 {max_plan_steps} 步，已拒绝执行。"
    if len(action_steps) == 1:
        return ""

    wait_count = sum(1 for action, _ in action_steps if action == "wait")
    if wait_count > 1:
        return "连续执行单轮最多只允许 1 个短等待步骤，已拒绝执行。"

    for action, step in action_steps:
        if action != "wait":
            continue
        try:
            wait_seconds = float(step.get("seconds", 0.0) or 0.0)
        except Exception:
            return "连续执行中的 wait 秒数无效，已拒绝执行。"
        if wait_seconds <= 0 or wait_seconds > CONTINUOUS_COMMAND_MAX_INLINE_WAIT_SECONDS:
            return (
                "连续执行中的 wait 必须是短等待，秒数需大于 0 且不超过 "
                f"{CONTINUOUS_COMMAND_MAX_INLINE_WAIT_SECONDS:g} 秒，已拒绝执行。"
            )

    if len(action_steps) == 2:
        first_action, first_step = action_steps[0]
        second_action, _ = action_steps[1]
        if second_action == "wait" and first_action in {"click", "key", "type"}:
            return ""
        if first_action == "click" and second_action == "type" and _step_is_input_box_click(first_step):
            return ""
        return "连续执行单轮仅允许“点击输入框后输入”或“单动作后短等待”这两类双步组合，已拒绝执行。"

    return "连续执行单轮动作链过长，已拒绝执行。"


def _command_is_web_navigation(command_text: str) -> bool:
    raw_text = str(command_text or "").strip()
    normalized = _normalize_text_for_match(raw_text)
    if not normalized:
        return False
    if re.search(r"(?i)\b(?:https?://)?(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)+\b", raw_text):
        return True
    nav_markers = ("地址栏", "网址", "url", "网页", "网站", "官网", "域名", "首页", "浏览器")
    action_markers = ("打开", "访问", "进入", "前往", "跳转", "输入", "键入")
    return any(marker in normalized for marker in nav_markers) and any(marker in normalized for marker in action_markers)


def _extract_navigation_targets(command_text: str) -> List[str]:
    raw_text = str(command_text or "").strip()
    if not raw_text:
        return []

    results: List[str] = []
    seen: set[str] = set()
    generic_words = {
        "网页", "网站", "官网", "首页", "页面", "浏览器", "地址栏", "搜索栏", "网址栏", "网址", "域名", "网页地址栏",
    }

    def _add_candidate(value: Any) -> None:
        candidate = str(value or "").strip().lower()
        for fragment in (
            "我需要在网页地址栏输入", "在网页地址栏输入", "网页地址栏输入", "在地址栏输入", "地址栏输入",
            "我需要", "请", "帮我", "输入", "打开", "访问", "进入", "并打开", "打开网页", "打开页面",
        ):
            candidate = candidate.replace(fragment, "")
        candidate = re.sub(r"(的)+$", "", candidate)
        candidate = candidate.strip(" \t\r\n,，。.:：;；\"'()（）[]【】<>《》")
        if not candidate or candidate in generic_words:
            return
        normalized_candidate = _normalize_text_for_match(candidate)
        if len(normalized_candidate) < 2 or normalized_candidate in seen:
            return
        seen.add(normalized_candidate)
        results.append(candidate)

    for match in re.finditer(r"(?i)\b(?:https?://)?(?:www\.)?([a-z0-9-]+(?:\.[a-z0-9-]+)+)\b", raw_text):
        domain = str(match.group(1) or "").strip().lower()
        if not domain:
            continue
        _add_candidate(domain)
        domain_parts = [part for part in domain.split(".") if part]
        if len(domain_parts) >= 2:
            _add_candidate(domain_parts[-2])

    chinese_patterns = (
        r"输入([\u4e00-\u9fffA-Za-z0-9]{2,16}?)(?:的)?网址",
        r"(?:打开|访问|进入)([\u4e00-\u9fffA-Za-z0-9]{2,16}?)(?:的)?(?:官网|网站|网页|首页)?",
    )
    for pattern in chinese_patterns:
        for match in re.finditer(pattern, raw_text):
            _add_candidate(match.group(1))

    return results


def _command_requires_submit_after_type(command_text: str) -> bool:
    return _command_is_web_navigation(command_text)


def _steps_provide_submit_after_type(steps: List[Dict[str, Any]]) -> bool:
    saw_type = False
    for step in steps or []:
        if not isinstance(step, dict):
            continue
        action = str(step.get("action") or step.get("task") or "").strip().lower()
        if action == "type":
            saw_type = True
            _, press_enter_after_text = _normalize_type_step_payload(step)
            if press_enter_after_text:
                return True
            continue
        if saw_type and action == "key":
            key_name = str(step.get("key") or "").strip().lower()
            if key_name in {"enter", "return"}:
                return True
    return not saw_type


def _completed_web_navigation_has_evidence(plan_obj: Dict[str, Any], command_text: str) -> bool:
    if not _command_is_web_navigation(command_text):
        return True

    targets = _extract_navigation_targets(command_text)
    text_candidates = [
        plan_obj.get("reason"),
        plan_obj.get("message"),
        plan_obj.get("detail"),
        plan_obj.get("expected_result"),
        plan_obj.get("expected"),
        plan_obj.get("verification"),
        plan_obj.get("completion_signal"),
        plan_obj.get("done_when"),
    ]
    normalized_text = _normalize_text_for_match(" ".join(str(item or "").strip() for item in text_candidates))
    if not normalized_text:
        return False

    vague_markers = ("相关页面", "相关内容", "看起来", "似乎", "疑似", "应该", "像是", "大概")
    strong_evidence_markers = (
        "地址栏", "网址", "域名", "url", "首页", "官网", "搜索页", "搜索框", "logo", "已打开", "已进入", "已加载", "已跳转",
    )
    has_strong_evidence = any(marker in normalized_text for marker in strong_evidence_markers)
    if any(marker in normalized_text for marker in vague_markers) and not has_strong_evidence:
        return False

    normalized_targets = [_normalize_text_for_match(item) for item in targets if item]
    normalized_targets = [item for item in normalized_targets if item]
    if not normalized_targets:
        return has_strong_evidence

    domain_targets = [item for item in normalized_targets if "." in item or re.search(r"[a-z0-9]", item)]
    if domain_targets:
        if not any(target in normalized_text for target in domain_targets):
            return False
        return has_strong_evidence

    if not any(target in normalized_text for target in normalized_targets):
        return False
    return has_strong_evidence


def _command_allows_target_skip(command_text: str, target_text: str) -> bool:
    normalized = _normalize_text_for_match(command_text)
    target = _normalize_text_for_match(target_text)
    if not normalized or not target:
        return False
    skip_markers = ("跳过", "无需", "不需要", "不用")
    conditional_markers = ("如果不是", "若不是", "不是")
    target_active_markers = ("如果是", "若是", "已经是", "当前是", "已是")
    return (
        target in normalized
        and any(marker in normalized for marker in skip_markers)
        and any(marker in normalized for marker in conditional_markers)
        and any(marker in normalized for marker in target_active_markers)
    )



def _command_requires_target_search(command_text: str, target_text: str) -> bool:
    normalized = _normalize_text_for_match(command_text)
    target = _normalize_text_for_match(target_text)
    if not normalized or not target or target not in normalized:
        return False
    search_markers = ("找到", "查找", "寻找", "搜到", "找出", "定位")
    action_markers = ("点击", "点开", "选中", "选择")
    return any(marker in normalized for marker in search_markers) and any(marker in normalized for marker in action_markers)


def _plan_text_indicates_exhausted_candidates(text: Any, target_text: str) -> bool:
    normalized = _normalize_text_for_match(text)
    target = _normalize_text_for_match(target_text)
    if not normalized:
        return False
    if target and target not in normalized and "候选" not in normalized and "遍历" not in normalized:
        return False
    markers = (
        "已遍历所有",
        "已经遍历所有",
        "所有可见候选都已尝试",
        "可见候选已尝试完",
        "当前页无更多候选",
        "没有更多候选",
        "无更多候选",
        "已尝试完当前页",
        "当前页已全部尝试",
        "所有球都已点过",
    )
    return any(marker in normalized for marker in markers)


def _plan_text_indicates_target_active(text: Any, target_text: str) -> bool:
    normalized = _normalize_text_for_match(text)
    target = _normalize_text_for_match(target_text)
    if not normalized or not target or target not in normalized:
        return False
    markers = (
        "已经是",
        "当前是",
        "已是",
        "无需切换",
        "不用切换",
        "不需要切换",
        "无需点击",
        "不用点击",
        "不需要点击",
        "无需再点",
        "已在",
        "当前会话是",
        "当前聊天对象是",
        "targetalreadyactive",
        "target_already_active",
    )
    return any(marker in normalized for marker in markers)



def _plan_explicitly_skips_target_click(
    plan_obj: Dict[str, Any],
    steps: List[Dict[str, Any]],
    command_text: str,
    target_text: str,
) -> bool:
    if not _command_allows_target_skip(command_text, target_text):
        return False
    text_candidates: List[Any] = []
    for key in ("decision", "reason", "message", "status", "target_state"):
        text_candidates.append(plan_obj.get(key))
    for step in steps:
        if not isinstance(step, dict):
            continue
        action = str(step.get("action") or step.get("task") or "").strip().lower()
        if action == "wait":
            continue
        for key in ("reason", "message", "description", "target_text"):
            text_candidates.append(step.get(key))
        break
    return any(_plan_text_indicates_target_active(value, target_text) for value in text_candidates)



def _build_command_repair_prompt(
    command_text: str,
    validation_error: str,
    previous_output: str,
    width: int,
    height: int,
    max_steps: int,
) -> str:
    previous_output = _truncate_error_detail(previous_output, limit=1200)
    return (
        _build_command_prompt(command_text, width, height, max_steps)
        + "\n\n上一次输出不合格，请完整重写，不要解释，不要补充说明文字。\n"
        + f"上一次问题: {validation_error}\n"
        + "修正规则：\n"
        + "1. 只输出严格JSON。\n"
        + "2. 若需要点击可见目标，必须提供target_text，且必须提供x1,y1,x2,y2或bbox，并写明reason。\n"
        + "3. 不允许只凭猜测给目标点击坐标。\n"
        + "3.1 type 的 text 里不要直接拼接 \\n 或回车；如果输入后需要提交/发送/打开，改用 press_enter_after_text=true。\n"
        + "4. 若当前已经是目标且允许跳过切换，必须在JSON顶层输出decision=\"target_already_active\"，并在reason里写明判定依据。\n"
        + "5. 若看不到目标且也无法确认已在目标中，输出 {\"steps\": [], \"error\": \"未找到目标\"}。\n"
        + "6. 如果用户指令要求找到并点击某个目标，除非指令明确允许跳过，否则禁止输出 completed 且 steps 为空。\n"
        + "7. 对于列表/背包搜索类任务，除非你明确说明当前页所有可见候选都已尝试完，否则禁止输出 failed 且 steps 为空。\n"
        + "8. 若本轮只是为了排查候选、查看右侧名称或确认目标，可输出探索性 click 步骤，但必须给出候选本身的 bbox/x1,y1,x2,y2，不接受只给中心点，并写明确 reason。\n"
        + "9. 若用户指令包含前置步骤，例如先按 B 键打开背包、切换页签、进入某区域后再找最终目标，本轮允许只输出这些前置 key/click 步骤；此时应返回 running，而不是因为尚未命中最终目标就 failed。\n"
        + "10. 如果是列表候选，请在 target_text 或 reason 中尽量写清第几行第几个，方便系统稳定去重。\n"
        + "11. 连续执行模式下，本轮只允许输出当前阶段可确定的短链动作，并补充 phase、progress、expected_result，下一轮再根据新截图继续决策。\n"
        + "11.1 多步仅允许“点击输入框后输入”或“单动作后短等待”这两类双步组合；禁止连续点击两个不同目标。\n"
        + f"11.2 wait 必须是短等待，秒数大于 0 且不超过 {CONTINUOUS_COMMAND_MAX_INLINE_WAIT_SECONDS:g} 秒。\n"
        + "12. 如果任务涉及聊天回复、发送消息、文本输入或填写内容，在没有明确点击输入框之前，禁止直接输出 type；必须先点输入框。\n"
        + f"截图坐标范围: 左上(0,0)，右下({width - 1},{height - 1})。\n"
        + f"最多 {max_steps} 步。\n"
        + f"上一次原始输出: {previous_output}"
    )


def _extract_command_response_reason(plan_obj: Dict[str, Any]) -> str:
    if not isinstance(plan_obj, dict):
        return ""
    for key in ("reason", "message", "error", "detail", "summary"):
        value = str(plan_obj.get(key) or "").strip()
        if value:
            return value
    return ""


def _extract_command_response_field(plan_obj: Dict[str, Any], *keys: str) -> str:
    if not isinstance(plan_obj, dict):
        return ""
    for key in keys:
        value = str(plan_obj.get(key) or "").strip()
        if value:
            return value
    return ""


def _summarize_continuous_round_context(round_record: Dict[str, Any]) -> str:
    if not isinstance(round_record, dict):
        return ""
    parts: List[str] = []
    round_index = round_record.get("round")
    if isinstance(round_index, int):
        parts.append(f"第{round_index}轮")
    status = str(round_record.get("status") or "").strip()
    if status:
        parts.append(f"状态={status}")
    phase = str(round_record.get("phase") or "").strip()
    if phase:
        parts.append(f"阶段={phase}")
    progress = str(round_record.get("progress") or "").strip()
    if progress:
        parts.append(f"进度={progress}")
    expected_result = str(round_record.get("expected_result") or "").strip()
    if expected_result:
        parts.append(f"上轮预期={expected_result}")
    reason = str(round_record.get("reason") or "").strip()
    if reason:
        parts.append(f"判断={reason}")
    exec_summary = str(round_record.get("exec_summary") or "").strip()
    if exec_summary:
        parts.append(f"执行结果={exec_summary}")
    return "；".join(parts)


def _normalize_command_response_status(plan_obj: Dict[str, Any]) -> str:
    if not isinstance(plan_obj, dict):
        return "running"
    status_text = str(plan_obj.get("status") or plan_obj.get("decision") or "").strip().lower()
    if _coerce_bool(plan_obj.get("done")) or _coerce_bool(plan_obj.get("completed")):
        return "completed"
    if status_text in {"completed", "complete", "done", "success", "finished", "target_already_active"}:
        return "completed"
    if status_text in {"failed", "error", "blocked", "not_found", "cannot_continue"}:
        return "failed"
    if plan_obj.get("error") and not (plan_obj.get("steps") or plan_obj.get("actions")):
        return "failed"
    return "running"


def _validate_command_steps(
    plan_obj: Dict[str, Any],
    steps: List[Dict[str, Any]],
    command_text: str,
    allow_exploratory_search: bool = False,
) -> str:
    expected_target = _extract_command_click_target(command_text)
    if not expected_target:
        return ""
    target_click_step = None
    first_action_step = None
    exploratory_click_step = None
    prerequisite_click_step = None
    prerequisite_key_step = None
    prerequisite_non_click_step = None
    normalized_target = _normalize_text_for_match(expected_target)
    requires_target_search = _command_requires_target_search(command_text, expected_target)
    for step in steps:
        if not isinstance(step, dict):
            continue
        action = str(step.get("action") or step.get("task") or "").strip().lower()
        if first_action_step is None and action in {"click", "key", "type", "wait"}:
            first_action_step = step
        if action == "key":
            if prerequisite_key_step is None and allow_exploratory_search and _step_is_prerequisite_key(step, command_text, expected_target):
                prerequisite_key_step = step
        elif action in {"type", "wait"}:
            if prerequisite_non_click_step is None and allow_exploratory_search and _step_is_prerequisite_non_click(step, plan_obj):
                prerequisite_non_click_step = step
            continue
        if action != "click":
            continue
        if allow_exploratory_search and requires_target_search and not _step_has_bbox_anchor(step):
            return "AI 候选排查点击缺少稳定范围框，必须提供 x1,y1,x2,y2 或 bbox，已拒绝执行。"
        step_target_text = _normalize_text_for_match(step.get("target_text"))
        matches_target = _step_mentions_target(step, expected_target)
        has_anchor = _step_has_visual_anchor(step)
        if matches_target and (has_anchor or (step_target_text and normalized_target in step_target_text)):
            target_click_step = step
            break
        if exploratory_click_step is None and allow_exploratory_search and _step_is_exploratory_search_click(step, expected_target):
            exploratory_click_step = step
        if prerequisite_click_step is None and allow_exploratory_search and _step_is_prerequisite_click(step, command_text, expected_target):
            prerequisite_click_step = step
    if target_click_step is None:
        if (
            exploratory_click_step is not None
            or prerequisite_click_step is not None
            or prerequisite_key_step is not None
            or prerequisite_non_click_step is not None
        ):
            return ""
        if _plan_explicitly_skips_target_click(plan_obj, steps, command_text, expected_target):
            return ""
        if first_action_step is None:
            return f"AI 指令计划缺少针对目标「{expected_target}」的可执行步骤。"
        return f"AI 指令计划未明确命中目标「{expected_target}」，已拒绝执行。"
    if not _step_has_visual_anchor(target_click_step):
        return f"AI 指令计划未给出目标「{expected_target}」的范围框，已拒绝执行。"
    reason_text = str(target_click_step.get("reason") or "").strip()
    if not reason_text:
        return f"AI 指令计划未说明为什么命中目标「{expected_target}」，已拒绝执行。"
    return ""


def _parse_and_validate_command_plan(
    output_text: str,
    command_text: str,
    max_plan_steps: int,
    allow_exploratory_search: bool = False,
) -> Tuple[Optional[Dict[str, Any]], Optional[List[Dict[str, Any]]], str, str, str]:
    plan_obj = _parse_json_from_text(output_text)
    if not plan_obj:
        return None, None, "running", "", f"AI 返回的不是有效 JSON: {_truncate_error_detail(output_text)}"
    if not isinstance(plan_obj, dict):
        return None, None, "running", "", "AI 指令计划格式无效，根对象必须是 JSON 对象。"
    status = _normalize_command_response_status(plan_obj)
    detail = _truncate_error_detail(_extract_command_response_reason(plan_obj), 300)
    steps = plan_obj.get("steps") or plan_obj.get("actions")
    if steps is None:
        steps = []
    if not isinstance(steps, list):
        return plan_obj, None, status, detail, "AI 指令计划缺少有效的 steps 列表。"
    if not steps:
        expected_target = _extract_command_click_target(command_text)
        if status == "completed":
            if not _completed_web_navigation_has_evidence(plan_obj, command_text):
                return (
                    plan_obj,
                    [],
                    status,
                    detail,
                    "AI 声称网页已打开，但未提供可核验的地址栏、域名或站点特征证据，已拒绝执行。",
                )
            if expected_target and not _plan_explicitly_skips_target_click(plan_obj, [], command_text, expected_target):
                return (
                    plan_obj,
                    [],
                    status,
                    detail,
                    f"AI 声称已完成，但未提供目标「{expected_target}」的命中证据，已拒绝执行。"
                )
            plan_obj["steps"] = []
            return plan_obj, [], status, detail, ""
        if status == "failed":
            if expected_target and _command_requires_target_search(command_text, expected_target):
                if not _plan_text_indicates_exhausted_candidates(detail or plan_obj.get("reason") or "", expected_target):
                    return (
                        plan_obj,
                        [],
                        status,
                        detail,
                        f"AI 声称无法继续，但未证明目标「{expected_target}」的可见候选已穷尽，已拒绝执行。"
                    )
            plan_obj["steps"] = []
            return plan_obj, [], status, detail or "AI 反馈当前任务无法继续。", ""
        return plan_obj, None, status, detail, "AI 指令计划缺少可执行 steps。"
    normalized_steps: List[Dict[str, Any]] = []
    for step in steps:
        if isinstance(step, dict):
            normalized_steps.append(step)
    if not normalized_steps:
        return plan_obj, None, status, detail, "AI 指令计划缺少有效步骤。"
    if max_plan_steps and len(normalized_steps) > max_plan_steps:
        logger.info("AI工具: 指令步骤数超限，截断为 %s", max_plan_steps)
        normalized_steps = normalized_steps[:max_plan_steps]
    plan_validation_error = _validate_command_steps(
        plan_obj,
        normalized_steps,
        command_text,
        allow_exploratory_search=allow_exploratory_search,
    )
    if plan_validation_error:
        return plan_obj, normalized_steps, status, detail, plan_validation_error
    plan_obj["steps"] = normalized_steps
    return plan_obj, normalized_steps, status, detail, ""


def _summarize_command_step(step: Dict[str, Any]) -> str:
    if not isinstance(step, dict):
        return "无效步骤"
    action = str(step.get("action") or step.get("task") or "").strip().lower()
    if action == "click":
        target_text = str(step.get("target_text") or "").strip()
        xy = _fill_click_xy(step)
        target_desc = target_text or "坐标目标"
        if xy:
            return f"点击 {target_desc} @ {xy[0]},{xy[1]}"
        return f"点击 {target_desc}"
    if action == "type":
        text_value = str(step.get("text") or step.get("content") or "").strip()
        return f"输入 {text_value[:30]}"
    if action == "key":
        return f"按键 {str(step.get('key') or '').strip()}"
    if action == "wait":
        return f"等待 {float(step.get('seconds', 0.5) or 0.5):.1f}s"
    return action or "未知动作"


def _summarize_exec_result(exec_result: Dict[str, Any]) -> str:
    if not isinstance(exec_result, dict):
        return "执行结果无效"
    items = exec_result.get("steps") or []
    if not isinstance(items, list) or not items:
        return "未执行任何步骤"
    parts: List[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        index = item.get("index")
        step_label = f"第{int(index) + 1}步" if isinstance(index, int) else "某一步"
        task_name = str(item.get("task") or item.get("action") or "").strip() or "动作"
        message = str(item.get("message") or "").strip()
        flag = "成功" if item.get("success") else "失败"
        parts.append(f"{step_label} {task_name} {flag}" + (f"({message})" if message else ""))
    return "；".join(parts) if parts else "未生成执行摘要"


def _extract_click_region(step: Dict[str, Any]) -> Optional[Tuple[int, int, int, int]]:
    if not isinstance(step, dict):
        return None
    if all(k in step for k in ("x1", "y1", "x2", "y2")):
        try:
            x1 = int(round(float(step["x1"])))
            y1 = int(round(float(step["y1"])))
            x2 = int(round(float(step["x2"])))
            y2 = int(round(float(step["y2"])))
            return min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)
        except Exception:
            return None
    bbox_val = step.get("bbox")
    if isinstance(bbox_val, (list, tuple)) and len(bbox_val) >= 4:
        try:
            x1 = int(round(float(bbox_val[0])))
            y1 = int(round(float(bbox_val[1])))
            x2 = int(round(float(bbox_val[2])))
            y2 = int(round(float(bbox_val[3])))
            return min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)
        except Exception:
            return None
    return None


def _normalize_click_region(region: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
    x1, y1, x2, y2 = region
    return (
        int(round(x1 / 10.0)) * 10,
        int(round(y1 / 10.0)) * 10,
        int(round(x2 / 10.0)) * 10,
        int(round(y2 / 10.0)) * 10,
    )


def _regions_strongly_overlap(
    left: Tuple[int, int, int, int],
    right: Tuple[int, int, int, int],
) -> bool:
    lx1, ly1, lx2, ly2 = left
    rx1, ry1, rx2, ry2 = right
    inter_x1 = max(lx1, rx1)
    inter_y1 = max(ly1, ry1)
    inter_x2 = min(lx2, rx2)
    inter_y2 = min(ly2, ry2)
    inter_w = max(0, inter_x2 - inter_x1)
    inter_h = max(0, inter_y2 - inter_y1)
    if inter_w <= 0 or inter_h <= 0:
        return False
    inter_area = inter_w * inter_h
    left_area = max(1, (lx2 - lx1) * (ly2 - ly1))
    right_area = max(1, (rx2 - rx1) * (ry2 - ry1))
    union_area = max(1, left_area + right_area - inter_area)
    iou = inter_area / union_area
    overlap_small = inter_area / max(1, min(left_area, right_area))
    return iou >= 0.35 or overlap_small >= 0.6


def _parse_chinese_index_token(token: str) -> Optional[int]:
    token = str(token or "").strip()
    if not token:
        return None
    if token.isdigit():
        return int(token)
    mapping = {
        "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
        "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
    }
    if token in mapping:
        return mapping[token]
    if token.startswith("十") and len(token) == 2 and token[1] in mapping:
        return 10 + mapping[token[1]]
    if token.endswith("十") and len(token) == 2 and token[0] in mapping:
        return mapping[token[0]] * 10
    if len(token) == 2 and token[0] in mapping and token[1] in mapping and token[0] != "十":
        if token[1] == "十":
            return mapping[token[0]] * 10
    if len(token) == 3 and token[1] == "十" and token[0] in mapping and token[2] in mapping:
        return mapping[token[0]] * 10 + mapping[token[2]]
    return None


def _extract_candidate_slot_key(step: Dict[str, Any]) -> str:
    if not isinstance(step, dict):
        return ""
    text = " ".join(
        str(step.get(key) or "").strip()
        for key in ("target_text", "reason", "description", "label", "message")
    )
    normalized = re.sub(r"\s+", "", text)
    if not normalized:
        return ""
    match = re.search(r"第([0-9一二两三四五六七八九十]+)行第([0-9一二两三四五六七八九十]+)个", normalized)
    if match:
        row = _parse_chinese_index_token(match.group(1))
        col = _parse_chinese_index_token(match.group(2))
        if row is not None and col is not None:
            return f"grid:{row}:{col}"
    simple_match = re.search(r"第([0-9一二两三四五六七八九十]+)个", normalized)
    if simple_match:
        index_value = _parse_chinese_index_token(simple_match.group(1))
        if index_value is not None:
            if "第1行" in normalized or "第一行" in normalized or "上排" in normalized:
                return f"grid:1:{index_value}"
            if "第2行" in normalized or "第二行" in normalized or "下排" in normalized:
                return f"grid:2:{index_value}"
    return ""


def _save_continuous_round_debug_snapshot(
    screenshot,
    steps: List[Dict[str, Any]],
    round_index: int,
    card_id: Optional[int],
) -> str:
    if screenshot is None:
        return ""
    if not logger.isEnabledFor(logging.DEBUG):
        return ""
    click_regions: List[Tuple[Tuple[int, int, int, int], str]] = []
    for step in steps or []:
        if not isinstance(step, dict):
            continue
        action = str(step.get("action") or step.get("task") or "").strip().lower()
        if action != "click":
            continue
        region = _extract_click_region(step)
        if region is None:
            continue
        label = str(step.get("target_text") or "").strip() or _extract_candidate_slot_key(step) or "click"
        click_regions.append((region, label[:24]))
    if not click_regions:
        return ""
    try:
        from utils.app_paths import get_logs_dir
        candidate_dirs = [
            os.path.join(get_logs_dir("LCA"), "ai_tool_continuous_debug"),
        ]
        image = screenshot.copy()
        if len(image.shape) == 3 and image.shape[2] == 4:
            image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
        for index, (region, label) in enumerate(click_regions, start=1):
            x1, y1, x2, y2 = region
            cv2.rectangle(image, (x1, y1), (x2, y2), (0, 180, 255), 2)
            cv2.putText(
                image,
                f"{index}:{label}",
                (x1, max(18, y1 - 6)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (0, 180, 255),
                1,
                cv2.LINE_AA,
            )
        card_text = str(card_id) if card_id is not None else "na"
        for snapshot_dir in candidate_dirs:
            try:
                os.makedirs(snapshot_dir, exist_ok=True)
            except Exception:
                continue
            snapshot_path = os.path.join(snapshot_dir, f"card_{card_text}_round_{round_index}.png")
            if _save_snapshot_image(image, snapshot_path):
                return snapshot_path
    except Exception:
        return ""
    return ""


def _build_click_signature(step: Dict[str, Any]) -> str:
    if not isinstance(step, dict):
        return ""
    region = _extract_click_region(step)
    if region is not None:
        x1, y1, x2, y2 = _normalize_click_region(region)
        return f"bbox:{x1},{y1},{x2},{y2}"
    xy = _fill_click_xy(step)
    if xy:
        return f"xy:{int(round(xy[0] / 10.0)) * 10},{int(round(xy[1] / 10.0)) * 10}"
    target_text = _normalize_text_for_match(step.get("target_text"))
    if target_text:
        return f"text:{target_text}"
    return ""


def _build_click_attempt_record(step: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(step, dict):
        return None
    region = _extract_click_region(step)
    signature = _build_click_signature(step)
    target_text = _normalize_text_for_match(step.get("target_text"))
    if region is None and not signature:
        return None
    return {
        "region": _normalize_click_region(region) if region is not None else None,
        "signature": signature,
        "target_text": target_text,
        "slot_key": _extract_candidate_slot_key(step),
        "input_box": _step_is_input_box_click(step),
    }


def _find_repeated_click_targets(
    steps: List[Dict[str, Any]],
    attempted_records: List[Dict[str, Any]],
) -> List[str]:
    repeated: List[str] = []
    if not attempted_records:
        return repeated
    for step in steps or []:
        if not isinstance(step, dict):
            continue
        action = str(step.get("action") or step.get("task") or "").strip().lower()
        if action != "click":
            continue
        current_record = _build_click_attempt_record(step)
        if not current_record:
            continue
        current_region = current_record.get("region")
        current_signature = str(current_record.get("signature") or "")
        current_target_text = str(current_record.get("target_text") or "")
        current_slot_key = str(current_record.get("slot_key") or "")
        for attempted_record in attempted_records:
            if not isinstance(attempted_record, dict):
                continue
            attempted_region = attempted_record.get("region")
            attempted_signature = str(attempted_record.get("signature") or "")
            attempted_target_text = str(attempted_record.get("target_text") or "")
            attempted_slot_key = str(attempted_record.get("slot_key") or "")
            if current_slot_key and attempted_slot_key and current_slot_key == attempted_slot_key:
                repeated.append(_summarize_command_step(step))
                break
            if current_region is not None and attempted_region is not None:
                if _regions_strongly_overlap(current_region, attempted_region):
                    repeated.append(_summarize_command_step(step))
                    break
            elif current_signature and attempted_signature and current_signature == attempted_signature:
                repeated.append(_summarize_command_step(step))
                break
            elif (
                current_target_text
                and attempted_target_text
                and current_target_text == attempted_target_text
                and current_signature
                and attempted_signature
                and current_signature == attempted_signature
            ):
                repeated.append(_summarize_command_step(step))
                break
    return repeated


def _summarize_attempted_click_record(record: Dict[str, Any]) -> str:
    if not isinstance(record, dict):
        return ""
    target_text = str(record.get("target_text") or "").strip()
    if target_text:
        return target_text
    slot_key = str(record.get("slot_key") or "").strip()
    if slot_key:
        return slot_key
    region = record.get("region")
    if isinstance(region, tuple) and len(region) >= 4:
        x1, y1, x2, y2 = region
        return f"bbox:{x1},{y1},{x2},{y2}"
    return str(record.get("signature") or "").strip()


def _normalize_window_region(value: Any) -> Optional[Tuple[int, int, int, int]]:
    if not value:
        return None
    if isinstance(value, dict):
        try:
            x = int(value.get("x", 0))
            y = int(value.get("y", 0))
            w = int(value.get("width", 0))
            h = int(value.get("height", 0))
            return (x, y, w, h)
        except Exception:
            return None
    if isinstance(value, (list, tuple)) and len(value) >= 4:
        try:
            return (int(value[0]), int(value[1]), int(value[2]), int(value[3]))
        except Exception:
            return None
    return None


def _call_task_execute_local(
    exec_fn,
    params: Dict[str, Any],
    execution_mode: str,
    target_hwnd: Optional[int],
    window_region: Optional[Tuple[int, int, int, int]],
    card_id: Optional[int],
) -> Tuple[bool, str, Optional[int]]:
    counters: Dict[str, int] = {}
    try:
        return exec_fn(params, counters, execution_mode, target_hwnd, window_region, card_id=card_id)
    except TypeError:
        try:
            return exec_fn(params, counters, execution_mode, target_hwnd, window_region)
        except TypeError:
            try:
                return exec_fn(params, counters, execution_mode, target_hwnd)
            except TypeError:
                return exec_fn(params, counters, execution_mode)


def _execute_click_action_local(step: Dict[str, Any], execution_mode: str, target_hwnd: Optional[int],
                                window_region: Optional[Tuple[int, int, int, int]]) -> Dict[str, Any]:
    from tasks import click_coordinate

    params = {
        "coordinate_x": int(step.get("x", 0)),
        "coordinate_y": int(step.get("y", 0)),
        "coordinate_mode": step.get("coordinate_mode", "客户区坐标"),
        "button": step.get("button", "左键"),
        "click_action": step.get("click_action", "完整点击"),
        "hold_duration": float(step.get("hold_duration", DEFAULT_CLICK_HOLD_SECONDS)),
        "clicks": int(step.get("clicks", 1)),
        "interval": float(step.get("interval", DEFAULT_DOUBLE_CLICK_INTERVAL_SECONDS)),
        "position_mode": step.get("position_mode", "精准坐标"),
        "fixed_offset_x": int(step.get("fixed_offset_x", 0)),
        "fixed_offset_y": int(step.get("fixed_offset_y", 0)),
        "random_offset_x": int(step.get("random_offset_x", 0)),
        "random_offset_y": int(step.get("random_offset_y", 0)),
        "on_success": "执行下一步",
        "on_failure": "执行下一步",
    }
    success, message, next_card_id = _call_task_execute_local(
        click_coordinate.execute_task,
        params,
        execution_mode,
        target_hwnd,
        window_region,
        None,
    )
    return {
        "task": "点击指定坐标",
        "success": bool(success),
        "message": message,
        "next_card_id": next_card_id,
    }


def _execute_type_action_local(step: Dict[str, Any], execution_mode: str, target_hwnd: Optional[int],
                               window_region: Optional[Tuple[int, int, int, int]]) -> Dict[str, Any]:
    from tasks import keyboard_input

    text_value, press_enter_after_text = _normalize_type_step_payload(step)
    params = {
        "input_type": "文本输入",
        "text_input_mode": "单组文本",
        "text_to_type": text_value,
        "press_enter_after_text": press_enter_after_text,
        "on_success": "执行下一步",
        "on_failure": "执行下一步",
    }
    success, message, next_card_id = _call_task_execute_local(
        keyboard_input.execute_task,
        params,
        execution_mode,
        target_hwnd,
        window_region,
        None,
    )
    return {
        "task": "模拟键盘操作",
        "success": bool(success),
        "message": message,
        "next_card_id": next_card_id,
    }


def _execute_key_action_local(step: Dict[str, Any], execution_mode: str, target_hwnd: Optional[int],
                              window_region: Optional[Tuple[int, int, int, int]]) -> Dict[str, Any]:
    from tasks import keyboard_input

    key_value = str(step.get("key", "")).strip()
    params = keyboard_input.build_single_key_params(
        key=key_value,
        single_key_action=step.get("single_key_action", "完整按键"),
        press_count=int(step.get("press_count", 1)),
        single_key_interval=float(step.get("single_key_interval", 0.05)),
        on_success="执行下一步",
        on_failure="执行下一步",
    )
    success, message, next_card_id = _call_task_execute_local(
        keyboard_input.execute_task,
        params,
        execution_mode,
        target_hwnd,
        window_region,
        None,
    )
    return {
        "task": "模拟键盘操作",
        "success": bool(success),
        "message": message,
        "next_card_id": next_card_id,
    }


def _fill_click_xy(step: Dict[str, Any]) -> Optional[Tuple[int, int]]:
    if all(k in step for k in ("x1", "y1", "x2", "y2")):
        try:
            x1 = int(step["x1"])
            y1 = int(step["y1"])
            x2 = int(step["x2"])
            y2 = int(step["y2"])
            return int(round((x1 + x2) / 2.0)), int(round((y1 + y2) / 2.0))
        except Exception:
            return None
    bbox_val = step.get("bbox")
    if isinstance(bbox_val, (list, tuple)) and len(bbox_val) >= 4:
        try:
            x1 = int(bbox_val[0])
            y1 = int(bbox_val[1])
            x2 = int(bbox_val[2])
            y2 = int(bbox_val[3])
            return int(round((x1 + x2) / 2.0)), int(round((y1 + y2) / 2.0))
        except Exception:
            return None
    if "x" in step and "y" in step:
        try:
            return int(step["x"]), int(step["y"])
        except Exception:
            return None
    return None


def _normalize_coordinate_mode(value: Any) -> str:
    if value is None:
        return "客户区坐标"
    text = str(value).strip()
    if not text:
        return "客户区坐标"
    lowered = text.lower()
    mapping = {
        "space": "客户区坐标",
        "window": "客户区坐标",
        "client": "客户区坐标",
        "screen": "屏幕坐标",
        "屏幕": "屏幕坐标",
        "屏幕坐标": "屏幕坐标",
        "客户区": "客户区坐标",
        "客户区坐标": "客户区坐标",
    }
    return mapping.get(lowered, text)


def _parse_xy_from_string(value: Any) -> Optional[Tuple[int, int]]:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    for sep in (",", "，", " "):
        if sep in text:
            parts = [p.strip() for p in text.split(sep) if p.strip()]
            if len(parts) >= 2:
                try:
                    return int(float(parts[0])), int(float(parts[1]))
                except Exception:
                    return None
    return None


def _normalize_step_for_execution(step: Dict[str, Any], img_w: int, img_h: int, scale_mode: str) -> Dict[str, Any]:
    if not isinstance(step, dict):
        return {}
    norm = dict(step)

    click_val = norm.get("click")
    if isinstance(click_val, dict):
        for k, v in click_val.items():
            if k not in norm or k in ("x", "y", "x1", "y1", "x2", "y2", "bbox"):
                norm[k] = v
    elif isinstance(click_val, (list, tuple)) and len(click_val) >= 2:
        try:
            norm["x"] = int(float(click_val[0]))
            norm["y"] = int(float(click_val[1]))
        except Exception:
            pass
    elif isinstance(click_val, str):
        parsed = _parse_xy_from_string(click_val)
        if parsed:
            norm["x"], norm["y"] = parsed

    type_val = norm.get("type")
    if isinstance(type_val, dict):
        for k, v in type_val.items():
            if k not in norm:
                norm[k] = v
    elif isinstance(type_val, str):
        if "text" not in norm:
            norm["text"] = type_val

    key_val = norm.get("key")
    if isinstance(key_val, dict):
        for k, v in key_val.items():
            if k not in norm:
                norm[k] = v

    if "action" not in norm or not str(norm.get("action") or "").strip():
        if any(k in norm for k in ("x", "y", "x1", "y1", "x2", "y2", "bbox", "click")):
            norm["action"] = "click"
        elif "text" in norm or "press_enter_after_text" in norm:
            norm["action"] = "type"
        elif "key" in norm or "press_count" in norm:
            norm["action"] = "key"
        elif "seconds" in norm or "wait" in norm:
            norm["action"] = "wait"

    action = str(norm.get("action", "")).lower().strip()
    if action == "wait":
        if "seconds" not in norm and "wait" in norm:
            norm["seconds"] = norm.get("wait")

    if action == "click":
        norm = _apply_step_scaling(norm, img_w, img_h, scale_mode)

    return norm


def _resolve_step_scale_base(step: Dict[str, Any], img_w: int, img_h: int, scale_mode: str) -> Optional[float]:
    mode = str(scale_mode or "").strip()
    if mode == "像素(不缩放)":
        return None
    if mode == "1000":
        return 1000.0
    if mode == "1024":
        return 1024.0
    if mode == "比例(0-1)":
        return 1.0
    scale_val = step.get("scale") or step.get("coord_scale") or step.get("scale_base")
    if scale_val is not None:
        try:
            scale_float = float(scale_val)
            if scale_float > 0:
                return scale_float
        except Exception:
            pass
    if mode != "自动(推荐)":
        return None
    coords = []
    for key in ("x", "y", "x1", "y1", "x2", "y2"):
        if key in step:
            try:
                coords.append(float(step[key]))
            except Exception:
                pass
    bbox_val = step.get("bbox")
    if isinstance(bbox_val, (list, tuple)) and len(bbox_val) >= 4:
        try:
            coords.extend([float(bbox_val[0]), float(bbox_val[1]), float(bbox_val[2]), float(bbox_val[3])])
        except Exception:
            pass
    if not coords:
        return None
    max_coord = max(coords)
    min_coord = min(coords)
    if 0.0 <= min_coord and max_coord <= 1.0:
        return 1.0
    return None


def _apply_step_scaling(step: Dict[str, Any], img_w: int, img_h: int, scale_mode: str) -> Dict[str, Any]:
    coord_mode = _normalize_coordinate_mode(step.get("coordinate_mode"))
    step["coordinate_mode"] = coord_mode
    if coord_mode == "屏幕坐标":
        return step
    scale_base = _resolve_step_scale_base(step, img_w, img_h, scale_mode)
    if not scale_base:
        return step
    if scale_base == 1.0:
        def _scale_ratio(value: Any, total: int) -> Any:
            try:
                return int(round(float(value) * total))
            except Exception:
                return value
        for key, total in (("x", img_w), ("x1", img_w), ("x2", img_w), ("y", img_h), ("y1", img_h), ("y2", img_h)):
            if key in step:
                step[key] = _scale_ratio(step[key], total)
        bbox_val = step.get("bbox")
        if isinstance(bbox_val, (list, tuple)) and len(bbox_val) >= 4:
            try:
                step["bbox"] = [
                    _scale_ratio(bbox_val[0], img_w),
                    _scale_ratio(bbox_val[1], img_h),
                    _scale_ratio(bbox_val[2], img_w),
                    _scale_ratio(bbox_val[3], img_h),
                ]
            except Exception:
                pass
        return step

    def _scale(value: Any, total: int, base: float) -> Any:
        try:
            return int(round(float(value) / base * total))
        except Exception:
            return value

    for key, total in (("x", img_w), ("x1", img_w), ("x2", img_w), ("y", img_h), ("y1", img_h), ("y2", img_h)):
        if key in step:
            step[key] = _scale(step[key], total, scale_base)
    bbox_val = step.get("bbox")
    if isinstance(bbox_val, (list, tuple)) and len(bbox_val) >= 4:
        try:
            step["bbox"] = [
                _scale(bbox_val[0], img_w, scale_base),
                _scale(bbox_val[1], img_h, scale_base),
                _scale(bbox_val[2], img_w, scale_base),
                _scale(bbox_val[3], img_h, scale_base),
            ]
        except Exception:
            pass
    return step


def _apply_step_coordinate_offset(step: Dict[str, Any], offset_x: int, offset_y: int) -> Dict[str, Any]:
    if not isinstance(step, dict):
        return step
    x_offset = int(offset_x or 0)
    y_offset = int(offset_y or 0)
    if x_offset == 0 and y_offset == 0:
        return step
    coord_mode = _normalize_coordinate_mode(step.get("coordinate_mode"))
    step["coordinate_mode"] = coord_mode
    if coord_mode == "屏幕坐标":
        return step

    def _offset_value(value: Any, delta: int) -> Any:
        try:
            return int(round(float(value))) + delta
        except Exception:
            return value

    for key, delta in (("x", x_offset), ("x1", x_offset), ("x2", x_offset), ("y", y_offset), ("y1", y_offset), ("y2", y_offset)):
        if key in step:
            step[key] = _offset_value(step[key], delta)
    bbox_val = step.get("bbox")
    if isinstance(bbox_val, (list, tuple)) and len(bbox_val) >= 4:
        try:
            step["bbox"] = [
                _offset_value(bbox_val[0], x_offset),
                _offset_value(bbox_val[1], y_offset),
                _offset_value(bbox_val[2], x_offset),
                _offset_value(bbox_val[3], y_offset),
            ]
        except Exception:
            pass
    return step


def _execute_task_by_name_local(
    task_name: str,
    params: Dict[str, Any],
    execution_mode: str,
    target_hwnd: Optional[int],
    window_region: Optional[Tuple[int, int, int, int]],
    card_id: Optional[int],
) -> Dict[str, Any]:
    from tasks import get_task_module

    module = get_task_module(task_name)
    if not module:
        raise RuntimeError(f"unknown task: {task_name}")
    exec_fn = getattr(module, "execute_task", None)
    if not callable(exec_fn):
        raise RuntimeError(f"task {task_name} has no execute_task")
    success, message, next_card_id = _call_task_execute_local(
        exec_fn,
        params or {},
        execution_mode,
        target_hwnd,
        window_region,
        card_id,
    )
    return {
        "task": task_name,
        "success": bool(success),
        "message": message,
        "next_card_id": next_card_id,
    }


def _execute_plan_local(steps: List[Dict[str, Any]], execution_mode: str, target_hwnd: Optional[int],
                        window_region: Optional[Tuple[int, int, int, int]], stop_on_failure: bool,
                        img_w: int, img_h: int, scale_mode: str,
                        coordinate_offset: Optional[Tuple[int, int]] = None) -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []
    overall_success = True
    offset_x = 0
    offset_y = 0
    if isinstance(coordinate_offset, (list, tuple)) and len(coordinate_offset) >= 2:
        try:
            offset_x = int(coordinate_offset[0] or 0)
            offset_y = int(coordinate_offset[1] or 0)
        except Exception:
            offset_x = 0
            offset_y = 0
    for idx, step in enumerate(steps or []):
        if not isinstance(step, dict):
            results.append({"index": idx, "success": False, "message": "invalid step"})
            overall_success = False
            if stop_on_failure:
                break
            continue
        step_execution_mode = step.get("execution_mode") or execution_mode
        step_target_hwnd = step.get("target_hwnd", target_hwnd)
        step_region = _normalize_window_region(step.get("window_region", window_region))
        try:
            step = _normalize_step_for_execution(step, img_w, img_h, scale_mode)
            if "task" in step:
                task_name = str(step.get("task") or "").strip()
                if task_name == "点击指定坐标":
                    params = step.get("params") or {}
                    step = {
                        "x": params.get("coordinate_x", step.get("x")),
                        "y": params.get("coordinate_y", step.get("y")),
                        "coordinate_mode": params.get("coordinate_mode", step.get("coordinate_mode", "客户区坐标")),
                        "button": params.get("button", step.get("button", "左键")),
                        "click_action": params.get("click_action", step.get("click_action", "完整点击")),
                        "clicks": params.get("clicks", step.get("clicks", 1)),
                        "interval": params.get("interval", step.get("interval", DEFAULT_DOUBLE_CLICK_INTERVAL_SECONDS)),
                        "hold_duration": params.get("hold_duration", step.get("hold_duration", DEFAULT_CLICK_HOLD_SECONDS)),
                        "position_mode": params.get("position_mode", step.get("position_mode", "精准坐标")),
                        "fixed_offset_x": params.get("fixed_offset_x", step.get("fixed_offset_x", 0)),
                        "fixed_offset_y": params.get("fixed_offset_y", step.get("fixed_offset_y", 0)),
                        "random_offset_x": params.get("random_offset_x", step.get("random_offset_x", 0)),
                        "random_offset_y": params.get("random_offset_y", step.get("random_offset_y", 0)),
                    }
                    step = _apply_step_scaling(step, img_w, img_h, scale_mode)
                    step = _apply_step_coordinate_offset(step, offset_x, offset_y)
                    xy = _fill_click_xy(step)
                    if not xy:
                        res = {"task": "点击指定坐标", "success": False, "message": "missing x/y", "next_card_id": None}
                    else:
                        step["x"], step["y"] = xy
                        res = _execute_click_action_local(step, step_execution_mode, step_target_hwnd, step_region)
                else:
                    res = _execute_task_by_name_local(
                        task_name,
                        step.get("params") or {},
                        step_execution_mode,
                        step_target_hwnd,
                        step_region,
                        step.get("card_id"),
                    )
            else:
                action = str(step.get("action", "")).lower()
                if action == "click":
                    step = _apply_step_coordinate_offset(step, offset_x, offset_y)
                    xy = _fill_click_xy(step)
                    if not xy:
                        res = {"task": "click", "success": False, "message": "missing x/y", "next_card_id": None}
                    else:
                        step["x"], step["y"] = xy
                        res = _execute_click_action_local(step, step_execution_mode, step_target_hwnd, step_region)
                elif action == "type":
                    text_value = step.get("text")
                    if text_value is None:
                        text_value = step.get("content", "")
                    if not str(text_value or "").strip():
                        res = {"task": "type", "success": False, "message": "empty text", "next_card_id": None}
                    else:
                        step["text"] = str(text_value)
                        res = _execute_type_action_local(step, step_execution_mode, step_target_hwnd, step_region)
                elif action == "key":
                    key_value = str(step.get("key", "")).strip()
                    if not key_value:
                        res = {"task": "key", "success": False, "message": "empty key", "next_card_id": None}
                    else:
                        res = _execute_key_action_local(step, step_execution_mode, step_target_hwnd, step_region)
                elif action == "wait":
                    time.sleep(float(step.get("seconds", 0.5)))
                    res = {"task": "wait", "success": True, "message": "ok", "next_card_id": None}
                else:
                    res = {"task": action or "unknown", "success": False, "message": "unsupported action", "next_card_id": None}
        except Exception as exc:
            res = {"task": step.get("task") or step.get("action") or "unknown", "success": False, "message": str(exc), "next_card_id": None}
        res["index"] = idx
        results.append(res)
        if not res.get("success"):
            overall_success = False
            if stop_on_failure:
                break
    return {"success": overall_success, "steps": results}


def _get_mcp_server_path() -> Optional[str]:
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    server_path = os.path.join(base_dir, "services", "mcp", "mcp_openai_server.py")
    return server_path if os.path.isfile(server_path) else None


def _build_mcp_server_command() -> List[str]:
    is_frozen = bool(getattr(sys, "frozen", False))
    if not is_frozen:
        main_mod = sys.modules.get("__main__")
        if main_mod is not None and hasattr(main_mod, "__compiled__"):
            is_frozen = True
    if is_frozen:
        cmd = build_main_worker_command("--mcp-server")
        if not cmd:
            cmd = [sys.executable, "--mcp-server"]
        return cmd

    server_path = _get_mcp_server_path()
    if not server_path:
        raise RuntimeError("未找到 MCP 服务脚本")
    return [sys.executable, server_path]


class _PersistentMcpToolClient:
    def __init__(self) -> None:
        self._proc: Optional[subprocess.Popen] = None
        self._response_queue: Optional["queue.Queue[Dict[str, Any]]"] = None
        self._stdout_thread: Optional[threading.Thread] = None
        self._stderr_thread: Optional[threading.Thread] = None
        self._stderr_lines: deque[str] = deque(maxlen=80)
        self._call_lock = threading.RLock()
        self._next_id = 2

    def close(self) -> None:
        with self._call_lock:
            proc = self._proc
            self._proc = None
            self._response_queue = None
            self._stdout_thread = None
            self._stderr_thread = None
            self._next_id = 2
            if proc is None:
                return
            try:
                if proc.stdin:
                    proc.stdin.close()
            except Exception:
                pass
            try:
                if proc.poll() is None:
                    proc.terminate()
                    proc.wait(timeout=1.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            try:
                if proc.stdout:
                    proc.stdout.close()
            except Exception:
                pass
            try:
                if proc.stderr:
                    proc.stderr.close()
            except Exception:
                pass

    def _collect_stderr(self, proc: subprocess.Popen) -> None:
        stderr = getattr(proc, "stderr", None)
        if stderr is None:
            return
        try:
            while True:
                line = stderr.readline()
                if not line:
                    break
                text = str(line).strip()
                if text:
                    self._stderr_lines.append(text)
        except Exception:
            return

    def _collect_stdout(self, proc: subprocess.Popen, response_queue: "queue.Queue[Dict[str, Any]]") -> None:
        stdout = getattr(proc, "stdout", None)
        if stdout is None:
            return
        try:
            while True:
                line = stdout.readline()
                if not line:
                    break
                text = str(line).strip()
                if not text:
                    continue
                try:
                    payload = json.loads(text)
                except Exception:
                    continue
                if isinstance(payload, dict):
                    response_queue.put(payload)
        except Exception:
            return

    def _stderr_detail(self) -> str:
        if not self._stderr_lines:
            return ""
        recent = " | ".join(list(self._stderr_lines)[-6:])
        return recent[:500].rstrip()

    @staticmethod
    def _serialize_transport_payload(payload: Dict[str, Any]) -> str:
        # JSON-RPC 管道传输统一使用 ASCII 转义，避免上游异常文本里的非法代理字符
        # 在写入 UTF-8 stdin 时直接触发编码失败。
        return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))

    def _send_json(self, payload: Dict[str, Any]) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None or proc.poll() is not None:
            raise RuntimeError("MCP 服务不可用")
        proc.stdin.write(self._serialize_transport_payload(payload) + "\n")
        proc.stdin.flush()

    def _wait_for_response(self, request_id: int, timeout: float) -> Dict[str, Any]:
        proc = self._proc
        response_queue = self._response_queue
        if proc is None or response_queue is None:
            raise RuntimeError("MCP 服务不可用")
        deadline = time.monotonic() + max(5.0, float(timeout or 0) + 5.0)
        while True:
            if proc.poll() is not None:
                detail = self._stderr_detail()
                if detail:
                    raise RuntimeError(f"MCP 服务异常退出：{detail}")
                raise RuntimeError("MCP 服务异常退出")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError("MCP 调用超时")
            try:
                payload = response_queue.get(timeout=min(0.2, remaining))
            except queue.Empty:
                continue
            if payload.get("id") == request_id:
                return payload

    def _ensure_started(self, timeout: float) -> None:
        proc = self._proc
        if proc is not None and proc.poll() is None and self._response_queue is not None:
            return
        self.close()
        self._stderr_lines.clear()
        response_queue: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        proc = subprocess.Popen(
            _build_mcp_server_command(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        self._proc = proc
        self._response_queue = response_queue
        self._stdout_thread = threading.Thread(
            target=self._collect_stdout,
            args=(proc, response_queue),
            daemon=True,
            name="ai-tool-mcp-stdout",
        )
        self._stdout_thread.start()
        self._stderr_thread = threading.Thread(
            target=self._collect_stderr,
            args=(proc,),
            daemon=True,
            name="ai-tool-mcp-stderr",
        )
        self._stderr_thread.start()
        init_id = 1
        self._next_id = 2
        self._send_json(
            {
                "jsonrpc": "2.0",
                "id": init_id,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "clientInfo": {"name": "lca-ai-tool", "version": "1.0"},
                },
            }
        )
        init_response = self._wait_for_response(init_id, timeout)
        if "error" in init_response:
            err = init_response.get("error") or {}
            detail = str(err.get("message") or "").strip() or "MCP 初始化错误"
            stderr_detail = self._stderr_detail()
            if stderr_detail:
                detail = f"{detail} | {stderr_detail}"
            raise RuntimeError(detail)

    @staticmethod
    def _should_retry_call_exception(exc: Exception) -> bool:
        message = str(exc or "").strip().lower()
        if not message:
            return False
        transport_retry_tokens = (
            "mcp 服务不可用",
            "mcp 服务异常退出",
            "mcp server exited",
            "server exited unexpectedly",
            "broken pipe",
            "connection reset",
            "connection aborted",
            "the pipe has been ended",
            "i/o operation on closed file",
            "invalid handle",
        )
        return any(token in message for token in transport_retry_tokens)

    def call_tool(self, tool_name: str, arguments: Dict[str, Any], timeout: float) -> Dict[str, Any]:
        with self._call_lock:
            last_error: Optional[Exception] = None
            for attempt in range(2):
                try:
                    self._ensure_started(timeout)
                    call_id = self._next_id
                    self._next_id += 1
                    self._send_json(
                        {
                            "jsonrpc": "2.0",
                            "id": call_id,
                            "method": "tools/call",
                            "params": {"name": tool_name, "arguments": arguments},
                        }
                    )
                    response = self._wait_for_response(call_id, timeout)
                    if "error" in response:
                        err = response.get("error") or {}
                        detail = str(err.get("message") or "").strip() or "MCP 调用错误"
                        stderr_detail = self._stderr_detail()
                        if stderr_detail:
                            detail = f"{detail} | {stderr_detail}"
                        raise RuntimeError(detail)

                    result = response.get("result") or {}
                    content = result.get("content") or []
                    if isinstance(content, list) and content:
                        item = content[0] or {}
                        if isinstance(item, dict):
                            text = item.get("text")
                            if isinstance(text, str):
                                try:
                                    return json.loads(text)
                                except Exception:
                                    return {"output_text": text}
                    return {}
                except Exception as exc:
                    last_error = exc
                    self.close()
                    if attempt >= 1 or not self._should_retry_call_exception(exc):
                        raise
            if last_error is not None:
                raise last_error
            raise RuntimeError("MCP 调用失败")


def _close_shared_mcp_tool_client() -> None:
    global _MCP_TOOL_CLIENT
    with _MCP_TOOL_CLIENT_LOCK:
        client = _MCP_TOOL_CLIENT
        _MCP_TOOL_CLIENT = None
    if client is not None:
        try:
            client.close()
        except Exception:
            pass


def _get_mcp_tool_client() -> _PersistentMcpToolClient:
    global _MCP_TOOL_CLIENT
    with _MCP_TOOL_CLIENT_LOCK:
        if _MCP_TOOL_CLIENT is None:
            _MCP_TOOL_CLIENT = _PersistentMcpToolClient()
        return _MCP_TOOL_CLIENT


atexit.register(_close_shared_mcp_tool_client)


def _call_mcp_tool(tool_name: str, arguments: Dict[str, Any], timeout: float) -> Dict[str, Any]:
    client = _get_mcp_tool_client()
    return client.call_tool(tool_name, arguments, timeout)


def _build_ai_protocol_cache_key(
    provider_mode: str,
    api_protocol: str,
    api_url_mode: str,
    api_base_url: str,
    api_key: str,
    model: str,
) -> str:
    api_key_hash = hashlib.sha1(str(api_key or "").encode("utf-8", errors="ignore")).hexdigest()
    raw = "|".join([
        str(provider_mode or "").strip().lower(),
        str(api_protocol or "").strip().lower(),
        str(api_url_mode or "").strip().lower(),
        str(api_base_url or "").strip().rstrip("/").lower(),
        str(model or "").strip(),
        api_key_hash,
    ])
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()


def _set_ai_protocol_support_cache(
    provider_mode: str,
    api_protocol: str,
    api_url_mode: str,
    api_base_url: str,
    api_key: str,
    model: str,
    is_supported: bool,
    detail: str = "",
) -> None:
    cache_key = _build_ai_protocol_cache_key(
        provider_mode,
        api_protocol,
        api_url_mode,
        api_base_url,
        api_key,
        model,
    )
    _AI_PROTOCOL_SUPPORT_CACHE[cache_key] = (bool(is_supported), str(detail or ""))


def _is_official_responses_protocol(provider_mode: str, api_protocol: str, api_base_url: str) -> bool:
    if _normalize_ai_api_protocol(
        api_protocol,
        provider_mode=provider_mode,
        api_base_url=api_base_url,
    ) != OPENAI_API_PROTOCOL_RESPONSES:
        return False
    normalized_provider_mode = _normalize_ai_provider_mode(provider_mode)
    normalized_base_url = str(api_base_url or "").strip().rstrip("/").lower()
    official_urls = {
        str(OPENAI_DEFAULT_BASE_URL or "").strip().rstrip("/").lower(),
        "https://api.openai.com/v1",
    }
    return normalized_provider_mode == OPENAI_PROVIDER_MODE_OFFICIAL and normalized_base_url in official_urls



def _looks_like_protocol_unsupported(exc: Exception, api_protocol: str) -> bool:
    message = str(exc or "")
    lower_msg = message.strip().lower()
    status_code = _extract_http_status_code(message)
    error_url = _extract_error_url(message).lower()
    model_related_tokens = (
        "modelnotopen",
        "has not activated the model",
        "model_not_found",
        "does not exist",
        "does not have access to the model",
        "unsupported value",
    )
    if any(token in lower_msg for token in model_related_tokens):
        return False
    if api_protocol == OPENAI_API_PROTOCOL_RESPONSES:
        if (status_code in {404, 405, 501}) and "/responses" in error_url:
            return True
        unsupported_tokens = (
            "method not allowed",
            "not found",
            "unsupported",
            "unknown endpoint",
            "no route",
            "route not found",
        )
        if ("/responses" in error_url or "responses" in lower_msg) and any(token in lower_msg for token in unsupported_tokens):
            return True
    return False



def _build_protocol_unsupported_message(exc: Exception, api_protocol: str) -> str:
    request_id = _extract_request_id(str(exc or ""))
    error_url = _extract_error_url(str(exc or ""))
    root_cause = _truncate_error_detail(_extract_root_cause_message(str(exc or "")) or str(exc or ""), 160)
    detail = (
        "当前供应商不支持 "
        + str(api_protocol or "").strip()
        + " 协议，请切换为 chat_completions 或更换支持该协议的服务端。"
    )
    if error_url:
        detail = f"{detail} 接口地址: {error_url}"
    if request_id:
        detail = _append_request_id(detail, request_id)
    if root_cause:
        detail = f"{detail} 详情: {root_cause}"
    return detail



def _probe_ai_protocol_support_if_needed(
    provider_mode: str,
    api_protocol: str,
    api_url_mode: str,
    api_base_url: str,
    api_key: str,
    model: str,
    timeout_seconds: float,
) -> str:
    normalized_protocol = _normalize_ai_api_protocol(
        api_protocol,
        provider_mode=provider_mode,
        api_base_url=api_base_url,
    )
    if normalized_protocol != OPENAI_API_PROTOCOL_RESPONSES:
        return ""
    if _is_official_responses_protocol(provider_mode, normalized_protocol, api_base_url):
        return ""
    normalized_url_mode = _normalize_ai_api_url_mode(
        api_url_mode,
        provider_mode=provider_mode,
        api_base_url=api_base_url,
    )
    cache_key = _build_ai_protocol_cache_key(
        provider_mode,
        normalized_protocol,
        normalized_url_mode,
        api_base_url,
        api_key,
        model,
    )
    cached = _AI_PROTOCOL_SUPPORT_CACHE.get(cache_key)
    if cached is not None:
        return "" if cached[0] else str(cached[1] or "")
    return ""


def _should_retry_exception(exc: Exception) -> bool:
    msg = str(exc).lower()
    if "invalidparameter" in msg or "badrequest" in msg:
        return False
    if "modelnotopen" in msg or "has not activated the model" in msg:
        return False
    if "model_not_found" in msg or "does not exist" in msg:
        return False
    if "does not have access to the model" in msg or "unsupported value" in msg:
        return False
    if "model do not support image input" in msg or "image input" in msg:
        return False
    if "image_url" in msg:
        return False
    if "401" in msg or "unauthorized" in msg or "forbidden" in msg or "invalid_api_key" in msg:
        return False
    retry_tokens = (
        "timeout",
        "timed out",
        "429",
        "rate limit",
        "503",
        "502",
        "500",
        "504",
        "connection reset",
        "connection error",
        "connecterror",
        "temporarily",
        "ssleoferror",
        "eof occurred in violation of protocol",
        "server disconnected without sending a response",
        "server disconnected",
        "remote protocol error",
        "tls",
        "ssl",
        "handshake",
    )
    return any(token in msg for token in retry_tokens)



def _extract_request_id(message: str) -> str:
    text = str(message or "").strip()
    match = re.search("(?:request[_ ]id|x-request-id|请求ID)\s*[:：]?\s*([A-Za-z0-9_-]+)", text, re.IGNORECASE)
    return match.group(1) if match else ""


def _clean_exception_detail_candidate(message: Any) -> str:
    text = str(message or "").strip()
    text = re.sub(r"\s+For more information check:\s*https?://\S+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^[A-Za-z_][A-Za-z0-9_.]*:\s*", "", text)
    return text.strip(" .,。，；;:：")


def _is_meaningful_error_detail(message: Any) -> bool:
    text = _clean_exception_detail_candidate(message)
    if not text:
        return False
    if re.fullmatch(r"[\d.]+", text):
        return False
    lowered = text.lower()
    if lowered in {"none", "null", "nan", "error", "exception"}:
        return False
    return bool(re.search(r"[A-Za-z\u4e00-\u9fff]", text))



def _extract_root_cause_message(message: str) -> str:
    text = str(message or "").strip()
    parts = [part.strip() for part in re.split(r"\s*<-\s*", text) if part.strip()]
    cleaned_parts = [_clean_exception_detail_candidate(part) for part in parts]
    for part in reversed(cleaned_parts):
        if _is_meaningful_error_detail(part):
            return part
    for part in reversed(cleaned_parts):
        if part:
            return part
    return _clean_exception_detail_candidate(text)


def _extract_http_status_code(message: str) -> Optional[int]:
    text = str(message or "")
    match = re.search(r"\b([1-5]\d\d)\b", text)
    if not match:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


def _extract_error_url(message: str) -> str:
    text = str(message or "")
    match = re.search(r"for url ['\"]([^'\"]+)['\"]", text, re.IGNORECASE)
    if match:
        return str(match.group(1) or "").strip()
    match = re.search(r"https?://\S+", text, re.IGNORECASE)
    if not match:
        return ""
    url = str(match.group(0) or "").strip()
    url = re.sub(r"[).,]+$", "", url)
    return url


def _append_request_id(message: str, request_id: str) -> str:
    clean_message = str(message or "").strip()
    clean_request_id = str(request_id or "").strip()
    if not clean_request_id:
        return clean_message
    if clean_request_id in clean_message:
        return clean_message
    return f"{clean_message} 请求ID: {clean_request_id}"



def _truncate_error_detail(message: Any, limit: int = 200) -> str:
    clean_message = re.sub(r"\s+", " ", str(message or "").strip())
    if len(clean_message) <= limit:
        return clean_message
    return clean_message[: limit - 3].rstrip() + "..."



def _extract_plan_failure_detail(exec_result: Any) -> str:
    if not isinstance(exec_result, dict):
        return "指令计划执行失败。"
    for item in exec_result.get("steps") or []:
        if not isinstance(item, dict) or item.get("success", False):
            continue
        index = item.get("index")
        task_name = str(item.get("task") or item.get("action") or "").strip()
        message = _truncate_error_detail(item.get("message") or "")
        step_label = f"第{int(index) + 1}步" if isinstance(index, int) else "某一步"
        if task_name and message:
            return f"指令计划执行失败：{step_label}（{task_name}） - {message}"
        if task_name:
            return f"指令计划执行失败：{step_label}（{task_name}）"
        if message:
            return f"指令计划执行失败：{message}"
    return "指令计划执行失败。"



def _format_ai_error_message(exc: Exception) -> str:
    msg = str(exc or "").strip()
    lower_msg = msg.lower()
    request_id = _extract_request_id(msg)
    root_cause = _extract_root_cause_message(msg)
    status_code = _extract_http_status_code(msg)
    error_url = _extract_error_url(msg)

    def _with_request_id(detail: str) -> str:
        return _append_request_id(detail, request_id)

    def _with_endpoint(detail: str) -> str:
        endpoint = f" 接口地址: {error_url}" if error_url else ""
        return _with_request_id(f"{detail}{endpoint}")

    if status_code == 503:
        return _with_endpoint("AI 接口暂时不可用（HTTP 503），服务端可能过载或维护中，请稍后重试。")
    if status_code == 502:
        return _with_endpoint("AI 接口网关异常（HTTP 502），上游服务返回无效响应，请稍后重试。")
    if status_code == 404:
        return _with_endpoint("AI 接口地址不存在（HTTP 404），请检查 API 地址、地址类型、版本前缀和协议路径是否与供应商文档一致。")
    if status_code == 504:
        return _with_endpoint("AI 接口网关超时（HTTP 504），上游服务响应过慢，请稍后重试。")
    if status_code == 500:
        return _with_endpoint("AI 接口内部错误（HTTP 500），请稍后重试。")
    if status_code and 500 <= status_code < 600:
        return _with_endpoint(f"AI 接口服务异常（HTTP {status_code}），请稍后重试。")

    if "mcp call timeout" in lower_msg or "mcp 调用超时" in msg.lower():
        return _with_request_id("请求 OpenAI 超时，请检查网络或适当增大超时时间。")
    if "readtimeout" in lower_msg or "read timeout" in lower_msg or "timed out" in lower_msg:
        return _with_endpoint("请求 OpenAI 超时，请检查网络或适当增大超时时间。")
    if "invalid json response" in lower_msg or "jsondecodeerror" in lower_msg:
        return _with_endpoint("AI 接口返回的不是有效 JSON，兼容接口可能返回了空响应或非 OpenAI 格式内容，请检查接口地址、协议和供应商兼容性。")
    if "expecting value: line 1 column 1" in lower_msg:
        return _with_endpoint("AI 接口返回了空响应或无效内容，请检查接口地址、协议和供应商兼容性。")
    if "mcp call no response" in lower_msg:
        return _with_request_id("OpenAI 服务未返回结果。")
    if "empty model output" in lower_msg:
        detail = _truncate_error_detail(root_cause or msg, 220)
        return _with_request_id(f"AI 接口已返回成功响应，但正文为空，当前兼容返回异常：{detail}")
    if "missing coordinates in mcp result" in lower_msg:
        return _with_request_id("AI 未返回可用坐标，请调整提示词或识别区域。")
    if "empty response from mcp" in lower_msg:
        return _with_request_id("AI 未返回内容，请检查提示词或模型状态。")
    if "model do not support image input" in lower_msg:
        return _with_request_id("模型不支持图片输入，请更换支持视觉的模型。")
    if "modelnotopen" in lower_msg or "has not activated the model" in lower_msg:
        model_name = ""
        match = re.search(r"activated the model\s+([a-zA-Z0-9._-]+)", msg)
        if match:
            model_name = match.group(1)
        if model_name:
            return _with_request_id(f"当前账号未开通模型 {model_name}，请更换已开通模型或到控制台开通。")
        return _with_request_id("当前账号未开通该模型，请更换已开通模型或到控制台开通。")
    if "model_not_found" in lower_msg or "does not exist" in lower_msg:
        return _with_request_id("OpenAI 模型不存在，请检查模型名称是否正确。")
    if "does not have access to the model" in lower_msg:
        return _with_request_id("当前账号无权使用该 OpenAI 模型，请更换有权限的模型。")
    if "unsupported value" in lower_msg and "model" in lower_msg:
        detail = _truncate_error_detail(root_cause or msg)
        return _with_request_id(f"模型参数无效，请检查 OpenAI 模型名称：{detail}")
    if "setlimitexceeded" in lower_msg or "too many requests" in lower_msg or "429" in lower_msg:
        return _with_request_id("模型调用已达限制，请稍后重试或检查额度。")
    if "unauthorized" in lower_msg or "forbidden" in lower_msg or "401" in lower_msg or "invalid_api_key" in lower_msg:
        return _with_request_id("OpenAI API Key 无效或无权限。")
    if "invalidparameter" in lower_msg or "badrequest" in lower_msg:
        detail = _truncate_error_detail(root_cause or msg)
        return _with_request_id(f"请求参数错误：{detail}")
    if "ssleoferror" in lower_msg or "eof occurred in violation of protocol" in lower_msg or "tls" in lower_msg:
        detail = "与 OpenAI 服务建立安全连接失败。"
        if root_cause:
            detail = f"与 OpenAI 服务建立安全连接失败：{root_cause}。"
        return _with_request_id(detail)
    if "server disconnected without sending a response" in lower_msg:
        return _with_request_id("连接 OpenAI 服务失败：服务端在返回数据前断开连接。")
    if "apiconnectionerror" in lower_msg or "connection error" in lower_msg or "remoteprotocolerror" in lower_msg:
        if "server disconnected without sending a response" in lower_msg:
            return _with_request_id("连接 OpenAI 服务失败：服务端在返回数据前断开连接。")
        if root_cause and root_cause.lower() not in {"connection error", "remote protocol error"}:
            return _with_request_id(f"连接 OpenAI 服务失败：{root_cause}。")
        return _with_request_id("连接 OpenAI 服务失败。")
    return _with_request_id(_truncate_error_detail(root_cause or msg))


def _record_ai_error(
    message: str,
    card_id: Optional[int],
    workflow_context=None,
    executor=None,
) -> None:
    if not message:
        return
    _update_runtime_parameter("runtime_status", f"执行失败：{message}", card_id, executor)
    _update_runtime_output(message, card_id, executor)
    try:
        if workflow_context is None:
            from task_workflow.workflow_context import get_workflow_context

            workflow_context = get_workflow_context()
        if workflow_context and card_id is not None:
            workflow_context.set_card_data(card_id, "ai_error_text", message)
    except Exception as exc:
        logger.debug("AI工具: 保存AI错误失败: %s", exc)



def _build_failure_result(params: Dict[str, Any], card_id: Optional[int], detail: str):
    failure_action = params.get('on_failure', '执行下一步')
    if _should_force_stop_ai_failure(detail, failure_action):
        failure_action = '停止工作流'
    success, action, next_card_id = resolve_step_action_result(
        success=False,
        action=failure_action,
        jump_id=params.get('failure_jump_target_id'),
        card_id=card_id,
    )
    return success, action, next_card_id, _truncate_error_detail(detail, 300)


def _should_force_stop_ai_failure(detail: str, failure_action: Any) -> bool:
    action_text = str(failure_action or "").strip()
    if action_text not in {"继续执行本步骤", "继续本步骤"}:
        return False
    clean_detail = str(detail or "").strip()
    if not clean_detail:
        return False
    terminal_tokens = (
        "AI 接口已返回成功响应，但正文为空",
        "empty model output",
        "OpenAI API Key 无效",
        "模型不支持图片输入",
        "模型不存在",
        "当前账号无权使用该 OpenAI 模型",
        "当前账号未开通该模型",
        "请求参数错误",
        "API 地址无效",
    )
    return any(token in clean_detail for token in terminal_tokens)



def _fail_ai_task(
    params: Dict[str, Any],
    card_id: Optional[int],
    detail: str,
    workflow_context=None,
    executor=None,
    log_level: int = logging.ERROR,
    write_output: bool = True,
):
    clean_detail = _truncate_error_detail(detail, 300) or "AI工具执行失败。"
    if log_level >= logging.ERROR:
        logger.error("AI工具: %s", clean_detail)
    elif log_level >= logging.WARNING:
        logger.warning("AI工具: %s", clean_detail)
    elif log_level >= logging.INFO:
        logger.info("AI工具: %s", clean_detail)
    else:
        logger.debug("AI工具: %s", clean_detail)
    if write_output:
        _record_ai_error(clean_detail, card_id, workflow_context, executor)
    return _build_failure_result(params, card_id, clean_detail)

def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().lower()
    return text in ("1", "true", "yes", "y")


def _is_window_dpi_aware(hwnd: Optional[int]) -> Optional[bool]:
    if not hwnd:
        return None
    try:
        import ctypes
        user32 = ctypes.windll.user32
        if not hasattr(user32, "GetWindowDpiAwarenessContext"):
            return None
        if not hasattr(user32, "GetAwarenessFromDpiAwarenessContext"):
            return None
        ctx = user32.GetWindowDpiAwarenessContext(hwnd)
        awareness = user32.GetAwarenessFromDpiAwarenessContext(ctx)
        return awareness >= 1
    except Exception:
        return None


def _get_thread_dpi_awareness() -> Optional[int]:
    try:
        import ctypes
        user32 = ctypes.windll.user32
        if not hasattr(user32, "GetThreadDpiAwarenessContext"):
            return None
        if not hasattr(user32, "GetAwarenessFromDpiAwarenessContext"):
            return None
        ctx = user32.GetThreadDpiAwarenessContext()
        awareness = user32.GetAwarenessFromDpiAwarenessContext(ctx)
        return int(awareness)
    except Exception:
        return None


def _get_window_dpi_scale(hwnd: Optional[int]) -> float:
    if not hwnd:
        return 1.0
    try:
        import ctypes
        user32 = ctypes.windll.user32
        if hasattr(user32, "GetDpiForWindow"):
            dpi = int(user32.GetDpiForWindow(hwnd))
            if dpi > 0:
                return dpi / 96.0
    except Exception:
        pass
    return 1.0


def _capture_ai_frame(params: Dict[str, Any], target_hwnd: int) -> Dict[str, Any]:
    from tasks.task_utils import capture_window_smart

    screenshot = capture_window_smart(
        hwnd=int(target_hwnd),
        client_area_only=True,
        use_cache=False,
        capture_timeout=4.0,
    )
    if screenshot is None:
        raise RuntimeError("窗口截图失败")

    full_img_h, full_img_w = screenshot.shape[:2]
    scale_x = 1.0
    scale_y = 1.0
    scale_mismatch_physical = False
    client_w = full_img_w
    client_h = full_img_h
    dpi_scale = _get_window_dpi_scale(target_hwnd)
    process_awareness = _get_thread_dpi_awareness()
    process_dpi_aware = process_awareness is not None and process_awareness >= 1

    try:
        import win32gui

        if target_hwnd and win32gui.IsWindow(target_hwnd):
            rect = win32gui.GetClientRect(target_hwnd)
            client_w = max(0, rect[2] - rect[0])
            client_h = max(0, rect[3] - rect[1])
            if client_w > 0 and client_h > 0:
                scale_x = full_img_w / client_w
                scale_y = full_img_h / client_h
                scale_delta = abs(scale_x - scale_y)
                scale_ratio = (scale_x + scale_y) / 2.0
                if scale_ratio > 1.05 and scale_delta < 0.05:
                    scale_mismatch_physical = True
                    logger.debug("AI工具: 检测到DPI缩放差异，ratio=%.3f", scale_ratio)
            else:
                client_w = full_img_w
                client_h = full_img_h
    except Exception:
        client_w = full_img_w
        client_h = full_img_h

    region_offset_x = 0
    region_offset_y = 0
    region_width = 0
    region_height = 0
    use_region = _coerce_bool(params.get("use_recognition_region", params.get("use_region", False)))
    crop_for_recognition = use_region
    if use_region:
        rx = int(params.get("recognition_region_x", params.get("region_x", 0)) or 0)
        ry = int(params.get("recognition_region_y", params.get("region_y", 0)) or 0)
        rw = int(params.get("recognition_region_width", params.get("region_width", 0)) or 0)
        rh = int(params.get("recognition_region_height", params.get("region_height", 0)) or 0)
        if abs(scale_x - 1.0) > 0.01 or abs(scale_y - 1.0) > 0.01:
            rx = int(round(rx * scale_x))
            ry = int(round(ry * scale_y))
            rw = int(round(rw * scale_x))
            rh = int(round(rh * scale_y))
        if rw <= 0 or rh <= 0:
            raise RuntimeError("识别区域尺寸无效")
        rx2 = min(full_img_w, rx + rw)
        ry2 = min(full_img_h, ry + rh)
        if rx < 0 or ry < 0 or rx >= rx2 or ry >= ry2:
            raise RuntimeError("识别区域范围无效")
        if crop_for_recognition:
            screenshot = screenshot[ry:ry2, rx:rx2]
        region_offset_x = rx
        region_offset_y = ry
        region_width = rw
        region_height = rh

    compare_image = screenshot
    if use_region and not crop_for_recognition and region_width > 0 and region_height > 0:
        try:
            compare_image = screenshot[
                region_offset_y:region_offset_y + region_height,
                region_offset_x:region_offset_x + region_width,
            ]
        except Exception:
            compare_image = screenshot

    img_h, img_w = screenshot.shape[:2]
    return {
        "screenshot": screenshot,
        "compare_image": compare_image,
        "img_h": img_h,
        "img_w": img_w,
        "full_img_h": full_img_h,
        "full_img_w": full_img_w,
        "scale_x": scale_x,
        "scale_y": scale_y,
        "client_w": client_w,
        "client_h": client_h,
        "dpi_scale": dpi_scale,
        "process_dpi_aware": process_dpi_aware,
        "scale_mismatch_physical": scale_mismatch_physical,
        "region_offset_x": region_offset_x,
        "region_offset_y": region_offset_y,
        "region_width": region_width,
        "region_height": region_height,
        "use_region": use_region,
        "crop_for_recognition": crop_for_recognition,
    }


def _execute_continuous_command_mode(
    params: Dict[str, Any],
    execution_mode: str,
    target_hwnd: int,
    window_region: Optional[Tuple[int, int, int, int]],
    card_id: Optional[int],
    command_prompt: str,
    max_plan_steps: int,
    continuous_max_rounds: int,
    continuous_wait_between_rounds: float,
    executor_ref: Any,
    stop_checker,
) -> Tuple[bool, str, Optional[int]]:
    workflow_context = None
    api_key = params.get("api_key") or os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return _fail_ai_task(params, card_id, "OpenAI API Key 未配置", workflow_context, executor_ref)

    provider_mode = _normalize_ai_provider_mode(params.get("provider_mode"))
    api_protocol = _normalize_ai_api_protocol(
        params.get("api_protocol"),
        provider_mode=provider_mode,
        api_base_url=params.get("api_base_url"),
    )
    api_url_mode = _normalize_ai_api_url_mode(
        params.get("api_url_mode"),
        provider_mode=provider_mode,
        api_base_url=params.get("api_base_url"),
    )
    base_url, base_url_error = _resolve_ai_api_base_url(params)
    if base_url_error:
        return _fail_ai_task(params, card_id, base_url_error, workflow_context, executor_ref)

    model = (params.get("model") or "").strip()
    if not model:
        return _fail_ai_task(params, card_id, "模型名称为空", workflow_context, executor_ref)

    timeout = _resolve_continuous_command_timeout_seconds(params)
    protocol_probe_error = _probe_ai_protocol_support_if_needed(
        provider_mode=provider_mode,
        api_protocol=api_protocol,
        api_url_mode=api_url_mode,
        api_base_url=base_url,
        api_key=api_key,
        model=model,
        timeout_seconds=timeout,
    )
    if protocol_probe_error:
        return _fail_ai_task(params, card_id, protocol_probe_error, workflow_context, executor_ref)

    retry_enabled = _coerce_bool(params.get("enable_retry", True))
    retry_attempts = int(params.get("retry_attempts", 2) or 2)
    retry_interval = float(params.get("retry_interval", 1.0) or 1.0)
    total_attempts = 1 + (retry_attempts if retry_enabled else 0)
    history_lines: List[str] = []
    round_records: List[Dict[str, Any]] = []
    attempted_click_records: List[Dict[str, Any]] = []
    effective_max_plan_steps = _resolve_continuous_max_plan_steps(max_plan_steps)

    def _wait_retry_delay(wait_seconds: float) -> bool:
        total_wait = max(0.0, float(wait_seconds))
        if total_wait <= 0:
            return True
        elapsed = 0.0
        while elapsed < total_wait:
            if stop_checker and stop_checker():
                return False
            sleep_time = min(0.1, total_wait - elapsed)
            time.sleep(sleep_time)
            elapsed += sleep_time
        return not (stop_checker and stop_checker())

    def _request_command_response(
        prompt_text: str,
        image_b64: str,
        image_mime_type: str,
        img_w: int,
        img_h: int,
        round_index: int,
    ) -> Dict[str, Any]:
        mcp_prompt_text = prompt_text
        for attempt in range(1, total_attempts + 1):
            try:
                _update_runtime_parameter(
                    "runtime_status",
                    f"第{round_index}轮请求AI中 {round_index}/{continuous_max_rounds}（尝试{attempt}/{total_attempts}，超时{timeout:g}秒）",
                    card_id,
                    executor_ref,
                )
                mcp_result = _call_mcp_tool(
                    "openai_raw",
                    {
                        "image_base64": image_b64,
                        "image_mime_type": image_mime_type,
                        "prompt": mcp_prompt_text,
                        "provider_mode": provider_mode,
                        "api_protocol": api_protocol,
                        "api_url_mode": api_url_mode,
                        "api_base_url": base_url,
                        "api_key": api_key,
                        "model": model,
                        "timeout_seconds": timeout,
                    },
                    timeout,
                )
                _update_runtime_parameter(
                    "runtime_status",
                    f"第{round_index}轮解析AI响应中 {round_index}/{continuous_max_rounds}",
                    card_id,
                    executor_ref,
                )
                _set_ai_protocol_support_cache(
                    provider_mode,
                    api_protocol,
                    api_url_mode,
                    base_url,
                    api_key,
                    model,
                    True,
                    "",
                )
                output_text = str(mcp_result.get("output_text") or "")
                if not output_text:
                    raise RuntimeError("empty response from MCP")
                plan_obj, steps, status, detail, plan_error = _parse_and_validate_command_plan(
                    output_text,
                    command_prompt,
                    effective_max_plan_steps,
                    allow_exploratory_search=True,
                )
                if not plan_error and _command_requires_input_focus(command_prompt):
                    first_action = ""
                    for step in steps or []:
                        if not isinstance(step, dict):
                            continue
                        first_action = str(step.get("action") or step.get("task") or "").strip().lower()
                        if first_action:
                            break
                    input_box_already_clicked = any(
                        isinstance(record, dict) and bool(record.get("input_box"))
                        for record in attempted_click_records
                    )
                    current_round_clicks_input_box = any(
                        _step_is_input_box_click(step)
                        for step in (steps or [])
                        if isinstance(step, dict)
                    )
                    if first_action == "type" and not input_box_already_clicked and not current_round_clicks_input_box:
                        plan_error = "AI 在文本输入前未先点击输入框，已拒绝执行。"
                if not plan_error and _command_requires_submit_after_type(command_prompt):
                    if not _steps_provide_submit_after_type(steps or []):
                        plan_error = "AI 在网页导航任务中只输入了内容但未提交打开，已拒绝执行。"
                if not plan_error:
                    plan_error = _validate_continuous_round_steps(
                        steps or [],
                        effective_max_plan_steps,
                    )
                if not plan_error:
                    repeated_targets = _find_repeated_click_targets(steps or [], attempted_click_records)
                    if repeated_targets:
                        plan_error = "AI 指令计划重复点击已尝试目标：" + "；".join(repeated_targets[:3])
                if not plan_error:
                    return {
                        "output_text": output_text,
                        "plan_obj": plan_obj or {},
                        "steps": steps or [],
                        "status": status,
                        "detail": detail,
                    }
                if attempt >= total_attempts:
                    return {"output_text": output_text, "plan_error": plan_error}
                mcp_prompt_text = _build_command_repair_prompt(
                    command_prompt,
                    plan_error,
                    output_text,
                    img_w,
                    img_h,
                    effective_max_plan_steps,
                )
                _update_runtime_parameter(
                    "runtime_status",
                    f"第{round_index}轮计划校验失败，准备重试 {round_index}/{continuous_max_rounds}（下一次尝试{attempt + 1}/{total_attempts}）",
                    card_id,
                    executor_ref,
                )
                if not _wait_retry_delay(max(0.1, retry_interval) * attempt):
                    return {"stop": True}
            except Exception as exc:
                if stop_checker and stop_checker():
                    return {"stop": True}
                if _looks_like_protocol_unsupported(exc, api_protocol):
                    detail = _build_protocol_unsupported_message(exc, api_protocol)
                    _set_ai_protocol_support_cache(
                        provider_mode,
                        api_protocol,
                        api_url_mode,
                        base_url,
                        api_key,
                        model,
                        False,
                        detail,
                    )
                    return {"error": detail}
                formatted_error = _format_ai_error_message(exc)
                if attempt >= total_attempts or not _should_retry_exception(exc):
                    return {"error": formatted_error}
                _update_runtime_parameter(
                    "runtime_status",
                    f"第{round_index}轮请求失败，准备重试 {round_index}/{continuous_max_rounds}（下一次尝试{attempt + 1}/{total_attempts}）",
                    card_id,
                    executor_ref,
                )
                if not _wait_retry_delay(max(0.1, retry_interval) * attempt):
                    return {"stop": True}
        return {"error": "AI 未返回内容，请检查提示词或模型状态。"}

    _update_runtime_parameter("runtime_status", f"第1轮复核中 1/{continuous_max_rounds}", card_id, executor_ref)
    for round_index in range(1, continuous_max_rounds + 1):
        if stop_checker and stop_checker():
            return False, "停止工作流", None
        _update_runtime_parameter("runtime_status", f"第{round_index}轮复核中 {round_index}/{continuous_max_rounds}", card_id, executor_ref)
        try:
            frame = _capture_ai_frame(params, int(target_hwnd))
        except Exception as exc:
            return _fail_ai_task(params, card_id, f"窗口截图失败: {exc}", workflow_context, executor_ref)
        try:
            image_b64, image_mime_type = _encode_image_to_base64(frame["screenshot"])
        except Exception as exc:
            return _fail_ai_task(params, card_id, f"图片编码失败: {exc}", workflow_context, executor_ref)
        if not image_b64 or not image_mime_type:
            return _fail_ai_task(params, card_id, "图片编码失败", workflow_context, executor_ref)

        if not attempted_click_records:
            tried_text = "无"
        else:
            recent_attempts = [
                item for item in (
                    _summarize_attempted_click_record(record)
                    for record in attempted_click_records[-6:]
                )
                if item
            ]
            tried_text = "已尝试点击数: " + str(len(attempted_click_records))
            if recent_attempts:
                tried_text += "；最近已尝试目标: " + "、".join(recent_attempts)
        round_context_lines = history_lines[-8:]
        if round_records:
            last_context = _summarize_continuous_round_context(round_records[-1])
            if last_context:
                round_context_lines.append(last_context)
        prompt_text = _build_continuous_command_prompt(
            command_prompt,
            frame["img_w"],
            frame["img_h"],
            effective_max_plan_steps,
            round_index,
            continuous_max_rounds,
            "\n".join(round_context_lines + [tried_text]),
        )
        response = _request_command_response(
            prompt_text,
            image_b64,
            image_mime_type,
            frame["img_w"],
            frame["img_h"],
            round_index,
        )
        if response.get("stop"):
            return False, "停止工作流", None
        if response.get("error"):
            return _fail_ai_task(params, card_id, str(response.get("error") or ""), workflow_context, executor_ref)
        if response.get("plan_error"):
            _update_runtime_output(str(response.get("output_text") or ""), card_id, executor_ref)
            return _fail_ai_task(params, card_id, str(response.get("plan_error") or ""), workflow_context, executor_ref)

        output_text = str(response.get("output_text") or "")
        plan_obj = response.get("plan_obj") or {}
        steps = response.get("steps") or []
        status = str(response.get("status") or "running")
        detail = str(response.get("detail") or "").strip()
        round_record: Dict[str, Any] = {
            "round": round_index,
            "status": status,
            "reason": detail,
            "plan": plan_obj,
            "phase": _extract_command_response_field(plan_obj, "phase", "stage"),
            "progress": _extract_command_response_field(plan_obj, "progress"),
            "expected_result": _extract_command_response_field(plan_obj, "expected_result", "expected", "verification"),
            "completion_signal": _extract_command_response_field(plan_obj, "completion_signal", "done_when"),
        }
        round_records.append(round_record)
        status_line = f"第{round_index}轮 规划状态: {status}"
        if round_record.get("phase"):
            status_line += f" | 阶段: {round_record['phase']}"
        if detail:
            status_line += f" - {detail}"
        _append_runtime_trace(status_line, card_id, executor_ref)
        if round_record.get("expected_result"):
            _append_runtime_trace(
                f"第{round_index}轮 预期结果: {round_record['expected_result']}",
                card_id,
                executor_ref,
            )

        if status == "completed" and not steps:
            _update_runtime_parameter("runtime_status", f"连续执行完成，共{round_index}轮", card_id, executor_ref)
            try:
                display_text = json.dumps(
                    {"mode": "continuous", "status": "completed", "reason": detail, "rounds": round_records},
                    ensure_ascii=False,
                )
            except Exception:
                display_text = detail or "任务已完成"
            _update_runtime_output(display_text, card_id, executor_ref)
            return handle_success_action(params, card_id, stop_checker)

        if status == "failed" and not steps:
            _update_runtime_output(output_text or detail, card_id, executor_ref)
            return _fail_ai_task(params, card_id, detail or "AI 反馈当前任务无法继续。", workflow_context, executor_ref)

        if not steps:
            _update_runtime_output(output_text, card_id, executor_ref)
            return _fail_ai_task(params, card_id, "连续执行未返回下一步动作。", workflow_context, executor_ref)

        plan_summary = "；".join(_summarize_command_step(step) for step in steps)
        history_lines.append(f"第{round_index}轮 计划: {plan_summary}")
        _append_runtime_trace(history_lines[-1], card_id, executor_ref)
        debug_snapshot_path = _save_continuous_round_debug_snapshot(
            frame["screenshot"],
            steps,
            round_index,
            card_id,
        )
        if debug_snapshot_path:
            _append_runtime_trace(f"第{round_index}轮 调试图: {debug_snapshot_path}", card_id, executor_ref)
        exec_result = _execute_plan_local(
            steps,
            execution_mode,
            target_hwnd,
            window_region,
            True,
            frame["img_w"],
            frame["img_h"],
            "自动(推荐)",
            (
                int(frame.get("region_offset_x", 0) or 0),
                int(frame.get("region_offset_y", 0) or 0),
            ) if frame.get("crop_for_recognition") and frame.get("use_region") else None,
        )
        round_record["result"] = exec_result
        exec_summary = _summarize_exec_result(exec_result)
        round_record["exec_summary"] = exec_summary
        history_lines.append(f"第{round_index}轮 执行: {exec_summary}")
        _append_runtime_trace(history_lines[-1], card_id, executor_ref)
        for step in steps:
            if not isinstance(step, dict):
                continue
            action = str(step.get("action") or step.get("task") or "").strip().lower()
            if action != "click":
                continue
            record = _build_click_attempt_record(step)
            if record:
                attempted_click_records.append(record)
        if not exec_result or not exec_result.get("success", False):
            try:
                display_text = json.dumps(
                    {"mode": "continuous", "status": "failed", "rounds": round_records},
                    ensure_ascii=False,
                )
            except Exception:
                display_text = exec_summary
            _update_runtime_output(display_text, card_id, executor_ref)
            return _fail_ai_task(params, card_id, _extract_plan_failure_detail(exec_result), workflow_context, executor_ref)

        if round_index < continuous_max_rounds:
            _update_runtime_parameter(
                "runtime_status",
                f"第{round_index}轮执行完成，等待第{round_index + 1}轮复核",
                card_id,
                executor_ref,
            )
            if not _wait_retry_delay(continuous_wait_between_rounds):
                return False, "停止工作流", None

    try:
        display_text = json.dumps(
            {"mode": "continuous", "status": "timeout", "rounds": round_records},
            ensure_ascii=False,
        )
    except Exception:
        display_text = "已达到最大轮数"
    _update_runtime_output(display_text, card_id, executor_ref)
    return _fail_ai_task(params, card_id, "已达到最大轮数，任务仍未完成。", workflow_context, executor_ref)


def _execute_direct_chat_mode(
    params: Dict[str, Any],
    card_id: Optional[int],
    command_prompt: str,
    executor_ref: Any,
    stop_checker,
) -> Tuple[bool, str, Optional[int]]:
    workflow_context = None
    api_key = params.get("api_key") or os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return _fail_ai_task(params, card_id, "OpenAI API Key 未配置", workflow_context, executor_ref)

    provider_mode = _normalize_ai_provider_mode(params.get("provider_mode"))
    api_protocol = _normalize_ai_api_protocol(
        params.get("api_protocol"),
        provider_mode=provider_mode,
        api_base_url=params.get("api_base_url"),
    )
    api_url_mode = _normalize_ai_api_url_mode(
        params.get("api_url_mode"),
        provider_mode=provider_mode,
        api_base_url=params.get("api_base_url"),
    )
    base_url, base_url_error = _resolve_ai_api_base_url(params)
    if base_url_error:
        return _fail_ai_task(params, card_id, base_url_error, workflow_context, executor_ref)

    model = (params.get("model") or "").strip()
    if not model:
        return _fail_ai_task(params, card_id, "模型名称为空", workflow_context, executor_ref)

    timeout = _resolve_direct_chat_timeout_seconds(params)
    protocol_probe_error = _probe_ai_protocol_support_if_needed(
        provider_mode=provider_mode,
        api_protocol=api_protocol,
        api_url_mode=api_url_mode,
        api_base_url=base_url,
        api_key=api_key,
        model=model,
        timeout_seconds=timeout,
    )
    if protocol_probe_error:
        return _fail_ai_task(params, card_id, protocol_probe_error, workflow_context, executor_ref)

    retry_enabled = _coerce_bool(params.get("enable_retry", True))
    retry_attempts = int(params.get("retry_attempts", 2) or 2)
    retry_interval = float(params.get("retry_interval", 1.0) or 1.0)
    total_attempts = 1 + (retry_attempts if retry_enabled else 0)
    history_messages = _normalize_chat_history_messages(params.get("ai_chat_history"))

    def _wait_retry_delay(wait_seconds: float) -> bool:
        total_wait = max(0.0, float(wait_seconds))
        if total_wait <= 0:
            return True
        elapsed = 0.0
        while elapsed < total_wait:
            if stop_checker and stop_checker():
                return False
            sleep_time = min(0.1, total_wait - elapsed)
            time.sleep(sleep_time)
            elapsed += sleep_time
        return not (stop_checker and stop_checker())

    for attempt in range(1, total_attempts + 1):
        if stop_checker and stop_checker():
            return False, "停止工作流", None
        try:
            _update_runtime_parameter(
                "runtime_status",
                f"直接对话请求AI中（尝试{attempt}/{total_attempts}，超时{timeout:g}秒）",
                card_id,
                executor_ref,
            )
            result = _request_text_response(
                prompt_text=command_prompt,
                api_base_url=base_url,
                api_key=api_key,
                model=model,
                timeout_seconds=timeout,
                provider_mode=provider_mode,
                api_protocol=api_protocol,
                api_url_mode=api_url_mode,
                history_messages=history_messages,
            )
            output_text = str(result.get("output_text") or "").strip()
            if not output_text:
                raise RuntimeError("empty model output")
            _update_runtime_parameter("runtime_status", "直接对话完成", card_id, executor_ref)
            _update_runtime_output(output_text, card_id, executor_ref)
            return handle_success_action(params, card_id, stop_checker)
        except Exception as exc:
            formatted_error = _format_ai_error_message(exc)
            if attempt >= total_attempts or not _should_retry_exception(exc):
                return _fail_ai_task(params, card_id, formatted_error, workflow_context, executor_ref)
            _update_runtime_parameter(
                "runtime_status",
                f"直接对话请求失败，准备重试（下一次尝试{attempt + 1}/{total_attempts}）",
                card_id,
                executor_ref,
            )
            if not _wait_retry_delay(max(0.1, retry_interval) * attempt):
                return False, "停止工作流", None

    return _fail_ai_task(params, card_id, "AI 未返回内容，请检查提示词或模型状态。", workflow_context, executor_ref)


def _resolve_ai_route_mode(params: Dict[str, Any], command_prompt: str) -> str:
    explicit_mode = str(params.get("ai_cli_route_mode") or params.get("route_mode") or "").strip().lower()
    if explicit_mode in {"chat", "tool"}:
        return explicit_mode
    return "tool" if _command_requires_tool_execution(command_prompt) else "chat"


def execute_task(params: Dict[str, Any], counters: Dict[str, int], execution_mode: str,
                 target_hwnd: Optional[int], window_region: Optional[Tuple[int, int, int, int]],
                 card_id: Optional[int] = None, **kwargs) -> Tuple[bool, str, Optional[int]]:
    """执行AI工具任务，普通对话直连模型，工具型指令走连续执行链路。"""
    executor_ref = kwargs.get("executor")
    stop_checker = kwargs.get("stop_checker")
    _clear_runtime_parameters(card_id, executor_ref)
    _update_runtime_parameter("runtime_status", "准备执行", card_id, executor_ref)

    command_prompt = (params.get("command_prompt") or "").strip()
    if not command_prompt:
        return _fail_ai_task(params, card_id, "执行指令为空", None, executor_ref)
    route_mode = _resolve_ai_route_mode(params, command_prompt)
    if route_mode == "chat":
        return _execute_direct_chat_mode(
            params=params,
            card_id=card_id,
            command_prompt=command_prompt,
            executor_ref=executor_ref,
            stop_checker=stop_checker,
        )
    if not target_hwnd:
        return _fail_ai_task(params, card_id, "需要有效的目标窗口句柄", None, executor_ref)

    return _execute_continuous_command_mode(
        params=params,
        execution_mode=execution_mode,
        target_hwnd=int(target_hwnd),
        window_region=window_region,
        card_id=card_id,
        command_prompt=command_prompt,
        max_plan_steps=CONTINUOUS_COMMAND_MAX_STEPS,
        continuous_max_rounds=CONTINUOUS_COMMAND_MAX_ROUNDS,
        continuous_wait_between_rounds=CONTINUOUS_COMMAND_WAIT_SECONDS,
        executor_ref=executor_ref,
        stop_checker=stop_checker,
    )



