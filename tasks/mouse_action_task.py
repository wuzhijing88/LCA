# -*- coding: utf-8 -*-

"""
模拟鼠标操作任务模块
整合了鼠标点击、滚轮操作和拖拽功能，通过下拉选择区分不同的操作模式
"""

import logging
import os
import random
import math
from typing import Dict, Any, Optional, Tuple, List
import cv2
import numpy as np

logger = logging.getLogger(__name__)

# 使用统一的延迟处理

# 导入高精度睡眠函数
from .task_utils import (
    precise_sleep,
    coerce_bool,
    safe_imread as _shared_safe_imread,
    capture_and_match_template_smart,
)
from .click_action_executor import execute_simulator_click_action
from .click_param_resolver import resolve_click_params, normalize_button
from utils.input.relative_mouse_move import perform_timed_relative_move as _shared_perform_timed_relative_move
from utils.match.smart_image_matcher import normalize_match_image
from utils.input.input_timing import (
    DEFAULT_CLICK_HOLD_SECONDS,
    DEFAULT_DOUBLE_CLICK_INTERVAL_SECONDS,
    DEFAULT_RANDOM_CLICK_HOLD_MAX_SECONDS,
    DEFAULT_RANDOM_CLICK_HOLD_MIN_SECONDS,
)

# 导入截图助手和驱动（方案三：保留截图，移除输入操作）

# _interruptible_sleep 函数已移至 task_utils.py

def safe_imread(image_path, flags=cv2.IMREAD_COLOR):
    """安全读取图片（统一复用 task_utils 版本，兼容BGRA->BGR）。"""
    try:
        image = _shared_safe_imread(image_path, flags=flags)
        if image is None:
            return None
        if (
            isinstance(image, np.ndarray)
            and len(image.shape) == 3
            and image.shape[2] == 4
            and flags != cv2.IMREAD_UNCHANGED
        ):
            return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
        return image
    except Exception as e:
        logger.error(f"安全图像读取失败 {image_path}: {e}")
        return None

# 任务类型标识
TASK_TYPE = "模拟鼠标操作"
TASK_NAME = "模拟鼠标操作"


def _resolve_drag_button(button: Any) -> Optional[str]:
    """统一解析拖拽按钮，避免链路中途回落为左键。"""
    normalized = normalize_button(button, default="")
    return normalized or None


def requires_input_lock(params: Dict[str, Any]) -> bool:
    """
    Lock input only when this card may perform real input actions.

    For image-recognition-only mode (find image + no click), input lock is skipped
    so parallel threads are not serialized by the input guard.
    """
    p = params or {}
    if "image_enable_click" in p and (not coerce_bool(p.get("image_enable_click", True))):
        return False
    return True


def _normalize_operation_mode(value: Any) -> str:
    """归一化操作模式，兼容旧模式名。"""
    legacy_mode_by_index = [
        "找图功能",
        "坐标点击",
        "文字点击",
        "找色功能",
        "元素点击",
        "鼠标滚轮",
        "鼠标拖拽",
        "鼠标移动",
    ]

    mode = ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        idx = int(value)
        if 0 <= idx < len(legacy_mode_by_index):
            mode = legacy_mode_by_index[idx]
        else:
            mode = str(value).strip()
    else:
        mode = str(value or "").strip()
        if mode.isdigit():
            idx = int(mode)
            if 0 <= idx < len(legacy_mode_by_index):
                mode = legacy_mode_by_index[idx]

    alias_map = {
        "图片点击": "找图功能",
        "找图点击": "找图功能",
        "找图功能": "找图功能",
        "找色点击": "找色功能",
        "找色功能": "找色功能",
    }
    return alias_map.get(mode, mode)


def _apply_click_offsets(
    base_x: int,
    base_y: int,
    position_mode: str,
    fixed_offset_x: int = 0,
    fixed_offset_y: int = 0,
    random_offset_x: int = 0,
    random_offset_y: int = 0,
) -> Tuple[int, int, int, int]:
    """统一处理点击偏移：固定偏移模式下也允许叠加随机偏移。"""
    click_x = int(base_x)
    click_y = int(base_y)
    applied_offset_x = 0
    applied_offset_y = 0

    if position_mode == '固定偏移':
        click_x += int(fixed_offset_x)
        click_y += int(fixed_offset_y)
        applied_offset_x += int(fixed_offset_x)
        applied_offset_y += int(fixed_offset_y)
        if random_offset_x > 0 or random_offset_y > 0:
            extra_offset_x = random.randint(-int(random_offset_x), int(random_offset_x)) if random_offset_x > 0 else 0
            extra_offset_y = random.randint(-int(random_offset_y), int(random_offset_y)) if random_offset_y > 0 else 0
            click_x += extra_offset_x
            click_y += extra_offset_y
            applied_offset_x += extra_offset_x
            applied_offset_y += extra_offset_y
    elif position_mode == '随机偏移':
        applied_offset_x = random.randint(-int(random_offset_x), int(random_offset_x)) if random_offset_x > 0 else 0
        applied_offset_y = random.randint(-int(random_offset_y), int(random_offset_y)) if random_offset_y > 0 else 0
        click_x += applied_offset_x
        click_y += applied_offset_y

    return click_x, click_y, applied_offset_x, applied_offset_y


def get_display_name(params: Dict[str, Any] = None) -> str:
    """获取任务显示名称"""
    if params and 'operation_mode' in params:
        operation_mode = _normalize_operation_mode(params['operation_mode'])
        if operation_mode == "鼠标移动":
            return "鼠标移动"
        elif operation_mode == "鼠标拖拽":
            return "鼠标拖拽"
        elif operation_mode == "鼠标滚轮":
            return "鼠标滚轮"
        else:
            return f"{operation_mode}"
    return TASK_NAME

def get_params_definition() -> Dict[str, Dict[str, Any]]:
    """获取参数定义"""
    params = {
        # 操作模式选择
        "operation_mode": {
            "label": "操作模式",
            "type": "select",
            "options": ["坐标点击", "找图功能", "文字点击", "找色功能", "元素点击", "鼠标滚轮", "鼠标拖拽", "鼠标移动"],
            "default": "坐标点击",
            "tooltip": "选择鼠标操作模式"
        },

        # 元素点击相关参数
        "---element_click_params---": {
            "type": "separator",
            "label": "元素点击参数（基于UIAutomation）",
            "condition": {"param": "operation_mode", "value": "元素点击"}
        },
        "element_picker": {
            "type": "button",
            "label": "拾取元素",
            "button_text": "拾取元素 (右键确认)",
            "widget_hint": "element_picker",
            "tooltip": "点击后移动鼠标到目标元素，右键确认拾取，ESC取消",
            "condition": {"param": "operation_mode", "value": "元素点击"}
        },
        "enable_browser_accessibility": {
            "type": "button",
            "label": "浏览器支持",
            "button_text": "启用浏览器辅助功能",
            "widget_hint": "enable_browser_accessibility",
            "tooltip": "为Chrome/Edge启用UIAutomation支持，启用后需重启浏览器",
            "condition": {"param": "operation_mode", "value": "元素点击"}
        },
        "element_name": {
            "label": "元素名称",
            "type": "text",
            "default": "",
            "tooltip": "元素的名称属性，如按钮文字\"确定\"、\"取消\"等",
            "condition": {"param": "operation_mode", "value": "元素点击"}
        },
        "element_automation_id": {
            "label": "自动化标识",
            "type": "text",
            "default": "",
            "tooltip": "元素的自动化标识属性，开发者定义的唯一标识",
            "condition": {"param": "operation_mode", "value": "元素点击"}
        },
        "element_class_name": {
            "label": "类名",
            "type": "text",
            "default": "",
            "tooltip": "元素的类名属性",
            "condition": {"param": "operation_mode", "value": "元素点击"}
        },
        "element_control_type": {
            "label": "控件类型",
            "type": "select",
            "options": ["无", "按钮", "编辑框", "文本", "复选框",
                       "单选按钮", "下拉框", "列表", "列表项",
                       "菜单", "菜单项", "树", "树节点",
                       "选项卡", "选项卡项", "超链接", "窗口",
                       "面板", "分组", "数据表格", "表格"],
            "default": "无",
            "tooltip": "控件类型，选择无表示不限制",
            "condition": {"param": "operation_mode", "value": "元素点击"}
        },
        "element_found_index": {
            "label": "匹配索引",
            "type": "int",
            "default": 0,
            "min": 0,
            "max": 99,
            "tooltip": "当匹配到多个元素时，选择第几个（从0开始）",
            "condition": {"param": "operation_mode", "value": "元素点击"}
        },
        "element_search_depth": {
            "label": "搜索深度",
            "type": "int",
            "default": 30,
            "min": 1,
            "max": 100,
            "tooltip": "控件树搜索深度，浏览器网页建议30以上",
            "condition": {"param": "operation_mode", "value": "元素点击"}
        },
        "element_timeout": {
            "label": "超时时间(秒)",
            "type": "float",
            "default": 5.0,
            "min": 0.5,
            "max": 60.0,
            "decimals": 1,
            "tooltip": "查找元素的超时时间",
            "condition": {"param": "operation_mode", "value": "元素点击"}
        },
        "element_use_invoke": {
            "label": "使用Invoke模式",
            "type": "bool",
            "default": True,
            "tooltip": "启用：使用Invoke模式点击（不移动鼠标，更可靠）；禁用：使用坐标点击",
            "condition": [
                {"param": "operation_mode", "value": "元素点击"},
                {"param": "element_enable_click", "value": True}
            ]
        },
        "element_enable_click": {
            "label": "启用点击",
            "type": "bool",
            "default": True,
            "tooltip": "关闭后仅定位元素，不执行点击",
            "condition": {"param": "operation_mode", "value": "元素点击"}
        },
        "element_button": {
            "label": "鼠标按钮",
            "type": "select",
            "options": ["左键", "右键", "中键"],
            "default": "左键",
            "tooltip": "选择要点击的鼠标按钮",
            "condition": [
                {"param": "operation_mode", "value": "元素点击"},
                {"param": "element_enable_click", "value": True}
            ]
        },

        # 找图功能相关参数
        "---image_click_params---": {
            "type": "separator",
            "label": "找图功能参数",
            "condition": {"param": "operation_mode", "value": "找图功能"}
        },
        "multi_image_mode": {
            "label": "多图识别模式",
            "type": "select",
            "options": ["单图识别", "多图识别"],
            "default": "单图识别",
            "tooltip": "单图识别：只配置一张图片；多图识别：配置多张图片进行识别",
            "condition": {"param": "operation_mode", "value": "找图功能"}
        },
        "enable_parallel_recognition": {
            "label": "启用并行识别",
            "type": "checkbox",
            "default": True,
            "tooltip": "启用：多张图片并行识别，速度提升3-5倍；禁用：传统串行识别",
            "condition": [
                {"param": "operation_mode", "value": "找图功能"},
                {"param": "multi_image_mode", "value": "多图识别"}
            ]
        },
        "image_path": {
            "label": "目标图片路径",
            "type": "file",
            "default": "",
            "file_filter": "图片 (*.png *.jpg *.jpeg *.bmp *.webp *.gif *.tif *.tiff);;所有文件 (*.*)",
            "tooltip": "需要查找并点击的图片文件",
            "condition": [
                {"param": "operation_mode", "value": "找图功能"},
                {"param": "multi_image_mode", "value": "单图识别"}
            ]
        },
        "image_paths": {
            "label": "多图片路径",
            "type": "text",
            "default": "",
            "tooltip": "多张图片路径，每行一个路径。支持相对路径和绝对路径",
            "multiline": True,
            "condition": [
                {"param": "operation_mode", "value": "找图功能"},
                {"param": "multi_image_mode", "value": "多图识别"}
            ]
        },
        "click_all_found": {
            "label": "全部点击",
            "type": "bool",
            "default": False,
            "tooltip": "启用：点击所有识别成功的图片；禁用：只点击第一张识别成功的图片",
            "condition": [
                {"param": "operation_mode", "value": "找图功能"},
                {"param": "multi_image_mode", "value": "多图识别"}
            ]
        },
        "clear_clicked_on_next_run": {
            "label": "下次执行清除已点击记录",
            "type": "bool",
            "default": False,
            "tooltip": "启用：下次执行时清除已点击的图片记录；禁用：保持已点击记录直到全部完成",
            "condition": [
                {"param": "operation_mode", "value": "找图功能"},
                {"param": "multi_image_mode", "value": "多图识别"}
            ]
        },
        "multi_image_delay": {
            "label": "每张图片识别延迟",
            "type": "float",
            "default": 1.0,
            "min": 0.0,
            "max": 10.0,
            "decimals": 1,
            "tooltip": "每张图片识别点击后的延迟时间（秒），防止速度过快导致图片识别失败",
            "condition": [
                {"param": "operation_mode", "value": "找图功能"},
                {"param": "multi_image_mode", "value": "多图识别"}
            ]
        },
        # 多图识别专用的识别区域参数
        "multi_use_recognition_region": {
            "label": "使用识别区域",
            "type": "bool",
            "default": False,
            "tooltip": "启用：仅在指定区域内识别图片；禁用：在整个窗口/屏幕范围识别",
            "condition": [
                {"param": "operation_mode", "value": "找图功能"},
                {"param": "multi_image_mode", "value": "多图识别"}
            ]
        },
        "multi_image_region_selector": {
            "label": "识别区域",
            "type": "button",
            "widget_hint": "multi_image_region_selector",
            "button_text": "点击框选识别区域",
            "tooltip": "点击按钮在目标窗口上框选多图识别区域",
            "condition": [
                {"param": "operation_mode", "value": "找图功能"},
                {"param": "multi_image_mode", "value": "多图识别"},
                {"param": "multi_use_recognition_region", "value": True}
            ]
        },
        "multi_recognition_region_x": {
            "label": "识别区域X",
            "type": "hidden",
            "default": 0,
            "condition": [
                {"param": "operation_mode", "value": "找图功能"},
                {"param": "multi_image_mode", "value": "多图识别"}
            ]
        },
        "multi_recognition_region_y": {
            "label": "识别区域Y",
            "type": "hidden",
            "default": 0,
            "condition": [
                {"param": "operation_mode", "value": "找图功能"},
                {"param": "multi_image_mode", "value": "多图识别"}
            ]
        },
        "multi_recognition_region_width": {
            "label": "识别区域宽度",
            "type": "hidden",
            "default": 0,
            "condition": [
                {"param": "operation_mode", "value": "找图功能"},
                {"param": "multi_image_mode", "value": "多图识别"}
            ]
        },
        "multi_recognition_region_height": {
            "label": "识别区域高度",
            "type": "hidden",
            "default": 0,
            "condition": [
                {"param": "operation_mode", "value": "找图功能"},
                {"param": "multi_image_mode", "value": "多图识别"}
            ]
        },
        "confidence": {
            "label": "查找置信度",
            "type": "float",
            "default": 0.8,
            "min": 0.1,
            "max": 1.0,
            "decimals": 2,
            "tooltip": "图片匹配的相似度阈值 (0.1 到 1.0)",
            "condition": {"param": "operation_mode", "value": "找图功能"}
        },
        "test_image_recognition": {
            "label": "找图测试",
            "type": "button",
            "button_text": "测试找图并绘制结果",
            "tooltip": "测试图片识别，在绑定窗口上绘制出找到的图片区域",
            "action": "test_image_recognition",
            "condition": {"param": "operation_mode", "value": "找图功能"}
        },
        "use_recognition_region": {
            "label": "使用识别区域",
            "type": "bool",
            "default": False,
            "tooltip": "启用：仅在指定区域内识别图片；禁用：在整个窗口/屏幕范围识别",
            "condition": [
                {"param": "operation_mode", "value": "找图功能"},
                {"param": "multi_image_mode", "value": "单图识别"}
            ]
        },
        "image_region_selector": {
            "label": "识别区域",
            "type": "button",
            "widget_hint": "image_region_selector",
            "button_text": "点击框选识别区域",
            "tooltip": "点击按钮在目标窗口上框选图片识别区域",
            "condition": [
                {"param": "operation_mode", "value": "找图功能"},
                {"param": "multi_image_mode", "value": "单图识别"},
                {"param": "use_recognition_region", "value": True}
            ]
        },
        "recognition_region_x": {
            "label": "识别区域X",
            "type": "hidden",
            "default": 0,
            "condition": [
                {"param": "operation_mode", "value": "找图功能"},
                {"param": "multi_image_mode", "value": "单图识别"}
            ]
        },
        "recognition_region_y": {
            "label": "识别区域Y",
            "type": "hidden",
            "default": 0,
            "condition": [
                {"param": "operation_mode", "value": "找图功能"},
                {"param": "multi_image_mode", "value": "单图识别"}
            ]
        },
        "recognition_region_width": {
            "label": "识别区域宽度",
            "type": "hidden",
            "default": 0,
            "condition": [
                {"param": "operation_mode", "value": "找图功能"},
                {"param": "multi_image_mode", "value": "单图识别"}
            ]
        },
        "recognition_region_height": {
            "label": "识别区域高度",
            "type": "hidden",
            "default": 0,
            "condition": [
                {"param": "operation_mode", "value": "找图功能"},
                {"param": "multi_image_mode", "value": "单图识别"}
            ]
        },
        "image_enable_click": {
            "label": "识别后执行点击",
            "type": "bool",
            "default": True,
            "tooltip": "启用：识别成功后执行点击；禁用：仅识别不点击",
            "condition": {"param": "operation_mode", "value": "找图功能"}
        },
        "image_position_mode": {
            "label": "点击位置",
            "type": "select",
            "options": ["精准坐标", "固定偏移", "随机偏移"],
            "default": "精准坐标",
            "tooltip": "精准坐标：使用图片中心精准点击\n固定偏移：先在图片中心基础上添加固定偏移，再可选叠加随机偏移\n随机偏移：在图片中心基础上添加随机偏移",
            "condition": {"param": "operation_mode", "value": "找图功能"}
        },
        "image_offset_selector_tool": {
            "label": "偏移选择",
            "type": "button",
            "button_text": "拖拽选择偏移",
            "tooltip": "从目标点拖拽选择固定偏移距离，会自动切换为固定偏移",
            "widget_hint": "offset_selector",
            "related_params": ["image_fixed_offset_x", "image_fixed_offset_y", "image_position_mode"],
            "condition": {"param": "operation_mode", "value": "找图功能"}
        },
"image_fixed_offset_x": {
            "label": "固定X偏移(像素)",
            "type": "int",
            "default": 0,
            "tooltip": "在图片位置上增加固定的X偏移（正数向右，负数向左）",
            "condition": [
                {"param": "operation_mode", "value": "找图功能"},
                {"param": "image_position_mode", "value": "固定偏移"}
            ]
        },
        "image_fixed_offset_y": {
            "label": "固定Y偏移(像素)",
            "type": "int",
            "default": 0,
            "tooltip": "在图片位置上增加固定的Y偏移（正数向下，负数向上）",
            "condition": [
                {"param": "operation_mode", "value": "找图功能"},
                {"param": "image_position_mode", "value": "固定偏移"}
            ]
        },
        "image_random_offset_x": {
            "label": "随机X偏移范围(像素)",
            "type": "int",
            "default": 5,
            "min": 0,
            "tooltip": "X轴随机偏移范围，实际偏移在 [-X, +X] 范围内随机；固定偏移模式下会叠加在固定偏移后的坐标上",
            "condition": {
                "param": "operation_mode",
                "value": "找图功能",
                "and": {"param": "image_position_mode", "value": ["固定偏移", "随机偏移"], "operator": "in"}
            }
        },
        "image_random_offset_y": {
            "label": "随机Y偏移范围(像素)",
            "type": "int",
            "default": 5,
            "min": 0,
            "tooltip": "Y轴随机偏移范围，实际偏移在 [-Y, +Y] 范围内随机；固定偏移模式下会叠加在固定偏移后的坐标上",
            "condition": {
                "param": "operation_mode",
                "value": "找图功能",
                "and": {"param": "image_position_mode", "value": ["固定偏移", "随机偏移"], "operator": "in"}
            }
        },
        "image_click_action": {
            "label": "点击动作",
            "type": "select",
            "options": ["完整点击", "双击", "仅按下", "仅松开"],
            "default": "完整点击",
            "tooltip": "完整点击：按下并松开；双击：连续两次点击；仅按下：按下不松开；仅松开：松开按钮",
            "condition": {"param": "operation_mode", "value": "找图功能"}
        },
        "image_enable_auto_release": {
            "label": "自动释放",
            "type": "bool",
            "default": True,
            "tooltip": "启用后，按下鼠标后会自动释放。",
            "condition": [
                {"param": "operation_mode", "value": "找图功能"},
                {"param": "image_click_action", "value": "仅按下"}
            ]
        },
        "image_hold_mode": {
            "label": "持续时间模式",
            "type": "select",
            "options": ["固定持续时间", "随机持续时间"],
            "default": "固定持续时间",
            "tooltip": "选择按键按下后持续时间的模式。",
            "condition": [
                {"param": "operation_mode", "value": "找图功能"},
                {"param": "image_click_action", "value": "仅按下"},
                {"param": "image_enable_auto_release", "value": True}
            ]
        },
        "image_hold_duration": {
            "label": "按下持续时间(秒)",
            "type": "float",
            "default": DEFAULT_CLICK_HOLD_SECONDS,
            "min": 0.0,
            "decimals": 2,
            "tooltip": "按下鼠标后保持的时间",
            "condition": [
                {"param": "operation_mode", "value": "找图功能"},
                {"param": "image_click_action", "value": "仅按下"},
                {"param": "image_enable_auto_release", "value": True},
                {"param": "image_hold_mode", "value": "固定持续时间"}
            ]
        },
        "image_hold_duration_min": {
            "label": "持续时间最小值(秒)",
            "type": "float",
            "default": DEFAULT_RANDOM_CLICK_HOLD_MIN_SECONDS,
            "min": 0.0,
            "decimals": 2,
            "tooltip": "随机持续时间的最小值。",
            "condition": [
                {"param": "operation_mode", "value": "找图功能"},
                {"param": "image_click_action", "value": "仅按下"},
                {"param": "image_enable_auto_release", "value": True},
                {"param": "image_hold_mode", "value": "随机持续时间"}
            ]
        },
        "image_hold_duration_max": {
            "label": "持续时间最大值(秒)",
            "type": "float",
            "default": DEFAULT_RANDOM_CLICK_HOLD_MAX_SECONDS,
            "min": 0.0,
            "decimals": 2,
            "tooltip": "随机持续时间的最大值。",
            "condition": [
                {"param": "operation_mode", "value": "找图功能"},
                {"param": "image_click_action", "value": "仅按下"},
                {"param": "image_enable_auto_release", "value": True},
                {"param": "image_hold_mode", "value": "随机持续时间"}
            ]
        },

        # 文字点击相关参数
        "---text_click_params---": {
            "type": "separator",
            "label": "文字点击参数",
            "condition": {"param": "operation_mode", "value": "文字点击"}
        },
        "text_match_mode": {
            "label": "文字匹配模式",
            "type": "select",
            "options": ["包含", "完全匹配"],
            "default": "包含",
            "tooltip": "文字匹配的方式\n包含：目标文字包含在识别文字中即可\n完全匹配：识别文字必须与目标文字完全一致",
            "condition": {"param": "operation_mode", "value": "文字点击"}
        },
        "text_enable_click": {
            "label": "识别后执行点击",
            "type": "bool",
            "default": True,
            "tooltip": "启用：识别到目标文字后执行点击；禁用：仅识别不点击",
            "condition": {"param": "operation_mode", "value": "文字点击"}
        },
        "text_position_mode": {
            "label": "点击位置",
            "type": "select",
            "options": ["精准坐标", "固定偏移", "随机偏移"],
            "default": "精准坐标",
            "tooltip": "精准坐标：使用文字中心精准点击\n固定偏移：先在文字中心基础上添加固定偏移，再可选叠加随机偏移\n随机偏移：在文字中心基础上添加随机偏移",
            "condition": {"param": "operation_mode", "value": "文字点击"}
        },
        "text_offset_selector_tool": {
            "label": "偏移选择",
            "type": "button",
            "button_text": "拖拽选择偏移",
            "tooltip": "从目标点拖拽选择固定偏移距离，会自动切换为固定偏移",
            "widget_hint": "offset_selector",
            "related_params": ["text_fixed_offset_x", "text_fixed_offset_y", "text_position_mode"],
            "condition": {"param": "operation_mode", "value": "文字点击"}
        },
"text_fixed_offset_x": {
            "label": "固定X偏移(像素)",
            "type": "int",
            "default": 0,
            "tooltip": "在文字位置上增加固定的X偏移（正数向右，负数向左）",
            "condition": [
                {"param": "operation_mode", "value": "文字点击"},
                {"param": "text_position_mode", "value": "固定偏移"}
            ]
        },
        "text_fixed_offset_y": {
            "label": "固定Y偏移(像素)",
            "type": "int",
            "default": 0,
            "tooltip": "在文字位置上增加固定的Y偏移（正数向下，负数向上）",
            "condition": [
                {"param": "operation_mode", "value": "文字点击"},
                {"param": "text_position_mode", "value": "固定偏移"}
            ]
        },
        "text_random_offset_x": {
            "label": "随机X偏移范围(像素)",
            "type": "int",
            "default": 5,
            "min": 0,
            "tooltip": "X轴随机偏移范围，实际偏移在 [-X, +X] 范围内随机；固定偏移模式下会叠加在固定偏移后的坐标上",
            "condition": {
                "param": "operation_mode",
                "value": "文字点击",
                "and": {"param": "text_position_mode", "value": ["固定偏移", "随机偏移"], "operator": "in"}
            }
        },
        "text_random_offset_y": {
            "label": "随机Y偏移范围(像素)",
            "type": "int",
            "default": 5,
            "min": 0,
            "tooltip": "Y轴随机偏移范围，实际偏移在 [-Y, +Y] 范围内随机；固定偏移模式下会叠加在固定偏移后的坐标上",
            "condition": {
                "param": "operation_mode",
                "value": "文字点击",
                "and": {"param": "text_position_mode", "value": ["固定偏移", "随机偏移"], "operator": "in"}
            }
        },
        "text_click_action": {
            "label": "点击动作",
            "type": "select",
            "options": ["完整点击", "双击", "仅按下", "仅松开"],
            "default": "完整点击",
            "tooltip": "完整点击：按下并松开；双击：连续两次点击；仅按下：按下不松开；仅松开：松开按钮",
            "condition": {"param": "operation_mode", "value": "文字点击"}
        },
        "text_enable_auto_release": {
            "label": "自动释放",
            "type": "bool",
            "default": True,
            "tooltip": "启用后，按下鼠标后会自动释放。",
            "condition": [
                {"param": "operation_mode", "value": "文字点击"},
                {"param": "text_click_action", "value": "仅按下"}
            ]
        },
        "text_hold_mode": {
            "label": "持续时间模式",
            "type": "select",
            "options": ["固定持续时间", "随机持续时间"],
            "default": "固定持续时间",
            "tooltip": "选择按键按下后持续时间的模式。",
            "condition": [
                {"param": "operation_mode", "value": "文字点击"},
                {"param": "text_click_action", "value": "仅按下"},
                {"param": "text_enable_auto_release", "value": True}
            ]
        },
        "text_hold_duration": {
            "label": "按下持续时间(秒)",
            "type": "float",
            "default": DEFAULT_CLICK_HOLD_SECONDS,
            "min": 0.0,
            "decimals": 2,
            "tooltip": "按下鼠标后保持的时间",
            "condition": [
                {"param": "operation_mode", "value": "文字点击"},
                {"param": "text_click_action", "value": "仅按下"},
                {"param": "text_enable_auto_release", "value": True},
                {"param": "text_hold_mode", "value": "固定持续时间"}
            ]
        },
        "text_hold_duration_min": {
            "label": "持续时间最小值(秒)",
            "type": "float",
            "default": DEFAULT_RANDOM_CLICK_HOLD_MIN_SECONDS,
            "min": 0.0,
            "decimals": 2,
            "tooltip": "随机持续时间的最小值。",
            "condition": [
                {"param": "operation_mode", "value": "文字点击"},
                {"param": "text_click_action", "value": "仅按下"},
                {"param": "text_enable_auto_release", "value": True},
                {"param": "text_hold_mode", "value": "随机持续时间"}
            ]
        },
        "text_hold_duration_max": {
            "label": "持续时间最大值(秒)",
            "type": "float",
            "default": DEFAULT_RANDOM_CLICK_HOLD_MAX_SECONDS,
            "min": 0.0,
            "decimals": 2,
            "tooltip": "随机持续时间的最大值。",
            "condition": [
                {"param": "operation_mode", "value": "文字点击"},
                {"param": "text_click_action", "value": "仅按下"},
                {"param": "text_enable_auto_release", "value": True},
                {"param": "text_hold_mode", "value": "随机持续时间"}
            ]
        },

        # 找色功能相关参数
        "---color_click_params---": {
            "type": "separator",
            "label": "找色功能参数",
            "condition": {"param": "operation_mode", "value": "找色功能"}
        },
        "target_color": {
            "label": "目标颜色",
            "type": "text",
            "default": "",
            "tooltip": "颜色格式：\n1. 单颜色: 255,0,0 （红色）\n2. 多颜色组合: 255,0,0;0,255,0 （用分号分隔）\n3. 多点定位: 255,0,0|10,20,0,255,0|50,0,0,0,255\n   格式：基准点R,G,B|偏移X,偏移Y,R,G,B|...\n\n使用本地截图和OpenCV HSV匹配",
            "condition": {"param": "operation_mode", "value": "找色功能"},
            "widget_hint": "colorpicker"
        },
        "search_region_enabled": {
            "label": "使用识别区域",
            "type": "checkbox",
            "default": False,
            "tooltip": "启用：仅在指定识别区域内找色；禁用：在整个窗口范围找色",
            "condition": {"param": "operation_mode", "value": "找色功能"}
        },
        "color_search_region_selector": {
            "label": "识别区域",
            "type": "button",
            "widget_hint": "color_region_selector",
            "button_text": "点击框选识别区域",
            "tooltip": "点击按钮在目标窗口上框选颜色识别区域",
            "condition": [
                {"param": "operation_mode", "value": "找色功能"},
                {"param": "search_region_enabled", "value": True}
            ]
        },
        "search_region_x": {
            "label": "识别区域X",
            "type": "hidden",
            "default": 0,
            "condition": {"param": "operation_mode", "value": "找色功能"}
        },
        "search_region_y": {
            "label": "识别区域Y",
            "type": "hidden",
            "default": 0,
            "condition": {"param": "operation_mode", "value": "找色功能"}
        },
        "search_region_width": {
            "label": "识别区域宽度",
            "type": "hidden",
            "default": 0,
            "condition": {"param": "operation_mode", "value": "找色功能"}
        },
        "search_region_height": {
            "label": "识别区域高度",
            "type": "hidden",
            "default": 0,
            "condition": {"param": "operation_mode", "value": "找色功能"}
        },
        "test_color_recognition": {
            "label": "找色测试",
            "type": "button",
            "button_text": "测试找色并绘制结果",
            "tooltip": "测试颜色识别，在绑定窗口上绘制出找到的颜色位置",
            "action": "test_color_recognition",
            "condition": {"param": "operation_mode", "value": "找色功能"}
        },
        "color_enable_click": {
            "label": "识别后执行点击",
            "type": "bool",
            "default": True,
            "tooltip": "启用：识别成功后执行点击；禁用：仅识别不点击",
            "condition": {"param": "operation_mode", "value": "找色功能"}
        },
        "click_position_mode": {
            "label": "点击位置",
            "type": "select",
            "options": ["精准坐标", "固定偏移", "随机偏移"],
            "default": "精准坐标",
            "tooltip": "精准坐标：使用颜色中心精准点击\n固定偏移：先在颜色中心基础上添加固定偏移，再可选叠加随机偏移\n随机偏移：在颜色中心基础上添加随机偏移",
            "condition": {"param": "operation_mode", "value": "找色功能"}
        },
        "color_offset_selector_tool": {
            "label": "偏移选择",
            "type": "button",
            "button_text": "拖拽选择偏移",
            "tooltip": "从目标点拖拽选择固定偏移距离，会自动切换为固定偏移",
            "widget_hint": "offset_selector",
            "related_params": ["color_fixed_offset_x", "color_fixed_offset_y", "click_position_mode"],
            "condition": {"param": "operation_mode", "value": "找色功能"}
        },
"color_fixed_offset_x": {
            "label": "固定X偏移(像素)",
            "type": "int",
            "default": 0,
            "tooltip": "在找到的位置上增加固定的X偏移（正数向右，负数向左）",
            "condition": [
                {"param": "operation_mode", "value": "找色功能"},
                {"param": "click_position_mode", "value": "固定偏移"}
            ]
        },
        "color_fixed_offset_y": {
            "label": "固定Y偏移(像素)",
            "type": "int",
            "default": 0,
            "tooltip": "在找到的位置上增加固定的Y偏移（正数向下，负数向上）",
            "condition": [
                {"param": "operation_mode", "value": "找色功能"},
                {"param": "click_position_mode", "value": "固定偏移"}
            ]
        },
        "color_random_offset_x": {
            "label": "随机X偏移范围(像素)",
            "type": "int",
            "default": 5,
            "min": 0,
            "tooltip": "X轴随机偏移范围，实际偏移在 [-X, +X] 范围内随机；固定偏移模式下会叠加在固定偏移后的坐标上",
            "condition": {
                "param": "operation_mode",
                "value": "找色功能",
                "and": {"param": "click_position_mode", "value": ["固定偏移", "随机偏移"], "operator": "in"}
            }
        },
        "color_random_offset_y": {
            "label": "随机Y偏移范围(像素)",
            "type": "int",
            "default": 5,
            "min": 0,
            "tooltip": "Y轴随机偏移范围，实际偏移在 [-Y, +Y] 范围内随机；固定偏移模式下会叠加在固定偏移后的坐标上",
            "condition": {
                "param": "operation_mode",
                "value": "找色功能",
                "and": {"param": "click_position_mode", "value": ["固定偏移", "随机偏移"], "operator": "in"}
            }
        },
        "color_click_button": {
            "label": "鼠标按钮",
            "type": "select",
            "options": ["左键", "右键", "中键"],
            "default": "左键",
            "condition": {"param": "operation_mode", "value": "找色功能"}
        },
        "color_click_clicks": {
            "label": "点击次数",
            "type": "int",
            "default": 1,
            "min": 1,
            "condition": {"param": "operation_mode", "value": "找色功能"}
        },
        "color_click_interval": {
            "label": "点击间隔(秒)",
            "type": "float",
            "default": DEFAULT_DOUBLE_CLICK_INTERVAL_SECONDS,
            "min": 0.0,
            "decimals": 2,
            "condition": {"param": "operation_mode", "value": "找色功能"}
        },
        "color_click_action": {
            "label": "点击动作",
            "type": "select",
            "options": ["完整点击", "双击", "仅按下", "仅松开"],
            "default": "完整点击",
            "tooltip": "完整点击：按下并松开；双击：连续两次点击；仅按下：按下不松开；仅松开：松开按钮",
            "condition": {"param": "operation_mode", "value": "找色功能"}
        },
        "color_enable_auto_release": {
            "label": "自动释放",
            "type": "bool",
            "default": True,
            "tooltip": "启用后，按下鼠标后会自动释放。",
            "condition": [
                {"param": "operation_mode", "value": "找色功能"},
                {"param": "color_click_action", "value": "仅按下"}
            ]
        },
        "color_hold_mode": {
            "label": "持续时间模式",
            "type": "select",
            "options": ["固定持续时间", "随机持续时间"],
            "default": "固定持续时间",
            "tooltip": "选择按键按下后持续时间的模式。",
            "condition": [
                {"param": "operation_mode", "value": "找色功能"},
                {"param": "color_click_action", "value": "仅按下"},
                {"param": "color_enable_auto_release", "value": True}
            ]
        },
        "color_hold_duration": {
            "label": "按下持续时间(秒)",
            "type": "float",
            "default": DEFAULT_CLICK_HOLD_SECONDS,
            "min": 0.0,
            "decimals": 2,
            "tooltip": "按下鼠标后保持的时间",
            "condition": [
                {"param": "operation_mode", "value": "找色功能"},
                {"param": "color_click_action", "value": "仅按下"},
                {"param": "color_enable_auto_release", "value": True},
                {"param": "color_hold_mode", "value": "固定持续时间"}
            ]
        },
        "color_hold_duration_min": {
            "label": "持续时间最小值(秒)",
            "type": "float",
            "default": DEFAULT_RANDOM_CLICK_HOLD_MIN_SECONDS,
            "min": 0.0,
            "decimals": 2,
            "tooltip": "随机持续时间的最小值。",
            "condition": [
                {"param": "operation_mode", "value": "找色功能"},
                {"param": "color_click_action", "value": "仅按下"},
                {"param": "color_enable_auto_release", "value": True},
                {"param": "color_hold_mode", "value": "随机持续时间"}
            ]
        },
        "color_hold_duration_max": {
            "label": "持续时间最大值(秒)",
            "type": "float",
            "default": DEFAULT_RANDOM_CLICK_HOLD_MAX_SECONDS,
            "min": 0.0,
            "decimals": 2,
            "tooltip": "随机持续时间的最大值。",
            "condition": [
                {"param": "operation_mode", "value": "找色功能"},
                {"param": "color_click_action", "value": "仅按下"},
                {"param": "color_enable_auto_release", "value": True},
                {"param": "color_hold_mode", "value": "随机持续时间"}
            ]
        },

        # 坐标点击相关参数
        "---coordinate_click_params---": {
            "type": "separator",
            "label": "坐标点击参数",
            "condition": {"param": "operation_mode", "value": "坐标点击"}
        },
        "coordinate_source_mode": {
            "label": "坐标获取方式",
            "type": "select",
            "options": ["坐标工具获取坐标", "手动输入", "无坐标"],
            "default": "坐标工具获取坐标",
            "tooltip": "选择坐标来源：可用坐标工具拾取、手动输入固定坐标，或直接点击当前鼠标位置",
            "condition": {"param": "operation_mode", "value": "坐标点击"}
        },
        "coordinate_selector_tool": {
            "label": "坐标获取工具",
            "type": "button",
            "button_text": "点击获取坐标",
            "tooltip": "点击后可以在目标窗口中选择坐标位置",
            "condition": [
                {"param": "operation_mode", "value": "坐标点击"},
                {"param": "coordinate_source_mode", "value": "坐标工具获取坐标"}
            ],
            "widget_hint": "coordinate_selector_with_display",
            "related_params": ["coordinate_x", "coordinate_y"]
        },
        "coordinate_value": {
            "label": "自定义坐标（兼容）",
            "type": "text",
            "default": "",
            "hidden": True,
            "placeholder": "示例: 100,200 或 {\"x\":100,\"y\":200}",
            "tooltip": "兼容旧工作流使用，新工作流请使用坐标工具或手动输入",
            "condition": {"param": "operation_mode", "value": "坐标点击"}
        },
        "coordinate_x": {
            "label": "X坐标",
            "type": "int",
            "default": 0,
            "min": 0,
            "tooltip": "点击位置的X坐标",
            "condition": [
                {"param": "operation_mode", "value": "坐标点击"},
                {"param": "coordinate_source_mode", "value": "手动输入"}
            ]
        },
        "coordinate_y": {
            "label": "Y坐标",
            "type": "int",
            "default": 0,
            "min": 0,
            "tooltip": "点击位置的Y坐标",
            "condition": [
                {"param": "operation_mode", "value": "坐标点击"},
                {"param": "coordinate_source_mode", "value": "手动输入"}
            ]
        },
        "coordinate_mode": {
            "label": "坐标模式",
            "type": "select",
            "options": ["客户区坐标", "窗口坐标", "屏幕坐标"],
            "default": "客户区坐标",
            "tooltip": "客户区坐标相对于窗口内容区域，窗口坐标相对于窗口左上角，屏幕坐标相对于整个屏幕",
            "condition": {
                "param": "operation_mode",
                "value": "坐标点击",
                "and": {
                    "param": "coordinate_source_mode",
                    "value": "无坐标",
                    "operator": "!="
                }
            }
        },
        "coordinate_enable_click": {
            "label": "执行点击",
            "type": "bool",
            "default": True,
            "tooltip": "关闭后仅解析坐标，不执行点击",
            "condition": {"param": "operation_mode", "value": "坐标点击"}
        },
        "coordinate_position_mode": {
            "label": "点击位置",
            "type": "select",
            "options": ["精准坐标", "固定偏移", "随机偏移"],
            "default": "精准坐标",
            "tooltip": "精准坐标：使用目标坐标精准点击\n固定偏移：先在目标坐标基础上添加固定偏移，再可选叠加随机偏移\n随机偏移：在目标坐标基础上添加随机偏移",
            "condition": {"param": "operation_mode", "value": "坐标点击"}
        },
        "coordinate_offset_selector_tool": {
            "label": "偏移选择",
            "type": "button",
            "button_text": "拖拽选择偏移",
            "tooltip": "从目标点拖拽选择固定偏移距离，会自动切换为固定偏移",
            "widget_hint": "offset_selector",
            "related_params": ["coordinate_fixed_offset_x", "coordinate_fixed_offset_y", "coordinate_position_mode"],
            "condition": {"param": "operation_mode", "value": "坐标点击"}
        },
"coordinate_fixed_offset_x": {
            "label": "固定X偏移(像素)",
            "type": "int",
            "default": 0,
            "tooltip": "在指定坐标上增加固定的X偏移（正数向右，负数向左）",
            "condition": [
                {"param": "operation_mode", "value": "坐标点击"},
                {"param": "coordinate_position_mode", "value": "固定偏移"}
            ]
        },
        "coordinate_fixed_offset_y": {
            "label": "固定Y偏移(像素)",
            "type": "int",
            "default": 0,
            "tooltip": "在指定坐标上增加固定的Y偏移（正数向下，负数向上）",
            "condition": [
                {"param": "operation_mode", "value": "坐标点击"},
                {"param": "coordinate_position_mode", "value": "固定偏移"}
            ]
        },
        "coordinate_random_offset_x": {
            "label": "随机X偏移范围(像素)",
            "type": "int",
            "default": 5,
            "min": 0,
            "tooltip": "X轴随机偏移范围，实际偏移在 [-X, +X] 范围内随机；固定偏移模式下会叠加在固定偏移后的坐标上",
            "condition": {
                "param": "operation_mode",
                "value": "坐标点击",
                "and": {"param": "coordinate_position_mode", "value": ["固定偏移", "随机偏移"], "operator": "in"}
            }
        },
        "coordinate_random_offset_y": {
            "label": "随机Y偏移范围(像素)",
            "type": "int",
            "default": 5,
            "min": 0,
            "tooltip": "Y轴随机偏移范围，实际偏移在 [-Y, +Y] 范围内随机；固定偏移模式下会叠加在固定偏移后的坐标上",
            "condition": {
                "param": "operation_mode",
                "value": "坐标点击",
                "and": {"param": "coordinate_position_mode", "value": ["固定偏移", "随机偏移"], "operator": "in"}
            }
        },
        "coordinate_click_action": {
            "label": "点击动作",
            "type": "select",
            "options": ["完整点击", "双击", "仅按下", "仅松开"],
            "default": "完整点击",
            "tooltip": "完整点击：按下并松开；双击：连续两次点击；仅按下：按下不松开；仅松开：松开按钮",
            "condition": {"param": "operation_mode", "value": "坐标点击"}
        },
        "coordinate_enable_auto_release": {
            "label": "自动释放",
            "type": "bool",
            "default": True,
            "tooltip": "启用后，按下鼠标后会自动释放。",
            "condition": [
                {"param": "operation_mode", "value": "坐标点击"},
                {"param": "coordinate_click_action", "value": "仅按下"}
            ]
        },
        "coordinate_hold_mode": {
            "label": "持续时间模式",
            "type": "select",
            "options": ["固定持续时间", "随机持续时间"],
            "default": "固定持续时间",
            "tooltip": "选择按键按下后持续时间的模式。",
            "condition": [
                {"param": "operation_mode", "value": "坐标点击"},
                {"param": "coordinate_click_action", "value": "仅按下"},
                {"param": "coordinate_enable_auto_release", "value": True}
            ]
        },
        "coordinate_hold_duration": {
            "label": "按下持续时间(秒)",
            "type": "float",
            "default": DEFAULT_CLICK_HOLD_SECONDS,
            "min": 0.0,
            "decimals": 2,
            "tooltip": "按下鼠标后保持的时间",
            "condition": [
                {"param": "operation_mode", "value": "坐标点击"},
                {"param": "coordinate_click_action", "value": "仅按下"},
                {"param": "coordinate_enable_auto_release", "value": True},
                {"param": "coordinate_hold_mode", "value": "固定持续时间"}
            ]
        },
        "coordinate_hold_duration_min": {
            "label": "持续时间最小值(秒)",
            "type": "float",
            "default": DEFAULT_RANDOM_CLICK_HOLD_MIN_SECONDS,
            "min": 0.0,
            "decimals": 2,
            "tooltip": "随机持续时间的最小值。",
            "condition": [
                {"param": "operation_mode", "value": "坐标点击"},
                {"param": "coordinate_click_action", "value": "仅按下"},
                {"param": "coordinate_enable_auto_release", "value": True},
                {"param": "coordinate_hold_mode", "value": "随机持续时间"}
            ]
        },
        "coordinate_hold_duration_max": {
            "label": "持续时间最大值(秒)",
            "type": "float",
            "default": DEFAULT_RANDOM_CLICK_HOLD_MAX_SECONDS,
            "min": 0.0,
            "decimals": 2,
            "tooltip": "随机持续时间的最大值。",
            "condition": [
                {"param": "operation_mode", "value": "坐标点击"},
                {"param": "coordinate_click_action", "value": "仅按下"},
                {"param": "coordinate_enable_auto_release", "value": True},
                {"param": "coordinate_hold_mode", "value": "随机持续时间"}
            ]
        },

        # 鼠标滚轮相关参数
        "---scroll_params---": {
            "type": "separator",
            "label": "鼠标滚轮参数",
            "condition": {"param": "operation_mode", "value": "鼠标滚轮"}
        },
        "scroll_direction": {
            "label": "滚动方向",
            "type": "select",
            "options": ["向上", "向下"],
            "default": "向下",
            "tooltip": "鼠标滚轮的滚动方向",
            "condition": {"param": "operation_mode", "value": "鼠标滚轮"}
        },
        "scroll_clicks": {
            "label": "滚动步数",
            "type": "int",
            "default": 3,
            "min": 1,
            "max": 999,
            "tooltip": "滚轮执行的步数",
            "condition": {"param": "operation_mode", "value": "鼠标滚轮"}
        },
        "scroll_interval": {
            "label": "滚动间隔(秒)",
            "type": "float",
            "default": 0.1,
            "min": 0.0,
            "decimals": 2,
            "tooltip": "多次滚动之间的间隔时间",
            "condition": {"param": "operation_mode", "value": "鼠标滚轮"}
        },
        "scroll_coordinate_selector": {
            "label": "坐标获取工具",
            "type": "button",
            "button_text": "点击获取坐标",
            "tooltip": "点击选择滚轮操作的起始坐标位置",
            "widget_hint": "coordinate_selector",
            "condition": {"param": "operation_mode", "value": "鼠标滚轮"}
        },
        "scroll_start_position": {
            "label": "滚动起始位置",
            "type": "text",
            "default": "500,300",
            "tooltip": "执行滚轮操作的起始坐标位置",
            "readonly": True,
            "condition": {"param": "operation_mode", "value": "鼠标滚轮"}
        },

        # 鼠标拖拽相关参数
        "---drag_params---": {
            "type": "separator",
            "label": "鼠标拖拽参数",
            "condition": {"param": "operation_mode", "value": "鼠标拖拽"}
        },
        "drag_mode": {
            "label": "拖拽模式",
            "type": "select",
            "options": ["简单拖拽", "多点路径拖拽"],
            "default": "简单拖拽",
            "tooltip": "简单拖拽: 直线移动\n多点路径: 沿复杂路径",
            "condition": {"param": "operation_mode", "value": "鼠标拖拽"}
        },

        # ===== 简单拖拽起点参数 =====
        "---drag_start_params---": {
            "type": "separator",
            "label": "拖拽起点设置",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标拖拽",
                "and": {"param": "drag_mode", "value": "简单拖拽"}
            }
        },
        "drag_start_mode": {
            "label": "起点定位方式",
            "type": "select",
            "options": ["坐标", "图片"],
            "default": "坐标",
            "tooltip": "坐标: 使用固定坐标\n图片: 通过图片识别定位",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标拖拽",
                "and": {"param": "drag_mode", "value": "简单拖拽"}
            }
        },
        # 起点 - 坐标模式参数
        "drag_start_coordinate_selector": {
            "label": "起点坐标获取",
            "type": "button",
            "button_text": "获取起点坐标",
            "tooltip": "点击选择拖拽操作的起点坐标",
            "widget_hint": "coordinate_selector",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标拖拽",
                "and": [
                    {"param": "drag_mode", "value": "简单拖拽"},
                    {"param": "drag_start_mode", "value": "坐标"}
                ]
            }
        },
        "drag_start_position": {
            "label": "拖拽起点",
            "type": "text",
            "default": "500,300",
            "tooltip": "拖拽操作的起点坐标(x,y)",
            "readonly": True,
            "condition": {
                "param": "operation_mode",
                "value": "鼠标拖拽",
                "and": [
                    {"param": "drag_mode", "value": "简单拖拽"},
                    {"param": "drag_start_mode", "value": "坐标"}
                ]
            }
        },
        # 起点 - 图片模式参数
        "drag_start_image_path": {
            "label": "起点图片",
            "type": "file",
            "default": "",
            "file_filter": "图片 (*.png *.jpg *.jpeg *.bmp *.webp *.gif *.tif *.tiff);;所有文件 (*.*)",
            "tooltip": "拖拽起点的目标图片",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标拖拽",
                "and": [
                    {"param": "drag_mode", "value": "简单拖拽"},
                    {"param": "drag_start_mode", "value": "图片"}
                ]
            }
        },
        "drag_start_confidence": {
            "label": "起点图片置信度",
            "type": "float",
            "default": 0.8,
            "min": 0.1,
            "max": 1.0,
            "step": 0.05,
            "decimals": 2,
            "tooltip": "起点图片匹配的相似度阈值",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标拖拽",
                "and": [
                    {"param": "drag_mode", "value": "简单拖拽"},
                    {"param": "drag_start_mode", "value": "图片"}
                ]
            }
        },
        "drag_start_offset_x": {
            "label": "起点X偏移",
            "type": "int",
            "default": 0,
            "min": -500,
            "max": 500,
            "tooltip": "相对于图片中心的X偏移量",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标拖拽",
                "and": [
                    {"param": "drag_mode", "value": "简单拖拽"},
                    {"param": "drag_start_mode", "value": "图片"}
                ]
            }
        },
        "drag_start_offset_y": {
            "label": "起点Y偏移",
            "type": "int",
            "default": 0,
            "min": -500,
            "max": 500,
            "tooltip": "相对于图片中心的Y偏移量",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标拖拽",
                "and": [
                    {"param": "drag_mode", "value": "简单拖拽"},
                    {"param": "drag_start_mode", "value": "图片"}
                ]
            }
        },

        # ===== 简单拖拽终点参数 =====
        "---drag_end_params---": {
            "type": "separator",
            "label": "拖拽终点设置",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标拖拽",
                "and": {"param": "drag_mode", "value": "简单拖拽"}
            }
        },
        "drag_end_mode": {
            "label": "终点定位方式",
            "type": "select",
            "options": ["坐标", "图片"],
            "default": "坐标",
            "tooltip": "坐标: 使用固定坐标\n图片: 通过图片识别定位",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标拖拽",
                "and": {"param": "drag_mode", "value": "简单拖拽"}
            }
        },
        # 终点 - 坐标模式参数
        "drag_end_coordinate_selector": {
            "label": "终点坐标获取",
            "type": "button",
            "button_text": "获取终点坐标",
            "tooltip": "点击选择拖拽操作的终点坐标",
            "widget_hint": "coordinate_selector",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标拖拽",
                "and": [
                    {"param": "drag_mode", "value": "简单拖拽"},
                    {"param": "drag_end_mode", "value": "坐标"}
                ]
            }
        },
        "drag_end_position": {
            "label": "拖拽终点",
            "type": "text",
            "default": "700,300",
            "tooltip": "拖拽操作的终点坐标(x,y)",
            "readonly": True,
            "condition": {
                "param": "operation_mode",
                "value": "鼠标拖拽",
                "and": [
                    {"param": "drag_mode", "value": "简单拖拽"},
                    {"param": "drag_end_mode", "value": "坐标"}
                ]
            }
        },
        # 终点 - 图片模式参数
        "drag_end_image_path": {
            "label": "终点图片",
            "type": "file",
            "default": "",
            "file_filter": "图片 (*.png *.jpg *.jpeg *.bmp *.webp *.gif *.tif *.tiff);;所有文件 (*.*)",
            "tooltip": "拖拽终点的目标图片",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标拖拽",
                "and": [
                    {"param": "drag_mode", "value": "简单拖拽"},
                    {"param": "drag_end_mode", "value": "图片"}
                ]
            }
        },
        "drag_end_confidence": {
            "label": "终点图片置信度",
            "type": "float",
            "default": 0.8,
            "min": 0.1,
            "max": 1.0,
            "step": 0.05,
            "decimals": 2,
            "tooltip": "终点图片匹配的相似度阈值",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标拖拽",
                "and": [
                    {"param": "drag_mode", "value": "简单拖拽"},
                    {"param": "drag_end_mode", "value": "图片"}
                ]
            }
        },
        "drag_end_offset_x": {
            "label": "终点X偏移",
            "type": "int",
            "default": 0,
            "min": -500,
            "max": 500,
            "tooltip": "相对于图片中心的X偏移量",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标拖拽",
                "and": [
                    {"param": "drag_mode", "value": "简单拖拽"},
                    {"param": "drag_end_mode", "value": "图片"}
                ]
            }
        },
        "drag_end_offset_y": {
            "label": "终点Y偏移",
            "type": "int",
            "default": 0,
            "min": -500,
            "max": 500,
            "tooltip": "相对于图片中心的Y偏移量",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标拖拽",
                "and": [
                    {"param": "drag_mode", "value": "简单拖拽"},
                    {"param": "drag_end_mode", "value": "图片"}
                ]
            }
        },

        # ===== 拖拽控制参数 =====
        "---drag_control_params---": {
            "type": "separator",
            "label": "拖拽控制参数",
            "condition": {"param": "operation_mode", "value": "鼠标拖拽"}
        },
        "drag_button": {
            "label": "拖拽按钮",
            "type": "select",
            "options": ["左键", "右键", "中键"],
            "default": "左键",
            "tooltip": "拖拽时使用的鼠标按钮",
            "condition": {"param": "operation_mode", "value": "鼠标拖拽"}
        },
        "drag_duration": {
            "label": "拖拽持续时间(秒)",
            "type": "float",
            "default": 1.0,
            "min": 0.1,
            "max": 10.0,
            "step": 0.1,
            "decimals": 1,
            "tooltip": "完成拖拽操作的时间(实际时间不会超过此值)",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标拖拽",
                "and": {"param": "drag_mode", "value": "简单拖拽"}
            }
        },
        "drag_smoothness": {
            "label": "拖拽平滑度",
            "type": "int",
            "default": 100,
            "min": 5,
            "max": 100,
            "tooltip": "拖拽轨迹的平滑程度，数值越大越平滑(默认100)",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标拖拽",
                "and": {"param": "drag_mode", "value": "简单拖拽"}
            }
        },

        # ===== 多点路径拖拽参数 =====
        "path_points": {
            "label": "路径点坐标",
            "type": "textarea",
            "default": "100,100\n200,150\n300,200\n400,250",
            "tooltip": "每行一个坐标: x,y,time\n如: 100,100,0.5",
            "rows": 8,
            "condition": {
                "param": "operation_mode",
                "value": "鼠标拖拽",
                "and": {"param": "drag_mode", "value": "多点路径拖拽"}
            }
        },

        # 鼠标移动相关参数
        "---move_params---": {
            "type": "separator",
            "label": "鼠标移动参数",
            "condition": {"param": "operation_mode", "value": "鼠标移动"}
        },
        "move_mode": {
            "label": "移动模式",
            "type": "select",
            "options": ["绝对移动", "相对移动"],
            "default": "绝对移动",
            "tooltip": "绝对移动: 从起点移动到终点\n相对移动: 相对当前位置移动",
            "condition": {"param": "operation_mode", "value": "鼠标移动"}
        },

        # 绝对移动 - 起点参数
        "move_start_coordinate_selector": {
            "label": "起点坐标获取",
            "type": "button",
            "button_text": "获取起点坐标",
            "tooltip": "点击选择移动的起点坐标",
            "widget_hint": "coordinate_selector",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标移动",
                "and": {"param": "move_mode", "value": "绝对移动"}
            }
        },
        "move_start_position": {
            "label": "移动起点",
            "type": "text",
            "default": "100,100",
            "tooltip": "鼠标移动的起点坐标(x,y)",
            "readonly": True,
            "condition": {
                "param": "operation_mode",
                "value": "鼠标移动",
                "and": {"param": "move_mode", "value": "绝对移动"}
            }
        },

        # 绝对移动 - 终点参数
        "move_end_coordinate_selector": {
            "label": "终点坐标获取",
            "type": "button",
            "button_text": "获取终点坐标",
            "tooltip": "点击选择移动的终点坐标",
            "widget_hint": "coordinate_selector",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标移动",
                "and": {"param": "move_mode", "value": "绝对移动"}
            }
        },
        "move_end_position": {
            "label": "移动终点",
            "type": "text",
            "default": "500,300",
            "tooltip": "鼠标移动的终点坐标(x,y)",
            "readonly": True,
            "condition": {
                "param": "operation_mode",
                "value": "鼠标移动",
                "and": {"param": "move_mode", "value": "绝对移动"}
            }
        },

        # 相对移动参数
        "move_offset_mode": {
            "label": "偏移模式",
            "type": "select",
            "options": ["固定偏移", "随机偏移"],
            "default": "固定偏移",
            "tooltip": "固定偏移: 使用固定的偏移值\n随机偏移: 在范围内随机偏移",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标移动",
                "and": {"param": "move_mode", "value": "相对移动"}
            }
        },
        "move_offset_x": {
            "label": "X偏移量",
            "type": "int",
            "default": 100,
            "min": -2000,
            "max": 2000,
            "tooltip": "相对当前鼠标位置的X偏移量\n正值: 向右移动\n负值: 向左移动",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标移动",
                "and": {
                    "param": "move_mode",
                    "value": "相对移动",
                    "and": {"param": "move_offset_mode", "value": "固定偏移"}
                }
            }
        },
        "move_offset_y": {
            "label": "Y偏移量",
            "type": "int",
            "default": 100,
            "min": -2000,
            "max": 2000,
            "tooltip": "相对当前鼠标位置的Y偏移量\n正值: 向下移动\n负值: 向上移动",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标移动",
                "and": {
                    "param": "move_mode",
                    "value": "相对移动",
                    "and": {"param": "move_offset_mode", "value": "固定偏移"}
                }
            }
        },
        "move_offset_x_min": {
            "label": "X偏移最小值",
            "type": "int",
            "default": -50,
            "min": -2000,
            "max": 2000,
            "tooltip": "X偏移量的最小值\n正值: 向右移动\n负值: 向左移动",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标移动",
                "and": {
                    "param": "move_mode",
                    "value": "相对移动",
                    "and": {"param": "move_offset_mode", "value": "随机偏移"}
                }
            }
        },
        "move_offset_x_max": {
            "label": "X偏移最大值",
            "type": "int",
            "default": 50,
            "min": -2000,
            "max": 2000,
            "tooltip": "X偏移量的最大值\n正值: 向右移动\n负值: 向左移动",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标移动",
                "and": {
                    "param": "move_mode",
                    "value": "相对移动",
                    "and": {"param": "move_offset_mode", "value": "随机偏移"}
                }
            }
        },
        "move_offset_y_min": {
            "label": "Y偏移最小值",
            "type": "int",
            "default": -50,
            "min": -2000,
            "max": 2000,
            "tooltip": "Y偏移量的最小值\n正值: 向下移动\n负值: 向上移动",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标移动",
                "and": {
                    "param": "move_mode",
                    "value": "相对移动",
                    "and": {"param": "move_offset_mode", "value": "随机偏移"}
                }
            }
        },
        "move_offset_y_max": {
            "label": "Y偏移最大值",
            "type": "int",
            "default": 50,
            "min": -2000,
            "max": 2000,
            "tooltip": "Y偏移量的最大值\n正值: 向下移动\n负值: 向上移动",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标移动",
                "and": {
                    "param": "move_mode",
                    "value": "相对移动",
                    "and": {"param": "move_offset_mode", "value": "随机偏移"}
                }
            }
        },
        "move_duration_mode": {
            "label": "持续时间模式",
            "type": "select",
            "options": ["固定持续时间", "随机持续时间"],
            "default": "固定持续时间",
            "tooltip": "固定持续时间: 使用固定的时间值\n随机持续时间: 在范围内随机选择时间",
            "condition": {"param": "operation_mode", "value": "鼠标移动"}
        },
        "move_duration": {
            "label": "移动持续时间(秒)",
            "type": "float",
            "default": 0.5,
            "min": 0.0,
            "max": 10.0,
            "step": 0.1,
            "decimals": 1,
            "tooltip": "完成移动操作的时间，0为瞬间移动",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标移动",
                "and": {"param": "move_duration_mode", "value": "固定持续时间"}
            }
        },
        "move_duration_min": {
            "label": "最小持续时间(秒)",
            "type": "float",
            "default": 0.3,
            "min": 0.0,
            "max": 10.0,
            "step": 0.1,
            "decimals": 1,
            "tooltip": "随机持续时间的最小值",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标移动",
                "and": {"param": "move_duration_mode", "value": "随机持续时间"}
            }
        },
        "move_duration_max": {
            "label": "最大持续时间(秒)",
            "type": "float",
            "default": 0.8,
            "min": 0.0,
            "max": 10.0,
            "step": 0.1,
            "decimals": 1,
            "tooltip": "随机持续时间的最大值",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标移动",
                "and": {"param": "move_duration_mode", "value": "随机持续时间"}
            }
        },
        "move_use_bezier": {
            "label": "使用贝塞尔曲线",
            "type": "bool",
            "default": False,
            "tooltip": "启用后使用随机贝塞尔曲线轨迹，模拟人类鼠标移动",
            "condition": {"param": "operation_mode", "value": "鼠标移动"}
        },
        "move_smoothness": {
            "label": "移动平滑度",
            "type": "int",
            "default": 50,
            "min": 5,
            "max": 100,
            "tooltip": "移动轨迹的平滑程度，数值越大越平滑（仅贝塞尔曲线模式有效）",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标移动",
                "and": {"param": "move_use_bezier", "value": True}
            }
        },

        # 鼠标移动后的点击参数
        "move_enable_click": {
            "label": "移动后启用点击",
            "type": "bool",
            "default": False,
            "tooltip": "启用后在移动到终点位置后执行点击操作",
            "condition": {"param": "operation_mode", "value": "鼠标移动"}
        },
        "move_click_button": {
            "label": "鼠标按钮",
            "type": "select",
            "options": ["左键", "右键", "中键"],
            "default": "左键",
            "tooltip": "选择要点击的鼠标按钮",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标移动",
                "and": {"param": "move_enable_click", "value": True}
            }
        },
        "move_click_clicks": {
            "label": "点击次数",
            "type": "int",
            "default": 1,
            "min": 1,
            "tooltip": "连续点击的次数",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标移动",
                "and": {"param": "move_enable_click", "value": True}
            }
        },
        "move_click_interval": {
            "label": "点击间隔(秒)",
            "type": "float",
            "default": DEFAULT_DOUBLE_CLICK_INTERVAL_SECONDS,
            "min": 0.0,
            "decimals": 2,
            "tooltip": "多次点击之间的间隔时间",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标移动",
                "and": {"param": "move_enable_click", "value": True}
            }
        },
        "move_click_action": {
            "label": "点击动作",
            "type": "select",
            "options": ["完整点击", "双击", "仅按下", "仅松开"],
            "default": "完整点击",
            "tooltip": "完整点击：按下并松开；双击：连续两次点击；仅按下：按下不松开；仅松开：松开按钮",
            "condition": {
                "param": "operation_mode",
                "value": "鼠标移动",
                "and": {"param": "move_enable_click", "value": True}
            }
        },
        "move_enable_auto_release": {
            "label": "自动释放",
            "type": "bool",
            "default": True,
            "tooltip": "启用后，按下鼠标后会自动释放。",
            "condition": [
                {"param": "operation_mode", "value": "鼠标移动"},
                {"param": "move_enable_click", "value": True},
                {"param": "move_click_action", "value": "仅按下"}
            ]
        },
        "move_hold_mode": {
            "label": "持续时间模式",
            "type": "select",
            "options": ["固定持续时间", "随机持续时间"],
            "default": "固定持续时间",
            "tooltip": "选择按键按下后持续时间的模式。",
            "condition": [
                {"param": "operation_mode", "value": "鼠标移动"},
                {"param": "move_enable_click", "value": True},
                {"param": "move_click_action", "value": "仅按下"},
                {"param": "move_enable_auto_release", "value": True}
            ]
        },
        "move_hold_duration": {
            "label": "按下持续时间(秒)",
            "type": "float",
            "default": DEFAULT_CLICK_HOLD_SECONDS,
            "min": 0.0,
            "decimals": 2,
            "tooltip": "按下鼠标后保持的时间",
            "condition": [
                {"param": "operation_mode", "value": "鼠标移动"},
                {"param": "move_enable_click", "value": True},
                {"param": "move_click_action", "value": "仅按下"},
                {"param": "move_enable_auto_release", "value": True},
                {"param": "move_hold_mode", "value": "固定持续时间"}
            ]
        },
        "move_hold_duration_min": {
            "label": "持续时间最小值(秒)",
            "type": "float",
            "default": DEFAULT_RANDOM_CLICK_HOLD_MIN_SECONDS,
            "min": 0.0,
            "decimals": 2,
            "tooltip": "随机持续时间的最小值。",
            "condition": [
                {"param": "operation_mode", "value": "鼠标移动"},
                {"param": "move_enable_click", "value": True},
                {"param": "move_click_action", "value": "仅按下"},
                {"param": "move_enable_auto_release", "value": True},
                {"param": "move_hold_mode", "value": "随机持续时间"}
            ]
        },
        "move_hold_duration_max": {
            "label": "持续时间最大值(秒)",
            "type": "float",
            "default": DEFAULT_RANDOM_CLICK_HOLD_MAX_SECONDS,
            "min": 0.0,
            "decimals": 2,
            "tooltip": "随机持续时间的最大值。",
            "condition": [
                {"param": "operation_mode", "value": "鼠标移动"},
                {"param": "move_enable_click", "value": True},
                {"param": "move_click_action", "value": "仅按下"},
                {"param": "move_enable_auto_release", "value": True},
                {"param": "move_hold_mode", "value": "随机持续时间"}
            ]
        },

        # 通用点击参数（仅点击模式显示）
        "---common_click_params---": {
            "type": "separator",
            "label": "点击参数",
            "condition": {"param": "operation_mode", "value": ["找图功能", "坐标点击", "文字点击"]}
        },
        "button": {
            "label": "鼠标按钮",
            "type": "select",
            "options": ["左键", "右键", "中键"],
            "default": "左键",
            "tooltip": "要使用的鼠标按钮",
            "condition": {"param": "operation_mode", "value": ["找图功能", "坐标点击", "文字点击"]}
        },
        "clicks": {
            "label": "点击次数",
            "type": "int",
            "default": 1,
            "min": 1,
            "tooltip": "连续点击的次数",
            "condition": {"param": "operation_mode", "value": ["找图功能", "坐标点击", "文字点击"]}
        },
        "interval": {
            "label": "点击间隔(秒)",
            "type": "float",
            "default": DEFAULT_DOUBLE_CLICK_INTERVAL_SECONDS,
            "min": 0.0,
            "decimals": 2,
            "tooltip": "多次点击之间的间隔时间",
            "condition": {"param": "operation_mode", "value": ["找图功能", "坐标点击", "文字点击"]}
        },

        # 重试机制（找图功能/找色功能）
        "---retry_params---": {
            "type": "separator",
            "label": "重试设置",
            "condition": {"param": "operation_mode", "value": ["找图功能", "找色功能"]}
        },
        "enable_retry": {
            "label": "启用失败重试",
            "type": "bool",
            "default": False,
            "tooltip": "如果识别失败，是否进行重试",
            "condition": {"param": "operation_mode", "value": ["找图功能", "找色功能"]}
        },
        "retry_attempts": {
            "label": "重试次数",
            "type": "int",
            "default": 3,
            "min": 1,
            "max": 10,
            "tooltip": "最大重试次数",
            "condition": [
                {"param": "operation_mode", "value": ["找图功能", "找色功能"]},
                {"param": "enable_retry", "value": True}
            ]
        },
        "retry_interval": {
            "label": "重试间隔(秒)",
            "type": "float",
            "default": 0.5,
            "min": 0.1,
            "decimals": 2,
            "tooltip": "重试之间的等待时间",
            "condition": [
                {"param": "operation_mode", "value": ["找图功能", "找色功能"]},
                {"param": "enable_retry", "value": True}
            ]
        },
        # 下一步延迟执行参数
        "---next_step_delay---": {"type": "separator", "label": "下一步延迟执行"},
        "enable_next_step_delay": {
            "label": "启用下一步延迟执行",
            "type": "bool",
            "default": False,
            "tooltip": "勾选后，执行完当前操作会等待指定时间再执行下一步"
        },
        "delay_mode": {
            "label": "延迟模式",
            "type": "select",
            "options": ["固定延迟", "随机延迟"],
            "default": "固定延迟",
            "tooltip": "选择固定延迟时间还是随机延迟时间",
            "condition": {"param": "enable_next_step_delay", "value": True}
        },
        "fixed_delay": {
            "label": "固定延迟 (秒)",
            "type": "float",
            "default": 1.0,
            "min": 0.0,
            "max": 3600.0,
            "step": 0.1,
            "decimals": 2,
            "tooltip": "设置固定的延迟时间",
            "condition": {
                "param": "delay_mode",
                "value": "固定延迟",
                "and": {"param": "enable_next_step_delay", "value": True}
            }
        },
        "min_delay": {
            "label": "最小延迟 (秒)",
            "type": "float",
            "default": 0.5,
            "min": 0.0,
            "max": 3600.0,
            "step": 0.1,
            "decimals": 2,
            "tooltip": "设置随机延迟的最小值",
            "condition": {
                "param": "delay_mode",
                "value": "随机延迟",
                "and": {"param": "enable_next_step_delay", "value": True}
            }
        },
        "max_delay": {
            "label": "最大延迟 (秒)",
            "type": "float",
            "default": 2.0,
            "min": 0.0,
            "max": 3600.0,
            "step": 0.1,
            "decimals": 2,
            "tooltip": "设置随机延迟的最大值",
            "condition": {
                "param": "delay_mode",
                "value": "随机延迟",
                "and": {"param": "enable_next_step_delay", "value": True}
            }
        },

        # 执行后操作
        "---post_execute---": {"type": "separator", "label": "执行后操作"},
        "on_success": {
            "label": "成功后操作",
            "type": "select",
            "options": ["继续执行本步骤", "执行下一步", "跳转到步骤", "停止工作流"],
            "default": "执行下一步",
            "tooltip": "点击成功后的操作"
        },
        "success_jump_target_id": {
            "label": "成功跳转目标ID",
            "type": "int",
            "default": 0,
            "min": 0,
            "widget_hint": "card_selector",
            "condition": {"param": "on_success", "value": "跳转到步骤"}
        },
        "on_failure": {
            "label": "失败后操作",
            "type": "select",
            "options": ["继续执行本步骤", "执行下一步", "跳转到步骤", "停止工作流"],
            "default": "执行下一步",
            "tooltip": "点击失败后的操作"
        },
        "failure_jump_target_id": {
            "label": "失败跳转目标ID",
            "type": "int",
            "default": 0,
            "min": 0,
            "widget_hint": "card_selector",
            "condition": {"param": "on_failure", "value": "跳转到步骤"}
        }
    }

    def _append_extra_condition(param_key: str, extra_condition: Dict[str, Any]) -> None:
        param_def = params.get(param_key)
        if not isinstance(param_def, dict):
            return
        existing_condition = param_def.get("condition")
        if existing_condition is None:
            param_def["condition"] = dict(extra_condition)
            return
        if isinstance(existing_condition, list):
            param_def["condition"] = list(existing_condition) + [dict(extra_condition)]
            return
        if isinstance(existing_condition, dict):
            and_condition = existing_condition.get("and")
            if and_condition is None:
                existing_condition["and"] = dict(extra_condition)
            elif isinstance(and_condition, list):
                existing_condition["and"] = list(and_condition) + [dict(extra_condition)]
            else:
                existing_condition["and"] = [and_condition, dict(extra_condition)]

    image_click_enabled = {"param": "image_enable_click", "value": True}
    for key in (
        "image_position_mode",
        "image_offset_selector_tool",
        "image_fixed_offset_x",
        "image_fixed_offset_y",
        "image_random_offset_x",
        "image_random_offset_y",
        "image_click_action",
        "image_enable_auto_release",
        "image_hold_mode",
        "image_hold_duration",
        "image_hold_duration_min",
        "image_hold_duration_max",
    ):
        _append_extra_condition(key, image_click_enabled)

    color_click_enabled = {"param": "color_enable_click", "value": True}
    for key in (
        "click_position_mode",
        "color_offset_selector_tool",
        "color_fixed_offset_x",
        "color_fixed_offset_y",
        "color_random_offset_x",
        "color_random_offset_y",
        "color_click_button",
        "color_click_clicks",
        "color_click_interval",
        "color_click_action",
        "color_enable_auto_release",
        "color_hold_mode",
        "color_hold_duration",
        "color_hold_duration_min",
        "color_hold_duration_max",
    ):
        _append_extra_condition(key, color_click_enabled)

    text_click_enabled = {"param": "text_enable_click", "value": True}
    for key in (
        "text_position_mode",
        "text_offset_selector_tool",
        "text_fixed_offset_x",
        "text_fixed_offset_y",
        "text_random_offset_x",
        "text_random_offset_y",
        "text_click_action",
        "text_enable_auto_release",
        "text_hold_mode",
        "text_hold_duration",
        "text_hold_duration_min",
        "text_hold_duration_max",
    ):
        _append_extra_condition(key, text_click_enabled)

    coordinate_click_enabled = {"param": "coordinate_enable_click", "value": True}
    for key in (
        "coordinate_position_mode",
        "coordinate_offset_selector_tool",
        "coordinate_fixed_offset_x",
        "coordinate_fixed_offset_y",
        "coordinate_random_offset_x",
        "coordinate_random_offset_y",
        "coordinate_click_action",
        "coordinate_enable_auto_release",
        "coordinate_hold_mode",
        "coordinate_hold_duration",
        "coordinate_hold_duration_min",
        "coordinate_hold_duration_max",
    ):
        _append_extra_condition(key, coordinate_click_enabled)

    return params

def _handle_success(action: str, jump_id: Optional[int], card_id: Optional[int]) -> Tuple[bool, str, Optional[int]]:
    """处理成功情况"""
    from .task_utils import resolve_step_action_result

    result = resolve_step_action_result(
        success=True,
        action=action,
        jump_id=jump_id,
        card_id=card_id,
        require_jump_target=True,
    )
    if result[1] == "跳转到步骤":
        logger.info(f"点击成功，跳转到步骤 {result[2]}")
    elif result[1] == "停止工作流":
        logger.info("点击成功，停止工作流")
    elif result[1] == "继续执行本步骤":
        logger.info("点击成功，继续执行本步骤")
    else:
        logger.info("点击成功，继续执行下一步")
    return result

def _handle_failure(action: str, jump_id: Optional[int], card_id: Optional[int]) -> Tuple[bool, str, Optional[int]]:
    """处理失败情况"""
    from .task_utils import resolve_step_action_result

    result = resolve_step_action_result(
        success=False,
        action=action,
        jump_id=jump_id,
        card_id=card_id,
        require_jump_target=True,
    )
    if result[1] == "跳转到步骤":
        logger.warning(f"点击失败，跳转到步骤 {result[2]}")
    elif result[1] == "停止工作流":
        logger.warning("点击失败，停止工作流")
    elif result[1] == "继续执行本步骤":
        logger.warning("点击失败，继续执行本步骤")
    else:
        logger.warning("点击失败，继续执行下一步")
    return result

def execute_task(params: Dict[str, Any], counters: Dict[str, int], execution_mode: str,
                target_hwnd: Optional[int], window_region: Optional[tuple], card_id: Optional[int],
                get_image_data=None, **kwargs) -> Tuple[bool, str, Optional[int]]:
    """执行模拟鼠标操作任务 - execute_task 接口"""
    return _execute_mouse_action(params, counters, execution_mode, target_hwnd, card_id, get_image_data,
                                 kwargs.get('stop_checker'), device_id=kwargs.get('device_id'))

def _execute_mouse_action(params: Dict[str, Any], counters: Dict[str, int], execution_mode: str,
                          target_hwnd: Optional[int], card_id: Optional[int], get_image_data=None, stop_checker=None,
                          device_id: Optional[str] = None) -> Tuple[bool, str, Optional[int]]:
    """执行模拟鼠标操作任务"""

    # 获取基本参数
    operation_mode = _normalize_operation_mode(params.get('operation_mode', ''))

    # 刷新 向后兼容：根据旧任务类型自动推断操作模式
    task_type = params.get('task_type', '')

    # 优先根据任务类型推断操作模式
    if task_type in ('图片点击', '找图功能', '找图点击'):
        operation_mode = '找图功能'
    elif task_type == '点击指定坐标':
        operation_mode = '坐标点击'
    elif not operation_mode:
        # 如果没有指定操作模式，根据参数推断
        if params.get('image_path'):
            operation_mode = '找图功能'
        elif 'coordinate_x' in params and 'coordinate_y' in params:
            operation_mode = '坐标点击'
        elif params.get('scroll_direction'):
            operation_mode = '鼠标滚轮'
        else:
            # 默认为找图功能
            operation_mode = '找图功能'

    on_success_action = params.get('on_success', '执行下一步')
    success_jump_id = params.get('success_jump_target_id')
    on_failure_action = params.get('on_failure', '执行下一步')
    failure_jump_id = params.get('failure_jump_target_id')

    logger.info(f"开始执行模拟鼠标操作任务，模式: {operation_mode} (任务类型: {task_type})")
    logger.info(f"跳转参数: 成功动作={on_success_action}, 成功跳转ID={success_jump_id}, 失败动作={on_failure_action}, 失败跳转ID={failure_jump_id}")

    try:
        # 执行具体操作
        if operation_mode == "找图功能":
            # 执行找图功能
            success, action, next_id = _execute_image_click(params, execution_mode, target_hwnd, card_id, get_image_data,
                                      on_success_action, success_jump_id, on_failure_action, failure_jump_id, stop_checker)
        elif operation_mode == "坐标点击":
            # 执行坐标点击
            success, action, next_id = _execute_coordinate_click(params, execution_mode, target_hwnd, card_id,
                                           on_success_action, success_jump_id, on_failure_action, failure_jump_id, stop_checker)
        elif operation_mode == "文字点击":
            # 执行文字点击
            success, action, next_id = _execute_text_click(params, execution_mode, target_hwnd, card_id,
                                              on_success_action, success_jump_id, on_failure_action, failure_jump_id, stop_checker)
        elif operation_mode == "找色功能":
            # 执行找色功能
            success, action, next_id = _execute_color_click(params, execution_mode, target_hwnd, card_id,
                                              on_success_action, success_jump_id, on_failure_action, failure_jump_id, stop_checker)
        elif operation_mode == "元素点击":
            # 执行元素点击（基于UIAutomation）
            success, action, next_id = _execute_element_click(params, execution_mode, target_hwnd, card_id,
                                              on_success_action, success_jump_id, on_failure_action, failure_jump_id)
        elif operation_mode == "鼠标滚轮":
            # 执行鼠标滚轮操作
            success, action, next_id = _execute_mouse_scroll(params, execution_mode, target_hwnd, card_id,
                                        on_success_action, success_jump_id, on_failure_action, failure_jump_id, stop_checker)
        elif operation_mode == "鼠标拖拽":
            # 执行鼠标拖拽操作
            success, action, next_id = _execute_mouse_drag(params, execution_mode, target_hwnd, card_id,
                                      on_success_action, success_jump_id, on_failure_action, failure_jump_id,
                                      device_id=device_id)
        elif operation_mode == "鼠标移动":
            # 执行鼠标移动操作
            success, action, next_id = _execute_mouse_move(params, execution_mode, target_hwnd, card_id,
                                      on_success_action, success_jump_id, on_failure_action, failure_jump_id, stop_checker)
        else:
            logger.error(f"未知的操作模式: {operation_mode}")
            return _handle_failure(on_failure_action, failure_jump_id, card_id)

        # 处理下一步延迟执行（只在跳转到步骤或执行下一步时应用）
        logger.info(f"模拟鼠标操作最终返回: success={success}, action={action}, next_id={next_id}")
        return success, action, next_id

    except Exception as e:
        logger.error(f"执行模拟鼠标操作任务时发生异常: {e}", exc_info=True)
        return _handle_failure(on_failure_action, failure_jump_id, card_id)

def _execute_image_click(params: Dict[str, Any], execution_mode: str, target_hwnd: Optional[int],
                        card_id: Optional[int], get_image_data, on_success_action: str,
                        success_jump_id: Optional[int], on_failure_action: str,
                        failure_jump_id: Optional[int], stop_checker=None) -> Tuple[bool, str, Optional[int]]:
    """执行找图功能"""
    # 检查是否为多图识别模式
    multi_image_mode = params.get('multi_image_mode', '单图识别')

    if multi_image_mode == '多图识别':
        return _execute_multi_image_click(params, execution_mode, target_hwnd, card_id, get_image_data,
                                        on_success_action, success_jump_id, on_failure_action, failure_jump_id,
                                        stop_checker)
    else:
        return _execute_single_image_click(params, execution_mode, target_hwnd, card_id, get_image_data,
                                         on_success_action, success_jump_id, on_failure_action, failure_jump_id,
                                         stop_checker)

def _execute_single_image_click(params: Dict[str, Any], execution_mode: str, target_hwnd: Optional[int],
                               card_id: Optional[int], get_image_data, on_success_action: str,
                               success_jump_id: Optional[int], on_failure_action: str,
                               failure_jump_id: Optional[int], stop_checker=None) -> Tuple[bool, str, Optional[int]]:
    """执行单找图功能"""
    # 导入找图功能模块
    try:
        from tasks.image_match_click import execute_task as execute_image_click
        
        # 构造找图功能的参数
        # 获取点击位置模式
        image_position_mode = params.get('image_position_mode', '精准坐标')

        click_button, click_count, click_interval, click_action, enable_auto_release, image_hold_duration = resolve_click_params(
            params,
            button_key="button",
            clicks_key="clicks",
            interval_key="interval",
            action_key="image_click_action",
            auto_release_key="image_enable_auto_release",
            hold_duration_key="image_hold_duration",
            hold_mode_key="image_hold_mode",
            hold_min_key="image_hold_duration_min",
            hold_max_key="image_hold_duration_max",
            mode_label="单找图功能",
            logger_obj=logger,
            log_hold_mode=False,
        )

        from task_workflow.resource_path import unwrap_resource_path

        image_params = {
            'image_path': unwrap_resource_path(params.get('image_path', '')) or '',
            'confidence': params.get('confidence', 0.8),
            'preprocessing_method': params.get('preprocessing_method', '无'),
            'enable_click': coerce_bool(params.get('image_enable_click', True)),
            'image_position_mode': image_position_mode,  # 关键：传递位置模式
            'button': click_button,
            'click_action': click_action,
            'hold_duration': image_hold_duration,
            'enable_auto_release': enable_auto_release,
            'clicks': click_count,
            'interval': click_interval,
            'enable_retry': params.get('enable_retry', False),
            'retry_attempts': params.get('retry_attempts', 3),
            'retry_interval': params.get('retry_interval', 0.5),
            # 添加识别区域参数
            'use_recognition_region': coerce_bool(params.get('use_recognition_region', False)),
            'recognition_region_x': params.get('recognition_region_x', 0),
            'recognition_region_y': params.get('recognition_region_y', 0),
            'recognition_region_width': params.get('recognition_region_width', 0),
            'recognition_region_height': params.get('recognition_region_height', 0),
            'on_success': on_success_action,
            'success_jump_target_id': success_jump_id,
            'on_failure': on_failure_action,
            'failure_jump_target_id': failure_jump_id
        }

        # 根据点击位置模式添加偏移参数
        if image_position_mode == '固定偏移':
            image_params['fixed_offset_x'] = params.get('image_fixed_offset_x', 0)
            image_params['fixed_offset_y'] = params.get('image_fixed_offset_y', 0)
            image_params['random_offset_x'] = params.get('image_random_offset_x', 5)
            image_params['random_offset_y'] = params.get('image_random_offset_y', 5)
        elif image_position_mode == '随机偏移':
            image_params['fixed_offset_x'] = 0
            image_params['fixed_offset_y'] = 0
            image_params['random_offset_x'] = params.get('image_random_offset_x', 5)
            image_params['random_offset_y'] = params.get('image_random_offset_y', 5)
        else:  # 精准坐标
            image_params['fixed_offset_x'] = 0
            image_params['fixed_offset_y'] = 0
            image_params['random_offset_x'] = 0
            image_params['random_offset_y'] = 0
        
        # 只显示图片名称，不显示完整路径
        image_path = unwrap_resource_path(params.get('image_path', '')) or ''
        if image_path.startswith('memory://'):
            image_name = image_path.replace('memory://', '')
        else:
            image_name = os.path.basename(image_path) if image_path else ''
        logger.info(f"执行单找图功能: {image_name}")
        result = execute_image_click(
            image_params,
            {},
            execution_mode,
            target_hwnd,
            None,
            card_id,
            get_image_data=get_image_data,
            stop_checker=stop_checker,
        )

        # 【防御性编程】检查返回值是否为 None，防止解包错误
        if result is None:
            logger.error("找图功能模块返回了 None")
            return _handle_failure(on_failure_action, failure_jump_id, card_id)

        return result

    except Exception as e:
        logger.error(f"执行单找图功能时发生错误: {e}", exc_info=True)
        return _handle_failure(on_failure_action, failure_jump_id, card_id)

def _execute_multi_image_click(params: Dict[str, Any], execution_mode: str, target_hwnd: Optional[int],
                              card_id: Optional[int], get_image_data, on_success_action: str,
                              success_jump_id: Optional[int], on_failure_action: str,
                              failure_jump_id: Optional[int], stop_checker=None) -> Tuple[bool, str, Optional[int]]:
    """执行多找图功能"""
    import time  # 确保time模块可用

    # 检查是否启用并行识别优化
    enable_parallel = params.get('enable_parallel_recognition', True)

    if enable_parallel:
        try:
            # 使用优化的并行识别模块
            from tasks.optimized_multi_image_click import execute_multi_image_click_optimized
            logger.info("[多图识别] 使用并行识别优化模式")
            return execute_multi_image_click_optimized(
                params, execution_mode, target_hwnd, card_id, get_image_data,
                on_success_action, success_jump_id, on_failure_action, failure_jump_id,
                stop_checker=stop_checker
            )
        except ImportError as e:
            logger.warning(f"[多图识别] 并行识别模块不可用，回退到传统模式: {e}")
        except Exception as e:
            logger.error(f"[多图识别] 并行识别执行失败，回退到传统模式: {e}")

    # 传统串行识别模式（原有逻辑）
    logger.info("[多图识别] 使用传统串行识别模式")
    try:
        from task_workflow.workflow_context import get_workflow_context
        from tasks.image_match_click import execute_task as execute_image_click
        import os

        context = get_workflow_context()

        # 获取参数
        from task_workflow.resource_path import format_resource_text

        image_paths_text = format_resource_text(params.get('image_paths', ''))
        click_all_found = params.get('click_all_found', False)
        clear_clicked_on_next_run = params.get('clear_clicked_on_next_run', False)

        if not image_paths_text:
            logger.error("多图识别模式下未配置图片路径")
            return _handle_failure(on_failure_action, failure_jump_id, card_id)

        # 解析图片路径列表
        raw_image_paths = [path.strip() for path in image_paths_text.split('\n') if path.strip()]
        if not raw_image_paths:
            logger.error("多图识别模式下图片路径列表为空")
            return _handle_failure(on_failure_action, failure_jump_id, card_id)

        # 智能纠正图片路径
        image_paths = _correct_image_paths(raw_image_paths)
        if not image_paths:
            logger.error("多图识别模式下所有图片路径都无效")
            # 显示错误对话框提示用户
            _show_no_images_found_dialog(raw_image_paths)
            return _handle_failure(on_failure_action, failure_jump_id, card_id)

        logger.info(f"[多图识别] 开始执行，共{len(image_paths)}张图片，全部点击: {click_all_found}")

        # 处理下次执行清除记录
        if clear_clicked_on_next_run:
            context.set_card_data(card_id, 'clicked_images', set())
            context.set_card_data(card_id, 'success_images', set())
            logger.info("[多图识别] 已清除上次点击记录和成功记录")

        # 获取已点击的图片记录
        clicked_images = context.get_card_data(card_id, 'clicked_images', set())
        if not isinstance(clicked_images, set):
            clicked_images = set(clicked_images) if clicked_images else set()

        logger.info(f"[多图识别] 已点击图片记录: {len(clicked_images)}张")

        if click_all_found:
            # 启用全部点击：只排除已成功的图片，失败的图片需要重新尝试
            success_images = context.get_card_data(card_id, 'success_images', set())
            remaining_images = [path for path in image_paths if path not in success_images]
            logger.info(f"[多图识别] 剩余待识别图片: {len(remaining_images)}张（排除已成功的{len(success_images)}张）")

            if not remaining_images:
                # 所有图片都已成功
                logger.info(f"[多图识别] 启用全部点击，全部{len(image_paths)}张图片都识别并点击成功")
                context.set_card_data(card_id, 'clicked_images', set())
                context.set_card_data(card_id, 'success_images', set())
                logger.info("[多图识别] 全部成功，已清除记忆")
                return _handle_success(on_success_action, success_jump_id, card_id)
        else:
            # 未启用全部点击：排除已尝试过的图片（成功+失败）
            remaining_images = [path for path in image_paths if path not in clicked_images]
            logger.info(f"[多图识别] 剩余待识别图片: {len(remaining_images)}张")

            if not remaining_images:
                # 所有图片都已尝试过且都失败了
                logger.error(f"[多图识别] 未启用全部点击，所有{len(image_paths)}张图片都已尝试且都失败，任务失败")
                context.set_card_data(card_id, 'clicked_images', set())  # 清除记忆
                return _handle_failure(on_failure_action, failure_jump_id, card_id)

        # 尝试识别和点击图片
        found_images = []
        clicked_count = 0

        for i, image_path in enumerate(remaining_images):
            # 构建单个图片的参数
            # 支持多图专用参数名
            use_region = (
                coerce_bool(params.get('use_recognition_region', False)) or
                coerce_bool(params.get('multi_use_recognition_region', False))
            )
            region_x = params.get('multi_recognition_region_x', params.get('recognition_region_x', 0))
            region_y = params.get('multi_recognition_region_y', params.get('recognition_region_y', 0))
            region_w = params.get('multi_recognition_region_width', params.get('recognition_region_width', 0))
            region_h = params.get('multi_recognition_region_height', params.get('recognition_region_height', 0))

            single_image_params = {
                'image_path': image_path,
                'confidence': params.get('confidence', 0.8),
                'preprocessing_method': params.get('preprocessing_method', '无'),
                'enable_click': coerce_bool(params.get('image_enable_click', True)),
                'image_position_mode': params.get('image_position_mode', '精准坐标'),  # 关键：传递位置模式
                'fixed_offset_x': params.get('image_fixed_offset_x', 0),
                'fixed_offset_y': params.get('image_fixed_offset_y', 0),
                'random_offset_x': params.get('image_random_offset_x', 5),
                'random_offset_y': params.get('image_random_offset_y', 5),
                'button': params.get('button', '左键'),
                'clicks': params.get('clicks', 1),
                'interval': params.get('interval', DEFAULT_DOUBLE_CLICK_INTERVAL_SECONDS),
                'enable_retry': params.get('enable_retry', False),
                'retry_attempts': params.get('retry_attempts', 3),
                'retry_interval': params.get('retry_interval', 0.5),
                # 【修复】添加识别区域参数（统一使用单图参数名传递给image_match_click）
                'use_recognition_region': use_region,
                'recognition_region_x': region_x,
                'recognition_region_y': region_y,
                'recognition_region_width': region_w,
                'recognition_region_height': region_h,
                'on_success': '执行下一步',  # 内部处理，不跳转
                'success_jump_target_id': None,
                'on_failure': '执行下一步',  # 内部处理，不跳转
                'failure_jump_target_id': None
            }

            # 显示图片名称
            if image_path.startswith('memory://'):
                image_name = image_path.replace('memory://', '')
            else:
                image_name = os.path.basename(image_path) if image_path else f'图片{i+1}'

            logger.info(f"[多图识别] 尝试识别第{i+1}张图片: {image_name}")

            # 添加详细调试日志
            logger.debug("[多图识别调试] 调用execute_image_click参数:")
            logger.debug(f"  - image_path: {single_image_params.get('image_path')}")
            logger.debug(f"  - execution_mode: {execution_mode}")
            logger.debug(f"  - target_hwnd: {target_hwnd}")
            logger.debug(f"  - button: {single_image_params.get('button')}")
            logger.debug(f"  - clicks: {single_image_params.get('clicks')}")

            # 执行单张图片的识别和点击
            result = execute_image_click(
                single_image_params,
                {},
                execution_mode,
                target_hwnd,
                None,
                card_id,
                get_image_data=get_image_data,
                stop_checker=stop_checker,
            )

            # 【防御性编程】检查返回值是否为 None，防止解包错误
            if result is None:
                logger.error(f"[多图识别] 找图功能模块返回了 None，图片: {image_name}")
                continue  # 跳过这张图片，尝试下一张

            success, action, next_id = result

            # 添加返回值调试日志
            logger.debug("[多图识别调试] execute_image_click返回值:")
            logger.debug(f"  - success: {success}")
            logger.debug(f"  - action: {action}")
            logger.debug(f"  - next_id: {next_id}")

            if success:
                logger.info(f"[多图识别] 第{i+1}张图片识别并点击成功: {image_name}")
                found_images.append(image_path)
                clicked_images.add(image_path)
                clicked_count += 1

                # 确保点击操作完成：添加适当延迟
                click_completion_delay = max(0.2, params.get('interval', 0.1))  # 增加最小延迟到200ms
                logger.debug(f"[多图识别] 等待点击操作完成，延迟{click_completion_delay}秒")
                precise_sleep(click_completion_delay)

                # 额外验证点击是否真正完成（针对模拟器和后台模式）
                if (execution_mode.startswith('background') or execution_mode.startswith('emulator_')) and target_hwnd:
                    # 后台窗口标准延迟
                    additional_delay = 0.1
                    logger.debug(f"[多图识别] 后台窗口响应时间，延迟{additional_delay}秒")
                    precise_sleep(additional_delay)

                # 更新已点击记录
                context.set_card_data(card_id, 'clicked_images', clicked_images)

                # 记录成功的图片（用于最终判断）
                success_images = context.get_card_data(card_id, 'success_images', set())
                success_images.add(image_path)
                context.set_card_data(card_id, 'success_images', success_images)

                # 用户自定义的每张图片识别延迟
                multi_image_delay = params.get('multi_image_delay', 1.0)
                if multi_image_delay > 0:
                    logger.debug(f"[多图识别] 用户自定义延迟，延迟{multi_image_delay}秒")
                    precise_sleep(multi_image_delay)

                if not click_all_found:
                    # 未启用全部点击：找到第一张成功的就完成任务，清除记忆
                    logger.info("[多图识别] 未启用全部点击，已点击第一张成功识别的图片，任务完成")
                    context.set_card_data(card_id, 'clicked_images', set())  # 清除记忆
                    context.set_card_data(card_id, 'success_images', set())  # 清除成功记录
                    return _handle_success(on_success_action, success_jump_id, card_id)
            else:
                logger.info(f"[多图识别] 第{i+1}张图片识别失败: {image_name}")
                if not click_all_found:
                    # 未启用全部点击：失败的图片加入已点击记录，避免无限重试
                    clicked_images.add(image_path)
                    context.set_card_data(card_id, 'clicked_images', clicked_images)
                # 启用全部点击：失败的图片不加入clicked_images，下次可以重新尝试

            # 在处理下一张图片前添加小延迟，确保当前操作完全完成
            if i < len(remaining_images) - 1:  # 不是最后一张图片
                # 图片间延迟
                inter_image_delay = 0.05
                logger.debug(f"[多图识别] 图片间延迟{inter_image_delay}秒")
                precise_sleep(inter_image_delay)

        # 处理结果
        if click_all_found:
            # 启用全部点击模式
            if found_images:
                # 本轮有图片成功
                # 检查是否还有未成功的图片（基于success_images而非clicked_images）
                all_success_images = context.get_card_data(card_id, 'success_images', set())
                remaining_after_click = [path for path in image_paths if path not in all_success_images]
                if remaining_after_click:
                    logger.info(f"[多图识别] 启用全部点击，本轮点击{clicked_count}张，还有{len(remaining_after_click)}张待处理，继续执行本卡片")
                    return True, '继续执行本步骤', card_id
                else:
                    # 所有图片都成功了
                    total_success_count = len(all_success_images)
                    if total_success_count == len(image_paths):
                        # 全部成功
                        logger.info(f"[多图识别] 启用全部点击，全部{len(image_paths)}张图片都识别并点击成功")
                        # 全部成功时可以清除记忆（任务彻底完成）
                        context.set_card_data(card_id, 'clicked_images', set())
                        context.set_card_data(card_id, 'success_images', set())
                        logger.info("[多图识别] 全部成功，已清除记忆")
                        return _handle_success(on_success_action, success_jump_id, card_id)
                    else:
                        # 部分成功，部分失败
                        failed_count = len(image_paths) - total_success_count
                        logger.warning(f"[多图识别] 启用全部点击，成功{total_success_count}张，失败{failed_count}张，按失败跳转")
                        # 部分失败时保持记忆，避免下次重复点击已成功的图片
                        logger.info("[多图识别] 部分失败，保持记忆避免重复点击")
                        return _handle_failure(on_failure_action, failure_jump_id, card_id)
            else:
                # 本轮没有图片成功，检查是否全部失败
                all_success_images = context.get_card_data(card_id, 'success_images', set())
                if len(all_success_images) == 0:
                    # 全部失败：清除记忆，按失败跳转
                    logger.warning(f"[多图识别] 启用全部点击，全部{len(image_paths)}张图片都识别失败，清除记忆，按失败跳转")
                    context.set_card_data(card_id, 'clicked_images', set())
                    context.set_card_data(card_id, 'success_images', set())
                    logger.info("[多图识别] 全部失败，已清除记忆")
                    return _handle_failure(on_failure_action, failure_jump_id, card_id)
                else:
                    # 本轮失败但之前有成功：保持记忆，按失败跳转
                    logger.warning("[多图识别] 启用全部点击，本轮所有剩余图片都识别失败，保持记忆，按失败跳转")
                    logger.info("[多图识别] 本轮失败，保持记忆等待下次重试")
                    return _handle_failure(on_failure_action, failure_jump_id, card_id)
        else:
            # 未启用全部点击模式
            if found_images:
                # 不应该到达这里，因为上面已经处理了
                logger.info("[多图识别] 未启用全部点击，有图片成功，任务完成")
                context.set_card_data(card_id, 'clicked_images', set())  # 清除记忆
                context.set_card_data(card_id, 'success_images', set())  # 清除成功记录
                return _handle_success(on_success_action, success_jump_id, card_id)
            else:
                # 检查是否还有其他图片没尝试过
                all_images_tried = len(clicked_images) == len(image_paths)
                if all_images_tried:
                    # 所有图片都尝试过且都失败了，才算真的失败
                    logger.error(f"[多图识别] 未启用全部点击，所有{len(image_paths)}张图片都已尝试且都失败，任务失败")
                    context.set_card_data(card_id, 'clicked_images', set())  # 清除记忆
                    context.set_card_data(card_id, 'success_images', set())  # 清除成功记录
                    return _handle_failure(on_failure_action, failure_jump_id, card_id)
                else:
                    # 还有其他图片没尝试过，继续尝试
                    untried_count = len(image_paths) - len(clicked_images)
                    logger.info(f"[多图识别] 未启用全部点击，本轮{len(remaining_images)}张失败，还有{untried_count}张未尝试，继续执行本卡片")
                    return True, '继续执行本步骤', card_id

    except Exception as e:
        logger.error(f"执行多找图功能时发生错误: {e}", exc_info=True)
        return _handle_failure(on_failure_action, failure_jump_id, card_id)

def _execute_coordinate_click(params: Dict[str, Any], execution_mode: str, target_hwnd: Optional[int],
                             card_id: Optional[int], on_success_action: str, success_jump_id: Optional[int],
                             on_failure_action: str, failure_jump_id: Optional[int], stop_checker=None) -> Tuple[bool, str, Optional[int]]:
    """执行坐标点击"""
    # 导入坐标点击模块
    try:
        from tasks.click_coordinate import execute_task as execute_coordinate_click

        if "coordinate_source_mode" not in params:
            raise ValueError("坐标点击参数缺少 coordinate_source_mode")
        coordinate_source_mode_raw = params["coordinate_source_mode"]
        coordinate_source_mode = str(coordinate_source_mode_raw or "").strip()
        if not coordinate_source_mode:
            raise ValueError("坐标点击 coordinate_source_mode 不能为空")
        if coordinate_source_mode not in ("坐标工具获取坐标", "手动输入", "无坐标"):
            logger.error(f"坐标点击不支持的坐标获取方式: {coordinate_source_mode}")
            return _handle_failure(on_failure_action, failure_jump_id, card_id)
        from task_workflow.card_payload import coerce_number

        resolved_coordinate_x = int(coerce_number(params.get('coordinate_x', 0), 0, as_float=False))
        resolved_coordinate_y = int(coerce_number(params.get('coordinate_y', 0), 0, as_float=False))
        coordinate_value_for_click = params.get('coordinate_value', '')

        # 坐标来源互斥；坐标工具/手动输入模式不读取旧的 coordinate_value 字段。
        if coordinate_source_mode in ('坐标工具获取坐标', '手动输入'):
            coordinate_value_for_click = ''

        coordinate_mode_for_click = params.get('coordinate_mode', '客户区坐标')

        if coordinate_source_mode == '无坐标':
            try:
                import win32api

                cursor_x, cursor_y = win32api.GetCursorPos()
                resolved_coordinate_x = int(cursor_x)
                resolved_coordinate_y = int(cursor_y)
                coordinate_value_for_click = ''
                coordinate_mode_for_click = '屏幕坐标'
                logger.info(
                    f"坐标点击使用无坐标模式: 当前鼠标屏幕位置=({resolved_coordinate_x}, {resolved_coordinate_y})"
                )
            except Exception as cursor_exc:
                logger.error(f"获取当前鼠标位置失败: {cursor_exc}", exc_info=True)
                return _handle_failure(on_failure_action, failure_jump_id, card_id)

        # 获取点击位置模式
        coordinate_position_mode = params.get('coordinate_position_mode', '精准坐标')
        if coordinate_source_mode == '无坐标':
            coordinate_position_mode = '精准坐标'
        coordinate_enable_click = coerce_bool(params.get('coordinate_enable_click', True))

        click_button, click_count, click_interval, click_action, enable_auto_release, coordinate_hold_duration = resolve_click_params(
            params,
            button_key="button",
            clicks_key="clicks",
            interval_key="interval",
            action_key="coordinate_click_action",
            auto_release_key="coordinate_enable_auto_release",
            hold_duration_key="coordinate_hold_duration",
            hold_mode_key="coordinate_hold_mode",
            hold_min_key="coordinate_hold_duration_min",
            hold_max_key="coordinate_hold_duration_max",
            mode_label="坐标点击",
            logger_obj=logger,
            log_hold_mode=False,
        )

        # 构造坐标点击的参数
        coordinate_params = {
            'coordinate_x': resolved_coordinate_x,
            'coordinate_y': resolved_coordinate_y,
            'coordinate_value': coordinate_value_for_click,
            'coordinate_mode': coordinate_mode_for_click,
            'position_mode': coordinate_position_mode,  # 关键：传递位置模式（click_coordinate使用position_mode）
            'enable_click': coordinate_enable_click,
            'button': click_button,
            'click_action': click_action,
            'hold_duration': coordinate_hold_duration,
            'enable_auto_release': enable_auto_release,
            'clicks': click_count,
            'interval': click_interval,
            'on_success': on_success_action,
            'success_jump_target_id': success_jump_id,
            'on_failure': on_failure_action,
            'failure_jump_target_id': failure_jump_id
        }

        # 根据点击位置模式添加偏移参数
        if coordinate_position_mode == '固定偏移':
            coordinate_params['fixed_offset_x'] = int(coerce_number(params.get('coordinate_fixed_offset_x', 0), 0, as_float=False))
            coordinate_params['fixed_offset_y'] = int(coerce_number(params.get('coordinate_fixed_offset_y', 0), 0, as_float=False))
            coordinate_params['random_offset_x'] = int(coerce_number(params.get('coordinate_random_offset_x', 5), 5, as_float=False))
            coordinate_params['random_offset_y'] = int(coerce_number(params.get('coordinate_random_offset_y', 5), 5, as_float=False))
            logger.info(f"执行坐标点击（固定偏移模式）: ({resolved_coordinate_x}, {resolved_coordinate_y})")
        elif coordinate_position_mode == '随机偏移':
            coordinate_params['fixed_offset_x'] = 0
            coordinate_params['fixed_offset_y'] = 0
            coordinate_params['random_offset_x'] = int(coerce_number(params.get('coordinate_random_offset_x', 5), 5, as_float=False))
            coordinate_params['random_offset_y'] = int(coerce_number(params.get('coordinate_random_offset_y', 5), 5, as_float=False))
            logger.info(f"执行坐标点击（随机偏移模式）: ({resolved_coordinate_x}, {resolved_coordinate_y})")
        else:  # 精准坐标
            coordinate_params['fixed_offset_x'] = 0
            coordinate_params['fixed_offset_y'] = 0
            coordinate_params['random_offset_x'] = 0
            coordinate_params['random_offset_y'] = 0
            logger.info(f"执行坐标点击（精准坐标模式）: ({resolved_coordinate_x}, {resolved_coordinate_y})")

        try:
            from task_workflow.card_payload import publish_card_payload
            from task_workflow.workflow_context import get_workflow_context

            publish_card_payload(
                get_workflow_context(),
                card_id,
                click_target_x=resolved_coordinate_x,
                click_target_y=resolved_coordinate_y,
            )
        except Exception:
            pass

        result = execute_coordinate_click(
            coordinate_params,
            {},
            execution_mode,
            target_hwnd,
            None,
            card_id,
            stop_checker=stop_checker,
        )

        # 【防御性编程】检查返回值是否为 None，防止解包错误
        if result is None:
            logger.error("坐标点击模块返回了 None")
            return _handle_failure(on_failure_action, failure_jump_id, card_id)

        return result

    except Exception as e:
        logger.error(f"执行坐标点击时发生错误: {e}", exc_info=True)
        return _handle_failure(on_failure_action, failure_jump_id, card_id)

def _execute_text_click(params: Dict[str, Any], execution_mode: str, target_hwnd: Optional[int],
                       card_id: Optional[int], on_success_action: str, success_jump_id: Optional[int],
                       on_failure_action: str, failure_jump_id: Optional[int], stop_checker=None) -> Tuple[bool, str, Optional[int]]:
    """执行文字点击"""
    try:
        from tasks.click_coordinate import execute_task as execute_coordinate_click

        # 获取文字位置参数
        text_match_mode = params.get('text_match_mode', '包含')
        text_position_mode = params.get('text_position_mode', '精准坐标')
        text_enable_click = coerce_bool(params.get('text_enable_click', True))

        # 根据点击位置模式获取偏移参数
        from task_workflow.card_payload import coerce_number

        if text_position_mode == '固定偏移':
            text_fixed_offset_x = int(coerce_number(params.get('text_fixed_offset_x', 0), 0, as_float=False))
            text_fixed_offset_y = int(coerce_number(params.get('text_fixed_offset_y', 0), 0, as_float=False))
            text_random_offset_x = int(coerce_number(params.get('text_random_offset_x', 5), 5, as_float=False))
            text_random_offset_y = int(coerce_number(params.get('text_random_offset_y', 5), 5, as_float=False))
        elif text_position_mode == '随机偏移':
            text_fixed_offset_x = 0
            text_fixed_offset_y = 0
            text_random_offset_x = int(coerce_number(params.get('text_random_offset_x', 5), 5, as_float=False))
            text_random_offset_y = int(coerce_number(params.get('text_random_offset_y', 5), 5, as_float=False))
        else:  # 精准坐标
            text_fixed_offset_x = 0
            text_fixed_offset_y = 0
            text_random_offset_x = 0
            text_random_offset_y = 0

        logger.info(f"执行文字点击: 点击位置={text_position_mode}")

        # 从工作流上下文中获取最新的识别结果
        # 支持OCR识别和字库识别两种模式，获取最新的识别结果
        ocr_results = _get_ocr_results_from_context(card_id)

        # 【关键修复】验证OCR结果是否来自同一个窗口，防止跨窗口上下文污染
        if ocr_results:
            try:
                from task_workflow.workflow_context import get_workflow_context
                context = get_workflow_context()
                latest_ocr_card_id = context.get_latest_ocr_card_id()

                if latest_ocr_card_id is not None:
                    ocr_window_hwnd = context.get_card_data(latest_ocr_card_id, 'ocr_window_hwnd')

                    if ocr_window_hwnd is not None:
                        if ocr_window_hwnd != target_hwnd:
                            logger.error(f"【窗口HWND不匹配】OCR结果来自窗口HWND={ocr_window_hwnd}，但当前文字点击任务的目标窗口HWND={target_hwnd}")
                            logger.error(f"这是跨窗口上下文污染！窗口{target_hwnd}的点击任务不应该使用窗口{ocr_window_hwnd}的OCR结果")
                            logger.error(f"OCR来源卡片: {latest_ocr_card_id}, 当前文字点击卡片: {card_id}")
                            logger.error("拒绝使用错误的OCR结果，判定为点击失败")
                            return _handle_failure(on_failure_action, failure_jump_id, card_id)
                        else:
                            logger.info(f"【窗口HWND验证通过】OCR结果和文字点击任务都在窗口HWND={target_hwnd}")
                    else:
                        logger.warning(f"OCR卡片{latest_ocr_card_id}未保存窗口HWND信息，无法验证窗口一致性")
                        logger.warning("建议更新OCR识别模块以保存窗口HWND")
            except Exception as e:
                logger.error(f"验证OCR窗口HWND时发生错误: {e}")
                import traceback
                logger.error(traceback.format_exc())

        if not ocr_results:
            # 检查是否是多组文字识别模式且上下文为空
            try:
                from task_workflow.workflow_context import get_workflow_context
                context = get_workflow_context()
                text_groups, current_index, clicked_texts = context.get_multi_text_recognition_state(card_id)

                if text_groups and len(text_groups) > 1:
                    logger.warning("多组文字识别模式下上下文为空，判断为点击失败")
                    logger.warning("所有文字组可能已识别完成或OCR识别失败")
                else:
                    logger.warning("未找到OCR识别结果，无法执行文字点击")
                    logger.warning("请确保在此卡片之前有OCR识别卡片，并且OCR识别成功")
            except Exception as e:
                logger.warning(f"检查多组文字识别状态时发生错误: {e}")
                logger.warning("未找到OCR识别结果，无法执行文字点击")

            return _handle_failure(on_failure_action, failure_jump_id, card_id)

        logger.info(f"获取到OCR识别结果: {len(ocr_results)} 个文字")
        for i, result in enumerate(ocr_results):
            text = result.get('text', '')
            confidence = result.get('confidence', 0)
            logger.info(f"  OCR结果{i+1}: '{text}' (置信度: {confidence:.3f})")

        # 从工作流上下文获取最新识别卡片的目标文字（支持OCR和字库识别）
        logger.info(f" [调试] 文字点击卡片{card_id}尝试获取目标文字")
        target_text, final_match_mode = _get_ocr_target_text_from_context(card_id)
        logger.info(f" [调试] 获取到的目标文字: '{target_text}', 匹配模式: {final_match_mode}")

        if not target_text:
            logger.error(" [调试] 最新的识别卡片未设置目标文字，无法执行文字点击")
            return _handle_failure(on_failure_action, failure_jump_id, card_id)
        else:
            logger.info(f" [调试] 使用OCR目标文字: '{target_text}', 匹配模式: {final_match_mode}")

        # 根据目标文字查找匹配的OCR结果
        matched_result = _find_matching_text_in_ocr_results(ocr_results, target_text, final_match_mode)

        if not matched_result:
            if target_text:
                logger.warning(f"在OCR结果中未找到匹配的文字: '{target_text}'")
                logger.warning("建议检查目标文字是否正确，或使用'包含'匹配模式")
            else:
                logger.warning("OCR结果为空，无法执行文字点击")
            return _handle_failure(on_failure_action, failure_jump_id, card_id)

        text_bbox = matched_result.get('bbox', [])
        matched_text = matched_result.get('text', '')
        confidence = matched_result.get('confidence', 0)
        logger.info(f"找到匹配文字: '{matched_text}' (置信度: {confidence:.3f})")
        logger.info(f" [调试] 文字边界框: {text_bbox}")

        # 计算点击坐标
        # 兼容两种bbox格式：扁平数组 [x1,y1,x2,y2,x3,y3,x4,y4] 或嵌套数组 [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
        if text_bbox:
            # 转换嵌套数组格式为扁平数组
            if isinstance(text_bbox[0], (list, tuple)):
                # 嵌套数组格式 [[x1,y1],[x2,y2],[x3,y3],[x4,y4]] -> [x1,y1,x2,y2,x3,y3,x4,y4]
                text_bbox = [coord for point in text_bbox for coord in point]
                logger.info(f" [调试] 转换嵌套bbox为扁平格式: {text_bbox}")

            if len(text_bbox) >= 8:
                # 统一使用文字中心（传入"精准点击"模式，让_calculate_click_position计算中心）
                relative_click_x, relative_click_y = _calculate_click_position(text_bbox, "精准点击", 0, 0)
                logger.info(f"[调试] 计算的相对坐标: ({relative_click_x}, {relative_click_y})")

                # 本地OCR返回的是相对于识别区域的局部坐标，需要加区域偏移。
                try:
                    from task_workflow.workflow_context import get_workflow_context
                    context = get_workflow_context()
                    latest_ocr_card_id = context.get_latest_ocr_card_id()
                    if latest_ocr_card_id is not None:
                        region_offset = context.get_card_data(latest_ocr_card_id, 'ocr_region_offset')

                        if region_offset:
                            offset_x, offset_y = region_offset
                            click_x = relative_click_x + offset_x
                            click_y = relative_click_y + offset_y
                            logger.info(f" [本地OCR] 局部坐标加区域偏移: ({relative_click_x}, {relative_click_y}) + ({offset_x}, {offset_y}) = ({click_x}, {click_y})")
                        else:
                            click_x, click_y = relative_click_x, relative_click_y
                            logger.info(f" [本地OCR] 无区域偏移，直接使用: ({click_x}, {click_y})")
                    else:
                        click_x, click_y = relative_click_x, relative_click_y
                        logger.warning(f" [本地OCR] 未找到OCR卡片信息，直接使用坐标: ({click_x}, {click_y})")
                except Exception as e:
                    logger.warning(f"获取OCR区域偏移失败: {e}，直接使用原始坐标")
                    import traceback
                    logger.debug(traceback.format_exc())
                    click_x, click_y = relative_click_x, relative_click_y

                # 应用偏移（根据点击位置模式）
                click_x, click_y, applied_offset_x, applied_offset_y = _apply_click_offsets(
                    click_x,
                    click_y,
                    text_position_mode,
                    text_fixed_offset_x,
                    text_fixed_offset_y,
                    text_random_offset_x,
                    text_random_offset_y,
                )
                if text_position_mode == "固定偏移":
                    logger.info(
                        f"计算得到点击坐标（固定偏移后叠加随机偏移）: ({click_x}, {click_y}), "
                        f"总偏移量=({applied_offset_x}, {applied_offset_y})"
                    )
                elif text_position_mode == "随机偏移":
                    logger.info(
                        f"计算得到点击坐标（应用随机偏移X={text_random_offset_x}, Y={text_random_offset_y}）: "
                        f"({click_x}, {click_y}), 偏移量=({applied_offset_x}, {applied_offset_y})"
                    )
                else:
                    logger.info(f"计算得到点击坐标（精准坐标）: ({click_x}, {click_y})")
            else:
                logger.error(f"无效的文字边界框: {text_bbox}")
                logger.error("边界框应包含8个坐标值 [x1,y1,x2,y2,x3,y3,x4,y4]")
                return _handle_failure(on_failure_action, failure_jump_id, card_id)
        else:
            logger.error("文字边界框为空")
            return _handle_failure(on_failure_action, failure_jump_id, card_id)

        click_button, click_count, click_interval, click_action, enable_auto_release, text_hold_duration = resolve_click_params(
            params,
            button_key="button",
            clicks_key="clicks",
            interval_key="interval",
            action_key="text_click_action",
            auto_release_key="text_enable_auto_release",
            hold_duration_key="text_hold_duration",
            hold_mode_key="text_hold_mode",
            hold_min_key="text_hold_duration_min",
            hold_max_key="text_hold_duration_max",
            mode_label="文字点击",
            logger_obj=logger,
            log_hold_mode=False,
        )

        # 构造坐标点击的参数（不再需要旧的disable_random_offset和random_offset）
        coordinate_params = {
            'coordinate_x': int(click_x),
            'coordinate_y': int(click_y),
            'coordinate_mode': '客户区坐标',  # OCR结果通常是相对于窗口的坐标
            'enable_click': text_enable_click,
            'button': click_button,
            'click_action': click_action,
            'hold_duration': text_hold_duration,
            'enable_auto_release': enable_auto_release,
            'clicks': click_count,
            'interval': click_interval,
            'fixed_offset_x': 0,  # 偏移已在上面应用
            'fixed_offset_y': 0,
            'random_offset_x': 0,
            'random_offset_y': 0,
            'on_success': on_success_action,
            'success_jump_target_id': success_jump_id,
            'on_failure': on_failure_action,
            'failure_jump_target_id': failure_jump_id
        }

        logger.info(f"执行文字点击坐标: ({click_x}, {click_y})")

        try:
            from task_workflow.card_payload import bounds_from_bbox, publish_click_target
            from task_workflow.workflow_context import get_workflow_context

            bounds = bounds_from_bbox(text_bbox)
            publish_click_target(
                get_workflow_context(),
                card_id,
                x=int(click_x),
                y=int(click_y),
                x1=None if bounds is None else bounds[0],
                y1=None if bounds is None else bounds[1],
                x2=None if bounds is None else bounds[2],
                y2=None if bounds is None else bounds[3],
                text=matched_text,
            )
        except Exception:
            pass

        # 执行坐标点击
        result = execute_coordinate_click(
            coordinate_params,
            {},
            execution_mode,
            target_hwnd,
            None,
            card_id,
            stop_checker=stop_checker,
        )

        # 【防御性编程】检查返回值是否为 None，防止解包错误
        if result is None:
            logger.error("坐标点击模块返回了 None")
            return _handle_failure(on_failure_action, failure_jump_id, card_id)

        success, action, next_id = result

        # 如果点击成功，处理多组文字识别逻辑
        if success:
            try:
                from task_workflow.workflow_context import get_workflow_context
                context = get_workflow_context()

                # 检查是否是多组文字识别模式
                # 需要使用OCR卡片的ID，而不是文字点击卡片的ID
                ocr_card_id = _get_ocr_card_id_from_context(card_id)
                if ocr_card_id is not None:
                    text_groups, current_index, clicked_texts = context.get_multi_text_recognition_state(ocr_card_id)
                else:
                    text_groups, current_index, clicked_texts = [], 0, []

                if text_groups and len(text_groups) > 1 and ocr_card_id is not None:
                    # 多组文字识别模式
                    # 记录已点击的文字
                    clicked_text = _get_clicked_text_from_context(card_id)
                    if clicked_text:
                        context.add_clicked_text(ocr_card_id, clicked_text)
                        logger.info(f"记录已点击文字到记忆: '{clicked_text}' (OCR卡片ID: {ocr_card_id})")

                    # 清除当前OCR上下文，但保留记忆
                    context.clear_card_ocr_context(ocr_card_id)
                    logger.info("清除OCR上下文数据，保留多组文字识别记忆")

                    # 推进到下一组文字
                    has_next = context.advance_text_recognition_index(ocr_card_id)
                    if has_next:
                        logger.info(f"推进到下一组文字识别，返回OCR卡片{ocr_card_id}继续执行")
                        # 返回到OCR识别卡片继续下一组识别
                        return success, "jump", ocr_card_id
                    else:
                        logger.info("所有文字组识别完成，清空所有数据")
                        context.clear_card_ocr_data(ocr_card_id)
                else:
                    # 单组文字识别模式，清除OCR上下文数据
                    context.clear_card_ocr_context(card_id)
                    logger.info("单组文字点击成功，已清除OCR上下文数据")

            except Exception as e:
                logger.warning(f"处理文字点击后续逻辑时发生错误: {e}")

        return success, action, next_id

    except Exception as e:
        logger.error(f"执行文字点击时发生错误: {e}", exc_info=True)
        return _handle_failure(on_failure_action, failure_jump_id, card_id)

def _execute_element_click(params: Dict[str, Any], execution_mode: str, target_hwnd: Optional[int],
                           card_id: Optional[int], on_success_action: str, success_jump_id: Optional[int],
                           on_failure_action: str, failure_jump_id: Optional[int]) -> Tuple[bool, str, Optional[int]]:
    """执行元素点击（基于UIAutomation）

    通过控件属性（Name、AutomationId、ClassName、ControlType）定位UI元素并点击。
    此功能使用本地 UIAutomation。

    Args:
        params: 任务参数
        execution_mode: 执行模式
        target_hwnd: 目标窗口句柄
        card_id: 卡片ID
        on_success_action: 成功时的动作
        success_jump_id: 成功时跳转的ID
        on_failure_action: 失败时的动作
        failure_jump_id: 失败时跳转的ID

    Returns:
        Tuple[bool, str, Optional[int]]: (是否成功, 动作类型, 跳转ID)
    """
    try:
        logger.info("[元素点击] 开始执行元素点击")

        # 检查窗口句柄
        if not target_hwnd:
            logger.error("[元素点击] 需要目标窗口句柄")
            return _handle_failure(on_failure_action, failure_jump_id, card_id)

        # 获取元素定位参数
        element_name = params.get('element_name', '').strip() or None
        element_automation_id = params.get('element_automation_id', '').strip() or None
        element_class_name = params.get('element_class_name', '').strip() or None
        element_control_type = params.get('element_control_type', '').strip() or None

        # 控件类型中文到英文映射
        control_type_map = {
            "无": None,
            "按钮": "ButtonControl",
            "编辑框": "EditControl",
            "文本": "TextControl",
            "复选框": "CheckBoxControl",
            "单选按钮": "RadioButtonControl",
            "下拉框": "ComboBoxControl",
            "列表": "ListControl",
            "列表项": "ListItemControl",
            "菜单": "MenuControl",
            "菜单项": "MenuItemControl",
            "树": "TreeControl",
            "树节点": "TreeItemControl",
            "选项卡": "TabControl",
            "选项卡项": "TabItemControl",
            "超链接": "HyperlinkControl",
            "窗口": "WindowControl",
            "面板": "PaneControl",
            "分组": "GroupControl",
            "数据表格": "DataGridControl",
            "表格": "TableControl",
        }
        if element_control_type:
            if element_control_type in control_type_map:
                element_control_type = control_type_map[element_control_type]
            elif element_control_type == "无":
                element_control_type = None

        element_found_index = params.get('element_found_index', 0)
        element_search_depth = params.get('element_search_depth', 30)
        element_timeout = params.get('element_timeout', 5.0)
        element_use_invoke = params.get('element_use_invoke', True)
        element_enable_click = coerce_bool(params.get('element_enable_click', True))

        # 获取鼠标按钮参数
        element_button = params.get('element_button', '左键')
        button_map = {'左键': 'left', '右键': 'right', '中键': 'middle'}
        element_button_mapped = button_map.get(element_button, 'left')

        # 至少需要一个定位条件
        if not any([element_name, element_automation_id, element_class_name, element_control_type]):
            logger.error("[元素点击] 至少需要指定一个元素定位条件（名称、自动化ID、类名或控件类型）")
            return _handle_failure(on_failure_action, failure_jump_id, card_id)

        logger.info(f"[元素点击] 定位条件: name={element_name}, automation_id={element_automation_id}, "
                   f"class_name={element_class_name}, control_type={element_control_type}")

        # 强制使用原生模式创建模拟器
        from utils.input_simulation import InputSimulatorFactory, SimulatorBackend, BackendNotAvailableError
        from utils.input_simulation.base import ElementNotFoundError

        try:
            simulator = InputSimulatorFactory.create_simulator(
                hwnd=target_hwnd,
                operation_mode="auto",
                execution_mode=execution_mode,
                backend=SimulatorBackend.NATIVE  # 强制原生模式
            )
        except BackendNotAvailableError as e:
            logger.error(f"[元素点击] 创建原生模式模拟器失败: {e}")
            return _handle_failure(on_failure_action, failure_jump_id, card_id)

        if not simulator:
            logger.error("[元素点击] 创建模拟器失败")
            return _handle_failure(on_failure_action, failure_jump_id, card_id)

        # 仅定位元素（不点击）
        if not element_enable_click:
            try:
                elements = simulator.find_all_elements(
                    name=element_name,
                    automation_id=element_automation_id,
                    class_name=element_class_name,
                    control_type=element_control_type,
                    search_depth=element_search_depth,
                    timeout=element_timeout,
                )
                if isinstance(elements, list) and 0 <= int(element_found_index) < len(elements):
                    logger.info("[元素点击] 已关闭点击执行，元素定位成功")
                    return _handle_success(on_success_action, success_jump_id, card_id)
                logger.warning("[元素点击] 已关闭点击执行，但未找到目标元素")
                return _handle_failure(on_failure_action, failure_jump_id, card_id)
            except NotImplementedError as e:
                logger.error(f"[元素点击] 当前模式不支持元素查找: {e}")
                return _handle_failure(on_failure_action, failure_jump_id, card_id)
            except TimeoutError as e:
                logger.warning(f"[元素点击] 元素查找超时: {e}")
                return _handle_failure(on_failure_action, failure_jump_id, card_id)
            except Exception as e:
                logger.error(f"[元素点击] 定位元素失败: {e}", exc_info=True)
                return _handle_failure(on_failure_action, failure_jump_id, card_id)

        # 执行元素点击
        try:
            success = simulator.click_element(
                name=element_name,
                automation_id=element_automation_id,
                class_name=element_class_name,
                control_type=element_control_type,
                found_index=element_found_index,
                search_depth=element_search_depth,
                timeout=element_timeout,
                use_invoke=element_use_invoke,
                button=element_button_mapped
            )

            if success:
                logger.info("[元素点击] 元素点击成功")
                return _handle_success(on_success_action, success_jump_id, card_id)
            else:
                logger.warning("[元素点击] 元素点击返回失败")
                return _handle_failure(on_failure_action, failure_jump_id, card_id)

        except ElementNotFoundError as e:
            logger.warning(f"[元素点击] 未找到目标元素: {e}")
            return _handle_failure(on_failure_action, failure_jump_id, card_id)
        except NotImplementedError as e:
            logger.error(f"[元素点击] 当前模式不支持元素点击: {e}")
            return _handle_failure(on_failure_action, failure_jump_id, card_id)
        except TimeoutError as e:
            logger.warning(f"[元素点击] 查找元素超时: {e}")
            return _handle_failure(on_failure_action, failure_jump_id, card_id)

    except Exception as e:
        logger.error(f"[元素点击] 执行时发生错误: {e}", exc_info=True)
        return _handle_failure(on_failure_action, failure_jump_id, card_id)

def _execute_color_click(params: Dict[str, Any], execution_mode: str, target_hwnd: Optional[int],
                        card_id: Optional[int], on_success_action: str, success_jump_id: Optional[int],
                        on_failure_action: str, failure_jump_id: Optional[int], stop_checker=None) -> Tuple[bool, str, Optional[int]]:
    """使用本地截图和 OpenCV 执行单色、多色组合或多点定位。"""
    try:
        target_color_str = str(params.get('target_color', '') or '').strip()
        if not target_color_str:
            logger.error("未设置目标颜色，请先通过颜色选择器获取颜色")
            return _handle_failure(on_failure_action, failure_jump_id, card_id)

        if not target_hwnd:
            logger.error("找色功能需要有效的目标窗口句柄")
            return _handle_failure(on_failure_action, failure_jump_id, card_id)

        enable_retry = coerce_bool(params.get('enable_retry', False))
        retry_attempts_raw = params.get('retry_attempts', 3)
        retry_interval_raw = params.get('retry_interval', 0.5)

        try:
            retry_attempts = int(retry_attempts_raw)
        except (TypeError, ValueError):
            retry_attempts = 3

        max_attempts = max(1, min(retry_attempts, 10)) if enable_retry else 1

        try:
            retry_interval = float(retry_interval_raw)
        except (TypeError, ValueError):
            retry_interval = 0.5
        retry_interval = max(0.0, retry_interval)

        logger.info("[找色功能] 使用本地截图和OpenCV")

        if max_attempts > 1:
            logger.info(f"[找色功能] 已启用重试: 最大{max_attempts}次，间隔{retry_interval:.2f}秒")

        last_result: Optional[Tuple[bool, str, Optional[int]]] = None
        for attempt in range(1, max_attempts + 1):
            if callable(stop_checker) and stop_checker():
                return False, '任务已停止', None
            if attempt > 1:
                logger.info(f"[找色功能] 开始第{attempt}次识别尝试")

            result = _execute_color_click_original(
                params,
                execution_mode,
                target_hwnd,
                card_id,
                on_success_action,
                success_jump_id,
                on_failure_action,
                failure_jump_id,
                stop_checker,
            )

            if result is None:
                logger.error("[找色功能] 找色模块返回了 None")
                result = _handle_failure(on_failure_action, failure_jump_id, card_id)

            last_result = result
            if isinstance(result, tuple) and len(result) > 0 and bool(result[0]):
                if attempt > 1:
                    logger.info(f"[找色功能] 第{attempt}次识别成功")
                return result

            if attempt < max_attempts:
                logger.info(f"[找色功能] 第{attempt}次识别失败，{retry_interval:.2f}秒后重试")
                if retry_interval > 0:
                    precise_sleep(retry_interval)

        if last_result is not None:
            return last_result
        return _handle_failure(on_failure_action, failure_jump_id, card_id)

    except Exception as e:
        logger.error(f"执行找色功能时发生错误: {e}", exc_info=True)
        return _handle_failure(on_failure_action, failure_jump_id, card_id)


def _store_color_match_context(
    card_id: Optional[int],
    center_x: Optional[int],
    center_y: Optional[int],
    color_items: Optional[List[Dict[str, Any]]],
    *,
    source_width: Optional[int] = None,
    source_height: Optional[int] = None,
) -> None:
    if card_id is None:
        return

    from task_workflow.workflow_context import get_workflow_context

    def _coerce_int(value: Any) -> Optional[int]:
        try:
            if value is None:
                return None
            return int(value)
        except Exception:
            return None

    context = get_workflow_context()
    context.set_card_data(card_id, 'color_target_x', _coerce_int(center_x))
    context.set_card_data(card_id, 'color_target_y', _coerce_int(center_y))
    context.set_card_data(card_id, 'color_target_x1', None)
    context.set_card_data(card_id, 'color_target_y1', None)
    context.set_card_data(card_id, 'color_target_x2', None)
    context.set_card_data(card_id, 'color_target_y2', None)
    context.set_card_data(card_id, 'color_items', list(color_items or []))
    context.set_card_data(card_id, 'color_source_width', _coerce_int(source_width))
    context.set_card_data(card_id, 'color_source_height', _coerce_int(source_height))


def _execute_color_click_original(params: Dict[str, Any], execution_mode: str, target_hwnd: Optional[int],
                                  card_id: Optional[int], on_success_action: str, success_jump_id: Optional[int],
                                  on_failure_action: str, failure_jump_id: Optional[int], stop_checker=None) -> Tuple[bool, str, Optional[int]]:
    """原生模式找色：截图与匹配都在主进程执行，主进程只消费结果。"""
    try:
        from services.screenshot_pool import (
            capture_and_find_color,
            clear_screenshot_engine_cache,
        )
    except Exception as exc:
        logger.error("[找色功能] 找色接口不可用: %s", exc)
        return _handle_failure(on_failure_action, failure_jump_id, card_id)

    try:
        target_color_str = params.get('target_color', '')
        if not target_color_str:
            logger.error("未设置目标颜色，请先通过颜色选择器获取颜色")
            return _handle_failure(on_failure_action, failure_jump_id, card_id)

        if not target_hwnd:
            logger.error("找色功能需要有效的目标窗口句柄")
            return _handle_failure(on_failure_action, failure_jump_id, card_id)

        recognition_region_enabled = coerce_bool(params.get('search_region_enabled', False))
        color_enable_click = coerce_bool(params.get('color_enable_click', True))
        click_position_mode = params.get('click_position_mode', '精准坐标')

        if click_position_mode == '固定偏移':
            color_fixed_offset_x = int(params.get('color_fixed_offset_x', 0) or 0)
            color_fixed_offset_y = int(params.get('color_fixed_offset_y', 0) or 0)
            color_random_offset_x = int(params.get('color_random_offset_x', 5) or 0)
            color_random_offset_y = int(params.get('color_random_offset_y', 5) or 0)
        elif click_position_mode == '随机偏移':
            color_fixed_offset_x = 0
            color_fixed_offset_y = 0
            color_random_offset_x = int(params.get('color_random_offset_x', 5) or 0)
            color_random_offset_y = int(params.get('color_random_offset_y', 5) or 0)
        else:
            color_fixed_offset_x = 0
            color_fixed_offset_y = 0
            color_random_offset_x = 0
            color_random_offset_y = 0

        h_tolerance = 10
        s_tolerance = 40
        v_tolerance = 40
        min_pixel_count = 1

        color_mode = 'single'
        colors_data: List[Dict[str, Any]] = []
        try:
            if '|' in target_color_str:
                color_mode = 'multipoint'
                parts = target_color_str.split('|')
                for idx, part in enumerate(parts):
                    values = [int(x.strip()) for x in part.split(',')]
                    if idx == 0:
                        if len(values) != 3:
                            logger.error(f"多点定位格式错误：第一个点应为 R,G,B，实际: {part}")
                            return _handle_failure(on_failure_action, failure_jump_id, card_id)
                        r, g, b = values
                        colors_data.append({'offset': (0, 0), 'rgb': (r, g, b), 'bgr': (b, g, r)})
                    else:
                        if len(values) != 5:
                            logger.error(f"多点定位格式错误：后续点应为 offsetX,offsetY,R,G,B，实际: {part}")
                            return _handle_failure(on_failure_action, failure_jump_id, card_id)
                        ox, oy, r, g, b = values
                        colors_data.append({'offset': (ox, oy), 'rgb': (r, g, b), 'bgr': (b, g, r)})
            elif ';' in target_color_str:
                color_mode = 'multi'
                parts = target_color_str.split(';')
                for part in parts:
                    values = [int(x.strip()) for x in part.split(',')]
                    if len(values) != 3:
                        logger.error(f"多颜色组合格式错误：每个颜色应为 R,G,B，实际: {part}")
                        return _handle_failure(on_failure_action, failure_jump_id, card_id)
                    r, g, b = values
                    colors_data.append({'rgb': (r, g, b), 'bgr': (b, g, r)})
            else:
                values = [int(x.strip()) for x in target_color_str.split(',')]
                if len(values) != 3:
                    logger.error(f"单颜色格式错误：应为 R,G,B，实际: {target_color_str}")
                    return _handle_failure(on_failure_action, failure_jump_id, card_id)
                r, g, b = values
                colors_data.append({'rgb': (r, g, b), 'bgr': (b, g, r)})
        except ValueError as exc:
            logger.error(f"解析目标颜色失败: {exc}")
            return _handle_failure(on_failure_action, failure_jump_id, card_id)

        roi = None
        if recognition_region_enabled:
            rx = int(params.get('search_region_x', 0) or 0)
            ry = int(params.get('search_region_y', 0) or 0)
            rw = int(params.get('search_region_width', 0) or 0)
            rh = int(params.get('search_region_height', 0) or 0)
            if rw > 0 and rh > 0:
                roi = (rx, ry, rw, rh)
                logger.info(f"[找色功能] 启用识别区域: X={rx}, Y={ry}, W={rw}, H={rh}")
            else:
                logger.warning(f"[找色功能] 识别区域宽高无效: W={rw}, H={rh}，将使用整窗")

        logger.info(f"[找色功能] 匹配开始，模式={color_mode}")
        find_response = capture_and_find_color(
            hwnd=int(target_hwnd),
            color_mode=color_mode,
            colors_data=colors_data,
            h_tolerance=h_tolerance,
            s_tolerance=s_tolerance,
            v_tolerance=v_tolerance,
            min_pixel_count=min_pixel_count,
            client_area_only=True,
            use_cache=False,
            timeout=4.0,
            roi=roi,
        )

        if not find_response.get('success') or not find_response.get('found'):
            try:
                clear_screenshot_engine_cache(hwnd=int(target_hwnd))
            except Exception as clear_exc:
                logger.debug('[找色功能] 清理截图缓存失败: %s', clear_exc)

            if not find_response.get('success'):
                logger.error('[找色功能] 匹配失败: %s', find_response.get('error'))
            else:
                logger.info('未找到匹配的目标颜色')
            return _handle_failure(on_failure_action, failure_jump_id, card_id)

        payload_positions = find_response.get('positions') or []
        found_positions: List[Tuple[int, int]] = []
        for pos in payload_positions[:4096]:
            if isinstance(pos, (list, tuple)) and len(pos) >= 2:
                try:
                    found_positions.append((int(pos[0]), int(pos[1])))
                except Exception:
                    continue

        if not found_positions:
            center_payload = find_response.get('center')
            if isinstance(center_payload, (list, tuple)) and len(center_payload) >= 2:
                try:
                    found_positions.append((int(center_payload[0]), int(center_payload[1])))
                except Exception:
                    pass

        if not found_positions:
            logger.info('未找到匹配的目标颜色')
            return _handle_failure(on_failure_action, failure_jump_id, card_id)

        center_payload = find_response.get('center')
        if isinstance(center_payload, (list, tuple)) and len(center_payload) >= 2:
            click_x = int(center_payload[0])
            click_y = int(center_payload[1])
        else:
            click_x = sum(pos[0] for pos in found_positions) // len(found_positions)
            click_y = sum(pos[1] for pos in found_positions) // len(found_positions)

        logger.info(f"[找色功能] 返回匹配点数: {len(found_positions)}，中心=({click_x}, {click_y})")
        base_click_x = click_x
        base_click_y = click_y

        click_x, click_y, applied_offset_x, applied_offset_y = _apply_click_offsets(
            click_x,
            click_y,
            click_position_mode,
            color_fixed_offset_x,
            color_fixed_offset_y,
            color_random_offset_x,
            color_random_offset_y,
        )
        if click_position_mode == '固定偏移':
            logger.info(
                "找到目标颜色，应用固定偏移并叠加随机偏移后的点击坐标: "
                f"({click_x}, {click_y}), 总偏移量=({applied_offset_x}, {applied_offset_y})"
            )
        elif click_position_mode == '随机偏移':
            logger.info(
                f"找到目标颜色，应用随机偏移（X={color_random_offset_x}, Y={color_random_offset_y}）后的点击坐标: "
                f"({click_x}, {click_y}), 偏移量=({applied_offset_x}, {applied_offset_y})"
            )
        else:
            logger.info(f"找到目标颜色，精准坐标点击: ({click_x}, {click_y})")

        if card_id is not None:
            try:
                def _calc_center(positions: List[Tuple[int, int]]):
                    if not positions:
                        return None, None
                    xs = [pos[0] for pos in positions]
                    ys = [pos[1] for pos in positions]
                    return int(round(sum(xs) / len(xs))), int(round(sum(ys) / len(ys)))

                base_positions = list(found_positions)
                base_cx, base_cy = _calc_center(base_positions)
                color_items: List[Dict[str, Any]] = []

                if color_mode == 'multipoint':
                    center_positions: List[Tuple[int, int]] = []
                    if base_cx is not None and base_cy is not None:
                        for idx, color_data in enumerate(colors_data):
                            r, g, b = color_data.get('rgb', (0, 0, 0))
                            if idx == 0:
                                cx, cy = base_cx, base_cy
                            else:
                                ox, oy = color_data.get('offset', (0, 0))
                                cx, cy = int(base_cx + int(ox)), int(base_cy + int(oy))
                            color_items.append({'颜色': f"{r},{g},{b}", '坐标X': int(cx), '坐标Y': int(cy)})
                            center_positions.append((int(cx), int(cy)))
                    center_x, center_y = _calc_center(center_positions)
                elif color_mode == 'multi':
                    # 多色组合的逐色匹配在截图链路完成；主进程不再做二次图像匹配。
                    for color_data in colors_data:
                        r, g, b = color_data.get('rgb', (0, 0, 0))
                        color_items.append({'颜色': f"{r},{g},{b}", '坐标X': base_cx, '坐标Y': base_cy})
                    center_x, center_y = base_cx, base_cy
                else:
                    r, g, b = colors_data[0].get('rgb', (0, 0, 0))
                    color_items.append({'颜色': f"{r},{g},{b}", '坐标X': base_cx, '坐标Y': base_cy})
                    center_x, center_y = base_cx, base_cy

                if center_x is None or center_y is None:
                    center_x, center_y = base_click_x, base_click_y

                _store_color_match_context(
                    card_id,
                    center_x,
                    center_y,
                    color_items,
                    source_width=find_response.get('screenshot_width'),
                    source_height=find_response.get('screenshot_height'),
                )
            except Exception as exc:
                logger.debug('[找色功能] 保存坐标失败: %s', exc)

        if not color_enable_click:
            logger.info('[找色功能] 仅识别模式，跳过点击')
            return _handle_success(on_success_action, success_jump_id, card_id)

        from tasks.click_coordinate import execute_task as execute_coordinate_click

        button_param = params.get('color_click_button', params.get('button', '左键'))
        clicks = params.get('color_click_clicks', params.get('clicks', 1))
        interval = params.get('color_click_interval', params.get('interval', DEFAULT_DOUBLE_CLICK_INTERVAL_SECONDS))
        click_action = params.get('color_click_action', '完整点击')
        hold_duration = params.get('color_hold_duration', DEFAULT_CLICK_HOLD_SECONDS)

        click_params = {
            'coordinate_x': click_x,
            'coordinate_y': click_y,
            'coordinate_mode': '客户区坐标',
            'button': button_param,
            'clicks': clicks,
            'interval': interval,
            'position_mode': '精准坐标',
            'click_action': click_action,
            'hold_duration': hold_duration,
            'on_success': on_success_action,
            'success_jump_target_id': success_jump_id,
            'on_failure': on_failure_action,
            'failure_jump_target_id': failure_jump_id,
        }

        logger.info(f"执行找色功能: ({click_x}, {click_y}), 模式={color_mode}, 按钮={button_param}, 次数={clicks}, 动作={click_action}")
        result = execute_coordinate_click(
            click_params,
            {},
            execution_mode,
            target_hwnd,
            None,
            card_id=card_id,
            stop_checker=stop_checker,
        )
        if result is None:
            logger.error('坐标点击模块返回了 None')
            return _handle_failure(on_failure_action, failure_jump_id, card_id)
        return result

    except Exception as e:
        logger.error(f"执行找色功能时发生错误: {e}", exc_info=True)
        return _handle_failure(on_failure_action, failure_jump_id, card_id)
def _find_single_color(screenshot_bgr: np.ndarray, target_color_bgr: Tuple[int, int, int],
                      h_tolerance: int, s_tolerance: int, v_tolerance: int,
                      min_pixel_count: int) -> List[Tuple[int, int]]:
    """查找单个颜色的所有匹配位置 - 优化版（自适应容差）"""
    # 转换BGR到HSV色彩空间
    hsv_image = cv2.cvtColor(screenshot_bgr, cv2.COLOR_BGR2HSV)
    target_color_hsv = cv2.cvtColor(np.uint8([[target_color_bgr]]), cv2.COLOR_BGR2HSV)[0][0]

    h, s, v = int(target_color_hsv[0]), int(target_color_hsv[1]), int(target_color_hsv[2])

    # 优化：自适应H容差（红色需要更大容差）
    # 红色在HSV中跨越0度边界（345-15度），需要特殊处理
    original_h_tol = h_tolerance
    if h < 10 or h > 170:  # 红色范围
        h_tolerance = max(h_tolerance, 10)  # 红色至少10度容差
        logger.debug(f"检测到红色，使用增强容差: H={h_tolerance} (原始={original_h_tol})")
    elif 20 < h < 40:  # 黄色
        h_tolerance = max(h_tolerance, 8)
        logger.debug(f"检测到黄色，使用增强容差: H={h_tolerance}")
    elif 100 < h < 130:  # 蓝色/青色
        h_tolerance = max(h_tolerance, 8)
        logger.debug(f"检测到蓝/青色，使用增强容差: H={h_tolerance}")

    # 优化：低饱和度颜色（灰色/白色）放宽S容差
    if s < 30:
        old_s_tol = s_tolerance
        s_tolerance = min(s_tolerance * 2, 60)
        logger.debug(f"低饱和度颜色，放宽S容差: {s_tolerance} (原始={old_s_tol})")

    logger.debug(f"查找颜色 BGR{target_color_bgr} -> HSV({h},{s},{v}), 优化后容差: H={h_tolerance}, S={s_tolerance}, V={v_tolerance}")

    # 处理色调的循环边界（防止numpy溢出）
    if h - h_tolerance < 0 or h + h_tolerance > 180:
        if h - h_tolerance < 0:
            hsv_lower_part1 = np.array([0, max(0, s - s_tolerance), max(0, v - v_tolerance)], dtype=np.uint8)
            hsv_upper_part1 = np.array([min(180, h + h_tolerance), min(255, s + s_tolerance), min(255, v + v_tolerance)], dtype=np.uint8)
            hsv_lower_part2 = np.array([max(0, 180 + (h - h_tolerance)), max(0, s - s_tolerance), max(0, v - v_tolerance)], dtype=np.uint8)
            hsv_upper_part2 = np.array([180, min(255, s + s_tolerance), min(255, v + v_tolerance)], dtype=np.uint8)
            mask1 = cv2.inRange(hsv_image, hsv_lower_part1, hsv_upper_part1)
            mask2 = cv2.inRange(hsv_image, hsv_lower_part2, hsv_upper_part2)
            color_mask = cv2.bitwise_or(mask1, mask2)
            logger.debug(f"色调环绕(下界): 范围1=[{hsv_lower_part1[0]},{hsv_upper_part1[0]}], 范围2=[{hsv_lower_part2[0]},{hsv_upper_part2[0]}]")
        else:
            hsv_lower_part1 = np.array([h - h_tolerance, max(0, s - s_tolerance), max(0, v - v_tolerance)], dtype=np.uint8)
            hsv_upper_part1 = np.array([180, min(255, s + s_tolerance), min(255, v + v_tolerance)], dtype=np.uint8)
            hsv_lower_part2 = np.array([0, max(0, s - s_tolerance), max(0, v - v_tolerance)], dtype=np.uint8)
            hsv_upper_part2 = np.array([max(0, min(180, (h + h_tolerance) - 180)), min(255, s + s_tolerance), min(255, v + v_tolerance)], dtype=np.uint8)
            mask1 = cv2.inRange(hsv_image, hsv_lower_part1, hsv_upper_part1)
            mask2 = cv2.inRange(hsv_image, hsv_lower_part2, hsv_upper_part2)
            color_mask = cv2.bitwise_or(mask1, mask2)
            logger.debug(f"色调环绕(上界): 范围1=[{hsv_lower_part1[0]},{hsv_upper_part1[0]}], 范围2=[{hsv_lower_part2[0]},{hsv_upper_part2[0]}]")
    else:
        hsv_lower = np.array([max(0, h - h_tolerance), max(0, s - s_tolerance), max(0, v - v_tolerance)], dtype=np.uint8)
        hsv_upper = np.array([min(180, h + h_tolerance), min(255, s + s_tolerance), min(255, v + v_tolerance)], dtype=np.uint8)
        color_mask = cv2.inRange(hsv_image, hsv_lower, hsv_upper)
        logger.debug(f"正常范围: H=[{hsv_lower[0]},{hsv_upper[0]}], S=[{hsv_lower[1]},{hsv_upper[1]}], V=[{hsv_lower[2]},{hsv_upper[2]}]")

    # 统计匹配的像素数量
    match_pixel_count = cv2.countNonZero(color_mask)

    logger.debug(f"匹配像素数量: {match_pixel_count} (阈值: {min_pixel_count})")

    if match_pixel_count < min_pixel_count:
        # 【闪退修复】添加调试信息时验证图像格式
        try:
            if len(hsv_image.shape) == 3 and hsv_image.shape[2] == 3:
                unique_colors_count = len(np.unique(hsv_image.reshape(-1, 3), axis=0))
                logger.debug(f"图像中唯一颜色数: {unique_colors_count}, 图像HSV范围: H=[{hsv_image[:,:,0].min()},{hsv_image[:,:,0].max()}], S=[{hsv_image[:,:,1].min()},{hsv_image[:,:,1].max()}], V=[{hsv_image[:,:,2].min()},{hsv_image[:,:,2].max()}]")
            else:
                logger.warning(f"HSV图像形状异常: {hsv_image.shape}，跳过调试统计")
        except Exception as e:
            logger.warning(f"计算颜色统计信息失败: {e}")
        return []

    # 查找所有匹配点
    nonzero_coords = cv2.findNonZero(color_mask)
    if nonzero_coords is None:
        return []

    # 返回所有匹配位置
    positions = [(int(pt[0][0]), int(pt[0][1])) for pt in nonzero_coords]
    logger.debug(f"返回 {len(positions)} 个匹配位置")
    return positions

def _find_multi_colors_combined(screenshot_bgr: np.ndarray, colors_data: List[Dict],
                                h_tolerance: int, s_tolerance: int, v_tolerance: int,
                                min_pixel_count: int) -> List[Tuple[int, int]]:
    """查找多颜色组合：所有颜色都存在才算匹配，返回第一个颜色的位置"""
    # 先检查每个颜色是否都存在
    all_masks = []
    for color_data in colors_data:
        positions = _find_single_color(screenshot_bgr, color_data['bgr'], h_tolerance, s_tolerance, v_tolerance, min_pixel_count)
        if not positions:
            # 有颜色不存在，匹配失败
            logger.info(f"多颜色组合：颜色 RGB{color_data['rgb']} 未找到")
            return []
        all_masks.append(positions)

    # 所有颜色都存在，返回第一个颜色的所有位置
    logger.info(f"多颜色组合：所有 {len(colors_data)} 个颜色都找到")
    return all_masks[0]

def _find_multipoint_color(screenshot_bgr: np.ndarray, colors_data: List[Dict],
                           h_tolerance: int, s_tolerance: int, v_tolerance: int) -> List[Tuple[int, int]]:
    """查找多点定位：找到满足所有点颜色和位置关系的基准点

    多点定位使用RGB精确匹配（每个通道±3误差），不使用HSV容差
    """
    if not colors_data:
        return []

    # 先找第一个点（基准点）的所有位置 - 使用RGB精确匹配
    base_color = colors_data[0]
    base_bgr = base_color['bgr']

    # RGB精确匹配查找基准点
    rgb_tolerance = 3
    img_h, img_w = screenshot_bgr.shape[:2]

    # 计算每个通道的匹配掩码
    b_match = np.abs(screenshot_bgr[:, :, 0].astype(np.int16) - base_bgr[0]) <= rgb_tolerance
    g_match = np.abs(screenshot_bgr[:, :, 1].astype(np.int16) - base_bgr[1]) <= rgb_tolerance
    r_match = np.abs(screenshot_bgr[:, :, 2].astype(np.int16) - base_bgr[2]) <= rgb_tolerance

    # 所有通道都匹配的像素
    color_mask = (b_match & g_match & r_match).astype(np.uint8) * 255

    # 查找所有匹配点
    nonzero_coords = cv2.findNonZero(color_mask)
    if nonzero_coords is None:
        logger.info("多点定位：基准点未找到（RGB精确匹配）")
        return []

    base_positions = [(int(pt[0][0]), int(pt[0][1])) for pt in nonzero_coords]

    if not base_positions:
        logger.info("多点定位：基准点未找到")
        return []

    logger.info(f"多点定位：找到 {len(base_positions)} 个基准点候选位置（RGB精确匹配±{rgb_tolerance}）")

    # 对每个基准点候选位置，检查其他点是否匹配
    valid_positions = []

    for base_x, base_y in base_positions:
        # 检查这个基准点是否满足所有其他点的条件
        all_points_match = True

        for i in range(1, len(colors_data)):
            point_data = colors_data[i]
            offset_x, offset_y = point_data['offset']
            target_x = base_x + offset_x
            target_y = base_y + offset_y

            # 检查坐标是否在图像范围内
            if target_x < 0 or target_x >= img_w or target_y < 0 or target_y >= img_h:
                all_points_match = False
                break

            # 检查该位置的颜色是否匹配
            # 多点定位使用RGB精确匹配（每个通道允许±3的误差）
            pixel_bgr = screenshot_bgr[target_y, target_x]
            target_bgr = point_data['bgr']

            # RGB精确匹配：每个通道的差异不能超过3
            b_diff = abs(int(pixel_bgr[0]) - int(target_bgr[0]))
            g_diff = abs(int(pixel_bgr[1]) - int(target_bgr[1]))
            r_diff = abs(int(pixel_bgr[2]) - int(target_bgr[2]))

            if b_diff <= rgb_tolerance and g_diff <= rgb_tolerance and r_diff <= rgb_tolerance:
                # 该点颜色匹配
                continue
            else:
                # 该点颜色不匹配
                all_points_match = False
                break

        if all_points_match:
            valid_positions.append((base_x, base_y))

    logger.info(f"多点定位：找到 {len(valid_positions)} 个完全匹配的位置（RGB精确匹配±{rgb_tolerance}）")
    return valid_positions

def _execute_mouse_scroll(params: Dict[str, Any], execution_mode: str, target_hwnd: Optional[int],
                         card_id: Optional[int], on_success_action: str, success_jump_id: Optional[int],
                         on_failure_action: str, failure_jump_id: Optional[int], stop_checker=None) -> Tuple[bool, str, Optional[int]]:
    """执行鼠标滚轮操作"""
    try:
        from tasks.mouse_scroll_runtime import execute_mouse_scroll

        # 解析滚动起始位置坐标
        scroll_position = params.get('scroll_start_position', '500,300')
        try:
            if isinstance(scroll_position, str) and ',' in scroll_position:
                scroll_x, scroll_y = map(int, scroll_position.split(','))
            else:
                # 兼容旧版本的 scroll_x 和 scroll_y 参数
                scroll_x = int(params.get('scroll_x', 500))
                scroll_y = int(params.get('scroll_y', 300))
        except (ValueError, TypeError):
            logger.warning(f"无法解析滚动坐标: {scroll_position}，使用默认值 (500, 300)")
            scroll_x, scroll_y = 500, 300

        # 构造鼠标滚轮的参数
        scroll_params = {
            'direction': params.get('scroll_direction', '向下'),
            'scroll_count': params.get('scroll_clicks', 3),  # 使用 scroll_count 而不是 clicks
            'interval': params.get('scroll_interval', 0.1),
            'location_mode': '指定坐标',  # 使用指定坐标模式
            'scroll_start_position': f"{scroll_x},{scroll_y}",  # 设置正确的坐标字符串
            'coordinate_mode': '客户区坐标',  # 设置坐标模式
            'scroll_x': scroll_x,  # 传递解析后的X坐标（兼容性）
            'scroll_y': scroll_y,  # 传递解析后的Y坐标（兼容性）
            'on_success': on_success_action,
            'success_jump_target_id': success_jump_id,
            'on_failure': on_failure_action,
            'failure_jump_target_id': failure_jump_id
        }

        logger.info(f"执行鼠标滚轮操作: {params.get('scroll_direction', '向下')} {params.get('scroll_clicks', 3)}次")
        result = execute_mouse_scroll(
            scroll_params,
            {},
            execution_mode,
            target_hwnd,
            None,
            card_id=card_id,
            stop_checker=stop_checker,
        )

        # 【防御性编程】检查返回值是否为 None，防止解包错误
        if result is None:
            logger.error("鼠标滚轮模块返回了 None")
            return _handle_failure(on_failure_action, failure_jump_id, card_id)

        return result

    except Exception as e:
        logger.error(f"执行鼠标滚轮操作时发生错误: {e}", exc_info=True)
        return _handle_failure(on_failure_action, failure_jump_id, card_id)

def _perform_move_click(params: Dict[str, Any], execution_mode: str, target_hwnd: Optional[int],
                        click_x: int, click_y: int, stop_checker=None) -> bool:
    """执行鼠标移动后的点击操作

    Args:
        params: 任务参数
        execution_mode: 执行模式
        target_hwnd: 目标窗口句柄
        click_x: 点击X坐标（客户区坐标）
        click_y: 点击Y坐标（客户区坐标）

    Returns:
        bool: 点击是否成功
    """
    try:
        resolved_point = _resolve_move_click_screen_point(execution_mode, target_hwnd, click_x, click_y)
        if resolved_point is None:
            return False
        click_x_screen, click_y_screen = resolved_point

        button_label = params.get('move_click_button', '左键')
        safe_click_button, safe_clicks, safe_interval, normalized_action, enable_auto_release, safe_hold_duration = resolve_click_params(
            params,
            button_key="move_click_button",
            fallback_button_key="button",
            clicks_key="move_click_clicks",
            fallback_clicks_key="clicks",
            interval_key="move_click_interval",
            fallback_interval_key="interval",
            action_key="move_click_action",
            auto_release_key="move_enable_auto_release",
            hold_duration_key="move_hold_duration",
            hold_mode_key="move_hold_mode",
            hold_min_key="move_hold_duration_min",
            hold_max_key="move_hold_duration_max",
            mode_label="鼠标移动点击",
            logger_obj=logger,
            log_hold_mode=False,
        )

        logger.info(
            f"[鼠标移动点击] 在屏幕坐标({click_x_screen}, {click_y_screen})执行点击: "
            f"按钮={button_label}, 次数={safe_clicks}, 间隔={safe_interval}s, 动作={normalized_action}"
        )

        # 创建输入模拟器并执行点击
        input_sim = _get_task_simulator(target_hwnd, execution_mode)
        if input_sim is None:
            logger.error("[鼠标移动点击] 无法创建输入模拟器")
            return False
        click_success = execute_simulator_click_action(
            simulator=input_sim,
            x=click_x_screen,
            y=click_y_screen,
            button=safe_click_button,
            click_action=normalized_action,
            clicks=safe_clicks,
            interval=safe_interval,
            hold_duration=safe_hold_duration,
            auto_release=enable_auto_release,
            mode_label="鼠标移动点击",
            logger_obj=logger,
            single_click_retry=False,
            require_atomic_hold=True,
            stop_checker=stop_checker,
            execution_mode=execution_mode,
            target_hwnd=target_hwnd,
            task_type=TASK_TYPE,
        )
        if not click_success:
            logger.error("[鼠标移动点击] 点击执行失败")
            return False

        logger.info("[鼠标移动点击] 点击执行成功")
        return True

    except Exception as e:
        logger.error(f"[鼠标移动点击] 执行点击时出错: {e}")
        return False

def _is_background_execution_mode(execution_mode: str) -> bool:
    return str(execution_mode or "").strip().lower().startswith("background")


def _get_task_simulator(target_hwnd: Optional[int], execution_mode: str):
    from utils.input_simulation import global_input_simulator_manager

    return global_input_simulator_manager.get_simulator(target_hwnd, "auto", execution_mode)


def _resolve_relative_move_start(execution_mode: str, target_hwnd: int) -> Tuple[int, int]:
    if _is_background_execution_mode(execution_mode):
        simulator = _get_task_simulator(target_hwnd, execution_mode)
        getter = getattr(simulator, "get_virtual_cursor", None) if simulator else None
        if callable(getter):
            try:
                cursor = getter()
                if cursor and len(cursor) >= 2:
                    return int(cursor[0]), int(cursor[1])
            except Exception:
                pass
        try:
            import win32gui

            rect = win32gui.GetClientRect(target_hwnd)
            return max(0, int(rect[2]) // 2), max(0, int(rect[3]) // 2)
        except Exception:
            return 0, 0

    try:
        import win32api
        import win32gui

        cursor_pos = win32api.GetCursorPos()
        start_x, start_y = win32gui.ScreenToClient(target_hwnd, cursor_pos)
        return int(start_x), int(start_y)
    except Exception as e:
        logger.warning(f"[鼠标移动] 获取鼠标位置失败: {e}，使用窗口中心点")
        try:
            import win32gui

            rect = win32gui.GetClientRect(target_hwnd)
            return int(rect[2]) // 2, int(rect[3]) // 2
        except Exception:
            return 500, 300


def _perform_background_client_move(
    simulator,
    start_x: int,
    start_y: int,
    end_x: int,
    end_y: int,
    duration: float,
    smoothness: int,
    use_bezier: bool,
    stop_checker=None,
) -> bool:
    if not simulator or not hasattr(simulator, "move_mouse"):
        return False
    if not bool(simulator.move_mouse(int(start_x), int(start_y))):
        return False
    offset_x = int(end_x) - int(start_x)
    offset_y = int(end_y) - int(start_y)
    if offset_x == 0 and offset_y == 0:
        return True
    if duration is None or float(duration) <= 0:
        return bool(simulator.move_mouse(int(end_x), int(end_y)))

    current = [int(start_x), int(start_y)]

    def _step(delta_x: int, delta_y: int) -> bool:
        current[0] += int(delta_x)
        current[1] += int(delta_y)
        return bool(simulator.move_mouse(current[0], current[1]))

    if not _shared_perform_timed_relative_move(
        offset_x,
        offset_y,
        duration,
        _step,
        smoothness=smoothness,
        use_bezier=use_bezier,
        stop_checker=stop_checker,
    ):
        return False
    return bool(simulator.move_mouse(int(end_x), int(end_y)))


def _execute_background_mouse_move(
    target_hwnd: int,
    execution_mode: str,
    start_x: int,
    start_y: int,
    end_x: int,
    end_y: int,
    duration: float,
    use_timed_move: bool,
    smoothness: int,
    use_bezier: bool,
    stop_checker=None,
) -> bool:
    simulator = _get_task_simulator(target_hwnd, execution_mode)
    if not simulator or not hasattr(simulator, "move_mouse"):
        logger.error("[鼠标移动] 无法创建后台输入模拟器")
        return False
    logger.info(f"[鼠标移动] 使用后台消息移动: {execution_mode}")
    return _perform_background_client_move(
        simulator,
        start_x,
        start_y,
        end_x,
        end_y,
        duration if use_timed_move else 0.0,
        smoothness,
        use_bezier,
        stop_checker,
    )


def _perform_relative_mouse_move(offset_x: int, offset_y: int, execution_mode: str) -> bool:
    """执行相对移动（不受窗口边界限制）"""
    if offset_x == 0 and offset_y == 0:
        return True

    try:
        from utils.input.foreground_input_manager import get_foreground_input_manager
        fg_input = get_foreground_input_manager()
        mode = (execution_mode or "").strip().lower()
        if mode.startswith("foreground"):
            fg_input.set_execution_mode(execution_mode)
        else:
            logger.error(f"[鼠标移动] 严格模式仅支持前台驱动，当前模式: {execution_mode}")
            return False

        if fg_input.move_mouse(int(offset_x), int(offset_y), absolute=False):
            return True
        logger.error("[鼠标移动] 前台驱动相对移动失败")
        return False
    except Exception as exc:
        logger.error(f"[鼠标移动] 前台相对移动失败: {exc}")
        return False

def _perform_timed_relative_move(offset_x: int, offset_y: int, duration: float,
                                 smoothness: int, use_bezier: bool, execution_mode: str,
                                 stop_checker=None) -> bool:
    """Execute relative move across a duration."""
    return _shared_perform_timed_relative_move(
        offset_x,
        offset_y,
        duration,
        lambda delta_x, delta_y: _perform_relative_mouse_move(delta_x, delta_y, execution_mode),
        smoothness=smoothness,
        use_bezier=use_bezier,
        stop_checker=stop_checker,
    )

def _client_to_screen_point(target_hwnd: int, x: int, y: int) -> tuple:
    """将客户区坐标转换为屏幕坐标，失败时回退原值。"""
    try:
        import win32gui
        sx, sy = win32gui.ClientToScreen(target_hwnd, (int(x), int(y)))
        return int(sx), int(sy)
    except Exception:
        return int(x), int(y)

def _screen_to_client_point(target_hwnd: int, x: int, y: int) -> tuple:
    """将屏幕坐标转换为客户区坐标，失败时回退原值。"""
    try:
        import win32gui
        cx, cy = win32gui.ScreenToClient(target_hwnd, (int(x), int(y)))
        return int(cx), int(cy)
    except Exception:
        return int(x), int(y)

def _resolve_move_click_screen_point(execution_mode: str, target_hwnd: Optional[int],
                                     click_x: int, click_y: int,
                                     log_conversion: bool = True) -> Optional[Tuple[int, int]]:
    """根据执行模式解析鼠标移动点击使用的屏幕坐标。"""
    mode_text = str(execution_mode or "").strip().lower()
    if mode_text.startswith("foreground"):
        if not target_hwnd:
            logger.error("[鼠标移动点击] 前台模式缺少窗口句柄，终止点击以避免坐标偏移")
            return None
        try:
            import win32gui
            click_x_screen, click_y_screen = win32gui.ClientToScreen(target_hwnd, (int(click_x), int(click_y)))
            if log_conversion:
                logger.info(
                    f"[鼠标移动点击] 坐标转换: 客户区({click_x}, {click_y}) -> "
                    f"屏幕({click_x_screen}, {click_y_screen})"
                )
            return int(click_x_screen), int(click_y_screen)
        except Exception as e:
            logger.error(f"[鼠标移动点击] 前台坐标转换失败，终止点击以避免点歪: {e}")
            return None

    return int(click_x), int(click_y)

def _execute_mouse_move(params: Dict[str, Any], execution_mode: str, target_hwnd: Optional[int],
                       card_id: Optional[int], on_success_action: str, success_jump_id: Optional[int],
                       on_failure_action: str, failure_jump_id: Optional[int], stop_checker=None) -> Tuple[bool, str, Optional[int]]:
    """执行鼠标移动操作"""
    try:
        if not target_hwnd:
            logger.error("[鼠标移动] 需要目标窗口句柄")
            return _handle_failure(on_failure_action, failure_jump_id, card_id)

        # 获取移动参数
        move_mode = params.get('move_mode', '绝对移动')

        # 根据持续时间模式获取持续时间
        duration_mode = params.get('move_duration_mode', '固定持续时间')
        instant_move_requested = False
        if duration_mode == '随机持续时间':
            try:
                min_duration = float(params.get('move_duration_min', 0.3))
                max_duration = float(params.get('move_duration_max', 0.8))
            except (TypeError, ValueError):
                logger.warning("[鼠标移动] 随机持续时间参数无效，使用默认值")
                min_duration, max_duration = 0.3, 0.8

            min_duration = max(0.0, min_duration)
            max_duration = max(0.0, max_duration)
            if min_duration > max_duration:
                min_duration, max_duration = max_duration, min_duration
            duration = random.uniform(min_duration, max_duration)
        else:
            try:
                duration = float(params.get('move_duration', 0.5))
            except (TypeError, ValueError):
                logger.warning("[鼠标移动] 固定持续时间参数无效，使用默认值0.5秒")
                duration = 0.5
            if duration < 0:
                logger.warning("[鼠标移动] 固定持续时间小于0，已按0秒处理")
                duration = 0.0
            instant_move_requested = duration <= 0.0

        use_bezier = params.get('move_use_bezier', False)
        smoothness = params.get('move_smoothness', 50)

        # 根据移动模式确定起点和终点坐标
        if move_mode == '绝对移动':
            # 绝对移动：从起点移动到终点
            start_position = params.get('move_start_position', '100,100')
            end_position = params.get('move_end_position', '500,300')

            try:
                if isinstance(start_position, str) and ',' in start_position:
                    start_x, start_y = map(int, start_position.split(','))
                else:
                    logger.error(f"[鼠标移动] 无效的起点坐标: {start_position}")
                    return _handle_failure(on_failure_action, failure_jump_id, card_id)

                if isinstance(end_position, str) and ',' in end_position:
                    end_x, end_y = map(int, end_position.split(','))
                else:
                    logger.error(f"[鼠标移动] 无效的终点坐标: {end_position}")
                    return _handle_failure(on_failure_action, failure_jump_id, card_id)
            except (ValueError, TypeError) as e:
                logger.error(f"[鼠标移动] 无法解析坐标: {e}")
                return _handle_failure(on_failure_action, failure_jump_id, card_id)

            # 根据距离调整持续时间（与相对移动保持一致）
            distance = math.hypot(end_x - start_x, end_y - start_y)
            if duration_mode == '随机持续时间':
                base_min = max(0.05, min_duration)
                base_max = max(base_min + 0.1, max_duration)
                distance_factor = (distance / 100) * random.uniform(0.05, 0.1)
                duration = random.uniform(base_min, base_max) + distance_factor
            else:
                if instant_move_requested:
                    duration = 0.0
                else:
                    base_duration = max(0.05, duration)
                    distance_factor = (distance / 100) * 0.08
                    duration = base_duration + distance_factor

            logger.info(f"[鼠标移动] 绝对移动: ({start_x}, {start_y}) -> ({end_x}, {end_y}), 距离{distance:.0f}px, 持续{duration:.2f}s")
        else:
            # 相对移动：基于当前鼠标位置的偏移
            offset_mode = params.get('move_offset_mode', '固定偏移')

            # 根据偏移模式获取偏移量
            if offset_mode == '随机偏移':
                try:
                    offset_x_min = int(params.get('move_offset_x_min', -50))
                    offset_x_max = int(params.get('move_offset_x_max', 50))
                    offset_y_min = int(params.get('move_offset_y_min', -50))
                    offset_y_max = int(params.get('move_offset_y_max', 50))
                except (ValueError, TypeError):
                    logger.warning("[鼠标移动] 随机偏移参数无效,使用默认值")
                    offset_x_min, offset_x_max = -50, 50
                    offset_y_min, offset_y_max = -50, 50

                # 防御性编程: 确保min <= max
                if offset_x_min > offset_x_max:
                    offset_x_min, offset_x_max = offset_x_max, offset_x_min
                if offset_y_min > offset_y_max:
                    offset_y_min, offset_y_max = offset_y_max, offset_y_min

                offset_x = random.randint(offset_x_min, offset_x_max)
                offset_y = random.randint(offset_y_min, offset_y_max)
            else:
                try:
                    offset_x = int(params.get('move_offset_x', 0))
                    offset_y = int(params.get('move_offset_y', 0))
                except (ValueError, TypeError):
                    logger.warning("[鼠标移动] 固定偏移参数无效,使用默认值0")
                    offset_x, offset_y = 0, 0

            start_x, start_y = _resolve_relative_move_start(execution_mode, target_hwnd)

            # 计算终点坐标（当前位置 + 偏移量）
            end_x = start_x + offset_x
            end_y = start_y + offset_y

            # 相对移动根据偏移距离自动调整持续时间
            offset_distance = math.sqrt(offset_x**2 + offset_y**2)
            if duration_mode == '随机持续时间':
                # 随机模式: 基于距离调整范围
                base_min = max(0.05, min_duration)
                base_max = max(base_min + 0.1, max_duration)
                # 距离系数: 每100像素增加0.05-0.1秒
                distance_factor = (offset_distance / 100) * random.uniform(0.05, 0.1)
                duration = random.uniform(base_min, base_max) + distance_factor
            else:
                if instant_move_requested:
                    duration = 0.0
                else:
                    # 固定模式: 基于距离调整
                    base_duration = max(0.05, duration)
                    # 距离系数: 每100像素增加0.08秒
                    distance_factor = (offset_distance / 100) * 0.08
                    duration = base_duration + distance_factor

            logger.info(f"[鼠标移动] 相对移动({offset_mode}): 当前位置({start_x},{start_y}) 偏移({offset_x},{offset_y}) -> 目标({end_x},{end_y}), 距离{offset_distance:.0f}px, 持续{duration:.2f}s")

        use_timed_move = duration is not None and duration > 0
        if _is_background_execution_mode(execution_mode):
            success = _execute_background_mouse_move(
                target_hwnd,
                execution_mode,
                start_x,
                start_y,
                end_x,
                end_y,
                duration,
                use_timed_move,
                smoothness,
                use_bezier,
                stop_checker,
            )
            if success:
                logger.info("[鼠标移动] 移动成功")
                move_enable_click = params.get('move_enable_click', False)
                if move_enable_click:
                    try:
                        logger.info("[鼠标移动] 检测到启用移动后点击")
                        click_result = _perform_move_click(
                            params,
                            execution_mode,
                            target_hwnd,
                            end_x,
                            end_y,
                            stop_checker,
                        )
                        if click_result:
                            logger.info("[鼠标移动] 移动后点击成功")
                        else:
                            logger.warning("[鼠标移动] 移动后点击失败，但移动已成功")
                    except Exception as click_error:
                        logger.error(f"[鼠标移动] 执行移动后点击时出错: {click_error}")
                return _handle_success(on_success_action, success_jump_id, card_id)
            logger.error("[鼠标移动] 移动失败")
            return _handle_failure(on_failure_action, failure_jump_id, card_id)

        effective_mode = execution_mode
        logger.info(f"[鼠标移动] 使用前台模式执行: {effective_mode}")

        # 严格模式：记录本次实际使用驱动
        if (effective_mode or '').startswith('foreground'):
            try:
                from utils.input.foreground_input_manager import get_foreground_input_manager
                from utils.input_simulation.mode_utils import get_foreground_driver, get_ibinputsimulator_config

                resolved_backend = get_foreground_driver(effective_mode)
                configured_driver_detail = resolved_backend
                if resolved_backend == 'ibinputsimulator':
                    ib_driver, _, _, _ = get_ibinputsimulator_config()
                    configured_driver_detail = f"{resolved_backend}:{ib_driver}"

                logger.info(f"[鼠标移动] 严格模式配置驱动: {configured_driver_detail}")

                fg_input = get_foreground_input_manager()
                fg_input.set_execution_mode(effective_mode)
                if not fg_input.initialize():
                    logger.error(f"[鼠标移动] 前台驱动初始化失败: {configured_driver_detail}")
                    return _handle_failure(on_failure_action, failure_jump_id, card_id)

                driver_type = str(fg_input.get_driver_type() or "unknown")
                active_driver = fg_input.get_active_driver()
                driver_detail = driver_type
                if driver_type == 'ibinputsimulator' and active_driver is not None:
                    selected_driver = getattr(active_driver, '_driver_name', None)
                    if selected_driver:
                        driver_detail = f"{driver_type}:{selected_driver}"
                logger.info(f"[鼠标移动] 严格模式驱动: {driver_detail}")
            except Exception as driver_err:
                logger.error(f"[鼠标移动] 获取驱动信息失败: {driver_err}")
                return _handle_failure(on_failure_action, failure_jump_id, card_id)

        use_timed_move = duration is not None and duration > 0

        success = False
        if move_mode != '绝对移动':
            # 相对移动：优先按持续时间分步移动
            if use_timed_move:
                success = _perform_timed_relative_move(
                    offset_x, offset_y, duration, smoothness, use_bezier, effective_mode, stop_checker
                )
            else:
                success = _perform_relative_mouse_move(offset_x, offset_y, effective_mode)
        else:
            # 绝对移动：严格按起点 -> 终点执行；起终点一致则不移动
            if start_x == end_x and start_y == end_y:
                logger.info("[鼠标移动] 绝对移动起点与终点一致，跳过移动")
                success = True
            else:
                start_screen_x, start_screen_y = _client_to_screen_point(target_hwnd, start_x, start_y)
                end_screen_x, end_screen_y = _client_to_screen_point(target_hwnd, end_x, end_y)
                try:
                    from utils.input_simulation import InputSimulatorFactory
                    input_sim = InputSimulatorFactory.create_simulator(target_hwnd, execution_mode=effective_mode)
                    if not input_sim or not hasattr(input_sim, 'move_mouse'):
                        logger.warning("[鼠标移动] 输入模拟器不支持鼠标移动操作")
                        success = False
                    elif not input_sim.move_mouse(start_screen_x, start_screen_y):
                        logger.error("[鼠标移动] 无法移动到绝对起点")
                        success = False
                    elif use_timed_move:
                        timed_ok = _perform_timed_relative_move(
                            end_screen_x - start_screen_x,
                            end_screen_y - start_screen_y,
                            duration,
                            smoothness,
                            use_bezier,
                            effective_mode,
                            stop_checker,
                        )
                        # 绝对移动模式用相对步进轨迹时，最后再做一次绝对对齐，避免累计误差导致未到位。
                        if timed_ok:
                            timed_ok = bool(input_sim.move_mouse(end_screen_x, end_screen_y))
                        success = timed_ok
                    else:
                        success = input_sim.move_mouse(end_screen_x, end_screen_y)
                except ImportError:
                    logger.error("[鼠标移动] 无法导入输入模拟器工厂")
                    success = False
                except Exception as move_error:
                    logger.error(f"[鼠标移动] 执行鼠标移动时出错: {move_error}")
                    success = False

        if success:
            logger.info("[鼠标移动] 移动成功")

            # 检查是否启用移动后点击
            move_enable_click = params.get('move_enable_click', False)
            if move_enable_click:
                try:
                    logger.info("[鼠标移动] 检测到启用移动后点击")
                    click_client_x, click_client_y = end_x, end_y
                    logger.info("[鼠标移动] 使用终点坐标执行点击")

                    click_result = _perform_move_click(
                        params,
                        effective_mode,
                        target_hwnd,
                        click_client_x,
                        click_client_y,
                        stop_checker,
                    )
                    if click_result:
                        logger.info("[鼠标移动] 移动后点击成功")
                        return _handle_success(on_success_action, success_jump_id, card_id)
                    else:
                        logger.warning("[鼠标移动] 移动后点击失败，但移动已成功")
                        return _handle_success(on_success_action, success_jump_id, card_id)
                except Exception as click_error:
                    logger.error(f"[鼠标移动] 执行移动后点击时出错: {click_error}")
                    return _handle_success(on_success_action, success_jump_id, card_id)

            return _handle_success(on_success_action, success_jump_id, card_id)
        else:
            logger.error("[鼠标移动] 移动失败")
            return _handle_failure(on_failure_action, failure_jump_id, card_id)

    except Exception as e:
        logger.error(f"执行鼠标移动操作失败: {e}", exc_info=True)
        return _handle_failure(on_failure_action, failure_jump_id, card_id)

def _find_image_for_drag_opencv(target_hwnd: int, image_path: str, confidence: float = 0.8) -> Optional[Tuple[int, int]]:
    """原有模式(OpenCV)的图片查找 - 用于拖拽定位。

    匹配逻辑已迁移到截图链路，主进程仅负责模板准备和结果解析。
    """
    try:
        import os

        if not image_path or not os.path.exists(image_path):
            logger.error(f"[原有模式找图] 图片不存在: {image_path}")
            return None

        if not target_hwnd:
            logger.error("[原有模式找图] 缺少有效窗口句柄")
            return None

        template = safe_imread(image_path)
        if template is None:
            logger.error(f"[原有模式找图] 无法读取模板图片: {image_path}")
            return None

        template = normalize_match_image(template)
        if template is None:
            logger.error(f"[原有模式找图] 模板规范化失败: {image_path}")
            return None

        match_response = capture_and_match_template_smart(
            target_hwnd=target_hwnd,
            template=template,
            confidence_threshold=float(confidence),
            template_key=(str(image_path) if image_path else None),
            capture_timeout=0.8,
            roi=None,
            client_area_only=True,
            use_cache=False,
        )

        if not match_response or not bool(match_response.get("success")):
            err = (match_response or {}).get("error") if isinstance(match_response, dict) else "unknown_error"
            logger.error(f"[原有模式找图] 匹配失败: {err}")
            return None

        try:
            max_val = float(match_response.get("confidence", 0.0) or 0.0)
        except Exception:
            max_val = 0.0

        raw_location = match_response.get("location")
        parsed_location = None
        if isinstance(raw_location, (list, tuple)) and len(raw_location) == 4:
            try:
                parsed_location = (
                    int(raw_location[0]),
                    int(raw_location[1]),
                    int(raw_location[2]),
                    int(raw_location[3]),
                )
            except Exception:
                parsed_location = None

        if bool(match_response.get("matched", False)) and parsed_location is not None and max_val >= confidence:
            match_x, match_y, template_w, template_h = parsed_location
            center_x = int(match_x) + int(template_w) // 2
            center_y = int(match_y) + int(template_h) // 2
            image_name = os.path.basename(image_path)
            logger.info(f"[原有模式找图] 找到图片 {image_name}: 中心坐标({center_x}, {center_y}), 置信度={max_val:.4f}")
            return (center_x, center_y)

        image_name = os.path.basename(image_path)
        logger.warning(f"[原有模式找图] 未找到图片 {image_name}: 最大置信度={max_val:.4f} < 阈值{confidence}")
        return None

    except Exception as e:
        logger.error(f"[原有模式找图] 图片查找失败: {e}", exc_info=True)
        return None
def _correct_single_image_path(raw_path: str) -> Optional[str]:
    """智能纠正单个图片路径（使用统一的路径解析器）

    Args:
        raw_path: 原始路径

    Returns:
        纠正后的有效路径，如果无法纠正则返回None
    """
    # 使用统一的路径解析器（支持多目录搜索、缓存、打包环境）
    from tasks.task_utils import correct_single_image_path
    return correct_single_image_path(raw_path)

def _find_image_for_drag(target_hwnd: int, image_path: str, confidence: float,
                         execution_mode: str) -> Optional[Tuple[int, int]]:
    """使用本地 OpenCV 查找拖拽起点或终点图片。

    Args:
        target_hwnd: 目标窗口句柄
        image_path: 图片路径
        confidence: 置信度阈值
        execution_mode: 执行模式（保留此参数以兼容任务调用接口）

    Returns:
        (x, y) 图片中心坐标，如果未找到则返回None
    """
    try:
        # 先尝试纠正路径
        corrected_path = _correct_single_image_path(image_path)
        if corrected_path is None:
            logger.error(f"[拖拽找图] 图片路径无效或不存在: {image_path}")
            return None

        # 如果路径被纠正，记录日志
        if corrected_path != image_path:
            logger.info(f"[拖拽找图] 路径已纠正: {os.path.basename(image_path)} -> {corrected_path}")

        logger.info("[拖拽找图] 使用本地OpenCV")
        return _find_image_for_drag_opencv(target_hwnd, corrected_path, confidence)
    except Exception as e:
        logger.error(f"[拖拽找图] 找图过程出错: {e}", exc_info=True)
        return None

def _execute_mouse_drag(params: Dict[str, Any], execution_mode: str, target_hwnd: Optional[int],
                       card_id: Optional[int], on_success_action: str, success_jump_id: Optional[int],
                       on_failure_action: str, failure_jump_id: Optional[int],
                       device_id: Optional[str] = None) -> Tuple[bool, str, Optional[int]]:
    """执行鼠标拖拽操作"""
    try:
        effective_mode = execution_mode
        logger.info(f"[拖拽] 执行模式: {execution_mode}")

        # 获取拖拽模式
        drag_mode = params.get('drag_mode', '简单拖拽')

        if drag_mode == '多点路径拖拽':
            # 多点路径拖拽模式
            return _execute_multi_point_drag(params, effective_mode, target_hwnd, card_id,
                                           on_success_action, success_jump_id,
                                           on_failure_action, failure_jump_id,
                                           device_id=device_id)
        else:
            # 简单拖拽模式（原有逻辑）
            return _execute_simple_drag(params, effective_mode, target_hwnd, card_id,
                                      on_success_action, success_jump_id,
                                      on_failure_action, failure_jump_id,
                                      device_id=device_id)

    except Exception as e:
        logger.error(f"执行鼠标拖拽操作失败: {e}")
        return _handle_failure(on_failure_action, failure_jump_id, card_id)

def _execute_simple_drag(params: Dict[str, Any], execution_mode: str, target_hwnd: Optional[int],
                        card_id: Optional[int], on_success_action: str, success_jump_id: Optional[int],
                        on_failure_action: str, failure_jump_id: Optional[int],
                        device_id: Optional[str] = None) -> Tuple[bool, str, Optional[int]]:
    """执行简单拖拽操作（支持坐标和图片两种定位方式）

    起点和终点都可以独立选择使用坐标或本地OpenCV图片识别定位。
    """
    try:
        # 获取拖拽控制参数
        raw_button = params.get('drag_button', '左键')
        button = _resolve_drag_button(raw_button)
        duration = params.get('drag_duration', 1.0)
        smoothness = params.get('drag_smoothness', 100)

        if not button:
            logger.error(f"[拖拽] 不支持的拖拽按钮: {raw_button}")
            return _handle_failure(on_failure_action, failure_jump_id, card_id)

        # 检查目标窗口
        if not target_hwnd:
            logger.error("[拖拽] 需要目标窗口句柄才能执行鼠标拖拽")
            return _handle_failure(on_failure_action, failure_jump_id, card_id)

        # ===== 获取起点坐标 =====
        drag_start_mode = params.get('drag_start_mode', '坐标')
        start_x, start_y = None, None

        if drag_start_mode == '图片':
            # 图片模式：通过图片识别获取起点
            from task_workflow.resource_path import unwrap_resource_path

            start_image_path = unwrap_resource_path(params.get('drag_start_image_path', '')) or ''
            start_confidence = params.get('drag_start_confidence', 0.8)
            start_offset_x = params.get('drag_start_offset_x', 0)
            start_offset_y = params.get('drag_start_offset_y', 0)

            if not start_image_path:
                logger.error("[拖拽] 起点使用图片模式但未设置图片路径")
                return _handle_failure(on_failure_action, failure_jump_id, card_id)

            logger.info(f"[拖拽] 起点使用图片模式，查找: {os.path.basename(start_image_path)}")

            # 使用本地OpenCV找图接口。
            start_result = _find_image_for_drag(target_hwnd, start_image_path, start_confidence, execution_mode)

            if start_result is None:
                logger.error(f"[拖拽] 起点图片未找到: {os.path.basename(start_image_path)}")
                return _handle_failure(on_failure_action, failure_jump_id, card_id)

            # 应用偏移
            start_x = start_result[0] + start_offset_x
            start_y = start_result[1] + start_offset_y
            logger.info(f"[拖拽] 起点图片定位成功: ({start_result[0]}, {start_result[1]}) + 偏移({start_offset_x}, {start_offset_y}) = ({start_x}, {start_y})")

        else:
            # 坐标模式：使用固定坐标
            drag_start = params.get('drag_start_position', '500,300')
            logger.info(f"[拖拽] 起点使用坐标模式: '{drag_start}'")
            try:
                if isinstance(drag_start, str) and ',' in drag_start:
                    start_x, start_y = map(int, drag_start.split(','))
                else:
                    start_x, start_y = 500, 300
                    logger.warning(f"[拖拽] 起点坐标格式错误，使用默认值: ({start_x}, {start_y})")
            except (ValueError, TypeError) as e:
                start_x, start_y = 500, 300
                logger.warning(f"[拖拽] 解析起点坐标失败: {e}，使用默认值: ({start_x}, {start_y})")

        # ===== 获取终点坐标 =====
        drag_end_mode = params.get('drag_end_mode', '坐标')
        end_x, end_y = None, None

        if drag_end_mode == '图片':
            # 图片模式：通过图片识别获取终点
            from task_workflow.resource_path import unwrap_resource_path

            end_image_path = unwrap_resource_path(params.get('drag_end_image_path', '')) or ''
            end_confidence = params.get('drag_end_confidence', 0.8)
            end_offset_x = params.get('drag_end_offset_x', 0)
            end_offset_y = params.get('drag_end_offset_y', 0)

            if not end_image_path:
                logger.error("[拖拽] 终点使用图片模式但未设置图片路径")
                return _handle_failure(on_failure_action, failure_jump_id, card_id)

            logger.info(f"[拖拽] 终点使用图片模式，查找: {os.path.basename(end_image_path)}")

            # 使用本地OpenCV找图接口。
            end_result = _find_image_for_drag(target_hwnd, end_image_path, end_confidence, execution_mode)

            if end_result is None:
                logger.error(f"[拖拽] 终点图片未找到: {os.path.basename(end_image_path)}")
                return _handle_failure(on_failure_action, failure_jump_id, card_id)

            # 应用偏移
            end_x = end_result[0] + end_offset_x
            end_y = end_result[1] + end_offset_y
            logger.info(f"[拖拽] 终点图片定位成功: ({end_result[0]}, {end_result[1]}) + 偏移({end_offset_x}, {end_offset_y}) = ({end_x}, {end_y})")

        else:
            # 坐标模式：使用固定坐标
            drag_end = params.get('drag_end_position', '700,300')
            logger.info(f"[拖拽] 终点使用坐标模式: '{drag_end}'")
            try:
                if isinstance(drag_end, str) and ',' in drag_end:
                    end_x, end_y = map(int, drag_end.split(','))
                else:
                    end_x, end_y = 700, 300
                    logger.warning(f"[拖拽] 终点坐标格式错误，使用默认值: ({end_x}, {end_y})")
            except (ValueError, TypeError) as e:
                end_x, end_y = 700, 300
                logger.warning(f"[拖拽] 解析终点坐标失败: {e}，使用默认值: ({end_x}, {end_y})")

        # ===== 坐标验证和限制 =====
        logger.info(f"[拖拽] 解析后的起点: ({start_x}, {start_y})")
        logger.info(f"[拖拽] 解析后的终点: ({end_x}, {end_y})")

        # 计算实际拖拽距离
        distance = int(math.sqrt((end_x - start_x)**2 + (end_y - start_y)**2))

        # 获取窗口客户区尺寸,限制坐标范围
        try:
            import win32gui
            client_rect = win32gui.GetClientRect(target_hwnd)
            max_x = client_rect[2] - 1  # 客户区宽度-1
            max_y = client_rect[3] - 1  # 客户区高度-1

            logger.info(f"[拖拽] 窗口客户区尺寸: {max_x+1}x{max_y+1}")

            # 限制起始坐标
            original_start_x, original_start_y = start_x, start_y
            start_x = max(0, min(start_x, max_x))
            start_y = max(0, min(start_y, max_y))
            if start_x != original_start_x or start_y != original_start_y:
                logger.warning(f"[拖拽] 起点坐标超出窗口范围，已调整: ({original_start_x},{original_start_y}) -> ({start_x},{start_y})")

            # 限制结束坐标
            original_end_x, original_end_y = end_x, end_y
            end_x = max(0, min(end_x, max_x))
            end_y = max(0, min(end_y, max_y))
            if end_x != original_end_x or end_y != original_end_y:
                logger.warning(f"[拖拽] 终点坐标超出窗口范围，已调整: ({original_end_x},{original_end_y}) -> ({end_x},{end_y})")

        except Exception as e:
            logger.warning(f"[拖拽] 无法获取窗口尺寸: {e}，使用原始坐标")

        # 显示最终拖拽信息
        start_mode_desc = "图片" if drag_start_mode == "图片" else "坐标"
        end_mode_desc = "图片" if drag_end_mode == "图片" else "坐标"
        logger.info(f"[拖拽] 开始执行: ({start_x},{start_y})[{start_mode_desc}] -> ({end_x},{end_y})[{end_mode_desc}]")
        logger.info(f"[拖拽] 距离={distance}像素, 按钮={button}, 持续时间={duration}秒, 平滑度={smoothness}")

        try:
            from task_workflow.card_payload import publish_click_target
            from task_workflow.workflow_context import get_workflow_context

            publish_click_target(
                get_workflow_context(),
                card_id,
                x=end_x,
                y=end_y,
                x1=min(start_x, end_x),
                y1=min(start_y, end_y),
                x2=max(start_x, end_x),
                y2=max(start_y, end_y),
            )
        except Exception:
            pass

        # ===== 执行拖拽操作 =====
        # 将起点和终点转换为路径点列表
        path_points = [(start_x, start_y), (end_x, end_y)]
        success = perform_mouse_drag_path(target_hwnd, path_points, duration=duration,
                                        execution_mode=execution_mode, button=button,
                                        device_id=device_id)

        if success:
            logger.info("[拖拽] 简单拖拽完成")
            result = _handle_success(on_success_action, success_jump_id, card_id)
            return result
        else:
            logger.error("[拖拽] 简单拖拽失败")
            result = _handle_failure(on_failure_action, failure_jump_id, card_id)
            return result

    except Exception as e:
        logger.error(f"[拖拽] 简单拖拽异常: {e}", exc_info=True)
        return _handle_failure(on_failure_action, failure_jump_id, card_id)

def _execute_multi_point_drag(params: Dict[str, Any], execution_mode: str, target_hwnd: Optional[int],
                             card_id: Optional[int], on_success_action: str, success_jump_id: Optional[int],
                             on_failure_action: str, failure_jump_id: Optional[int],
                             device_id: Optional[str] = None) -> Tuple[bool, str, Optional[int]]:
    """执行多点路径拖拽操作"""
    try:
        # 获取路径点参数（包含时间戳）
        path_points_text = params.get('path_points', '100,100,0\n200,150,0.5\n300,200,1.0\n400,250,1.5')

        # 解析路径点（包含时间戳）
        path_points, timestamps = _parse_path_points(path_points_text)
        if not path_points or len(path_points) < 2:
            logger.error("路径点数量不足，至少需要2个点")
            return _handle_failure(on_failure_action, failure_jump_id, card_id)

        # 必须有时间戳
        if not timestamps:
            logger.error("多点路径拖拽必须提供时间戳")
            return _handle_failure(on_failure_action, failure_jump_id, card_id)

        actual_duration = timestamps[-1]
        logger.info(f"开始多点路径拖拽: {len(path_points)}个点, 总时长={actual_duration:.3f}s")

        logger.info(f" 路径点: {path_points}")

        if not target_hwnd:
            logger.error(" 需要目标窗口句柄才能执行多点拖拽")
            return _handle_failure(on_failure_action, failure_jump_id, card_id)

        raw_button = params.get('drag_button', '左键')
        button = _resolve_drag_button(raw_button)
        if not button:
            logger.error(f"路径拖拽按钮无效: {raw_button}")
            return _handle_failure(on_failure_action, failure_jump_id, card_id)

        # 执行多点拖拽操作（传递时间戳和device_id）
        success = perform_mouse_drag_path(
            target_hwnd,
            path_points,
            actual_duration,
            execution_mode,
            timestamps,
            button=button,
            device_id=device_id,
        )

        if success:
            logger.info(" 多点路径拖拽完成")
            logger.info(f" 处理成功跳转: 动作={on_success_action}, 跳转ID={success_jump_id}, 卡片ID={card_id}")
            result = _handle_success(on_success_action, success_jump_id, card_id)
            logger.info(f" 成功跳转结果: {result}")
            return result
        else:
            logger.error(" 多点路径拖拽失败")
            logger.info(f" 处理失败跳转: 动作={on_failure_action}, 跳转ID={failure_jump_id}, 卡片ID={card_id}")
            result = _handle_failure(on_failure_action, failure_jump_id, card_id)
            logger.info(f" 失败跳转结果: {result}")
            return result

    except Exception as e:
        logger.error(f"执行多点路径拖拽操作失败: {e}", exc_info=True)
        return _handle_failure(on_failure_action, failure_jump_id, card_id)

def _parse_path_points(path_points_text: str) -> tuple:
    """解析路径点文本为坐标列表和时间戳列表

    Args:
        path_points_text: 路径点文本，每行一个坐标点
                        格式1（带时间戳）: x,y,timestamp
                        格式2（无时间戳）: x,y

    Returns:
        tuple: (坐标点列表, 时间戳列表)
              坐标点列表: [(x1, y1), (x2, y2), ...]
              时间戳列表: [t1, t2, ...] 或 None（如果没有时间戳）
    """
    try:
        path_points = []
        timestamps = []
        has_timestamps = False
        lines = path_points_text.strip().split('\n')

        for i, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue

            try:
                if ',' in line:
                    parts = line.split(',')
                    x = int(parts[0].strip())
                    y = int(parts[1].strip())
                    path_points.append((x, y))

                    # 检查是否有时间戳
                    if len(parts) >= 3:
                        try:
                            timestamp = float(parts[2].strip())
                            timestamps.append(timestamp)
                            has_timestamps = True
                        except (ValueError, IndexError):
                            # 如果时间戳解析失败，标记为无时间戳
                            has_timestamps = False
                            timestamps = []
                            logger.debug(f"第{i+1}行时间戳解析失败，将使用默认时间分配")
                    else:
                        # 没有时间戳字段
                        if has_timestamps:
                            # 前面有时间戳但这里没有，数据不一致
                            logger.warning(f"路径点格式不一致（第{i+1}行），将使用默认时间分配")
                            has_timestamps = False
                            timestamps = []
                else:
                    logger.warning(f"路径点格式错误（第{i+1}行）: {line}，跳过")
            except (ValueError, TypeError) as e:
                logger.warning(f"解析路径点失败（第{i+1}行）: {line}，错误: {e}")
                continue

        if has_timestamps and len(timestamps) == len(path_points):
            logger.info(f"解析路径点完成: {len(path_points)}个有效点, 带时间戳, 总时长={timestamps[-1]:.3f}s")
            return path_points, timestamps
        else:
            logger.debug(f"解析路径点完成: {len(path_points)}个有效点, 无时间戳")
            return path_points, None

    except Exception as e:
        logger.error(f"解析路径点文本失败: {e}")
        return [], None

def perform_mouse_drag_path(hwnd: int, path_points: list, duration: float = 1.0,
                           execution_mode: str = 'background', timestamps: list = None,
                           button: str = 'left',
                           device_id: str = None) -> bool:
    """执行多点路径拖拽操作

    Args:
        hwnd: 目标窗口句柄
        path_points: 路径点列表，格式: [(x1, y1), (x2, y2), (x3, y3), ...]
        duration: 总持续时间（秒），如果提供timestamps则此参数被忽略
        execution_mode: 执行模式 ('foreground' 或 'background')
        timestamps: 时间戳列表（秒），如果提供则按时间戳执行精确回放
        device_id: 目标设备ID (多设备支持)

    Returns:
        bool: 是否执行成功
    """
    try:
        if not path_points or len(path_points) < 2:
            logger.error("路径点数量不足，至少需要2个点")
            return False

        raw_button = button
        button = _resolve_drag_button(raw_button)
        if not button:
            logger.error(f"拖拽按钮无效: {raw_button}")
            return False

        # 如果有时间戳，使用时间戳作为实际时长
        if timestamps and len(timestamps) == len(path_points):
            actual_duration = timestamps[-1]
            logger.info(f"开始多点路径拖拽: {len(path_points)}个点, 带时间戳回放, 总时长: {actual_duration:.3f}秒, 执行模式: {execution_mode}")
        else:
            actual_duration = duration
            logger.info(f"开始多点路径拖拽: {len(path_points)}个点, 均匀分配时间, 总时长: {duration}秒, 执行模式: {execution_mode}")

        logger.info(f"执行本地多点拖拽，device_id={device_id}，execution_mode={execution_mode}")
        return perform_mouse_drag_path_native(
            hwnd,
            path_points,
            actual_duration,
            execution_mode,
            timestamps,
            button=button,
        )

    except Exception as e:
        logger.error(f"多点拖拽执行失败: {e}", exc_info=True)
        return False


def _convert_client_path_to_screen(hwnd: int, path_points: list) -> list:
    """将客户区路径点转换为屏幕坐标路径点。"""
    import win32gui

    converted = []
    for point in path_points:
        x = int(point[0])
        y = int(point[1])
        try:
            sx, sy = win32gui.ClientToScreen(hwnd, (x, y))
        except Exception:
            sx, sy = x, y
        converted.append((int(sx), int(sy)))
    return converted


def perform_mouse_drag_path_native(hwnd: int, path_points: list, duration: float = 1.0,
                                   execution_mode: str = 'background', timestamps: list = None,
                                   button: str = 'left') -> bool:
    """原生模式完整路径拖拽实现

    支持前台模式（使用驱动）和后台模式（使用 Win32 消息）

    Args:
        hwnd: 目标窗口句柄
        path_points: 路径点列表，格式: [(x1, y1), (x2, y2), (x3, y3), ...]
        duration: 总持续时间（秒）
        execution_mode: 执行模式 ('foreground', 'foreground_*', 'background', 'background_*')
        timestamps: 时间戳列表（秒），如果提供则按时间戳执行精确回放

    Returns:
        bool: 是否执行成功
    """
    try:
        import win32gui, win32con, win32api
        import time

        if not path_points or len(path_points) < 2:
            logger.error("路径点数量不足，至少需要2个点")
            return False

        raw_button = button
        button = _resolve_drag_button(raw_button)
        if not button:
            logger.error(f"原生路径拖拽按钮无效: {raw_button}")
            return False

        start_x, start_y = path_points[0]

        # Determine if foreground mode should be used
        use_foreground = execution_mode.startswith('foreground') if execution_mode else False
        
        def _format_execution_mode_name(mode: str) -> str:
            if not mode:
                return "未知"
            mode = mode.strip().lower()
            if mode == "foreground_driver":
                return "前台一"
            if mode == "foreground_py":
                return "前台二"
            if mode == "background_sendmessage":
                return "后台一"
            if mode == "background_postmessage":
                return "后台二"
            if mode.startswith("background"):
                return "后台"
            if mode.startswith("foreground"):
                return "前台"
            return mode
        
        mode_name = _format_execution_mode_name(execution_mode)
        if use_foreground:
            # 前台模式：使用驱动进行多点路径拖拽
            logger.info(f"\u524d\u53f0\u9a71\u52a8\u6a21\u5f0f\u5b8c\u6574\u8def\u5f84\u62d6\u62fd({mode_name}): \u8d77\u70b9({start_x},{start_y}), {len(path_points)}\u4e2a\u70b9, \u603b\u65f6\u957f: {duration}\u79d2")
            from utils.input_simulation.factory import InputSimulatorFactory

            try:
                simulator = InputSimulatorFactory.create_simulator(hwnd, execution_mode=execution_mode)
                if not simulator:
                    logger.error("无法创建输入模拟器")
                    return False

                # 前台驱动以屏幕坐标执行，拖拽点统一从客户区坐标转换
                screen_path_points = _convert_client_path_to_screen(hwnd, path_points)

                # 获取起点和终点
                end_x, end_y = screen_path_points[-1]

                # 使用多点路径拖拽 - 一次按下经过所有点最后松开
                # 当有timestamps时，使用timestamps[-1]作为总时长；否则使用duration
                actual_drag_duration = timestamps[-1] if (timestamps and len(timestamps) == len(path_points)) else duration
                result = simulator.drag_path(
                    screen_path_points,
                    actual_drag_duration,
                    button=button,
                    timestamps=timestamps,
                )
                if result:
                    logger.info(f"前台模式多点路径拖拽成功，通过 {len(path_points)} 个路径点")
                    return True
                else:
                    logger.error("前台模式多点路径拖拽失败")
                    return False

            except Exception as foreground_error:
                logger.error(f"前台驱动模式拖拽失败: {foreground_error}", exc_info=True)
                return False

        # 后台模式：使用 Win32 消息
        logger.info(f"\u540e\u53f0\u6d88\u606f\u6a21\u5f0f\u5b8c\u6574\u8def\u5f84\u62d6\u62fd({mode_name}): \u8d77\u70b9({start_x},{start_y}), {len(path_points)}\u4e2a\u70b9, \u603b\u65f6\u957f: {duration}\u79d2")
        use_simple_background = (execution_mode or "").strip().lower() == "background_postmessage"
        send_fn = win32gui.PostMessage if use_simple_background else win32gui.SendMessage

        button_message_map = {
            "left": (
                win32con.WM_LBUTTONDOWN,
                win32con.WM_LBUTTONUP,
                win32con.MK_LBUTTON,
                "WM_LBUTTONDOWN",
                "WM_LBUTTONUP",
            ),
            "right": (
                win32con.WM_RBUTTONDOWN,
                win32con.WM_RBUTTONUP,
                win32con.MK_RBUTTON,
                "WM_RBUTTONDOWN",
                "WM_RBUTTONUP",
            ),
            "middle": (
                win32con.WM_MBUTTONDOWN,
                win32con.WM_MBUTTONUP,
                win32con.MK_MBUTTON,
                "WM_MBUTTONDOWN",
                "WM_MBUTTONUP",
            ),
        }
        down_msg, up_msg, move_wparam, down_msg_name, up_msg_name = button_message_map[button]

        def _background_drag_sleep(wait_seconds: float) -> None:
            """后台拖拽等待：优先让出CPU，避免多窗口并发时忙等抢占导致速度下降。"""
            try:
                wait_value = float(wait_seconds)
            except Exception:
                return
            if wait_value <= 0:
                return
            time.sleep(wait_value)

        # 多层级窗口查找：构建完整的窗口链并向所有层级发送消息
        window_chain = [hwnd]  # 至少包含主窗口
        window_coords = {}  # 存储每个窗口相对于自己客户区的坐标
        window_screen_offsets = {}  # 存储窗口左上角屏幕坐标，避免每步重复GetWindowRect
        try:
            from utils.window.enhanced_child_window_finder import EnhancedChildWindowFinder

            finder = EnhancedChildWindowFinder()
            screen_x, screen_y = win32gui.ClientToScreen(hwnd, (start_x, start_y))

            # 查找完整的窗口链：find_deepest_child 返回 (deepest_hwnd, chain_list, client_coords)
            deepest_hwnd, chain_dicts, client_coords = finder.find_deepest_child(hwnd, screen_x, screen_y)

            if chain_dicts and len(chain_dicts) > 0:
                # chain_dicts 是字典列表，每个字典包含 'hwnd' 等信息
                window_chain = [c['hwnd'] for c in chain_dicts if 'hwnd' in c]
                if window_chain:
                    logger.info(f"[多层级查找] 找到 {len(window_chain)} 层窗口链，将向所有层级发送消息")
                    # 为每个窗口计算相对于其客户区的坐标
                    for i, w in enumerate(window_chain):
                        logger.debug(f"  第{i+1}层: 0x{w:08X}")
                        try:
                            # 将屏幕坐标转换为该窗口的客户区坐标
                            rect = win32gui.GetWindowRect(w)
                            window_screen_offsets[w] = (int(rect[0]), int(rect[1]))
                            client_x = screen_x - rect[0]
                            client_y = screen_y - rect[1]
                            window_coords[w] = (client_x, client_y)
                            logger.debug(f"    坐标: ({client_x}, {client_y})")
                        except Exception as e:
                            logger.debug(f"    坐标转换失败: {e}，使用原始坐标")
                            window_coords[w] = (start_x, start_y)
                else:
                    logger.info(f"[多层级查找] 链路为空，使用原始窗口: 0x{hwnd:08X}")
                    window_coords[hwnd] = (start_x, start_y)
            else:
                logger.info(f"[多层级查找] 未找到多层窗口，使用原始窗口: 0x{hwnd:08X}")
                window_coords[hwnd] = (start_x, start_y)
                try:
                    rect = win32gui.GetWindowRect(hwnd)
                    window_screen_offsets[hwnd] = (int(rect[0]), int(rect[1]))
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"[多层级查找] 失败: {e}，使用原始窗口")
            window_chain = [hwnd]
            window_coords[hwnd] = (start_x, start_y)
            try:
                rect = win32gui.GetWindowRect(hwnd)
                window_screen_offsets[hwnd] = (int(rect[0]), int(rect[1]))
            except Exception:
                pass

        # 按下鼠标（在起点）- 向所有层级发送（使用各自的坐标）
        for target_hwnd in window_chain:
            coord_x, coord_y = window_coords.get(target_hwnd, (start_x, start_y))
            start_lparam = win32api.MAKELONG(coord_x, coord_y)
            send_fn(target_hwnd, down_msg, move_wparam, start_lparam)
            logger.debug(f"[{down_msg_name}] 发送到 0x{target_hwnd:08X}，坐标: ({coord_x}, {coord_y})")
        _background_drag_sleep(0.01)

        # 根据是否有时间戳，选择回放方式
        if timestamps and len(timestamps) == len(path_points):
            # 使用时间戳精确回放（60fps插值）
            logger.info("使用时间戳进行精确回放")
            total_steps = max(1, int(max(0.001, float(duration)) * 60.0))
            last_time = 0.0

            for step in range(1, total_steps + 1):
                current_time = (step / total_steps) * duration

                point_idx = 0
                for i in range(len(timestamps) - 1):
                    if timestamps[i] <= current_time <= timestamps[i + 1]:
                        point_idx = i
                        break
                else:
                    if current_time > timestamps[-1]:
                        point_idx = len(timestamps) - 2

                p1 = path_points[point_idx]
                p2 = path_points[point_idx + 1]
                t1, t2 = timestamps[point_idx], timestamps[point_idx + 1]

                if t2 > t1:
                    progress = (current_time - t1) / (t2 - t1)
                else:
                    progress = 0.0
                progress = max(0.0, min(1.0, progress))

                current_x = int(p1[0] + (p2[0] - p1[0]) * progress)
                current_y = int(p1[1] + (p2[1] - p1[1]) * progress)

                # 发送消息（需要包含按钮状态标志）- 向所有层级发送
                screen_move_x, screen_move_y = win32gui.ClientToScreen(hwnd, (current_x, current_y))
                for target_hwnd in window_chain:
                    coord_x, coord_y = window_coords.get(target_hwnd, (current_x, current_y))
                    # 使用缓存窗口偏移，避免每步调用GetWindowRect导致并发拖拽变慢
                    offset = window_screen_offsets.get(target_hwnd)
                    if offset is not None:
                        coord_x = screen_move_x - offset[0]
                        coord_y = screen_move_y - offset[1]
                    move_lparam = win32api.MAKELONG(coord_x, coord_y)
                    send_fn(target_hwnd, win32con.WM_MOUSEMOVE, move_wparam, move_lparam)

                # 时间控制
                time_delta = current_time - last_time
                if time_delta > 0:
                    _background_drag_sleep(time_delta)
                    last_time = current_time
        else:
            # 无时间戳，均匀分配时间（60fps）
            safe_duration = max(0.001, float(duration))
            target_fps = 60.0
            total_steps = max(1, int(safe_duration * target_fps))

            for step in range(1, total_steps + 1):
                progress = step / total_steps

                # 找到当前进度对应的两个路径点
                point_idx = int(progress * (len(path_points) - 1))
                if point_idx >= len(path_points) - 1:
                    point_idx = len(path_points) - 2

                # 段内进度
                segment_progress = (progress * (len(path_points) - 1)) - point_idx

                p1 = path_points[point_idx]
                p2 = path_points[point_idx + 1]

                current_x = int(p1[0] + (p2[0] - p1[0]) * segment_progress)
                current_y = int(p1[1] + (p2[1] - p1[1]) * segment_progress)

                # 发送消息（需要包含按钮状态标志）- 向所有层级发送
                screen_move_x, screen_move_y = win32gui.ClientToScreen(hwnd, (current_x, current_y))
                for target_hwnd in window_chain:
                    coord_x, coord_y = window_coords.get(target_hwnd, (current_x, current_y))
                    # 使用缓存窗口偏移，避免每步调用GetWindowRect导致并发拖拽变慢
                    offset = window_screen_offsets.get(target_hwnd)
                    if offset is not None:
                        coord_x = screen_move_x - offset[0]
                        coord_y = screen_move_y - offset[1]
                    move_lparam = win32api.MAKELONG(coord_x, coord_y)
                    send_fn(target_hwnd, win32con.WM_MOUSEMOVE, move_wparam, move_lparam)

                # 时间控制
                _background_drag_sleep(safe_duration / total_steps)

        # 释放鼠标（在终点）- 向所有层级发送
        end_x, end_y = path_points[-1]
        screen_end_x, screen_end_y = win32gui.ClientToScreen(hwnd, (end_x, end_y))
        for target_hwnd in window_chain:
            coord_x, coord_y = window_coords.get(target_hwnd, (end_x, end_y))
            # 使用缓存窗口偏移，避免每步调用GetWindowRect导致并发拖拽变慢
            offset = window_screen_offsets.get(target_hwnd)
            if offset is not None:
                coord_x = screen_end_x - offset[0]
                coord_y = screen_end_y - offset[1]
            end_lparam = win32api.MAKELONG(coord_x, coord_y)
            send_fn(target_hwnd, up_msg, 0, end_lparam)
            logger.debug(f"[{up_msg_name}] 发送到 0x{target_hwnd:08X}，坐标: ({coord_x}, {coord_y})")
        _background_drag_sleep(0.01)

        logger.info(f"\u540e\u53f0\u6d88\u606f\u6a21\u5f0f\u5b8c\u6574\u8def\u5f84\u62d6\u62fd\u5b8c\u6210({mode_name})\uff0c\u7ec8\u70b9: ({end_x},{end_y})")
        return True

    except Exception as e:
        logger.error(f"\u540e\u53f0\u6d88\u606f\u6a21\u5f0f\u5b8c\u6574\u8def\u5f84\u62d6\u62fd\u6267\u884c\u5931\u8d25({mode_name}): {e}", exc_info=True)
        # 紧急释放鼠标
        try:
            end_x, end_y = path_points[-1]
            end_lparam = win32api.MAKELONG(end_x, end_y)
            send_fn(hwnd, up_msg, 0, end_lparam)
        except Exception:
            pass
        return False


def _correct_image_paths(raw_image_paths: list) -> list:
    """纠正和验证图片路径列表"""
    if not raw_image_paths:
        return []

    import os
    from tasks.task_utils import correct_image_paths

    parsed_paths = []
    common_dir = None

    for raw in raw_image_paths:
        if not isinstance(raw, str):
            continue

        line = raw.replace('\u200b', '').replace('\u200c', '').replace('\u200d', '').replace('\ufeff', '')
        line = line.strip()
        if not line:
            continue

        if line.startswith('#'):
            if line.startswith('# 共同目录:') or line.startswith('#共同目录:'):
                parts = line.split(':', 1)
                common_dir = parts[1].strip() if len(parts) > 1 else None
            continue

        # Support "filename  # directory" display format from UI.
        if '  # ' in line:
            filename, directory = line.split('  # ', 1)
            filename = filename.strip()
            directory = directory.strip()
            if filename and directory:
                line = os.path.join(directory, filename)
            else:
                line = filename or directory

        if common_dir and line and not os.path.isabs(line) and not line.startswith('memory://'):
            line = os.path.join(common_dir, line)

        if line:
            parsed_paths.append(line)

    return correct_image_paths(parsed_paths, card_id=None)


def _show_no_images_found_dialog(image_paths: list) -> None:
    """显示未找到图片的对话框"""
    logger.warning(f"未找到有效的图片路径，收到的路径列表: {image_paths}")


def _get_ocr_results_from_context(card_id: Optional[int]) -> Optional[list]:
    """从工作流上下文获取OCR识别结果"""
    try:
        from task_workflow.workflow_context import get_workflow_context
        context = get_workflow_context()
        if card_id is not None:
            results = context.get_ocr_results(card_id)
            if results:
                return results
        return context.get_latest_ocr_results()
    except Exception as e:
        logger.debug(f"获取OCR结果失败: {e}")
        return None


def _get_ocr_target_text_from_context(card_id: Optional[int]) -> Tuple[Optional[str], str]:
    """从工作流上下文获取OCR目标文本和匹配模式"""
    try:
        from task_workflow.workflow_context import get_workflow_context
        context = get_workflow_context()
        candidates = []
        if card_id is not None:
            candidates.append(card_id)
        latest_ocr_card_id = context.get_latest_ocr_card_id()
        if latest_ocr_card_id is not None and latest_ocr_card_id not in candidates:
            candidates.append(latest_ocr_card_id)

        target_text = None
        match_mode = None
        for ocr_card_id in candidates:
            target_text = context.get_card_data(ocr_card_id, 'ocr_target_text')
            match_mode = context.get_card_data(ocr_card_id, 'ocr_match_mode')
            if target_text:
                break

        if not match_mode:
            match_mode = '包含'
        return target_text, match_mode
    except Exception as e:
        logger.debug(f"获取OCR目标文本失败: {e}")
        return None, '包含'


def _find_matching_text_in_ocr_results(ocr_results: list, target_text: str, match_mode: str) -> Optional[dict]:
    """在OCR结果中查找匹配的文本"""
    if not ocr_results or not target_text:
        return None

    for result in ocr_results:
        result_text = result.get('text', '') if isinstance(result, dict) else str(result)

        if match_mode == '完全匹配':
            if result_text == target_text:
                return result
        elif match_mode == '包含':
            if target_text in result_text:
                return result

    return None
def _calculate_click_position(bbox: tuple, position_mode: str, offset_x: int = 0, offset_y: int = 0) -> Tuple[int, int]:
    """根据边界框和位置模式计算点击位置"""
    if not bbox or len(bbox) < 4:
        return 0, 0

    points = []
    try:
        if isinstance(bbox[0], (list, tuple)):
            for point in bbox:
                if not isinstance(point, (list, tuple)) or len(point) < 2:
                    continue
                points.append((float(point[0]), float(point[1])))
        else:
            flat_values = [float(value) for value in bbox]
            pair_count = len(flat_values) // 2
            for index in range(pair_count):
                points.append((flat_values[index * 2], flat_values[index * 2 + 1]))
    except Exception:
        return 0, 0

    if not points:
        return 0, 0

    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    x1 = min(xs)
    y1 = min(ys)
    x2 = max(xs)
    y2 = max(ys)

    if position_mode == '中心':
        click_x = int((x1 + x2) / 2) + offset_x
        click_y = int((y1 + y2) / 2) + offset_y
    elif position_mode == '左上角':
        click_x = x1 + offset_x
        click_y = y1 + offset_y
    elif position_mode == '右下角':
        click_x = x2 + offset_x
        click_y = y2 + offset_y
    else:  # 默认精准点击为中心
        click_x = int((x1 + x2) / 2) + offset_x
        click_y = int((y1 + y2) / 2) + offset_y

    return click_x, click_y


def _get_ocr_card_id_from_context(card_id: Optional[int]) -> Optional[int]:
    """从工作流上下文获取OCR卡片ID"""
    try:
        from task_workflow.workflow_context import get_workflow_context
        context = get_workflow_context()
        ocr_card_id = context.get_card_data(card_id, 'ocr_card_id')
        return ocr_card_id
    except Exception as e:
        logger.debug(f"获取OCR卡片ID失败: {e}")
        return card_id


def _get_clicked_text_from_context(card_id: Optional[int]) -> Optional[str]:
    """从工作流上下文获取已点击的文本"""
    try:
        from task_workflow.workflow_context import get_workflow_context
        context = get_workflow_context()
        clicked_text = context.get_card_data(card_id, 'clicked_text')
        return clicked_text
    except Exception as e:
        logger.debug(f"获取已点击文本失败: {e}")
        return None


def test_image_recognition(params: Dict[str, Any], target_hwnd: Optional[int] = None, main_window=None, parameter_panel=None):
    """测试图像识别功能（调用统一测试模块）"""
    try:
        from tasks.image_match_probe import test_image_recognition as unified_test
        unified_test(params, target_hwnd, main_window, parameter_panel)
    except Exception as e:
        logger.error(f"测试图像识别失败: {e}", exc_info=True)

def test_color_recognition(params: Dict[str, Any], target_hwnd: Optional[int] = None, main_window=None, parameter_panel=None):
    """测试找色识别功能（复用找色执行链路，仅识别不点击）。"""
    def restore_windows():
        try:
            from PySide6.QtCore import QTimer

            if main_window:
                QTimer.singleShot(0, main_window, main_window.show)
                if hasattr(main_window, "raise_"):
                    QTimer.singleShot(0, main_window, main_window.raise_)

            if parameter_panel:
                QTimer.singleShot(0, parameter_panel, parameter_panel.show)
                if hasattr(parameter_panel, "raise_"):
                    QTimer.singleShot(0, parameter_panel, parameter_panel.raise_)
                if hasattr(parameter_panel, "activateWindow"):
                    QTimer.singleShot(0, parameter_panel, parameter_panel.activateWindow)
        except Exception as exc:
            logger.warning(f"[找色测试] 恢复窗口失败: {exc}")

    try:
        import win32gui
        from task_workflow.workflow_context import get_workflow_context
        from tasks.image_match_probe import _draw_overlay

        logger.info("=" * 60)
        logger.info("开始测试找色识别")
        logger.info("=" * 60)

        if not target_hwnd:
            logger.error("测试失败: 未绑定目标窗口")
            restore_windows()
            return

        target_hwnd = int(target_hwnd)
        if not win32gui.IsWindow(target_hwnd):
            logger.error(f"测试失败: 窗口句柄无效: {target_hwnd}")
            restore_windows()
            return

        card_id = getattr(parameter_panel, "current_card_id", None) if parameter_panel else None
        if card_id is None:
            logger.error("测试失败: 未获取到当前卡片ID")
            restore_windows()
            return

        test_params = dict(params or {})
        test_params["color_enable_click"] = False

        success, _, _ = _execute_color_click(
            test_params,
            execution_mode="自动",
            target_hwnd=target_hwnd,
            card_id=card_id,
            on_success_action="执行下一步",
            success_jump_id=None,
            on_failure_action="执行下一步",
            failure_jump_id=None,
        )
        if not success:
            logger.info("测试完成 - 未找到目标颜色")
            restore_windows()
            return

        context = get_workflow_context()
        color_items = context.get_card_data(card_id, "color_items") or []
        source_width = context.get_card_data(card_id, "color_source_width")
        source_height = context.get_card_data(card_id, "color_source_height")
        match_results: List[Tuple[str, int, int, int, int, float]] = []
        marker_radius = 6
        marker_size = marker_radius * 2

        for idx, item in enumerate(color_items):
            if not isinstance(item, dict):
                continue
            raw_x = item.get("坐标X")
            raw_y = item.get("坐标Y")
            if raw_x is None or raw_y is None:
                continue
            try:
                point_x = int(raw_x)
                point_y = int(raw_y)
            except Exception:
                continue
            color_name = str(item.get("颜色", f"颜色{idx + 1}") or f"颜色{idx + 1}")
            match_results.append((
                color_name,
                point_x - marker_radius,
                point_y - marker_radius,
                marker_size,
                marker_size,
                1.0,
            ))

        if not match_results:
            raw_center_x = context.get_card_data(card_id, "color_target_x")
            raw_center_y = context.get_card_data(card_id, "color_target_y")
            if raw_center_x is not None and raw_center_y is not None:
                try:
                    center_x = int(raw_center_x)
                    center_y = int(raw_center_y)
                    color_name = str(test_params.get("target_color", "目标颜色") or "目标颜色")
                    match_results.append((
                        color_name,
                        center_x - marker_radius,
                        center_y - marker_radius,
                        marker_size,
                        marker_size,
                        1.0,
                    ))
                except Exception:
                    pass

        if not match_results:
            logger.info("测试完成 - 未获取到可绘制的识别点")
            restore_windows()
            return

        logger.info(f"[找色测试] 共绘制 {len(match_results)} 个识别点")
        overlay_source_size = None
        try:
            if source_width is not None and source_height is not None:
                overlay_source_size = (int(source_width), int(source_height))
        except Exception:
            overlay_source_size = None

        _draw_overlay(
            target_hwnd,
            match_results,
            restore_windows,
            source_size=overlay_source_size,
        )

        logger.info("=" * 60)
        logger.info("测试完成")
        logger.info("=" * 60)

    except Exception as exc:
        logger.error(f"测试找色识别失败: {exc}", exc_info=True)
        restore_windows()
